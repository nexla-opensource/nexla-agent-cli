"""`triage runs` / `flow-quarantine` / `summary` / `doctor` -- hermetic."""

from __future__ import annotations

import json as jsonlib
from collections.abc import Callable

import httpx
import respx
from typer.testing import CliRunner

from .conftest import MONITORING_URL


def _sse(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=f"event: message\ndata: {jsonlib.dumps(payload)}\n\n",
    )


def _tool_result(request: httpx.Request, body: dict, *, is_error: bool = False) -> httpx.Response:
    req_id = jsonlib.loads(request.content)["id"]
    result: dict = {"content": [{"type": "text", "text": jsonlib.dumps(body)}]}
    if is_error:
        result["isError"] = True
    return _sse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _dispatch(responses: dict[str, dict], error_tools: tuple[str, ...] = ()) -> Callable:
    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content)
        if body["method"] == "tools/list":
            return _tool_result(request, {})
        name = body["params"]["name"]
        return _tool_result(request, responses.get(name, {}), is_error=name in error_tools)

    return handler


_STATUS_WITH_RUNS = {
    "flow_id": 7,
    "flow_name": "f",
    "latest_run": {"run_id": 300, "created_at": "2026-07-27T03:00:00"},
    "recent_runs": [
        {"run_id": 300, "created_at": "2026-07-27T03:00:00"},
        {"run_id": 200, "created_at": "2026-07-26T03:00:00"},
        {"run_id": 100, "created_at": "2026-07-25T03:00:00"},
    ],
}


def test_runs_lists_newest_first_with_latest_marked(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch({"get_flow_status": _STATUS_WITH_RUNS})
    )
    result = runner.invoke(cli_app, ["triage", "runs", "7"])
    assert result.exit_code == 0, result.output
    data = jsonlib.loads(result.stdout)
    assert [r["run_id"] for r in data] == [300, 200, 100]
    assert data[0]["latest"] is True
    assert data[1]["latest"] is False


def test_runs_limit_caps(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch({"get_flow_status": _STATUS_WITH_RUNS})
    )
    result = runner.invoke(cli_app, ["triage", "runs", "7", "--limit", "2"])
    assert result.exit_code == 0
    assert len(jsonlib.loads(result.stdout)) == 2


def test_runs_no_history_is_empty_not_error(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A flow that has never run is a normal early state, not a failure.
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(
            {"get_flow_status": {"flow_id": 7, "flow_name": "f", "latest_run": None, "recent_runs": []}}
        )
    )
    result = runner.invoke(cli_app, ["triage", "runs", "7"])
    assert result.exit_code == 0
    assert jsonlib.loads(result.stdout) == []


def test_runs_unknown_flow_not_found(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch({"get_flow_status": {"flow_id": 9, "flow_name": None, "owner_email": None}})
    )
    result = runner.invoke(cli_app, ["triage", "runs", "9"])
    assert result.exit_code == 5


def test_flow_quarantine_resolves_resource_from_logs(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    responses = {
        "get_flow_status": {"flow_id": 7, "flow_name": "f", "latest_run": {"run_id": 1}},
        "get_flow_logs": {
            "logs": {"data": [{"log": "bad row", "resource_type": "SOURCE", "resource_id": 55}]}
        },
        "get_quarantine_samples": {"samples": [{"error": "column x expected NUMBER"}]},
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["triage", "flow-quarantine", "7"])
    assert result.exit_code == 0, result.output
    data = jsonlib.loads(result.stdout)
    assert data[0]["resource_type"] == "SOURCE"
    assert data[0]["resource_id"] == 55
    assert "column x" in data[0]["reason"]


def test_flow_quarantine_falls_back_to_affected_resources(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    responses = {
        "get_flow_status": {
            "flow_id": 7,
            "flow_name": "f",
            "status": {
                "healthStatus": "RED",
                "affectedResources": [{"resource_type": "data_sinks", "resource_id": 88}],
            },
        },
        "get_flow_logs": {"logs": {"data": []}},  # no log attribution
        "get_quarantine_samples": {"samples": [{"error": "type mismatch"}]},
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["triage", "flow-quarantine", "7"])
    assert result.exit_code == 0
    assert jsonlib.loads(result.stdout)[0]["resource_id"] == 88


def test_flow_quarantine_degrades_when_samples_error(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    responses = {
        "get_flow_status": {"flow_id": 7, "flow_name": "f", "latest_run": {"run_id": 1}},
        "get_flow_logs": {
            "logs": {"data": [{"log": "x", "resource_type": "SOURCE", "resource_id": 55}]}
        },
        "get_quarantine_samples": {"error": "expired"},
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(responses, error_tools=("get_quarantine_samples",))
    )
    result = runner.invoke(cli_app, ["triage", "flow-quarantine", "7"])
    assert result.exit_code == 0  # tool error must not sink the command
    assert jsonlib.loads(result.stdout)[0]["sample_count"] == 0


_ERRORS_BOARD = {
    "count": 3,
    "window": {"from": "2026-07-27", "to": "2026-07-28"},
    "flows": [
        {"flow_id": 1, "flow_name": "a", "errors": 2, "last_run_status": "RED"},
        {"flow_id": 2, "flow_name": "b", "errors": 99, "last_run_status": "RED"},
        {"flow_id": 3, "flow_name": "c", "errors": 5, "last_run_status": "YELLOW"},
    ],
}


def test_summary_ranks_worst_flows(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(
            {"list_flows_with_errors": _ERRORS_BOARD, "get_org_metrics": {"records": 10}}
        )
    )
    result = runner.invoke(cli_app, ["triage", "summary", "--top", "2"])
    assert result.exit_code == 0, result.output
    data = jsonlib.loads(result.stdout)
    assert [f["flow_id"] for f in data["worst_flows"]] == [2, 3]  # by error count
    assert data["flows_with_errors"] == 3
    assert any("diagnose 2" in c for c in data["next_commands"])


def test_summary_survives_a_failing_tool(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # org metrics errors -> partial board, still exit 0, and it says what's missing.
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(
            {"list_flows_with_errors": _ERRORS_BOARD, "get_org_metrics": {"error": "boom"}},
            error_tools=("get_org_metrics",),
        )
    )
    result = runner.invoke(cli_app, ["triage", "summary"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    assert data["worst_flows"]
    assert "get_org_metrics" in data["unavailable"]


def test_doctor_passes_when_configured(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter, monkeypatch
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", "https://api.test")
    monkeypatch.setenv("NEXLA_TOKEN", "secret-token-value")
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _sse(
            {
                "jsonrpc": "2.0",
                "id": jsonlib.loads(req.content)["id"],
                "result": {"tools": [{"name": "get_flow_status"}]},
            }
        )
    )
    result = runner.invoke(cli_app, ["triage", "doctor"])
    assert result.exit_code == 0, result.output
    data = jsonlib.loads(result.stdout)
    assert data["ok"] is True
    # A token value must never be printed.
    assert "secret-token-value" not in result.output


def test_doctor_flags_missing_monitoring_url(
    runner: CliRunner, cli_app, monkeypatch
) -> None:
    monkeypatch.setenv("NEXLA_API_URL", "https://api.test")
    monkeypatch.setenv("NEXLA_TOKEN", "t")
    monkeypatch.delenv("NEXLA_MONITORING_URL", raising=False)
    result = runner.invoke(cli_app, ["triage", "doctor"])
    # Non-critical: reported as FAIL with a fix, but doesn't fail the command.
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    mon = next(c for c in data["checks"] if c["check"] == "monitoring_url")
    assert mon["ok"] is False
    assert "login --monitoring-url" in mon["hint"]


def test_doctor_fails_without_auth(runner: CliRunner, cli_app, monkeypatch) -> None:
    monkeypatch.setenv("NEXLA_API_URL", "https://api.test")
    monkeypatch.delenv("NEXLA_TOKEN", raising=False)
    monkeypatch.delenv("NEXLA_MONITORING_URL", raising=False)
    result = runner.invoke(cli_app, ["triage", "doctor"])
    assert result.exit_code == 3  # EXIT.CONFIG -- a critical check failed


def test_runs_survives_non_numeric_run_id(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # Schema drift must degrade the ordering, never raise an uncaught
    # TypeError (str vs int is unorderable) and leak a traceback.
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(
            {
                "get_flow_status": {
                    "flow_id": 7,
                    "flow_name": "f",
                    "recent_runs": [{"run_id": 300}, {"run_id": "weird"}, {"run_id": 100}],
                }
            }
        )
    )
    result = runner.invoke(cli_app, ["triage", "runs", "7"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert len(jsonlib.loads(result.stdout)) == 3


def test_summary_survives_non_numeric_error_count(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(
            {
                "list_flows_with_errors": {
                    "count": 2,
                    "flows": [
                        {"flow_id": 1, "errors": 5},
                        {"flow_id": 2, "errors": "lots"},
                    ],
                }
            }
        )
    )
    result = runner.invoke(cli_app, ["triage", "summary"])
    assert result.exit_code == 0, result.output
    assert "Traceback" not in result.output
    assert jsonlib.loads(result.stdout)["worst_flows"][0]["flow_id"] == 1
