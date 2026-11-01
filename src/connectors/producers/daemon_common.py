"""Shared daemon infrastructure for producer containers.

Provides the ``producer_main()`` entry point that handles ``--mode daemon``
(default), ``--mode scan``, and ``--mode test`` CLI dispatch.  The daemon
mode uses a sync ``pika`` loop to consume commands from the
``command_n_control`` exchange and spawns child processes via
``subprocess.Popen``.  Children are reaped by a ``SIGCHLD`` handler.  The
scan mode parses the command arguments and runs the producer's async scan
logic.  The test mode runs a lightweight connectivity check (same config
loading, no data publishing).

Usage in a producer's ``main.py``::

    from connectors.producers.daemon_common import producer_main

    def main():
        producer_main(
            description="GitHub Producer",
            default_container="github-producer",
            producer_main_path=__file__,
            scan_func=main_async,
            test_func=test_connection,
        )
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
import threading
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import aio_pika
import httpx
import pika

from common.auth import ServiceTokenError, get_service_token, invalidate_service_token
from common.command_n_control.models import CommandEnvelope, CommandStatusUpdate
from common.logger import logger
from common.runtime_settings import RuntimeConfigCache
from common.runtime_settings.client import fetch_runtime_snapshot
from common.messaging.settings_events import listen_for_settings_changed


@dataclass
class ScanResult:
    """Aggregate outcome of a one-shot scan across all configured items.

    A scan iterates over multiple configured items (GitHub repo configs,
    Jira/Confluence accounts).  Each item is processed independently and may
    fail without aborting the remaining items.  ``ScanResult`` collects those
    per-item errors so ``run_scan`` can report the scan as ``failed`` when any
    item errored, instead of always reporting ``completed``.
    """

    success: bool = True
    items_processed: int = 0
    items_succeeded: int = 0
    items_failed: int = 0
    errors: list[dict[str, str]] = field(default_factory=list)

    def add_error(self, item: str, error: str) -> None:
        """Record a failed item, updating the aggregate counters."""
        self.items_failed += 1
        self.success = False
        self.errors.append({"item": item, "error": error})

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serialisable result summary for ``result_summary``."""
        summary: dict[str, Any] = {
            "items_processed": self.items_processed,
            "items_succeeded": self.items_succeeded,
            "items_failed": self.items_failed,
        }
        if self.errors:
            summary["errors"] = self.errors
        return summary

    def error_message(self) -> str:
        """Return a concise human-readable error message for the status PATCH."""
        if self.items_failed == 0:
            return ""
        message = (
            f"{self.items_failed} of {self.items_processed} "
            f"configs failed"
        )
        if self.errors:
            first_error = self.errors[0]["error"]
            message += f". 1/{self.items_failed}: {first_error}"
        return message

# ── Module-level runtime settings cache (shared across daemon functions) ──
# Initialised with all-defaults.  Refreshed at daemon startup and at each
# scan/test child startup so child processes get a fresh snapshot without
# inheriting the parent's in-memory state.
runtime_cache: RuntimeConfigCache = RuntimeConfigCache()

# ── RabbitMQ fanout listener thread ──────────────────────────────────────
# Background daemon thread that listens for ``settings.changed`` events
# and refreshes the local runtime settings cache.  Startup failure is
# non-fatal — the process continues with the startup snapshot.
# Initialised lazily by ``run_daemon()``.
_settings_listener_thread: threading.Thread | None = None


def _start_settings_listener(rabbitmq_url: str) -> None:
    """Start a background daemon thread listening for runtime config events.

    The thread runs its own asyncio event loop with
    ``listen_for_settings_changed()``.  If the RabbitMQ connection fails,
    a warning is logged and the process continues with the startup snapshot.

    This function is idempotent: if a listener thread is already running,
    it does nothing.
    """
    global _settings_listener_thread  # noqa: PLW0603

    if _settings_listener_thread is not None and _settings_listener_thread.is_alive():
        logger.debug("Settings listener thread already running — skipping")
        return

    async def _listen() -> None:
        connection = None
        try:
            connection = await aio_pika.connect_robust(rabbitmq_url)

            async def _on_event(changed_keys: list[str]) -> None:
                logger.info(f"Daemon received settings.changed event: keys={changed_keys}")
                runtime_cache.refresh(fetch_runtime_snapshot(_api_base()))

            await listen_for_settings_changed(
                connection=connection,
                on_event=_on_event,
                instance_id=f"daemon-{os.environ.get('CONTAINER_NAME', 'unknown')}",
            )
        except Exception:  # pylint: disable=broad-except
            logger.warning(
                "Failed to start daemon settings listener — "
                "settings changes will apply on next container restart",
                exc_info=True,
            )
        finally:
            if connection is not None and not connection.is_closed:
                await connection.close()

    def _run_loop() -> None:
        asyncio.run(_listen())

    if _settings_listener_thread is None or not _settings_listener_thread.is_alive():
        thread = threading.Thread(
            target=_run_loop,
            daemon=True,
            name="settings-listener",
        )
        thread.start()
        _settings_listener_thread = thread
        logger.info("Daemon settings listener thread started")

# ── Module-level state (shared across daemon functions) ───────────────────
_children: Dict[int, uuid.UUID] = {}  # pid → command_id
_exited: Dict[int, tuple[uuid.UUID, int]] = {}  # pid → (command_id, exit code)
_test_children: Dict[int, tuple[uuid.UUID, subprocess.Popen[Any]]] = {}  # pid → (command_id, Popen[Any])
_max_scans: int = int(os.environ.get("MAX_CONCURRENT_SCANS", "5"))


def _api_base() -> str:
    """Return the base URL of the app API (lazy, respects env changes)."""
    return os.environ.get("API_SERVER", "http://localhost:8000").rstrip("/")


def _auth_headers() -> dict[str, str]:
    """Return an Authorization header for the app API, or {} if unavailable.

    A token failure must not stop status reporting: the request then goes out
    unauthenticated and the caller's existing ``except`` block handles the
    result.
    """
    try:
        return {"Authorization": f"Bearer {get_service_token()}"}
    except ServiceTokenError:
        client_id = os.environ.get("KEYCLOAK_SERVICE_CLIENT_ID", "wba-internal")
        logger.warning(f"Service token unavailable for client_id={client_id} — sending daemon request unauthenticated")
        return {}


def _api_request(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Send an authenticated request, retrying once with a fresh token on 401."""
    with httpx.Client(timeout=10) as client:
        send = getattr(client, method.lower())
        resp: httpx.Response = send(url, headers=_auth_headers(), **kwargs)
        if resp.status_code == 401:
            invalidate_service_token()
            resp = send(url, headers=_auth_headers(), **kwargs)
    return resp


def _reap_children(signum: int, frame: Any) -> None:  # pylint: disable=unused-argument
    """SIGCHLD handler — record finished children so the loop can reconcile them.

    The handler runs in signal context, so it does no HTTP work; it records the
    command id and exit code in ``_exited`` and the consume loop's idle tick
    reports them.  The exit code must be captured here rather than via
    ``Popen.poll()``: this handler has already reaped the child through
    ``os.waitpid``, so a later ``poll()`` sees ``ECHILD`` and returns ``0``,
    which would look like success.
    """
    while True:
        try:
            pid, exit_code = os.waitpid(-1, os.WNOHANG)
            if pid == 0:
                break
            command_id = _children.pop(pid, None)
            if command_id:
                logger.info(f"Child reaped pid={pid} command_id={command_id} exit_code={exit_code}")
                _exited[pid] = (command_id, exit_code)
        except ChildProcessError:
            break


def _find_pid_by_command_id(command_id: uuid.UUID) -> int | None:
    """Linear scan of ``_children`` — max 5 entries, trivially cheap."""
    for pid, cid in _children.items():
        if cid == command_id:
            return pid
    return None


def _poll_test_children() -> None:
    """Poll all test child processes and PATCH status when they finish.

    Parses the child's stdout for ``SUCCESS:`` or ``FAILED:`` prefix to
    determine the outcome, rather than relying on the exit code (which can
    be unreliable across subprocess boundary).  The error message is
    extracted into ``error_message`` for clean display in the UI.
    """
    for pid in list(_test_children.keys()):
        command_id, popen_obj = _test_children[pid]
        if popen_obj.poll() is not None:
            stdout_bytes, stderr_bytes = popen_obj.communicate()
            raw = (stdout_bytes or stderr_bytes or b"").decode("utf-8", errors="replace").strip()
            logger.debug(f"_poll_test_children pid={pid} raw_stdout={raw!r}")

            # Search for SUCCESS: / FAILED: in any line (child prints log
            # lines before the result line).
            success = None
            error_message = None
            for line in raw.split("\n"):
                stripped = line.strip()
                if stripped.startswith("SUCCESS:"):
                    success = True
                    error_message = None
                    break
                if stripped.startswith("FAILED:"):
                    success = False
                    error_message = stripped[len("FAILED: "):]
                    break

            if success is None:
                # Fallback to exit code if no recognizable prefix
                success = popen_obj.returncode == 0
                error_message = None
                logger.debug(
                    f"_poll_test_children pid={pid} no SUCCESS/FAILED prefix, falling back to returncode="
                    f"{popen_obj.returncode} success={success}"
                )

            logger.debug(f"_poll_test_children pid={pid} success={success} error_message={error_message}")

            # Advance through running first so the terminal-status PATCH
            # has a valid transition path from accepted (if the child
            # already set it, same-state is now accepted server-side).
            _update_status(command_id, CommandStatusUpdate(
                status="running", started_at=datetime.now(timezone.utc),
            ))
            _update_status(command_id, CommandStatusUpdate(
                status="completed" if success else "failed",
                completed_at=datetime.now(timezone.utc),
                error_message=error_message,
                result_summary={"message": raw},
            ))
            del _test_children[pid]


def _poll_scan_children() -> None:
    """Reconcile scan children that exited without reporting a terminal status.

    The SIGCHLD handler records exits in ``_exited``; this drains that map and
    marks any command still non-terminal as ``failed``.  A child that reported
    ``completed`` before exiting is already terminal, so
    ``_finalize_if_active`` leaves it alone.  ``_children`` is not consulted —
    ``_reap_children`` has already removed the entry.
    """
    for pid in list(_exited.keys()):
        command_id, exit_code = _exited.pop(pid)
        _finalize_if_active(
            command_id,
            error_message=f"Scan process exited unexpectedly (exit code {exit_code})",
            result_summary={"exit_code": exit_code},
        )


def _reconcile_startup_orphans(container_name: str) -> None:
    """Mark scans left ``running`` by a previous daemon instance as failed.

    Only rows in ``running`` are reconciled.  An ``accepted`` row may still be
    queued in RabbitMQ waiting for this daemon to consume it, so it is left
    alone — failing it would cancel a legitimate pending scan.
    """
    url = f"{_api_base()}/api/v1/commands/"
    try:
        resp = _api_request("GET", url, params={
            "target": container_name,
            "status": "running",
            "limit": 100,
        })
        resp.raise_for_status()
        commands = resp.json().get("commands", [])
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning(f"Startup orphan reconciliation skipped — could not list commands: {exc}")
        return

    for command in commands:
        if command.get("command_type") != "scan":
            continue
        command_id = command.get("command_id")
        if not command_id:
            continue
        try:
            parsed_id = uuid.UUID(str(command_id))
        except ValueError:
            continue
        _finalize_if_active(
            parsed_id,
            error_message="Scan interrupted: producer restarted",
        )


def _update_status(command_id: uuid.UUID, update: CommandStatusUpdate) -> None:
    """PATCH a status update to the app's API (sync)."""
    url = f"{_api_base()}/api/v1/commands/{command_id}/status"
    payload = update.model_dump(mode="json", exclude_none=True)
    logger.debug(f"PATCH {url} {payload}")
    try:
        resp = _api_request("PATCH", url, json=payload)
        logger.debug(f"Response status={resp.status_code} body={resp.text}")
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning(f"Failed to update command status ({url} → {payload.get('status')}): {exc}")


def _get_command_status(command_id: uuid.UUID) -> str | None:
    """GET a command's current status, or ``None`` if it cannot be determined.

    Returns ``None`` on any HTTP or parsing error so callers treat an
    unreadable status as "do not touch" rather than guessing.
    """
    url = f"{_api_base()}/api/v1/commands/{command_id}"
    try:
        resp = _api_request("GET", url)
        resp.raise_for_status()
        return str(resp.json().get("status"))
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        logger.warning(f"Failed to read command status ({url}): {exc}")
        return None


def _finalize_if_active(
    command_id: uuid.UUID,
    error_message: str,
    result_summary: dict[str, Any] | None = None,
) -> bool:
    """Mark a command ``failed`` unless it has already reached a terminal state.

    Used to reconcile rows orphaned by a child process that died without
    reporting.  A GET is issued first so an already-terminal row (``completed``,
    ``failed``, ``cancelled``) is left untouched — the API rejects transitions
    out of a terminal state with a 422, and a scan that legitimately finished
    must not be relabelled a failure.

    The GET-then-PATCH is deliberately not atomic.  If the row completes in
    between, the PATCH is rejected by the server's transition validator and the
    row correctly stays ``completed``; ``_update_status`` logs the rejection and
    does not raise.  That is the desired outcome, so no locking is used.

    Returns ``True`` when a terminal status was written.
    """
    current = _get_command_status(command_id)
    if current is None:
        return False
    if current in ("completed", "failed", "cancelled"):
        logger.debug(f"Command already terminal — not reconciling command_id={command_id} status={current}")
        return False
    logger.warning(f"Reconciling orphaned command command_id={command_id} was={current} error={error_message}")
    _update_status(command_id, CommandStatusUpdate(
        status="failed",
        completed_at=datetime.now(timezone.utc),
        error_message=error_message,
        result_summary=result_summary,
    ))
    return True


def _spawn_scan(
    envelope: CommandEnvelope,
    producer_main_path: str,
) -> Optional[subprocess.Popen]:  # type: ignore[type-arg]
    """Spawn a child process to run the scan (or reject if at capacity)."""
    if len(_children) >= _max_scans:
        logger.warning(f"Max concurrent scans reached ({_max_scans}) — rejecting command_id={envelope.command_id}")
        _update_status(envelope.command_id, CommandStatusUpdate(
            status="failed", completed_at=datetime.now(timezone.utc),
            error_message=f"Max concurrent scans reached ({_max_scans})",
        ))
        return None

    cmd = [
        sys.executable, producer_main_path,
        "--mode", "scan",
        "--command-id", str(envelope.command_id),
        "--target", envelope.target,
    ]
    if envelope.parameters:
        cmd += ["--parameters", json.dumps(envelope.parameters)]

    logger.info(f"Spawning scan child command_id={envelope.command_id} pid={len(_children) + 1}")
    child = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)  # pylint: disable=consider-using-with
    _children[child.pid] = envelope.command_id
    return child


def _spawn_test(
    envelope: CommandEnvelope,
    producer_main_path: str,
) -> Optional[subprocess.Popen]:  # type: ignore[type-arg]
    """Spawn a child process to run the test (or reject if at capacity)."""
    if len(_test_children) >= _max_scans:
        logger.warning(f"Max concurrent tests reached ({_max_scans}) — rejecting command_id={envelope.command_id}")
        _update_status(envelope.command_id, CommandStatusUpdate(
            status="failed", completed_at=datetime.now(timezone.utc),
            error_message=f"Max concurrent tests reached ({_max_scans})",
        ))
        return None

    cmd = [
        sys.executable, producer_main_path,
        "--mode", "test",
        "--command-id", str(envelope.command_id),
        "--target", envelope.target,
    ]
    if envelope.parameters:
        cmd += ["--parameters", json.dumps(envelope.parameters)]

    logger.info(f"Spawning test child command_id={envelope.command_id}")
    child = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)  # pylint: disable=consider-using-with
    _test_children[child.pid] = (envelope.command_id, child)
    return child


def _cancel_scan(envelope: CommandEnvelope) -> None:
    """Handle a cancel command — find the child PID, send SIGTERM, PATCH statuses.

    Looks up the target scan via ``parameters.cancel_command_id``, sends
    SIGTERM to the child process, and PATCHes both the scan and the cancel
    command to their terminal statuses.
    """
    cancel_command_id = envelope.command_id
    target_command_id_str = (envelope.parameters or {}).get("cancel_command_id")

    # Mark the cancel command as running first so the eventual
    # completed/failed PATCH is a valid transition.
    _update_status(cancel_command_id, CommandStatusUpdate(
        status="running", started_at=datetime.now(timezone.utc),
    ))

    if not target_command_id_str:
        logger.warning("Cancel command missing cancel_command_id parameter")
        _update_status(cancel_command_id, CommandStatusUpdate(
            status="failed", completed_at=datetime.now(timezone.utc),
            error_message="Missing cancel_command_id parameter",
        ))
        return

    try:
        target_command_id = uuid.UUID(str(target_command_id_str))
    except ValueError:
        logger.warning(f"Invalid cancel_command_id: {target_command_id_str}")
        _update_status(cancel_command_id, CommandStatusUpdate(
            status="failed", completed_at=datetime.now(timezone.utc),
            error_message=f"Invalid cancel_command_id: {target_command_id_str}",
        ))
        return

    pid = _find_pid_by_command_id(target_command_id)
    if pid is None:
        logger.info(f"No running scan found for command_id={target_command_id}")
        _finalize_if_active(
            target_command_id,
            error_message="Scan process not found — orphaned",
        )
        _update_status(cancel_command_id, CommandStatusUpdate(
            status="completed", completed_at=datetime.now(timezone.utc),
            result_summary={"message": f"No running scan found for {target_command_id}"},
        ))
        return

    try:
        os.kill(pid, signal.SIGTERM)
        logger.info(f"Sent SIGTERM to pid={pid} for command_id={target_command_id}")
        # Remove from _children so reaper doesn't double-log
        _children.pop(pid, None)
        # Mark the scan as cancelled
        _update_status(target_command_id, CommandStatusUpdate(
            status="cancelled", completed_at=datetime.now(timezone.utc),
        ))
        # Mark the cancel command as completed
        _update_status(cancel_command_id, CommandStatusUpdate(
            status="completed", completed_at=datetime.now(timezone.utc),
            result_summary={"cancelled_command_id": str(target_command_id)},
        ))
    except ProcessLookupError:
        logger.warning(f"Process pid={pid} already exited for command_id={target_command_id}")
        _children.pop(pid, None)
        _finalize_if_active(
            target_command_id,
            error_message="Scan process exited before cancel",
        )
        _update_status(cancel_command_id, CommandStatusUpdate(
            status="completed", completed_at=datetime.now(timezone.utc),
            result_summary={"message": f"Process already exited for {target_command_id}"},
        ))


def run_daemon(
    *,
    container_name: str,
    producer_main_path: str,
) -> None:
    """Daemon entry point — sync pika loop + subprocess children + SIGCHLD."""
    # Fetch runtime settings snapshot at startup (best-effort).
    runtime_cache.refresh(fetch_runtime_snapshot(_api_base()))

    # Start background listener for live runtime config changes.
    rabbitmq_url = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    _start_settings_listener(rabbitmq_url)

    signal.signal(signal.SIGCHLD, _reap_children)  # reap child processes when they exit
    signal.signal(signal.SIGTERM, lambda sig, frame: sys.exit(0))  # trigger finally block to kill children + close connection

    rabbitmq_url = os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    queue_name = f"cnc.{container_name}"

    logger.info(f"Daemon started container={container_name} max_concurrent_scans={_max_scans}")

    _reconcile_startup_orphans(container_name)

    connection = pika.BlockingConnection(pika.URLParameters(rabbitmq_url))
    channel = connection.channel()
    channel.basic_qos(prefetch_count=1)

    # Declare exchange + queue + binding (idempotent)
    channel.exchange_declare(
        exchange="command_n_control",
        exchange_type="topic",
        durable=True,
    )
    channel.queue_declare(
        queue=queue_name,
        durable=True,
        arguments={
            "x-dead-letter-exchange": "command_n_control_dlx",
            "x-dead-letter-routing-key": "command_n_control_dlq",
        },
    )
    channel.queue_bind(
        queue=queue_name,
        exchange="command_n_control",
        routing_key=f"command_n_control.{container_name}",
    )

    logger.info(f"Consuming from queue={queue_name}")

    try:
        for method_frame, properties, body in channel.consume(
            queue_name, inactivity_timeout=1
        ):
            if method_frame is None:
                _poll_test_children()  # poll test children on idle ticks
                _poll_scan_children()  # reconcile scan children that died silently
                continue  # timeout, loop back

            try:
                envelope = CommandEnvelope.model_validate_json(body)
            except Exception:
                logger.warning("Invalid command message — nacking to DLQ")
                channel.basic_nack(method_frame.delivery_tag, requeue=False)
                continue

            logger.info(f"Received command command_id={envelope.command_id} type={envelope.command_type}")

            if envelope.command_type == "scan":
                _spawn_scan(envelope, producer_main_path)
            elif envelope.command_type == "test":
                _spawn_test(envelope, producer_main_path)
            elif envelope.command_type == "cancel":
                _cancel_scan(envelope)
            else:
                logger.warning(f"Unknown command type={envelope.command_type} — discarding")

            channel.basic_ack(method_frame.delivery_tag)

    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt — shutting down")
    finally:
        for pid, command_id in list(_children.items()):
            _finalize_if_active(
                command_id,
                error_message="Scan interrupted: producer shut down",
            )
            try:
                os.kill(pid, signal.SIGTERM)
                logger.info(f"Sent SIGTERM to child pid={pid}")
            except ProcessLookupError:
                pass
        for pid, (command_id, _popen) in list(_test_children.items()):
            _finalize_if_active(
                command_id,
                error_message="Test interrupted: producer shut down",
            )
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        connection.close()
        logger.info("Daemon stopped")


def run_scan(
    *,
    command_id: uuid.UUID,
    parameters: dict[str, Any],
    scan_func: Callable[[], Coroutine[Any, Any, ScanResult]],
) -> None:
    """Scan mode entry point — run scan and report status.

    ``scan_func`` must return a :class:`ScanResult`.  The scan is reported
    ``completed`` only when every configured item succeeded; if any item
    errored (even if others succeeded), the scan is reported ``failed`` with
    the per-item errors carried in ``result_summary``.
    """
    # Fetch a fresh runtime settings snapshot at child startup (best-effort).
    runtime_cache.refresh(fetch_runtime_snapshot(_api_base()))

    logger.info(f"Scan started command_id={command_id}")

    _update_status(command_id, CommandStatusUpdate(
        status="running", started_at=datetime.now(timezone.utc),
    ))

    try:
        result = asyncio.run(scan_func())
        if result.success:
            logger.info(f"Scan completed command_id={command_id}")
            _update_status(command_id, CommandStatusUpdate(
                status="completed", completed_at=datetime.now(timezone.utc),
                result_summary=result.summary(),
            ))
        else:
            logger.error(f"Scan failed command_id={command_id}: {result.error_message()} errors={result.errors}")
            _update_status(command_id, CommandStatusUpdate(
                status="failed", completed_at=datetime.now(timezone.utc),
                error_message=result.error_message(),
                result_summary=result.summary(),
            ))
            sys.exit(1)
    except Exception as exc:
        logger.error(f"Scan failed command_id={command_id}: {exc}", exc_info=True)
        _update_status(command_id, CommandStatusUpdate(
            status="failed", completed_at=datetime.now(timezone.utc),
            error_message=str(exc),
        ))
        sys.exit(1)


def run_test(
    *,
    command_id: uuid.UUID,
    parameters: dict[str, Any],
    test_func: Callable[[], Coroutine[Any, Any, tuple[bool, str]]],
) -> None:
    """Test mode entry point — run test and print result to stdout.

    The daemon parent process captures stdout/stderr via ``PIPE`` and
    PATCHes the terminal status in ``_poll_test_children()`` based on
    the exit code and printed message.  This function only needs to
    print the result and exit with the appropriate code.
    """
    # Fetch a fresh runtime settings snapshot at child startup (best-effort).
    runtime_cache.refresh(fetch_runtime_snapshot(_api_base()))

    logger.info(f"Test started command_id={command_id}")

    # Forward item_id to the test function via environment variable
    # (Option A from design: keeps test_func signature clean)
    if "item_id" in parameters:
        os.environ["TEST_ITEM_ID"] = str(parameters["item_id"])

    # Mark the test as running so the parent's terminal-status PATCH
    # (completed/failed) has a valid transition path.
    _update_status(command_id, CommandStatusUpdate(
        status="running", started_at=datetime.now(timezone.utc),
    ))

    try:
        success, message = asyncio.run(test_func())
        if success:
            print(f"SUCCESS: {message}")
        else:
            print(f"FAILED: {message}")
            sys.exit(1)
    except Exception as exc:
        print(f"FAILED: {exc}")
        sys.exit(1)


def producer_main(
    *,
    description: str,
    default_container: str,
    producer_main_path: str,
    scan_func: Callable[[], Coroutine[Any, Any, ScanResult]],
    test_func: Callable[[], Coroutine[Any, Any, tuple[bool, str]]] | None = None,
) -> None:
    """Unified CLI entry point — dispatch to daemon, scan, or test mode.

    Args:
        description: Human-readable description for ``argparse`` help.
        default_container: Default ``CONTAINER_NAME`` (e.g. ``"github-producer"``).
        producer_main_path: ``__file__`` from the caller's module — used to
            spawn child processes.
        scan_func: The producer's async scan function (e.g. ``main_async``).
            Must return a :class:`ScanResult` describing the aggregate outcome.
        test_func: Optional async function returning ``(success, message)``
            for connectivity testing.  Required for ``--mode test``.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--mode", choices=["daemon", "scan", "test"], default="daemon")
    parser.add_argument("--command-id")
    parser.add_argument("--target")
    parser.add_argument("--parameters")

    args = parser.parse_args()

    if args.mode == "daemon":
        run_daemon(
            container_name=os.environ.get("CONTAINER_NAME", default_container),
            producer_main_path=producer_main_path,
        )
    elif args.mode == "test":
        if test_func is None:
            print("ERROR: No test function provided for this producer.")
            sys.exit(1)
        command_id = uuid.UUID(args.command_id) if args.command_id else uuid.uuid4()
        parameters = json.loads(args.parameters) if args.parameters else {}
        run_test(
            command_id=command_id,
            parameters=parameters,
            test_func=test_func,
        )
    else:
        command_id = uuid.UUID(args.command_id) if args.command_id else uuid.uuid4()
        parameters = json.loads(args.parameters) if args.parameters else {}
        run_scan(
            command_id=command_id,
            parameters=parameters,
            scan_func=scan_func,
        )