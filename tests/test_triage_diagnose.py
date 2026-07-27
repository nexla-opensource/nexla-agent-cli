from __future__ import annotations

import datetime as dt
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
    result = {"content": [{"type": "text", "text": jsonlib.dumps(body)}]}
    if is_error:
        result["isError"] = True
    return _sse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _dispatch(
    responses: dict[str, dict], error_tools: tuple[str, ...] = ()
) -> Callable[[httpx.Request], httpx.Response]:
    """Route one mocked POST to the right per-tool body by tool name."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = jsonlib.loads(request.content)
        if body["method"] == "tools/list":
            return _tool_result(request, {})
        name = body["params"]["name"]
        return _tool_result(request, responses.get(name, {}), is_error=name in error_tools)

    return handler


def _tool_calls(route: respx.Route) -> list[dict]:
    """Decoded `tools/call` request params, in order."""
    out = []
    for call in route.calls:
        body = jsonlib.loads(call.request.content)
        if body["method"] == "tools/call":
            out.append(body["params"])
    return out


# Live-shape RED flow: healthStatus null, empty affectedResources, error lives
# only in the ERROR logs (with resource attribution) -- the 586838 SSL case.
_FAILED = {
    "get_flow_status": {
        "flow_id": 42,
        "flow_name": "spacex-sync",
        "owner_email": "o@x.com",
        "status": {"originNodeId": 42, "healthStatus": None, "affectedResources": []},
        "latest_run": {"run_id": 1785, "flow_id": 42, "data_source_id": 118249},
        "chain": {},
        "recent_runs": [{"run_id": 1785, "flow_id": 42}],
    },
    "get_flow_logs": {
        "status": 200,
        "message": "Ok",
        "logs": {
            "data": [
                {
                    "log": "525: SSL handshake failed connecting to spacexdata.com",
                    "log_id": 1,
                    "log_type": "error",
                    "resource_id": 118249,
                    "resource_type": "data_sources",
                    "run_id": 1785,
                    "severity": "ERROR",
                    "timestamp": "2026-07-27T00:00:00Z",
                }
            ]
        },
    },
    # quarantine tool-errors for this source (see error_tools in the test)
    "get_quarantine_samples": {"error": "no quarantine for source"},
}


def test_diagnose_failed_flow_json(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(_FAILED, error_tools=("get_quarantine_samples",))
    )
    result = runner.invoke(cli_app, ["triage", "diagnose", "42"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    assert data["flow_id"] == 42
    assert data["status"] != "OK"
    assert data["root_causes"], "expected at least one ranked root cause"
    top = data["root_causes"][0]
    # quarantine errored -> log-backed cause wins, attributed to the source
    assert top["signal"] == "logs"
    assert "SSL" in top["detail"]
    assert top["resource_type"] == "data_sources"
    assert top["resource_id"] == 118249
    calls = {c["name"]: c["arguments"] for c in _tool_calls(route)}
    assert calls["get_flow_logs"]["severity"] == "ERROR"
    assert calls["get_flow_logs"]["run_id"] == 1785  # scoped to latest_run
    assert data["evidence"]["logs"]
    assert any("logs" in c for c in data["next_commands"])


def test_diagnose_failed_flow_human(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(_FAILED, error_tools=("get_quarantine_samples",))
    )
    result = runner.invoke(cli_app, ["-o", "table", "triage", "diagnose", "42"])
    assert result.exit_code == 0
    assert result.stdout.startswith("FAILED:")
    assert "SSL" in result.stdout
    assert "next:" in result.stdout


def test_diagnose_long_log_message_is_truncated_one_line(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A real ERROR log can be a multi-KB HTML error page with embedded
    # newlines; the human FAILED line and the JSON detail must stay a short
    # one-liner, while evidence.logs keeps the raw message.
    blob = "525: SSL handshake failed\n" + "<div>x</div>\n" * 500
    responses = {
        "get_flow_status": {"flow_id": 42, "flow_name": "f", "status": {"healthStatus": None}},
        "get_flow_logs": {
            "logs": {
                "data": [
                    {"log": blob, "resource_id": 1, "resource_type": "data_sources", "severity": "ERROR"}
                ]
            }
        },
        "get_quarantine_samples": {"error": "none"},
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(responses, error_tools=("get_quarantine_samples",))
    )
    result = runner.invoke(cli_app, ["triage", "diagnose", "42"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    detail = data["root_causes"][0]["detail"]
    assert len(detail) <= 200
    assert "\n" not in detail  # collapsed to one line
    assert "SSL handshake failed" in detail  # the useful head survives
    # raw evidence is preserved in full
    assert len(data["evidence"]["logs"][0]["log"]) > 200


def test_diagnose_quarantine_ranks_first(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    # ERROR log attributes a sink; quarantine has a concrete sample -> ranks #1
    responses = {
        "get_flow_status": {
            "flow_id": 50,
            "flow_name": "orders",
            "status": {"healthStatus": "RED", "affectedResources": []},
            "latest_run": {"run_id": 9},
        },
        "get_flow_logs": {
            "logs": {
                "data": [
                    {
                        "log": "sink write rejected rows",
                        "resource_id": 300,
                        "resource_type": "data_sinks",
                        "severity": "ERROR",
                    }
                ]
            }
        },
        "get_quarantine_samples": {
            "samples": [{"error": "column 'amount' expected NUMBER got STRING"}]
        },
    }
    route = respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["triage", "diagnose", "50"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    top = data["root_causes"][0]
    assert top["signal"] == "quarantine"
    assert "amount" in top["detail"]
    calls = {c["name"]: c["arguments"] for c in _tool_calls(route)}
    assert calls["get_quarantine_samples"]["resource_type"] == "data_sinks"
    assert calls["get_quarantine_samples"]["resource_id"] == 300
    assert any("quarantine" in c for c in data["next_commands"])


def test_diagnose_healthy_flow(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    # null health + zero ERROR logs + not in errors oracle -> HEALTHY
    responses = {
        "get_flow_status": {
            "flow_id": 9,
            "flow_name": "clean-flow",
            "status": {"healthStatus": None, "affectedResources": []},
            "latest_run": {"run_id": 3},
        },
        "get_flow_logs": {"logs": {"data": []}},
        "list_flows_with_errors": {"flows": [{"flow_id": 111, "last_run_status": "RED", "errors": 2}]},
    }
    route = respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["triage", "diagnose", "9"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    assert data["status"] == "OK"
    assert data["root_causes"] == []
    # never fetches quarantine for a healthy flow
    called = {c["name"] for c in _tool_calls(route)}
    assert "get_quarantine_samples" not in called


def test_diagnose_healthy_flow_human(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    responses = {
        "get_flow_status": {"flow_id": 9, "flow_name": "clean-flow", "status": {"healthStatus": None}},
        "get_flow_logs": {"logs": {"data": []}},
        "list_flows_with_errors": {"flows": []},
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["-o", "table", "triage", "diagnose", "9"])
    assert result.exit_code == 0
    assert result.stdout.startswith("HEALTHY:")


def test_diagnose_oracle_detects_when_status_and_logs_silent(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # health null, no ERROR logs, but the errors oracle lists it RED -> FAILED
    responses = {
        "get_flow_status": {"flow_id": 77, "flow_name": "silent", "status": {"healthStatus": None}},
        "get_flow_logs": {"logs": {"data": []}},
        "list_flows_with_errors": {"flows": [{"flow_id": 77, "last_run_status": "RED", "errors": 5}]},
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["triage", "diagnose", "77"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    assert data["status"] != "OK"
    assert data["root_causes"]
    assert data["root_causes"][0]["signal"] == "status"


def test_diagnose_affected_resources_fallback(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # RED health, no log attribution, affectedResources names the sink
    responses = {
        "get_flow_status": {
            "flow_id": 60,
            "flow_name": "aff",
            "status": {
                "healthStatus": "RED",
                "affectedResources": [{"resource_type": "data_sinks", "resource_id": 88, "name": "wh"}],
            },
            "latest_run": {"run_id": 2},
        },
        "get_flow_logs": {"logs": {"data": []}},
        "get_quarantine_samples": {"samples": [{"error": "type mismatch on col x"}]},
    }
    route = respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["triage", "diagnose", "60"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    top = data["root_causes"][0]
    assert top["signal"] == "quarantine"
    assert top["resource_id"] == 88
    calls = {c["name"]: c["arguments"] for c in _tool_calls(route)}
    assert calls["get_quarantine_samples"]["resource_id"] == 88


def test_diagnose_degrades_when_logs_error(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # get_flow_logs tool-errors; RED health + affectedResources + quarantine
    # still yield a diagnosis -> exit 0 with empty logs evidence
    responses = {
        "get_flow_status": {
            "flow_id": 61,
            "flow_name": "deg",
            "status": {
                "healthStatus": "RED",
                "affectedResources": [{"resource_type": "data_sinks", "resource_id": 99, "name": "s"}],
            },
            "latest_run": {"run_id": 1},
        },
        "get_flow_logs": {"error": "ES timeout"},
        "get_quarantine_samples": {"samples": [{"error": "bad row"}]},
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=_dispatch(responses, error_tools=("get_flow_logs",))
    )
    result = runner.invoke(cli_app, ["triage", "diagnose", "61"])
    assert result.exit_code == 0
    data = jsonlib.loads(result.stdout)
    assert data["evidence"]["logs"] == []
    assert data["root_causes"][0]["signal"] == "quarantine"


def test_diagnose_nonexistent_flow_is_not_found(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # A bogus flow_id doesn't error server-side; get_flow_status echoes the id
    # with name/owner null. That must surface as NOT_FOUND, not a false "OK".
    responses = {
        "get_flow_status": {
            "flow_id": 999999999,
            "flow_name": None,
            "owner_email": None,
            "status": {},
            "latest_run": None,
            "recent_runs": [],
        },
    }
    respx_mock.post(f"{MONITORING_URL}/").mock(side_effect=_dispatch(responses))
    result = runner.invoke(cli_app, ["triage", "diagnose", "999999999"])
    assert result.exit_code == 5  # EXIT.NOT_FOUND


def test_since_relative_hours(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _tool_result(req, {"flows": []})
    )
    result = runner.invoke(cli_app, ["triage", "errors", "--since", "24h"])
    assert result.exit_code == 0
    args = jsonlib.loads(route.calls.last.request.content)["params"]["arguments"]
    parsed = dt.date.fromisoformat(args["from_date"])
    today = dt.datetime.now(dt.UTC).date()
    assert 0 <= (today - parsed).days <= 1


def test_since_relative_days(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _tool_result(req, {"logs": {"data": []}})
    )
    result = runner.invoke(cli_app, ["triage", "logs", "42", "--since", "7d"])
    assert result.exit_code == 0
    args = jsonlib.loads(route.calls.last.request.content)["params"]["arguments"]
    parsed = dt.date.fromisoformat(args["from_date"])
    today = dt.datetime.now(dt.UTC).date()
    assert 6 <= (today - parsed).days <= 7


def test_since_absolute_passthrough(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _tool_result(req, {"flows": []})
    )
    result = runner.invoke(cli_app, ["triage", "errors", "--since", "2026-01-02"])
    assert result.exit_code == 0
    args = jsonlib.loads(route.calls.last.request.content)["params"]["arguments"]
    assert args["from_date"] == "2026-01-02"


def test_since_invalid_value(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    result = runner.invoke(cli_app, ["triage", "errors", "--since", "yesterday"])
    assert result.exit_code == 2


def test_since_conflicts_with_from_date(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    result = runner.invoke(
        cli_app, ["triage", "errors", "--since", "24h", "--from-date", "2026-01-01"]
    )
    assert result.exit_code == 2
