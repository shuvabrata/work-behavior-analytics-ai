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
from pathlib import Path

import pytest

from app.settings import settings


@pytest.fixture(autouse=True)
def _disable_timeline_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the dev-only activity-timeline mock off for all tests."""
    monkeypatch.setattr(settings, "TIMELINE_MOCK_SCENARIO", "")


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
