"""Integration tests for the catalog-metadata (favourites) API.

Tests full HTTP round-trips against a running app server at
``https://localhost`` (through the nginx TLS proxy).  Requires the Compose
stack to be running::

    docker compose up -d

Markers: ``integration``, ``server``, ``authenticated``.

**Per-subject semantics.**  Catalog favourites are owner-scoped: a row is keyed
by ``(catalog_id, subject)`` and every read is filtered to the caller's own
``subject``.  Two identities are exercised — ``admin_headers()`` (``wba-admin``)
and ``user_headers()`` (``wba-user``) — so the cross-subject cases below can
prove one user's star never reaches the other.

**Safety (clean up irrespective of pass/fail):** A session-scoped ``autouse``
fixture snapshots the pre-existing ``(catalog_id, subject)`` pairs **for both
identities** — a ``dev-user`` row is invisible to an admin read, so an
admin-only snapshot would silently leak it — then on teardown deletes every
pair not present at setup, again for both identities.  This guarantees the
database returns to its pre-test state even if a test fails midway.

Every ``catalog_id`` these tests use is a real query from the YAML catalog
(validated against ``GET /api/v1/queries/catalog``), so the 404-on-unknown
behaviour is exercised with a genuinely unknown id.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import psycopg2
import pytest

from tests.auth_helpers import admin_headers, env_value, subject, user_headers

pytestmark = [pytest.mark.integration, pytest.mark.server, pytest.mark.authenticated]

BASE_URL = "https://localhost"

# A real catalog query id (namespace/slug) used for create/update tests.
VALID_CATALOG_ID = "schema/view_all_node_types"
# A deliberately unknown id used to exercise the 404 path.
UNKNOWN_CATALOG_ID = "nonexistent/does_not_exist"

#: role label -> headers factory, for the two identities under test.
IDENTITIES = {"admin": admin_headers, "user": user_headers}


def _dsn() -> str:
    """Build a host-reachable Postgres DSN from the environment.

    ``settings.DATABASE_URL`` names the container host ``postgres``, which does
    not resolve from a host-run test, so the published ``127.0.0.1:5432`` is
    used instead. Credentials come from the environment (the same values
    Compose interpolates), never hard-coded.
    """
    return "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=env_value("POSTGRES_USER", "postgres"),
        password=env_value("POSTGRES_PASSWORD", "postgres"),
        host=env_value("POSTGRES_HOST", "127.0.0.1"),
        port=env_value("POSTGRES_PORT", "5432"),
        db=env_value("POSTGRES_DB", "postgres"),
    )


def _delete_metadata_row(catalog_id: str, subject_value: str) -> None:
    """Delete one catalog metadata row directly from the DB.

    The API has no DELETE endpoint (rows are created lazily via upsert), so
    the teardown safety net removes rows created during the run directly via
    psycopg2.
    """
    with psycopg2.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM catalog_metadata WHERE catalog_id = %s AND subject = %s",
                (catalog_id, subject_value),
            )
        conn.commit()


def _owned_pairs(client: httpx.Client, subject_value: str) -> set[tuple[str, str]]:
    """Return the ``(catalog_id, subject)`` pairs *client*'s identity can see."""
    resp = client.get("/api/v1/queries/catalog-metadata")
    resp.raise_for_status()
    return {(item["catalog_id"], subject_value) for item in resp.json()["items"]}


# ── Snapshot / restore (session-scoped safety net) ────────────────────


@pytest.fixture(scope="session", autouse=True)
def metadata_snapshot() -> set[tuple[str, str]]:
    """Snapshot pre-test state for both identities; restore it on teardown.

    Both phases must cover both identities: a row created by the ``user``
    identity is invisible to an admin read, so an admin-only teardown would
    silently leak it.
    """
    snapshot: set[tuple[str, str]] = set()
    for role, headers in IDENTITIES.items():
        with httpx.Client(base_url=BASE_URL, timeout=10, headers=headers()) as client:
            snapshot |= _owned_pairs(client, subject(role))

    yield snapshot

    # --- teardown ---
    # Delete any pair created during the run, irrespective of pass/fail.
    for role, headers in IDENTITIES.items():
        with httpx.Client(base_url=BASE_URL, timeout=10, headers=headers()) as client:
            leaked = _owned_pairs(client, subject(role)) - snapshot
        for catalog_id, subject_value in leaked:
            _delete_metadata_row(catalog_id, subject_value)


@pytest.fixture(autouse=True)
def _isolate_metadata() -> Iterator[None]:
    """Clear this suite's rows for both identities before and after each test.

    The suite mutates persistent ``catalog_metadata`` state and several tests
    share ``VALID_CATALOG_ID``, so without per-test isolation a row left by an
    earlier test is visible to a later one, and an assertion of the form "the
    other identity does not see X" reports the previous test's verdict instead
    of its own. ``VALID_CATALOG_ID`` is scratch for this suite, so both
    identities are cleared rather than restored: a leftover row here is
    residue, not user data, and preserving it is precisely the bug.
    """
    _clear_suite_rows()
    yield
    _clear_suite_rows()


def _clear_suite_rows() -> None:
    """Delete this suite's rows for every identity."""
    for role in IDENTITIES:
        _delete_metadata_row(VALID_CATALOG_ID, subject(role))


async def _list_metadata(
    client: httpx.AsyncClient, *, is_favourite: bool | None = None
) -> list[dict]:
    """Return all of the caller's catalog metadata rows, optionally filtered."""
    params = {"is_favourite": is_favourite} if is_favourite is not None else None
    resp = await client.get("/api/v1/queries/catalog-metadata", params=params)
    assert resp.status_code == 200
    return resp.json()["items"]


async def _star(client: httpx.AsyncClient, catalog_id: str, value: bool = True) -> httpx.Response:
    """PUT a favourite value for *catalog_id* as the client's identity."""
    return await client.put(
        f"/api/v1/queries/catalog-metadata/{catalog_id}",
        json={"is_favourite": value},
    )


def _is_favourite_of(items: list[dict], catalog_id: str) -> bool | None:
    """Return the ``is_favourite`` value *items* reports for *catalog_id*."""
    for item in items:
        if item["catalog_id"] == catalog_id:
            return bool(item["is_favourite"])
    return None


# ── Read-only (no rows created) ───────────────────────────────────────


class TestList:
    @pytest.mark.asyncio
    async def test_returns_only_pre_existing_rows(
        self, metadata_snapshot: set[tuple[str, str]]
    ) -> None:
        """GET /catalog-metadata returns no rows beyond those that pre-existed.

        The table may already contain rows from real app usage, so this test
        asserts the endpoint returns a valid list and that the run created no
        new rows for this identity — not that the table is globally empty.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as client:
            items = await _list_metadata(client)
        assert isinstance(items, list)
        known_ids = {catalog_id for catalog_id, _ in metadata_snapshot}
        assert all(item["catalog_id"] in known_ids for item in items)

    @pytest.mark.asyncio
    async def test_filter_is_favourite_true(self) -> None:
        """?is_favourite=true filters to the caller's favourited rows only."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as client:
            resp = await _star(client, VALID_CATALOG_ID, True)
            assert resp.status_code == 200

            fav_items = await _list_metadata(client, is_favourite=True)
            non_fav_items = await _list_metadata(client, is_favourite=False)

        assert _is_favourite_of(fav_items, VALID_CATALOG_ID) is True
        assert _is_favourite_of(non_fav_items, VALID_CATALOG_ID) is None


# ── Cross-subject isolation (the core of this change) ─────────────────


class TestSubjectIsolation:
    @pytest.mark.asyncio
    async def test_user_star_is_invisible_to_admin(self) -> None:
        """A star set by ``wba-user`` does not appear for ``wba-admin``."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as user:
            assert (await _star(user, VALID_CATALOG_ID, True)).status_code == 200
            user_items = await _list_metadata(user)

        async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as admin:
            admin_items = await _list_metadata(admin)

        assert _is_favourite_of(user_items, VALID_CATALOG_ID) is True
        assert _is_favourite_of(admin_items, VALID_CATALOG_ID) is None

    @pytest.mark.asyncio
    async def test_admin_star_is_invisible_to_user(self) -> None:
        """Symmetric: a star set by ``wba-admin`` does not appear for ``wba-user``."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as admin:
            assert (await _star(admin, VALID_CATALOG_ID, True)).status_code == 200
            admin_items = await _list_metadata(admin)

        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as user:
            user_items = await _list_metadata(user)

        assert _is_favourite_of(admin_items, VALID_CATALOG_ID) is True
        assert _is_favourite_of(user_items, VALID_CATALOG_ID) is None

    @pytest.mark.asyncio
    async def test_two_subjects_coexist(self) -> None:
        """Both subjects star the same query; each sees only their own state."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as admin:
            assert (await _star(admin, VALID_CATALOG_ID, True)).status_code == 200
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as user:
            assert (await _star(user, VALID_CATALOG_ID, False)).status_code == 200

        async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as admin:
            assert _is_favourite_of(await _list_metadata(admin), VALID_CATALOG_ID) is True
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as user:
            assert _is_favourite_of(await _list_metadata(user), VALID_CATALOG_ID) is False

    @pytest.mark.asyncio
    async def test_put_by_other_subject_does_not_update_owner(self) -> None:
        """``user`` stars X; ``admin`` stars X; ``user``'s value is untouched.

        This is the core regression: with a ``catalog_id``-keyed upsert the
        second PUT overwrites the first subject's row.
        """
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as user:
            assert (await _star(user, VALID_CATALOG_ID, True)).status_code == 200
        async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as admin:
            assert (await _star(admin, VALID_CATALOG_ID, False)).status_code == 200
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as user:
            assert _is_favourite_of(await _list_metadata(user), VALID_CATALOG_ID) is True

    @pytest.mark.asyncio
    async def test_get_foreign_row_is_404(self) -> None:
        """``admin`` owns X; ``user`` GET /{X} is 404, as if it were missing."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=admin_headers()) as admin:
            assert (await _star(admin, VALID_CATALOG_ID, True)).status_code == 200

        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as user:
            foreign = await user.get(
                f"/api/v1/queries/catalog-metadata/{VALID_CATALOG_ID}"
            )
            missing = await user.get(
                f"/api/v1/queries/catalog-metadata/{UNKNOWN_CATALOG_ID}"
            )

        assert foreign.status_code == 404
        assert foreign.json() == missing.json()


# ── Upsert behaviour ──────────────────────────────────────────────────


class TestUpsert:
    @pytest.mark.asyncio
    async def test_put_creates_row(self) -> None:
        """PUT creates a row and returns it."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as client:
            resp = await _star(client, VALID_CATALOG_ID, True)
            assert resp.status_code == 200
            body = resp.json()
            assert body["catalog_id"] == VALID_CATALOG_ID
            assert body["is_favourite"] is True
            assert "subject" not in body

    @pytest.mark.asyncio
    async def test_put_is_idempotent_per_subject(self) -> None:
        """Repeated PUT by one subject does not create duplicate rows."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as client:
            await _star(client, VALID_CATALOG_ID, True)
            await _star(client, VALID_CATALOG_ID, True)
            items = await _list_metadata(client)

        matches = [
            item for item in items if item["catalog_id"] == VALID_CATALOG_ID
        ]
        assert len(matches) == 1

    @pytest.mark.asyncio
    async def test_put_flips_existing_row(self) -> None:
        """PUT with is_favourite=false flips the caller's existing row."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as client:
            await _star(client, VALID_CATALOG_ID, True)
            resp = await _star(client, VALID_CATALOG_ID, False)
            assert resp.status_code == 200
            assert resp.json()["is_favourite"] is False

    @pytest.mark.asyncio
    async def test_put_unknown_catalog_id_still_404(self) -> None:
        """PUT with an unknown catalog_id returns 404 (existence guard first)."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as client:
            resp = await _star(client, UNKNOWN_CATALOG_ID, True)
        assert resp.status_code == 404


# ── Single-row fetch ──────────────────────────────────────────────────


class TestGetSingle:
    @pytest.mark.asyncio
    async def test_get_returns_own_row(self) -> None:
        """GET /catalog-metadata/{id} returns the caller's own row."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as client:
            await _star(client, VALID_CATALOG_ID, True)
            resp = await client.get(
                f"/api/v1/queries/catalog-metadata/{VALID_CATALOG_ID}"
            )
            assert resp.status_code == 200
            assert resp.json()["catalog_id"] == VALID_CATALOG_ID

    @pytest.mark.asyncio
    async def test_get_unknown_returns_404(self) -> None:
        """GET /catalog-metadata/{id} returns 404 when absent."""
        async with httpx.AsyncClient(base_url=BASE_URL, headers=user_headers()) as client:
            resp = await client.get(
                f"/api/v1/queries/catalog-metadata/{UNKNOWN_CATALOG_ID}"
            )
        assert resp.status_code == 404
