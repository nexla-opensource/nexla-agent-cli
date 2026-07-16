from __future__ import annotations

import json as jsonlib

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


def _rpc_result(request: httpx.Request, result: dict) -> httpx.Response:
    req_id = jsonlib.loads(request.content)["id"]
    return _sse({"jsonrpc": "2.0", "id": req_id, "result": result})


def _tool_result(request: httpx.Request, body: dict, *, is_error: bool = False) -> httpx.Response:
    result = {"content": [{"type": "text", "text": jsonlib.dumps(body)}]}
    if is_error:
        result["isError"] = True
    return _rpc_result(request, result)


def test_status(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _tool_result(req, {"flow_id": 42, "flow_name": "my-flow"})
    )
    result = runner.invoke(cli_app, ["triage", "status", "42"])
    assert result.exit_code == 0
    assert "my-flow" in result.stdout
    sent = jsonlib.loads(route.calls.last.request.content)
    assert sent["params"]["name"] == "get_flow_status"
    assert sent["params"]["arguments"] == {"flow_id": 42}


def test_logs_with_filters(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _tool_result(req, {"logs": {"data": []}})
    )
    result = runner.invoke(
        cli_app, ["triage", "logs", "42", "--run-id", "7", "--severity", "ERROR"]
    )
    assert result.exit_code == 0
    sent = jsonlib.loads(route.calls.last.request.content)
    assert sent["params"]["arguments"] == {"flow_id": 42, "run_id": 7, "severity": "ERROR", "size": 50}


def test_search(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _tool_result(req, {"term": "foo", "flows": []})
    )
    result = runner.invoke(cli_app, ["triage", "search", "foo"])
    assert result.exit_code == 0
    assert '"term": "foo"' in result.stdout


def test_rpc_level_error(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _sse(
            {"jsonrpc": "2.0", "id": jsonlib.loads(req.content)["id"], "error": {"message": "boom"}}
        )
    )
    result = runner.invoke(cli_app, ["triage", "status", "42"])
    assert result.exit_code == 1
    assert "boom" in result.stderr


def test_tool_level_error(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _tool_result(req, {"error": "flow not found"}, is_error=True)
    )
    result = runner.invoke(cli_app, ["triage", "status", "999"])
    assert result.exit_code == 1
    assert "flow not found" in result.stderr


def test_dry_run_valid(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _rpc_result(
            req,
            {
                "tools": [
                    {
                        "name": "get_flow_status",
                        "inputSchema": {
                            "properties": {"flow_id": {"type": "integer"}},
                            "required": ["flow_id"],
                            "type": "object",
                        },
                    }
                ]
            },
        )
    )
    result = runner.invoke(cli_app, ["triage", "status", "42", "--dry-run"])
    assert result.exit_code == 0
    assert jsonlib.loads(result.stdout) == {"valid": True, "body": {"flow_id": 42}}
    # only `tools/list` fired -- the real `tools/call` never happened
    assert all(jsonlib.loads(c.request.content)["method"] == "tools/list" for c in route.calls)


def test_dry_run_invalid(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    respx_mock.post(f"{MONITORING_URL}/").mock(
        side_effect=lambda req: _rpc_result(
            req,
            {
                "tools": [
                    {
                        "name": "search_flows",
                        "inputSchema": {
                            # server's live schema disagrees with what this CLI sends --
                            # `limit` here is (wrongly, for this test) declared a string.
                            "properties": {
                                "name": {"type": "string"},
                                "limit": {"type": "string"},
                            },
                            "required": ["name"],
                            "type": "object",
                        },
                    }
                ]
            },
        )
    )
    result = runner.invoke(cli_app, ["triage", "search", "foo", "--dry-run"])
    assert result.exit_code == 2
    errors = jsonlib.loads(result.stderr)["errors"]
    assert any("limit" in e for e in errors)


def test_missing_monitoring_url(cli_app, monkeypatch) -> None:
    monkeypatch.setenv("NEXLA_TOKEN", "test-token")
    monkeypatch.delenv("NEXLA_MONITORING_URL", raising=False)
    result = CliRunner().invoke(cli_app, ["triage", "status", "42"])
    assert result.exit_code == 3
