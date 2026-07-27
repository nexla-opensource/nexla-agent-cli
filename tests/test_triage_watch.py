"""`triage watch` -- block until a run reaches a terminal state.

Hermetic: the monitoring server is respx-mocked and `time.sleep` is patched
out, so polling loops run instantly.
"""

from __future__ import annotations

import json as jsonlib
from collections.abc import Callable

import httpx
import pytest
import respx
from typer.testing import CliRunner

from nexla_cli.errors import EXIT

from .conftest import MONITORING_URL


def _sse(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=f"event: message\ndata: {jsonlib.dumps(payload)}\n\n",
    )


def _tool_result(request: httpx.Request, body: dict) -> httpx.Response:
    req_id = jsonlib.loads(request.content)["id"]
    return _sse(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": jsonlib.dumps(body)}]},
        }
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("nexla_cli.resources.triage.time.sleep", lambda _s: None)


def _sequence(status_bodies: list[dict], logs: dict | None = None) -> Callable:
    """Serve get_flow_status from a list (one per poll), logs/oracle fixed."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content)
        if body["method"] == "tools/list":
            return _tool_result(request, {})
        name = body["params"]["name"]
        if name == "get_flow_status":
            i = min(calls["n"], len(status_bodies) - 1)
            calls["n"] += 1
            return _tool_result(request, status_bodies[i])
        if name == "get_flow_logs":
            return _tool_result(request, logs or {"logs": {"data": []}})
        return _tool_result(request, {"flows": []})  # list_flows_with_errors

    return handler


_NO_RUN = {"flow_id": 7, "flow_name": "f", "status": {"healthStatus": None}, "latest_run": None}
_RAN = {
    "flow_id": 7,
    "flow_name": "f",
    "status": {"healthStatus": None},
    "latest_run": {"run_id": 99},
}
_ERROR_LOGS = {
    "logs": {"data": [{"log": "boom: table missing", "resource_type": "SOURCE", "resource_id": 1}]}
}


def test_watch_pending_then_complete(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    # No run yet is *pending*, not failed -- keep polling until one lands.
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_sequence([_NO_RUN, _RAN]))
    result = runner.invoke(cli_app, ["triage", "watch", "7", "--interval", "1"])
    assert result.exit_code == 0, result.output
    data = jsonlib.loads(result.stdout)
    assert data["outcome"] == "complete"
    assert data["run_id"] == 99
    assert data["polls"] >= 2  # polled through the pending state


def test_watch_detects_failure_and_points_at_diagnose(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_sequence([_RAN], logs=_ERROR_LOGS))
    result = runner.invoke(cli_app, ["triage", "watch", "7", "--interval", "1"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    assert data["outcome"] == "failed"
    assert "table missing" in data["cause"]
    assert any("diagnose" in c for c in data["next_commands"])


def test_watch_until_failed_ignores_healthy(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Healthy run + --until failed -> never satisfied -> times out (exit 1).
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_sequence([_RAN]))
    result = runner.invoke(
        cli_app, ["triage", "watch", "7", "--until", "failed", "--timeout", "2", "--interval", "1"]
    )
    assert result.exit_code == 1
    assert jsonlib.loads(result.stdout)["outcome"] == "timeout"


def test_watch_timeout_is_distinct_from_failure(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_sequence([_NO_RUN]))
    result = runner.invoke(
        cli_app, ["triage", "watch", "7", "--timeout", "2", "--interval", "1"]
    )
    assert result.exit_code == 1  # EXIT.ERROR, not a flow failure
    data = jsonlib.loads(result.stdout)
    assert data["outcome"] == "timeout"
    assert data["last_state"] == "pending"


def test_watch_human_output_goes_to_stdout_progress_to_stderr(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_sequence([_RAN]))
    result = runner.invoke(cli_app, ["-o", "table", "triage", "watch", "7", "--interval", "1"])
    assert result.exit_code == 0
    assert result.stdout.startswith("COMPLETE:")


def test_watch_rejects_bad_until(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    result = runner.invoke(cli_app, ["triage", "watch", "7", "--until", "banana"])
    assert result.exit_code == 2  # EXIT.VALIDATION


def test_watch_unknown_flow_is_not_found(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_sequence([{"flow_id": 999, "flow_name": None, "owner_email": None}])
    )
    result = runner.invoke(cli_app, ["triage", "watch", "999", "--interval", "1"])
    assert result.exit_code == 5  # EXIT.NOT_FOUND


def test_watch_detects_failure_with_no_run_id_in_status(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Observed live: 50 ERROR logs against a status payload showing no run at
    # all. Short-circuiting to "pending" there made watch sit until timeout on
    # an already-broken flow, while diagnose correctly called it failed.
    status_no_run = {"flow_id": 7, "flow_name": "f", "status": {"healthStatus": None},
                     "latest_run": None, "recent_runs": []}
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_sequence([status_no_run], logs=_ERROR_LOGS)
    )
    result = runner.invoke(cli_app, ["triage", "watch", "7", "--interval", "1", "--timeout", "10"])
    assert result.exit_code == 0, result.output
    data = jsonlib.loads(result.stdout)
    assert data["outcome"] == "failed"
    assert "table missing" in data["cause"]


def test_watch_still_pending_when_nothing_has_happened(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # The converse: no run AND no error logs really is pending, not failed.
    status_no_run = {"flow_id": 7, "flow_name": "f", "status": {"healthStatus": None},
                     "latest_run": None, "recent_runs": []}
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_sequence([status_no_run]))
    result = runner.invoke(cli_app, ["triage", "watch", "7", "--interval", "1", "--timeout", "3"])
    assert result.exit_code == 1
    assert jsonlib.loads(result.stdout)["last_state"] == "pending"


def test_watch_survives_transient_upstream_error(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A poll loop that runs for minutes must survive a blip: the monitoring
    # server 503'd mid-watch during live testing and killed the command.
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content)
        if body["method"] == "tools/list":
            return _tool_result(request, {})
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503, text="upstream unavailable")
        name = body["params"]["name"]
        if name == "get_flow_status":
            return _tool_result(request, _RAN)
        return _tool_result(request, {"logs": {"data": []}})

    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=handler)
    result = runner.invoke(cli_app, ["triage", "watch", "7", "--interval", "1", "--timeout", "30"])
    assert result.exit_code == 0, result.output
    assert jsonlib.loads(result.stdout)["outcome"] == "complete"


def test_watch_gives_up_if_upstream_never_recovers(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Tolerating blips must not mean hanging forever on a dead server.
    respx_mock.post(f"{MONITORING_URL}/").mock(
        return_value=httpx.Response(503, text="down")
    )
    result = runner.invoke(cli_app, ["triage", "watch", "7", "--interval", "1", "--timeout", "3"])
    assert result.exit_code == EXIT.UPSTREAM


def test_watch_non_upstream_error_still_aborts(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A bad flow id is a real error -- don't retry it for the whole timeout.
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_sequence([{"flow_id": 9, "flow_name": None, "owner_email": None}])
    )
    result = runner.invoke(cli_app, ["triage", "watch", "9", "--interval", "1", "--timeout", "30"])
    assert result.exit_code == 5  # NOT_FOUND, immediately
