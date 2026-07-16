from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_get(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/context").mock(
        return_value=httpx.Response(
            200,
            json={
                "flows": [],
                "data_sources": [],
                "data_sets": [],
                "credentials": [],
                "connectors_source": [],
                "connectors_destination": [],
            },
        )
    )
    result = runner.invoke(cli_app, ["context", "get"])
    assert result.exit_code == 0
    assert route.calls.last.request.method == "GET"
    assert route.calls.last.request.url.path == "/nexla/context"
