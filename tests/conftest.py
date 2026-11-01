"""Shared pytest configuration for the test suite.

Two concerns live here:

1. The Activity Timeline API supports a dev-only mock mode controlled by the
   ``TIMELINE_MOCK_SCENARIO`` env var (used for manual UI QA). It must never leak
   into the test suite: a developer who enabled it in their local ``.env`` would
   otherwise see invented data satisfy API assertions. Force it off for every
   test; tests that need it set override it explicitly with ``monkeypatch``.

2. The server-marked integration tests talk to the application through the nginx
   TLS proxy at ``https://localhost``, so ``httpx`` must trust the locally issued
   certificate. ``httpx`` verifies against ``certifi``'s bundle rather than the
   system store, so the local CA has to be supplied explicitly; see
   ``_trust_local_ca`` below.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import Request

from app.settings import settings


@pytest.fixture(autouse=True)
def _disable_timeline_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the dev-only activity-timeline mock off for all tests."""
    monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "")


@pytest.fixture(autouse=True)
def _ensure_connector_encryption_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply a Fernet key when the environment has none.

    ``CONNECTOR_ENCRYPTION_KEY`` defaults to empty and is validated at use time,
    so any test that reaches the cookie/PKCE/refresh-token helpers through the
    real app raises ``RuntimeError`` when the key is unset. Locally a developer's
    ``.env`` supplies one, but ``.env`` is gitignored and CI sets no such
    variable, so the suite failed there for reasons unrelated to what it asserts.
    Generating a key per session keeps the encrypted-value tests exercising real
    Fernet round-trips instead of skipping them.
    """
    if settings.CONNECTOR_ENCRYPTION_KEY:
        return
    from cryptography.fernet import Fernet

    monkeypatch.setattr(
        settings, "CONNECTOR_ENCRYPTION_KEY", Fernet.generate_key().decode()
    )


@pytest.fixture(autouse=True)
def _admin_principal_by_default() -> Iterator[None]:
    """Authenticate every credential-less API test as an admin.

    Enforcement lives in FastAPI dependencies, so one override covers the ~15
    files that drive the real app through httpx.ASGITransport. Auth-specific
    tests clear it and set their own principal (see
    tests/test_authz_enforcement.py), which is why the fixture also provides the
    `unauthenticated` helper below.

    A request that carries its own credential — an ``Authorization`` header or a
    ``wba_session`` cookie — falls through to the real ``get_principal`` instead
    of the admin default, so tests that assert real bearer/cookie rejection
    (tests/test_auth_flow.py::TestMe) still observe the verifier rather than the
    override.

    Imports live inside the fixture body so tests/conftest.py does not import
    app.api_main at collection time — that constructs the LLM provider and reads
    settings for suites that never touch the API.
    """
    from app.api_main import app
    from app.auth.dependencies import get_principal
    from app.auth.principal import Principal
    from app.auth.session_cookie import SESSION_COOKIE_NAME

    async def _override(request: Request) -> Principal:
        if request.headers.get("authorization") or request.cookies.get(SESSION_COOKIE_NAME):
            return await get_principal(request)
        return Principal(
            subject="test-admin",
            username="test-admin",
            roles=frozenset({"wba-admin", "wba-user"}),
        )

    app.dependency_overrides[get_principal] = _override
    yield
    app.dependency_overrides.pop(get_principal, None)


@pytest.fixture
def unauthenticated() -> Iterator[None]:
    """Clear the principal override so requests reach get_principal for real."""
    from app.api_main import app
    from app.auth.dependencies import get_principal

    app.dependency_overrides.pop(get_principal, None)
    yield


def _resolve_local_ca() -> Path | None:
    """Locate mkcert's local CA certificate, or return ``None`` if absent.

    Checked in order:

    1. ``mkcert -CAROOT`` — authoritative, and works without the Linux trust-store
       install. Requires the ``mkcert`` binary on ``PATH``.
    2. The system trust store, populated by ``mkcert -install``.
    """
    try:
        caroot = subprocess.run(
            ["mkcert", "-CAROOT"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        caroot = ""

    if caroot:
        ca = Path(caroot) / "rootCA.pem"
        if ca.is_file():
            return ca

    for candidate in sorted(Path("/usr/local/share/ca-certificates").glob("mkcert*.crt")):
        return candidate

    return None


_LOCAL_CA: Path | None = None
_LOCAL_CA_RESOLVED = False


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Trust the local mkcert CA, for ``server``-marked tests only.

    Those tests reach the app over HTTPS through the nginx proxy at
    ``https://localhost``, and ``httpx`` verifies against ``certifi`` rather than
    the system store, so the local CA must be injected via ``SSL_CERT_FILE``
    (read by ``httpx`` at request time).

    **Scoped to ``server``-marked tests deliberately.** An autouse session
    fixture would apply to every test in the run — including the unit tests CI
    executes — and CI has neither mkcert nor the system trust-store copy, so an
    unconditional failure would error out the entire suite on a machine that
    never needs the CA. That regression is why this is a per-test hook rather
    than a fixture.

    Verification is left **on** — the point is to prove the certificate chain is
    valid, not to bypass it. A ``server`` test with no resolvable CA is **failed
    loudly**, not skipped: a silent skip would hide a stack that is not actually
    reachable.
    """
    global _LOCAL_CA, _LOCAL_CA_RESOLVED

    if not item.get_closest_marker("server"):
        return

    if not _LOCAL_CA_RESOLVED:
        _LOCAL_CA = _resolve_local_ca()
        _LOCAL_CA_RESOLVED = True

    if _LOCAL_CA is None:
        pytest.fail(
            "Could not locate the mkcert local CA, so https://localhost cannot be "
            "verified. Run `mkcert -install` and generate the certificate per "
            "USER_GUIDE.md, or ensure the mkcert binary is on PATH. These tests "
            "require the Compose stack to be running (docker compose up -d).",
            pytrace=False,
        )

    os.environ["SSL_CERT_FILE"] = str(_LOCAL_CA)
