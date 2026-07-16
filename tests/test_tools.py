from __future__ import annotations

import json

import httpx
import respx
from typer.testing import CliRunner

from .conftest import BASE_URL, mock_openapi

_TOOLS_SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/nexla/tools/{tool_id}/runtime-config": {
            "patch": {
                "operationId": "set_runtime_config_nexla_tools__tool_id__runtime_config_patch",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/SetRuntimeConfigIn"}
                        }
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "SetRuntimeConfigIn": {
                "type": "object",
                "required": ["strategy", "connector_name", "connector_type"],
                "properties": {
                    "strategy": {"type": "string"},
                    "connector_name": {"type": "string"},
                    "connector_type": {"type": "string"},
                    "credential_mappings": {
                        "anyOf": [{"type": "array"}, {"type": "null"}]
                    },
                },
            }
        }
    },
}


def _mock_openapi(respx_mock: respx.MockRouter, spec: dict) -> respx.Route:
    return mock_openapi(respx_mock, spec)


def test_list(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/tools").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": 1, "name": "t1", "kind": "nexset_read"}], "page": 1, "per_page": 50}
        )
    )
    result = runner.invoke(cli_app, ["tools", "list"])
    assert result.exit_code == 0
    assert route.calls.last.request.url.path == "/nexla/tools"
    assert "t1" in result.stdout


def test_get(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.get(f"{BASE_URL}/nexla/tools/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "t1"})
    )
    result = runner.invoke(cli_app, ["tools", "get", "1"])
    assert result.exit_code == 0
    assert route.called


def test_set_runtime_config(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.patch(f"{BASE_URL}/nexla/tools/1/runtime-config").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "t1"})
    )
    result = runner.invoke(
        cli_app,
        [
            "tools",
            "set-runtime-config",
            "1",
            "--strategy",
            "auto",
            "--connector-name",
            "newsapi_api",
            "--connector-type",
            "templatized_api",
        ],
    )
    assert result.exit_code == 0
    assert route.called


def test_set_runtime_config_json_and_params_passthrough(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    respx_mock.patch(f"{BASE_URL}/nexla/tools/1/runtime-config").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "t1"})
    )
    result = runner.invoke(
        cli_app,
        [
            "tools",
            "set-runtime-config",
            "1",
            "--strategy",
            "auto",
            "--connector-name",
            "newsapi_api",
            "--connector-type",
            "templatized_api",
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


def test_set_runtime_config_mapped_dry_run_missing_credential_mappings_fails(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _TOOLS_SPEC)
    mutating = respx_mock.patch(f"{BASE_URL}/nexla/tools/1/runtime-config").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "t1"})
    )
    result = runner.invoke(
        cli_app,
        [
            "tools",
            "set-runtime-config",
            "1",
            "--strategy",
            "mapped",
            "--connector-name",
            "newsapi_api",
            "--connector-type",
            "templatized_api",
            "--dry-run",
        ],
    )
    assert result.exit_code == 2
    assert mutating.called is False
    errors = json.loads(result.stderr)
    assert errors["valid"] is False
    assert any("credential_mappings" in e for e in errors["errors"])


def test_set_runtime_config_mapped_dry_run_with_credential_mappings_passes(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _TOOLS_SPEC)
    mutating = respx_mock.patch(f"{BASE_URL}/nexla/tools/1/runtime-config").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "t1"})
    )
    result = runner.invoke(
        cli_app,
        [
            "tools",
            "set-runtime-config",
            "1",
            "--strategy",
            "mapped",
            "--connector-name",
            "newsapi_api",
            "--connector-type",
            "templatized_api",
            "--credential-mappings",
            '[{"user_id": 1, "credential_id": 2}]',
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert mutating.called is False
    payload = json.loads(result.stdout)
    assert payload["valid"] is True


def test_set_runtime_config_auto_dry_run_passes_without_credential_mappings(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _TOOLS_SPEC)
    mutating = respx_mock.patch(f"{BASE_URL}/nexla/tools/1/runtime-config").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "t1"})
    )
    result = runner.invoke(
        cli_app,
        [
            "tools",
            "set-runtime-config",
            "1",
            "--strategy",
            "auto",
            "--connector-name",
            "newsapi_api",
            "--connector-type",
            "templatized_api",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert mutating.called is False
    payload = json.loads(result.stdout)
    assert payload["valid"] is True


def test_clear_runtime_config(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete(f"{BASE_URL}/nexla/tools/1/runtime-config").mock(
        return_value=httpx.Response(200, json={"id": 1, "name": "t1"})
    )
    result = runner.invoke(cli_app, ["tools", "clear-runtime-config", "1"])
    assert result.exit_code == 0
    assert route.called


def test_delete(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    # The backend can soft-pause a nexset-derived tool instead of hard-deleting
    # it; the CLI must surface the real response body rather than an
    # unconditional "deleted" claim.
    route = respx_mock.delete(f"{BASE_URL}/nexla/tools/1").mock(
        return_value=httpx.Response(200, json={"id": 1, "status": "paused"})
    )
    result = runner.invoke(cli_app, ["tools", "delete", "1"])
    assert result.exit_code == 0
    assert route.called
    assert "deleted tool 1" not in result.stdout
    assert "paused" in result.stdout


def test_delete_no_content(runner: CliRunner, cli_app, respx_mock: respx.MockRouter) -> None:
    route = respx_mock.delete(f"{BASE_URL}/nexla/tools/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["tools", "delete", "1"])
    assert result.exit_code == 0
    assert route.called
    assert "deleted tool 1" not in result.stdout
