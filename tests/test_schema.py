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


def _commands_catalog(runner: CliRunner, cli_app) -> dict:
    """Invoke `schema --commands` and return the parsed catalog (no network)."""
    result = runner.invoke(cli_app, ["schema", "--commands"])
    assert result.exit_code == 0, result.stdout
    return json.loads(result.stdout)


def _by_path(catalog: dict) -> dict:
    return {c["path"]: c for c in catalog["commands"]}


def test_commands_catalog_lists_known_commands(runner: CliRunner, cli_app) -> None:
    by_path = _by_path(_commands_catalog(runner, cli_app))
    for path in ("sources create", "sinks list", "credentials get", "triage errors"):
        assert path in by_path, sorted(by_path)


def test_commands_catalog_dry_run_is_bool_flag(runner: CliRunner, cli_app) -> None:
    by_path = _by_path(_commands_catalog(runner, cli_app))
    params = {p["name"]: p for p in by_path["sources create"]["params"]}
    assert "--dry-run" in params, sorted(params)
    dry = params["--dry-run"]
    assert dry["is_flag"] is True
    assert dry["type"] == "boolean"
    assert dry["required"] is False


def test_commands_catalog_source_id_is_required_argument(runner: CliRunner, cli_app) -> None:
    by_path = _by_path(_commands_catalog(runner, cli_app))
    params = {p["name"]: p for p in by_path["sources get"]["params"]}
    assert "source_id" in params, sorted(params)
    assert params["source_id"]["required"] is True
    assert params["source_id"]["is_flag"] is False


def test_commands_catalog_includes_exit_code_taxonomy(runner: CliRunner, cli_app) -> None:
    catalog = _commands_catalog(runner, cli_app)
    codes = {e["name"]: e["code"] for e in catalog["exit_codes"]}
    assert codes["OK"] == 0
    assert codes["VALIDATION"] == 2
    assert codes["AUTH"] == 4
    assert codes["NOT_FOUND"] == 5
    assert codes["UPSTREAM"] == 6


def test_commands_catalog_excludes_hidden_v1_groups(runner: CliRunner, cli_app) -> None:
    # The not-implemented-in-v1 groups are hidden from `--help`, so the
    # catalog excludes them too (matching --help).
    by_path = _by_path(_commands_catalog(runner, cli_app))
    for hidden in ("users", "metrics", "notifications", "code-containers"):
        assert not any(
            p == hidden or p.startswith(f"{hidden} ") for p in by_path
        ), f"{hidden} should be hidden from the catalog"


def test_commands_catalog_needs_no_network(runner: CliRunner, cli_app) -> None:
    # No respx mock is installed here: if `--commands` tried to fetch
    # /openapi.json it would fail, not return a clean catalog. Pure
    # introspection must succeed with the full command tree.
    catalog = _commands_catalog(runner, cli_app)
    assert "sources create" in {c["path"] for c in catalog["commands"]}


def test_commands_catalog_exposes_global_output_options(runner: CliRunner, cli_app) -> None:
    catalog = _commands_catalog(runner, cli_app)
    names = {p["name"] for p in catalog["global_options"]}
    assert "--output" in names
    # Typer's shell-completion plumbing must be filtered out.
    assert "--install-completion" not in names
    assert "install_completion" not in names
