from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_list(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/toolsets/1/mcp-servers").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 5,
                    "toolset_id": 1,
                    "server_name": "srv1",
                    "server_url": "https://mcp.example.com",
                    "status": "active",
                }
            ],
        )
    )
    result = runner.invoke(cli_app, ["mcp-servers", "list", "1"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/toolsets/1/mcp-servers"
    assert "srv1" in result.stdout


def test_attach(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/toolsets/1/mcp-servers").mock(
        return_value=httpx.Response(
            201, json={"id": 5, "toolset_id": 1, "server_name": "srv1", "server_url": "https://x.com"}
        )
    )
    result = runner.invoke(
        cli_app,
        [
            "mcp-servers",
            "attach",
            "1",
            "--server-name",
            "srv1",
            "--server-url",
            "https://x.com",
            "--auth-type",
            "bearer",
            "--auth-value",
            "secret-token",
        ],
    )
    assert result.exit_code == 0
    assert route.called


def test_attach_json_and_params_passthrough(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.post(f"{BASE_URL}/nexla/toolsets/1/mcp-servers").mock(
        return_value=httpx.Response(
            201, json={"id": 5, "toolset_id": 1, "server_name": "srv1", "server_url": "https://x.com"}
        )
    )
    result = runner.invoke(
        cli_app,
        [
            "mcp-servers",
            "attach",
            "1",
            "--server-name",
            "srv1",
            "--server-url",
            "https://x.com",
            "--json",
            '{"extra_field": "from-json"}',
            "--params",
            "params_field=from-params",
        ],
    )
    assert result.exit_code == 0
    body = respx_mock.calls.last.request.content
    assert b"from-json" in body
    assert b"from-params" in body


def test_sync(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/toolsets/1/mcp-servers/5/sync").mock(
        return_value=httpx.Response(200, json={"triggered": True, "server_id": 5})
    )
    result = runner.invoke(cli_app, ["mcp-servers", "sync", "1", "5"])
    assert result.exit_code == 0
    assert route.called


def test_detach(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete(f"{BASE_URL}/nexla/toolsets/1/mcp-servers/5").mock(
        return_value=httpx.Response(204)
    )
    result = runner.invoke(cli_app, ["mcp-servers", "detach", "1", "5"])
    assert result.exit_code == 0
    assert route.called
    assert "detached mcp server 5" in result.stdout
