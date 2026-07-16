from __future__ import annotations

import json

import respx
from typer.testing import CliRunner

from .conftest import mock_openapi

_SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/nexla/sources": {
            "get": {"operationId": "list_sources_nexla_sources_get"},
            "post": {
                "operationId": "create_source_nexla_sources_post",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/CreateSourceIn"}}
                    }
                },
            },
        },
        "/nexla/sources/{source_id}": {
            "get": {"operationId": "get_source_nexla_sources__source_id__get"}
        },
        "/health": {"get": {"operationId": "health"}},
    },
    "components": {
        "schemas": {
            "CreateSourceIn": {
                "type": "object",
                "required": ["name", "connector"],
                "properties": {"name": {"type": "string"}, "connector": {"type": "string"}},
            }
        }
    },
}


def _mock_openapi(respx_mock: respx.MockRouter) -> respx.Route:
    return mock_openapi(respx_mock, _SPEC)


def test_schema_no_arg_dumps_full_nexla_subset(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock)
    result = runner.invoke(cli_app, ["schema"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert set(payload["paths"]) == {"/nexla/sources", "/nexla/sources/{source_id}"}
    assert "/health" not in payload["paths"]


def test_schema_sources_create_returns_distinct_focused_schema(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock)
    result = runner.invoke(cli_app, ["schema", "sources.create"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["method"] == "POST"
    assert payload["path"] == "/nexla/sources"
    assert payload["request_body"]["required"] == ["name", "connector"]

    full = runner.invoke(cli_app, ["schema"])
    assert json.loads(full.stdout) != payload


def test_schema_sanitizes_ansi_and_zero_width_chars_in_request_body_schema(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # `schema`'s output only ever includes method/path/parameters/request_body
    # (see openapi_client.resolve/request_body_schema) — a dirty "summary" on
    # the operation itself would never be echoed, so inject into a property
    # description inside the dereferenced request body schema instead, which
    # genuinely flows through to stdout.
    dirty_spec = json.loads(json.dumps(_SPEC))
    dirty_spec["components"]["schemas"]["CreateSourceIn"]["properties"]["name"]["description"] = (
        "Source name\x1b[31m" + chr(0x200B) + "hidden"
    )
    mock_openapi(respx_mock, dirty_spec)
    result = runner.invoke(cli_app, ["schema", "sources.create"])
    assert result.exit_code == 0
    assert "\x1b[31m" not in result.stdout
    assert chr(0x200B) not in result.stdout
    assert "Source name" in result.stdout
    assert "hidden" in result.stdout


def test_schema_unknown_command_exits_not_found(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock)
    result = runner.invoke(cli_app, ["schema", "sources.bogus"])
    assert result.exit_code == 5  # EXIT.NOT_FOUND


def test_schema_bad_command_shape_exits_validation(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock)
    result = runner.invoke(cli_app, ["schema", "sources"])
    assert result.exit_code == 2  # EXIT.VALIDATION
