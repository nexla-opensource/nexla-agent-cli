from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_list(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/flows").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": 1, "name": "f1", "status": "ACTIVE"}], "page": 1, "per_page": 50}
        )
    )
    result = runner.invoke(cli_app, ["flows", "list"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/flows"
    assert "f1" in result.stdout


def test_get(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/flows/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "f1"})
    )
    result = runner.invoke(cli_app, ["flows", "get", "1"])
    assert result.exit_code == 0
    assert route.called


def test_activate(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.put(f"{BASE_URL}/nexla/flows/1/activate").mock(
        return_value=httpx.Response(200, json={"ok": True, "flow_id": 1})
    )
    result = runner.invoke(cli_app, ["flows", "activate", "1"])
    assert result.exit_code == 0
    assert route.called


def test_pause(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.put(f"{BASE_URL}/nexla/flows/1/pause").mock(
        return_value=httpx.Response(200, json={"ok": True, "flow_id": 1})
    )
    result = runner.invoke(cli_app, ["flows", "pause", "1"])
    assert result.exit_code == 0
    assert route.called


def test_delete(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete(f"{BASE_URL}/nexla/flows/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["flows", "delete", "1"])
    assert result.exit_code == 0
    assert route.called
    assert "deleted" in result.stdout and "true" in result.stdout
