"""Guard the UI runtime's isolation: ``src/ui/**`` must import with no driver.

The UI container ships no database driver, no data-store credentials and no LLM
provider key. Nothing in the test suite, the Dockerfile or the type checker
catches a UI module that transitively reaches one of those packages — the suite
runs where the packages are installed, ``mypy`` never imports the modules, and
``ui_main.py``'s own imports say nothing about ``create_dash_app()``'s transitive
``pages/`` tree. So this test imports every ``src/ui/**`` module in a process
where the DB/LLM packages are genuinely absent.

Any module that cannot import under those conditions is a boot-time crash in the
UI container. Before Step 6 of plan 052, 25 UI files imported
``app.runtime_settings`` / ``app.common.timezone`` / ``app.settings``, each of
which pulls ``sqlalchemy`` or requires ``DATABASE_URL``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_PENDING_STEP_7: set[str] = set()
# Drained in Step 7: the five modules that used to reach ``neo4j``/``elasticsearch``
# through the in-process bypasses (collab filter, ego filter, spotlight, and the
# ``layout`` import pulling all three page packages) now go over HTTP through
# ``ui.api_client``. The set stays as an empty, asserted sentinel so a future UI
# module that reaches a driver fails this test rather than passing via a stale
# allowance.

# The worker runs in a fresh interpreter so ``sys.modules`` holds no copy of the
# blocked packages: a finder that only intercepts *new* imports would otherwise
# pass vacuously the moment any earlier test imported ``sqlalchemy``.
_WORKER = r"""
import importlib
import json
import pkgutil
import sys

BLOCKED = {
    "sqlalchemy", "asyncpg", "neo4j", "elasticsearch", "openai", "aio_pika",
    "matplotlib", "networkx", "community", "langchain", "langchain_core", "mcp",
}


class _Blocker:
    def find_spec(self, fullname, path=None, target=None):
        top = fullname.split(".")[0]
        if top in BLOCKED:
            raise ModuleNotFoundError(f"No module named {top!r} (UI image)", name=fullname)
        return None


# Import one blocked package normally, then prove the finder actually blocks it.
import sqlalchemy  # noqa: F401,E402
sys.meta_path.insert(0, _Blocker())
del sys.modules["sqlalchemy"]
try:
    importlib.import_module("sqlalchemy")
except ModuleNotFoundError:
    blocker_effective = True
else:
    blocker_effective = False

failures = {}
if blocker_effective:
    import ui

    def _record(name):
        failures[name] = True

    for info in pkgutil.walk_packages(ui.__path__, prefix="ui.", onerror=_record):
        try:
            importlib.import_module(info.name)
        except Exception:  # pylint: disable=broad-except
            failures[info.name] = True

print(json.dumps({"blocker_effective": blocker_effective, "failures": sorted(failures)}))
"""


def _walk_ui_with_packages_blocked() -> set[str]:
    """Return the set of ``ui.*`` modules that fail to import without a driver."""
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", _WORKER],
        capture_output=True,
        text=True,
        cwd=str(repo_root),
        env={**_py_path_env(repo_root)},
        timeout=600,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    assert payload["blocker_effective"], "the import blocker was inert — test is vacuous"
    return set(payload["failures"])


def _py_path_env(repo_root: Path) -> dict[str, str]:
    import os

    src = str(repo_root / "src")
    existing = os.environ.get("PYTHONPATH", "")
    return {"PYTHONPATH": f"{src}{os.pathsep}{existing}" if existing else src}


def test_ui_modules_import_without_db_or_llm_packages() -> None:
    """Every src/ui/** module must import with no database driver present.

    Regression guard: 25 UI files imported app.runtime_settings /
    app.common.timezone / app.settings, each of which pulls sqlalchemy or
    requires DATABASE_URL. The UI image ships neither, so the container
    crash-looped at boot with ModuleNotFoundError while every other gate
    passed.

    ``_PENDING_STEP_7`` is now empty: Step 7 replaced the four in-process
    bypasses (collab filter, ego filter, spotlight, and the ``layout`` import
    that pulled all three page packages) with HTTP calls, so the full blocked
    walk — including ``neo4j``/``elasticsearch`` — must pass with no exemptions.
    The set is kept and asserted empty so a future UI module that reaches a
    driver fails here rather than passing via a stale allowance.
    """
    failures = _walk_ui_with_packages_blocked()
    unexpected = sorted(set(failures) - _PENDING_STEP_7)
    assert not unexpected, unexpected
    assert not _PENDING_STEP_7, _PENDING_STEP_7
