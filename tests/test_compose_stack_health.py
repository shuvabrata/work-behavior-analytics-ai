"""Every service the Compose file declares must be up — and healthy where it can be.

Unit suites, the type checker and the linters all run where every dependency in
the repository is installed, so none of them can observe a service that
crash-loops on a missing package in its own image. A container that dies at
import time still passes ``pytest -m unit``, ``mypy src/``, ``pylint src`` and
``bandit``; only a container that is actually running betrays it. This suite is
that observation point: it asks Docker what the stack looks like and fails when a
declared service has no running container, or has one that is unhealthy or
restart-looping.

The service list comes from ``docker compose config``, not from
``docker compose ps``. That distinction is load-bearing: a service that never
started because of a bad build, a missing profile or a failed dependency has no
container for ``ps`` to report at all, so comparing ``ps`` against itself would
pass on a stack that is missing half its services.

A service is only required to report ``healthy`` if its Compose definition
declares a ``healthcheck``; asserting it otherwise would be impossible rather
than strict. Services without one — ``nginx`` and the four connector daemons —
are asserted to be running, and are listed by ``test_services_without_a_healthcheck``
so the gap stays visible rather than silently tolerated.

Requires the Compose stack::

    docker compose up -d

Run with:
    pytest -m integration tests/test_compose_stack_health.py -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[1]

_RUNNING = "running"


def _compose(*args: str) -> str:
    """Run ``docker compose`` from the repository root, failing loudly."""
    if shutil.which("docker") is None:
        pytest.fail(
            "the docker CLI is not on PATH, so the Compose stack cannot be "
            "inspected. These tests require `docker compose up -d`.",
            pytrace=False,
        )
    completed = subprocess.run(
        ["docker", "compose", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"`docker compose {' '.join(args)}` failed with exit code "
            f"{completed.returncode}: {completed.stderr.strip()}",
            pytrace=False,
        )
    return completed.stdout


def _json_rows(output: str) -> list[dict[str, Any]]:
    """Parse ``--format json``'s one-object-per-line output."""
    return [json.loads(line) for line in output.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def declared_services() -> dict[str, dict[str, Any]]:
    """Every service the Compose file declares, healthcheck or not."""
    payload = json.loads(_compose("config", "--format", "json"))
    services: dict[str, dict[str, Any]] = payload.get("services") or {}
    assert services, "`docker compose config` reported no services — nothing to check"
    return services


@pytest.fixture(scope="module")
def containers() -> dict[str, dict[str, Any]]:
    """Every container Compose knows about, running or not, keyed by service."""
    rows = _json_rows(_compose("ps", "--all", "--format", "json"))
    assert rows, (
        "`docker compose ps --all` reported no containers. The stack is not up — "
        "run `docker compose up -d`."
    )
    return {row["Service"]: row for row in rows}


def _describe(row: dict[str, Any]) -> str:
    """A container's Compose status line, for a failure message."""
    return f"{row['State']} ({row.get('Status') or 'no status'})"


def test_every_declared_service_has_a_running_container(
    declared_services: dict[str, dict[str, Any]],
    containers: dict[str, dict[str, Any]],
) -> None:
    """No declared service may be absent, stopped or restart-looping.

    A crash-looping container reports ``restarting``, so this catches the failure
    mode where a service dies at import time and Compose restarts it forever —
    the container exists and the stack looks almost up, but the service is doing
    no work.
    """
    problems: list[str] = []
    for name in sorted(declared_services):
        row = containers.get(name)
        if row is None:
            problems.append(f"{name}: no container at all")
        elif row["State"] != _RUNNING:
            problems.append(f"{name}: {_describe(row)}")
    assert not problems, "not running:\n  " + "\n  ".join(problems)


def test_services_declaring_a_healthcheck_are_healthy(
    declared_services: dict[str, dict[str, Any]],
    containers: dict[str, dict[str, Any]],
) -> None:
    """Every service with a ``healthcheck`` must report ``healthy``.

    ``starting`` is a failure too: the readiness gate is what the rest of the
    stack depends on, so a service still inside its start period when the suite
    runs has not yet proven itself.
    """
    problems: list[str] = []
    checked = 0
    for name, spec in sorted(declared_services.items()):
        if not spec.get("healthcheck"):
            continue
        checked += 1
        row = containers.get(name)
        if row is None:
            problems.append(f"{name}: no container to report health")
        elif row.get("Health") != "healthy":
            problems.append(f"{name}: health={row.get('Health') or 'none'}, {_describe(row)}")
    assert checked, "no service in the Compose file declares a healthcheck — nothing was verified"
    assert not problems, "not healthy:\n  " + "\n  ".join(problems)


def test_services_without_a_healthcheck_are_running(
    declared_services: dict[str, dict[str, Any]],
    containers: dict[str, dict[str, Any]],
) -> None:
    """Services without a ``healthcheck`` can only be asserted to be running.

    This test is deliberately weaker than the one above. It exists so those
    services are still covered, and so the set is named out loud instead of
    being mistaken for "healthy" in a stack-wide summary.
    """
    without = sorted(name for name, spec in declared_services.items() if not spec.get("healthcheck"))
    problems: list[str] = []
    for name in without:
        row = containers.get(name)
        if row is None:
            problems.append(f"{name}: no container at all")
        elif row["State"] != _RUNNING:
            problems.append(f"{name}: {_describe(row)}")
    assert not problems, (
        f"services without a healthcheck are not running ({', '.join(without)}):\n  "
        + "\n  ".join(problems)
    )
