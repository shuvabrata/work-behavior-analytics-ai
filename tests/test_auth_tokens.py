"""Unit tests for JWKS-backed bearer-token verification and role mapping.

These tests sign real JWTs with a generated RSA keypair and point the JWKS
client at the matching public key, so a stubbed signature check cannot pass.
No network I/O and no Keycloak are involved.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import tokens
from app.auth.principal import CredentialType
from app.settings import settings

pytestmark = [pytest.mark.unit]

_ISSUER = settings.KEYCLOAK_ISSUER
_CLIENT_ID = settings.KEYCLOAK_CLIENT_ID
_JWKS_URI = "https://localhost/auth/realms/wba/protocol/openid-connect/certs"


def _generate_keypair() -> tuple[bytes, Any]:
    """Return an RSA private key PEM and its public key object."""
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_pem, private_key.public_key()


class _FakeSigningKey:
    """Stand-in for ``jwt.PyJWK`` — exposes the cryptography key."""

    def __init__(self, key: Any) -> None:
        self.key = key


class _FakeJWKClient:
    """Stand-in for ``jwt.PyJWKClient`` returning a fixed public key."""

    def __init__(self, key: Any) -> None:
        self._key = key

    def get_signing_key_from_jwt(self, _token: str) -> _FakeSigningKey:
        return _FakeSigningKey(self._key)


class _FailIfConstructed:
    """A ``PyJWKClient`` stand-in that fails loudly if ever constructed.

    Used to prove the issuer gate fires *before* any JWKS client is built.
    """

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise AssertionError("PyJWKClient must not be constructed past the issuer gate")


@pytest.fixture(autouse=True)
def _reset_jwks_cache() -> Iterator[None]:
    """Clear the module-level cached JWKS client around every test."""
    tokens._jwks_client = None  # pylint: disable=protected-access
    yield
    tokens._jwks_client = None  # pylint: disable=protected-access


@pytest.fixture(name="keypair")
def _keypair() -> tuple[bytes, Any]:
    """One RSA keypair shared by the signer and the JWKS client."""
    return _generate_keypair()


@pytest.fixture(name="public_key")
def _public_key(keypair: tuple[bytes, Any]) -> Any:
    return keypair[1]


@pytest.fixture(name="private_pem")
def _private_pem(keypair: tuple[bytes, Any]) -> bytes:
    return keypair[0]


@pytest.fixture(name="jwks")
def _jwks(monkeypatch: pytest.MonkeyPatch, public_key: Any) -> Any:
    """Patch the network boundary only, so the real issuer check still runs.

    ``_open_discovery`` is the HTTP seam; ``_fetch_discovery`` (which performs
    the ``issuer`` comparison) is deliberately left real, so every test below
    exercises the issuer assertion rather than replacing it.
    """
    monkeypatch.setattr(
        tokens,
        "_open_discovery",  # pylint: disable=protected-access
        lambda _url: {"issuer": _ISSUER, "jwks_uri": _JWKS_URI},
    )
    monkeypatch.setattr(tokens.jwt, "PyJWKClient", lambda *a, **k: _FakeJWKClient(public_key))
    return public_key


def _sign(
    private_pem: bytes,
    *,
    sub: str = "sub-1",
    username: str = "alice",
    roles: tuple[str, ...] = ("wba-user",),
    aud: Any = _CLIENT_ID,
    azp: str = _CLIENT_ID,
    iss: str = _ISSUER,
    exp_delta: int = 900,
    include_exp: bool = True,
) -> str:
    """Sign a token with *private_pem* shaped like a Keycloak access token."""
    now = datetime.now(tz=timezone.utc)
    payload: dict[str, Any] = {
        "sub": sub,
        "preferred_username": username,
        "iss": iss,
        "aud": aud,
        "azp": azp,
        "iat": now,
        "realm_access": {"roles": list(roles)},
    }
    if include_exp:
        payload["exp"] = now + timedelta(seconds=exp_delta)
    return jwt.encode(payload, private_pem, algorithm="RS256", headers={"kid": "test-key"})


class TestInternalJwksUri:
    def test_rewrites_to_internal_origin(self) -> None:
        """The discovered public host is replaced by the internal origin."""
        uri = tokens._internal_jwks_uri({"jwks_uri": _JWKS_URI})  # pylint: disable=protected-access
        assert uri == (
            "http://keycloak:8080/auth/realms/wba/protocol/openid-connect/certs"
        )

    def test_no_trailing_query(self) -> None:
        """Query and fragment from the discovery URL are dropped."""
        uri = tokens._internal_jwks_uri(  # pylint: disable=protected-access
            {"jwks_uri": _JWKS_URI + "?foo=bar#frag"}
        )
        assert "?" not in uri and "#" not in uri


class TestValidateBearerToken:
    def test_valid_token_returns_principal(
        self, private_pem: bytes, jwks: Any
    ) -> None:
        """A valid token maps to a Principal with the recognised roles."""
        token = _sign(private_pem, roles=("wba-user",))
        principal = tokens.validate_bearer_token(token)
        assert principal.subject == "sub-1"
        assert principal.username == "alice"
        assert principal.roles == frozenset({"wba-user"})
        assert principal.credential is CredentialType.BEARER

    def test_unknown_roles_are_dropped(self, private_pem: bytes, jwks: Any) -> None:
        """Realm roles outside the mapped set never reach the principal."""
        token = _sign(private_pem, roles=("wba-user", "offline_access"))
        principal = tokens.validate_bearer_token(token)
        assert principal.roles == frozenset({"wba-user"})

    def test_user_and_admin_both_mapped(self, private_pem: bytes, jwks: Any) -> None:
        """Two recognised roles are both carried; ``is_admin`` is true."""
        token = _sign(private_pem, roles=("wba-user", "wba-admin"))
        principal = tokens.validate_bearer_token(token)
        assert principal.roles == frozenset({"wba-user", "wba-admin"})
        assert principal.is_admin is True

    def test_expired_token_rejected(self, private_pem: bytes, jwks: Any) -> None:
        """An expired token raises TokenValidationError."""
        token = _sign(private_pem, exp_delta=-3600)
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token(token)

    def test_missing_exp_rejected(self, private_pem: bytes, jwks: Any) -> None:
        """A token without ``exp`` fails the required-claims check."""
        token = _sign(private_pem, include_exp=False)
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token(token)

    def test_wrong_issuer_rejected(self, private_pem: bytes, jwks: Any) -> None:
        """A token from another issuer is rejected."""
        token = _sign(private_pem, iss="https://evil.example/auth/realms/wba")
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token(token)

    def test_wrong_audience_rejected(self, private_pem: bytes, jwks: Any) -> None:
        """A token minted for another client is rejected."""
        token = _sign(private_pem, aud="other-client", azp="other-client")
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token(token)

    def test_matching_aud_but_wrong_azp_rejected(
        self, private_pem: bytes, jwks: Any
    ) -> None:
        """``aud`` alone is not enough — ``azp`` must name the expected client."""
        token = _sign(private_pem, aud=[_CLIENT_ID, "account"], azp="other-client")
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token(token)

    def test_matching_azp_accepted(self, private_pem: bytes, jwks: Any) -> None:
        """A token whose ``azp`` matches is accepted even with a wider ``aud``."""
        token = _sign(private_pem, aud=[_CLIENT_ID, "account"], azp=_CLIENT_ID)
        principal = tokens.validate_bearer_token(token)
        assert principal.subject == "sub-1"

    def test_no_recognised_role_raises(self, private_pem: bytes, jwks: Any) -> None:
        """A roleless token raises NoRecognisedRoleError, never downgrades."""
        token = _sign(private_pem, roles=("offline_access", "uma_authorization"))
        with pytest.raises(tokens.NoRecognisedRoleError):
            tokens.validate_bearer_token(token)

    def test_no_recognised_role_is_token_validation_error(
        self, private_pem: bytes, jwks: Any
    ) -> None:
        """``NoRecognisedRoleError`` is a ``TokenValidationError`` subclass."""
        assert issubclass(tokens.NoRecognisedRoleError, tokens.TokenValidationError)

    def test_token_from_another_key_rejected(
        self, public_key: Any, jwks: Any
    ) -> None:
        """A token signed by a different key fails signature verification."""
        other_private, _ = _generate_keypair()
        token = _sign(other_private)
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token(token)

    def test_empty_token_rejected(self, jwks: Any) -> None:
        """An empty token raises rather than reaching decode."""
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token("")

    def test_discovery_issuer_mismatch_raises(
        self, private_pem: bytes, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A discovery issuer that disagrees with KEYCLOAK_ISSUER raises.

        The fetch seam is patched (not ``_fetch_discovery``), so the real
        issuer assertion runs. A JWKS client is stubbed to fail if it is ever
        constructed — the gate must fire before any key fetch.
        """
        monkeypatch.setattr(
            tokens,
            "_open_discovery",  # pylint: disable=protected-access
            lambda _url: {"issuer": "https://wrong.example/auth/realms/wba", "jwks_uri": _JWKS_URI},
        )
        monkeypatch.setattr(tokens.jwt, "PyJWKClient", _FailIfConstructed)
        token = _sign(private_pem)
        with pytest.raises(tokens.TokenValidationError):
            tokens.validate_bearer_token(token)

    def test_correct_issuer_passes_the_check(
        self, private_pem: bytes, jwks: Any
    ) -> None:
        """A discovery issuer equal to KEYCLOAK_ISSUER proceeds past the gate.

        The positive counterpart to the mismatch test: the assertion is a real
        gate, not an unconditional raise.
        """
        token = _sign(private_pem, roles=("wba-user",))
        principal = tokens.validate_bearer_token(token)
        assert principal.subject == "sub-1"
