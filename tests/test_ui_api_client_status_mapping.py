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

    def _fake_transport(
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> _StubResponse:
        return response

    monkeypatch.setattr(api_client, "_transport", _fake_transport)


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
# Half 1b — the five verb helpers, one contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verb", ["get", "post", "put", "patch", "delete"])
def test_every_verb_raises_the_single_api_error(
    monkeypatch: pytest.MonkeyPatch, verb: str
) -> None:
    """``get``/``post``/``put``/``patch``/``delete`` all raise ``ApiError``.

    Step 10's migration put every UI call site through these five helpers, so
    a verb that returned a raw response for a non-2xx would reintroduce the
    dead-handler bug one page at a time.
    """
    _install_transport(monkeypatch, _StubResponse(500, {"detail": {"message": "boom"}}))
    with pytest.raises(ApiError) as excinfo:
        getattr(api_client, verb)("/api/v1/anything")
    assert excinfo.value.status_code == 500


def test_verb_returns_the_response_on_2xx(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 2xx is returned verbatim so callers can still read headers/status."""
    _install_transport(monkeypatch, _StubResponse(200, {"items": []}))
    response = api_client.get("/api/v1/anything")
    assert response.status_code == 200
    assert response.json() == {"items": []}


def test_transport_failure_raises_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request that never reaches the API raises the same single type.

    ``ApiError`` carries ``STATUS_NO_RESPONSE`` (0) — a value no real HTTP
    status takes — so a caller can tell "no response" from a 4xx without a
    second exception type.
    """
    import requests

    def _failing(*_args: Any, **_kwargs: Any) -> _StubResponse:
        raise requests.exceptions.ConnectionError("Connection refused")

    monkeypatch.setattr(api_client, "_transport", _failing)
    with pytest.raises(ApiError) as excinfo:
        api_client.get("/api/v1/anything")
    assert excinfo.value.status_code == api_client.STATUS_NO_RESPONSE


def test_plain_string_detail_is_the_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """A plain-string ``detail`` is surfaced as the error message.

    The migrated handlers show ``str(exc)`` to the user; before this, a
    ``{"detail": "Catalog query not found"}`` body (which many routers return)
    fell through to the raw JSON text.
    """
    _install_transport(
        monkeypatch,
        _StubResponse(404, {"detail": "Catalog query not found"},
                      text='{"detail":"Catalog query not found"}'),
    )
    with pytest.raises(ApiError) as excinfo:
        api_client.get("/api/v1/anything")
    assert str(excinfo.value) == "Catalog query not found"


def test_timeout_is_read_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    """The timeout is read from the runtime-settings cache on every call.

    A value captured at import is the bug class Step 6 fixed across the UI;
    this asserts the client re-reads it rather than freezing it.
    """
    from common.runtime_settings import RuntimeConfig

    captured: list[int | None] = []

    def _capture(
        _method: str, _url: str, *, params: Any = None,
        json: Any = None, timeout: int | None = None,
    ) -> _StubResponse:
        _ = params, json
        captured.append(timeout)
        return _StubResponse(200, {})

    monkeypatch.setattr(api_client, "_transport", _capture)
    previous = api_client.runtime_settings.current()
    try:
        for value in (111, 222):
            api_client.runtime_settings.refresh(
                RuntimeConfig(HTTP_REQUEST_TIMEOUT=value)
            )
            api_client.get("/api/v1/anything")
    finally:
        api_client.runtime_settings.refresh(previous)

    assert captured == [111, 222]


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
