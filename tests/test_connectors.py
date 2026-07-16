from __future__ import annotations

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL


def test_search(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/connectors/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "name": "bigquery",
                        "display_name": "BigQuery",
                        "kind": "db",
                        "supported": True,
                        "supports": {"credential": True, "source": True, "sink": True},
                        "score": 0.9,
                    }
                ],
                "total_indexed": 1,
                "next_offset": None,
            },
        )
    )
    result = runner.invoke(cli_app, ["connectors", "search", "big"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/connectors/search"
    assert route.calls.last.request.url.params["q"] == "big"
    assert "bigquery" in result.stdout


def test_search_no_query_lists_everything(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/connectors/search").mock(
        return_value=httpx.Response(200, json={"items": [], "total_indexed": 0, "next_offset": None})
    )
    result = runner.invoke(cli_app, ["connectors", "search"])
    assert result.exit_code == 0
    assert "q" not in route.calls.last.request.url.params


def test_describe(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/connectors/describe/bigquery").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "bigquery",
                "display_name": "BigQuery",
                "kind": "db",
                "supported": True,
                "supports": {"credential": True, "source": True, "sink": True},
            },
        )
    )
    result = runner.invoke(cli_app, ["connectors", "describe", "bigquery"])
    assert result.exit_code == 0
    assert route.called


def test_describe_credential(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/connectors/describe/bigquery/credential").mock(
        return_value=httpx.Response(200, json={"auth_modes": [], "instructions": None})
    )
    result = runner.invoke(cli_app, ["connectors", "describe-credential", "bigquery"])
    assert result.exit_code == 0
    assert route.called


def test_describe_credential_mode(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(
        f"{BASE_URL}/nexla/connectors/describe/bigquery/credential/default"
    ).mock(return_value=httpx.Response(200, json={"auth_mode": "default", "fields": []}))
    result = runner.invoke(cli_app, ["connectors", "describe-credential-mode", "bigquery", "default"])
    assert result.exit_code == 0
    assert route.called


def test_describe_source(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/connectors/describe/bigquery/source").mock(
        return_value=httpx.Response(200, json={"kind": "db", "modes": []})
    )
    result = runner.invoke(cli_app, ["connectors", "describe-source", "bigquery"])
    assert result.exit_code == 0
    assert route.called


def test_describe_source_endpoint(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(
        f"{BASE_URL}/nexla/connectors/describe/shopify_api/source/get_customers"
    ).mock(return_value=httpx.Response(200, json={"endpoint": "get_customers", "fields": []}))
    result = runner.invoke(
        cli_app, ["connectors", "describe-source-endpoint", "shopify_api", "get_customers"]
    )
    assert result.exit_code == 0
    assert route.called


def test_describe_sink(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/connectors/describe/s3/sink").mock(
        return_value=httpx.Response(200, json={"kind": "file", "fields": []})
    )
    result = runner.invoke(cli_app, ["connectors", "describe-sink", "s3"])
    assert result.exit_code == 0
    assert route.called


def test_describe_sink_endpoint(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(
        f"{BASE_URL}/nexla/connectors/describe/shopify_api/sink/create_order"
    ).mock(return_value=httpx.Response(200, json={"endpoint": "create_order", "fields": []}))
    result = runner.invoke(
        cli_app, ["connectors", "describe-sink-endpoint", "shopify_api", "create_order"]
    )
    assert result.exit_code == 0
    assert route.called


def test_no_list_or_get_commands(cli_app) -> None:
    runner = CliRunner()
    result = runner.invoke(cli_app, ["connectors", "list"])
    assert result.exit_code != 0
    result = runner.invoke(cli_app, ["connectors", "get", "bigquery"])
    assert result.exit_code != 0
