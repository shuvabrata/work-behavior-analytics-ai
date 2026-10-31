"""JWKS-backed bearer-token verification and role mapping.

Verification is against the realm's cached JWKS with an explicit algorithm
allowlist and exact ``iss``/``aud`` checks. The JWKS client is built lazily so a
Keycloak that is unreachable at API startup does not block boot: the design
requires Keycloak's availability to affect only new logins.
"""

from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlsplit, urlunsplit

import jwt

from app.auth.principal import CredentialType, Principal
from app.settings import settings
from common.logger import logger

_MAPPED_ROLES = frozenset({"wba-admin", "wba-user", "wba-service"})

_ALGORITHMS = ["RS256"]

_DISCOVERY_PATH = "/.well-known/openid-configuration"


class TokenValidationError(Exception):
    """A bearer token was missing, malformed, expired, or failed a claim check."""


class NoRecognisedRoleError(TokenValidationError):
    """The token carried no wba-* realm role — rejected, never downgraded."""


def _open_discovery(url: str) -> dict[str, object]:
    """Fetch the discovery document at *url* — the network boundary."""
    with urllib.request.urlopen(url, timeout=settings.HTTP_REQUEST_TIMEOUT) as response:
        discovery: dict[str, object] = json.load(response)
    return discovery


def _fetch_discovery() -> dict[str, object]:
    """Fetch and validate the realm discovery document.

    Raises:
        TokenValidationError: The document's ``issuer`` does not match
            ``KEYCLOAK_ISSUER``.
    """
    url = settings.KEYCLOAK_INTERNAL_URL + _DISCOVERY_PATH
    discovery = _open_discovery(url)

    issuer = discovery.get("issuer")
    if issuer != settings.KEYCLOAK_ISSUER:
        logger.error(
            f"Keycloak discovery issuer {issuer!r} does not match "
            f"KEYCLOAK_ISSUER {settings.KEYCLOAK_ISSUER!r}"
        )
        raise TokenValidationError("Keycloak discovery issuer does not match KEYCLOAK_ISSUER")
    return discovery


def _internal_jwks_uri(discovery: dict[str, object]) -> str:
    """Rewrite a discovery ``jwks_uri`` onto the internal Keycloak origin.

    Keycloak builds ``jwks_uri`` from ``KC_HOSTNAME``, which is the public
    origin, so the discovered URL points at the public host and is answered only
    by nginx. Inside the API container that host is unreachable; the internal
    origin is substituted so the JWKS fetch resolves.
    """
    internal = urlsplit(settings.KEYCLOAK_INTERNAL_URL)
    public = urlsplit(str(discovery["jwks_uri"]))
    return urlunsplit((internal.scheme, internal.netloc, public.path, "", ""))


_jwks_client: jwt.PyJWKClient | None = None


def _get_jwks_client() -> jwt.PyJWKClient:
    """Return the lazily constructed, key-caching ``PyJWKClient``."""
    global _jwks_client  # pylint: disable=global-statement
    if _jwks_client is None:
        discovery = _fetch_discovery()
        _jwks_client = jwt.PyJWKClient(
            _internal_jwks_uri(discovery),
            cache_keys=True,
            timeout=settings.HTTP_REQUEST_TIMEOUT,
        )
    return _jwks_client


def _mapped_roles(claims: dict[str, object]) -> frozenset[str]:
    """Intersect the token's realm roles with the mapped role set."""
    realm_access = claims.get("realm_access")
    raw_roles: object = None
    if isinstance(realm_access, dict):
        raw_roles = realm_access.get("roles")
    if not isinstance(raw_roles, list):
        return frozenset()
    return frozenset(role for role in raw_roles if role in _MAPPED_ROLES)


def validate_bearer_token(token: str) -> Principal:
    """Verify *token* against the realm's JWKS and map it to a Principal.

    Raises:
        TokenValidationError: The token is malformed, expired, signed by an
            unknown key, or fails an ``iss``/``aud``/``azp`` check.
        NoRecognisedRoleError: The token carries no mapped ``wba-*`` role.
    """
    if not token:
        raise TokenValidationError("No bearer token supplied")

    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        claims: dict[str, object] = jwt.decode(
            token,
            signing_key.key,
            algorithms=_ALGORITHMS,
            issuer=settings.KEYCLOAK_ISSUER,
            audience=settings.KEYCLOAK_CLIENT_ID,
            leeway=30,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenValidationError(f"Bearer token rejected: {exc}") from exc

    if claims.get("azp") != settings.KEYCLOAK_CLIENT_ID:
        raise TokenValidationError("Bearer token azp does not match the expected client")

    roles = _mapped_roles(claims)
    subject = str(claims["sub"])
    username = str(claims.get("preferred_username", subject))

    if not roles:
        logger.error(
            f"Bearer token for sub={subject!r} username={username!r} carries no "
            f"recognised wba-* role"
        )
        raise NoRecognisedRoleError("Token carries no recognised role")

    logger.info(
        f"Bearer token validated for sub={subject!r} username={username!r} "
        f"roles={sorted(roles)!r}"
    )
    return Principal(
        subject=subject,
        username=username,
        roles=roles,
        credential=CredentialType.BEARER,
    )
