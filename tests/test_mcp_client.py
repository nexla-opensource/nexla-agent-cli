"""Direct tests for the monitoring MCP JSON-RPC client.

`mcp_client` was previously exercised only indirectly through `test_triage.py`.
These cover its transport seams head-on: SSE-vs-plain-JSON envelope decoding,
the MCP result-unwrap, and the error paths (JSON-RPC error, non-2xx, empty
body).
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from nexla_cli import mcp_client
from nexla_cli.errors import EXIT, CliError

from .conftest import MONITORING_URL


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEXLA_MONITORING_URL", MONITORING_URL)
    monkeypatch.setenv("NEXLA_TOKEN", "test-token")


def _sse(payload: dict) -> httpx.Response:
    """An SSE-framed single reply, the shape the live server actually sends."""
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        text=f"event: message\ndata: {json.dumps(payload)}\n\n",
    )


def test_list_tools_parses_sse_framed_reply(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(MONITORING_URL).mock(
        return_value=_sse(
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": [{"name": "get_flow_status"}]}}
        )
    )
    tools = mcp_client.list_tools()
    assert tools == [{"name": "get_flow_status"}]


def test_parse_handles_plain_json_body(respx_mock: respx.MockRouter) -> None:
    # The server *usually* uses SSE, but the client must not assume it — a
    # bare application/json envelope decodes too.
    respx_mock.post(MONITORING_URL).mock(
        return_value=httpx.Response(
            200, json={"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        )
    )
    assert mcp_client.list_tools() == []


def test_call_tool_unwraps_mcp_content(respx_mock: respx.MockRouter) -> None:
    # call_tool must peel result.content[0].text (itself a JSON string) down
    # to the plain object triage renders.
    inner = {"flow_id": 42, "status": "ACTIVE"}
    respx_mock.post(MONITORING_URL).mock(
        return_value=_sse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {"content": [{"type": "text", "text": json.dumps(inner)}]},
            }
        )
    )
    assert mcp_client.call_tool("get_flow_status", {"flow_id": 42}) == inner


def test_jsonrpc_error_maps_to_cli_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(MONITORING_URL).mock(
        return_value=_sse(
            {"jsonrpc": "2.0", "id": 1, "error": {"code": -32601, "message": "no such method"}}
        )
    )
    with pytest.raises(CliError) as exc:
        mcp_client.list_tools()
    assert exc.value.code == EXIT.ERROR
    assert "no such method" in exc.value.message


def test_tool_iserror_result_raises(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(MONITORING_URL).mock(
        return_value=_sse(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": json.dumps({"error": "boom"})}],
                },
            }
        )
    )
    with pytest.raises(CliError) as exc:
        mcp_client.call_tool("get_flow_status", {"flow_id": 1})
    assert exc.value.code == EXIT.ERROR
    assert "boom" in exc.value.message


def test_non_2xx_maps_to_exit_code(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(MONITORING_URL).mock(return_value=httpx.Response(404, text="nope"))
    with pytest.raises(CliError) as exc:
        mcp_client.list_tools()
    assert exc.value.code == EXIT.NOT_FOUND


def test_empty_sse_body_raises_upstream(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(MONITORING_URL).mock(
        return_value=httpx.Response(
            200, headers={"content-type": "text/event-stream"}, text="event: ping\n\n"
        )
    )
    with pytest.raises(CliError) as exc:
        mcp_client.list_tools()
    assert exc.value.code == EXIT.UPSTREAM


def test_missing_monitoring_url_raises_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEXLA_MONITORING_URL", raising=False)
    with pytest.raises(CliError) as exc:
        mcp_client.list_tools()
    assert exc.value.code == EXIT.CONFIG
