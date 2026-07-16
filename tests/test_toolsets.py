from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_list(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/toolsets").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": 1,
                        "name": "ts1",
                        "status": "active",
                        "mcp_gateway_enabled": True,
                        "tool_count": 2,
                    }
                ],
                "page": 1,
                "per_page": 50,
            },
        )
    )
    result = runner.invoke(cli_app, ["toolsets", "list"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/toolsets"
    assert "ts1" in result.stdout


def test_get(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/toolsets/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "ts1"})
    )
    result = runner.invoke(cli_app, ["toolsets", "get", "1"])
    assert result.exit_code == 0
    assert route.called


def test_create(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/toolsets").mock(
        return_value=httpx.Response(201, json={"id": 2, "name": "new-ts"})
    )
    result = runner.invoke(
        cli_app, ["toolsets", "create", "--name", "new-ts", "--nexset-id", "1", "--nexset-id", "2"]
    )
    assert result.exit_code == 0
    assert route.called
    body = route.calls.last.request.content
    assert b"[1, 2]" in body or b"[1,2]" in body


def test_update(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.patch(f"{BASE_URL}/nexla/toolsets/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "renamed"})
    )
    result = runner.invoke(cli_app, ["toolsets", "update", "1", "--name", "renamed"])
    assert result.exit_code == 0
    assert route.called


def test_delete(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete(f"{BASE_URL}/nexla/toolsets/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["toolsets", "delete", "1"])
    assert result.exit_code == 0
    assert route.called
    assert "deleted" in result.stdout and "true" in result.stdout


def test_add_nexsets(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(f"{BASE_URL}/nexla/toolsets/1/nexsets").mock(
        return_value=httpx.Response(200, json={"toolset_id": 1, "added_tool_ids": [5], "nexsets_already_present": []})
    )
    result = runner.invoke(cli_app, ["toolsets", "add-nexsets", "1", "--nexset-id", "9"])
    assert result.exit_code == 0
    assert route.called
    assert route.calls.last.request.url.path == "/nexla/toolsets/1/nexsets"
