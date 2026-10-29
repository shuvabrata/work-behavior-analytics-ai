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

_PENDING_STEP_7 = {
    "ui.layout",
    "ui.pages.collaboration_network",
    "ui.pages.collaboration_network_ego",
    "ui.pages.graph",
    "ui.components.spotlight",
}  # reach neo4j/ES via the 4 in-process bypasses Step 7 swaps. MUST be empty
# after Step 7 — see the plan's Step 7 gate.

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

    ``_PENDING_STEP_7`` is a *staging* allowance, not a permanent one: the five
    modules in it reach ``neo4j``/``elasticsearch`` through the four in-process
    bypasses (collab filter, ego filter, spotlight, and the ``layout`` import
    that pulls all three page packages) which Step 7 replaces with HTTP calls.
    Remove the set — and assert it is empty — in Step 7, the step that makes
    that true.
    """
    failures = _walk_ui_with_packages_blocked()
    unexpected = sorted(set(failures) - _PENDING_STEP_7)
    assert not unexpected, unexpected
