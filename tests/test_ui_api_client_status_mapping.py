"""Guards on the UI client's two error-translation halves.

The UI reached Neo4j/Elasticsearch in-process until Step 7 of plan 052, where
the three bypasses became HTTP calls through ``ui.api_client``. That swap has
two halves, and each is a distinct failure mode:

1. **The client turns a status into ``ApiError``.** A raw ``requests.get``
   returns a ``Response`` for a 404; the old in-process call *raised*
   ``CollaborationDataUnavailable``. Without this half the collab callbacks'
   ``except`` blocks would go dead and the page would render "An unexpected
   error occurred." for an empty but legitimate result.
2. **The collaboration helper turns ``ApiError`` into the domain errors the
   callbacks catch** — and *only* the collaboration errors. A 404 whose
   ``detail.error`` differs (a wrong URL) must be re-raised unchanged, or the
   user is told "you have no collaborations" because a route was mistyped.

The baseline script cannot cover either half (its ``in_process`` leg calls the
services directly and never passes through ``api_client``), so this file is the
only automated guard on the mapping.
"""

from __future__ import annotations

from typing import Any

import pytest

from domain.collaboration.errors import CollaborationDataUnavailable
from ui import api_client
from ui.api_client import ApiError
from ui.collaboration_params import translate_api_error

pytestmark = pytest.mark.unit


class _StubResponse:
    """Minimal stand-in for ``requests.Response`` for the transport seam."""

    def __init__(self, status_code: int, payload: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> Any:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _install_transport(monkeypatch: pytest.MonkeyPatch, response: _StubResponse) -> None:
    """Point ``api_client``'s transport seam at a canned response."""

    def _fake_call(
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> _StubResponse:
        return response

    monkeypatch.setattr(api_client, "_call", _fake_call)


# ---------------------------------------------------------------------------
# Half 1 — the client turns a status into ApiError, and nothing else
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 404, 500])
def test_non_2xx_raises_api_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Every non-2xx becomes the one transport-level type, carrying the status."""
    _install_transport(
        monkeypatch,
        _StubResponse(status, {"detail": {"error": "boom", "message": "boom"}}),
    )
    with pytest.raises(ApiError) as excinfo:
        api_client.get_json("/api/v1/anything")
    assert excinfo.value.status_code == status


@pytest.mark.parametrize("status", [400, 404, 500])
def test_client_raises_only_api_error(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """The generic client must not raise a domain type.

    ``CollaborationDataUnavailable`` (a ``LookupError``) and ``ValueError`` are
    the collaboration callbacks' vocabulary, not the client's. If the client
    raised them, Step 10's single-type contract (one exception carrying
    ``status_code`` — Gate 10 check 3) could not be satisfied.
    """
    _install_transport(
        monkeypatch,
        _StubResponse(status, {"detail": {"error": CollaborationDataUnavailable.__name__}}),
    )
    with pytest.raises(ApiError) as excinfo:
        api_client.get_json("/api/v1/anything")
    assert not isinstance(excinfo.value, (CollaborationDataUnavailable, ValueError))


def test_post_json_raises_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The POST path (the spotlight's scoped search) has the same contract."""
    _install_transport(monkeypatch, _StubResponse(404, {"detail": {"error": "x"}}))
    with pytest.raises(ApiError) as excinfo:
        api_client.post_json("/api/v1/search/scoped", json={"q": "x", "ids": []})
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# Half 2 — the collaboration helper maps ApiError to the domain types
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (
            ApiError(404, detail_error="No collaboration data", message="no data"),
            CollaborationDataUnavailable,
        ),
        (
            ApiError(
                400,
                detail_error="Invalid collaboration configuration",
                message="bad",
            ),
            ValueError,
        ),
    ],
)
def test_translate_api_error_maps_to_domain_type(
    exc: ApiError, expected: type[BaseException]
) -> None:
    """The collab call sites must keep receiving the types their except blocks catch.

    Regression guard: a raw ``requests.get`` returns a Response, so the
    ``except CollaborationDataUnavailable`` branch went dead and the page
    rendered "An unexpected error occurred." instead of the real banner.
    """
    with pytest.raises(expected):
        translate_api_error(exc)


def test_translate_api_error_re_raises_unrelated_404() -> None:
    """A 404 that is *not* the collaboration error passes through unchanged.

    A wrong URL also answers 404. Mapping it to ``CollaborationDataUnavailable``
    would tell the user "no collaborations in this window" because a route was
    mistyped — so the mapping is keyed on ``detail.error``, not the bare status.
    """
    exc = ApiError(404, detail_error="Not Found", message="not found")
    with pytest.raises(ApiError) as excinfo:
        translate_api_error(exc)
    assert excinfo.value is exc


def test_translate_api_error_re_raises_unrelated_status() -> None:
    """A 500 is neither an empty result nor a config error — it passes through."""
    exc = ApiError(500, detail_error="Execution failed", message="boom")
    with pytest.raises(ApiError):
        translate_api_error(exc)
