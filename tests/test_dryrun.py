"""``--dry-run`` tests: fires zero calls to the real mutating endpoint.

Covers one command per mutating category (create, update, delete-style,
and the nested `mcp-servers attach` case), each with a valid and an
invalid body, plus the local `validate_body` unit-level checks.
"""

from __future__ import annotations

import json

import httpx
import respx
from typer.testing import CliRunner

from nexla_cli import dryrun

from .conftest import BASE_URL, mock_openapi

_SOURCES_SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/nexla/sources": {
            "post": {
                "operationId": "create_source_nexla_sources_post",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/CreateSourceIn"}}
                    }
                },
            }
        },
        "/nexla/sources/{source_id}": {
            "patch": {
                "operationId": "update_source_nexla_sources__source_id__patch",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/UpdateSourceIn"}}
                    }
                },
            },
            "delete": {"operationId": "delete_source_nexla_sources__source_id__delete"},
        },
    },
    "components": {
        "schemas": {
            "CreateSourceIn": {
                "type": "object",
                "required": ["name", "connector"],
                "properties": {
                    "name": {"type": "string"},
                    "connector": {"type": "string"},
                    "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "credential_id": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    "endpoint": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "mode": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "config": {"anyOf": [{"type": "object"}, {"type": "null"}]},
                    "schedule": {"type": "string"},
                },
            },
            "UpdateSourceIn": {
                "type": "object",
                "properties": {
                    "name": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "config": {"anyOf": [{"type": "object"}, {"type": "null"}]},
                },
            },
        }
    },
}

_MCP_SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/nexla/toolsets/{toolset_id}/mcp-servers": {
            "post": {
                "operationId": "attach_mcp_server_post",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/AttachMcpServerIn"}}
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "AttachMcpServerIn": {
                "type": "object",
                "required": ["server_name", "server_url"],
                "properties": {
                    "server_name": {"type": "string"},
                    "server_url": {"type": "string"},
                    "server_description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "auth": {"anyOf": [{"$ref": "#/components/schemas/ExternalMcpAuth"}, {"type": "null"}]},
                },
            },
            "ExternalMcpAuth": {
                "type": "object",
                "required": ["type"],
                "properties": {"type": {"type": "string"}, "value": {"anyOf": [{}, {"type": "null"}]}},
            },
        }
    },
}

_TOOLSETS_SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/nexla/toolsets": {
            "post": {
                "operationId": "create_toolset_nexla_toolsets_post",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/CreateToolsetIn"}}
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "CreateToolsetIn": {
                "type": "object",
                "required": ["name", "nexset_ids"],
                "properties": {
                    "name": {"type": "string"},
                    "nexset_ids": {"type": "array", "items": {"type": "integer"}},
                    "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "mcp_gateway_enabled": {"type": "boolean"},
                },
            }
        }
    },
}


def _mock_openapi(respx_mock: respx.MockRouter, spec: dict) -> respx.Route:
    return mock_openapi(respx_mock, spec)


# ---- unit-level validate_body ----------------------------------------------


def test_validate_body_missing_required_field() -> None:
    schema = _SOURCES_SPEC["components"]["schemas"]["CreateSourceIn"]
    errors = dryrun.validate_body(schema, {"name": "x"})
    assert any("connector" in e for e in errors)


def test_validate_body_wrong_type() -> None:
    schema = _SOURCES_SPEC["components"]["schemas"]["CreateSourceIn"]
    errors = dryrun.validate_body(schema, {"name": "x", "connector": "y", "credential_id": "not-an-int"})
    assert any("credential_id" in e for e in errors)


def test_validate_body_rejects_bool_for_integer_field() -> None:
    # `bool` is a subclass of `int`, so a naive isinstance(x, int) check
    # would wrongly accept True/False for an integer field. A JSON boolean
    # is not a valid integer, so it must be rejected.
    schema = _SOURCES_SPEC["components"]["schemas"]["CreateSourceIn"]
    errors = dryrun.validate_body(schema, {"name": "x", "connector": "y", "credential_id": True})
    assert any("credential_id" in e for e in errors)


def test_validate_body_accepts_bool_for_boolean_field() -> None:
    # ...but a real boolean field must still accept a bool.
    schema = _TOOLSETS_SPEC["components"]["schemas"]["CreateToolsetIn"]
    errors = dryrun.validate_body(
        schema, {"name": "t", "nexset_ids": [1], "mcp_gateway_enabled": True}
    )
    assert errors == []


def test_validate_body_valid_body_is_empty_errors() -> None:
    schema = _SOURCES_SPEC["components"]["schemas"]["CreateSourceIn"]
    errors = dryrun.validate_body(schema, {"name": "x", "connector": "y"})
    assert errors == []


def test_validate_body_optional_null_is_allowed() -> None:
    schema = _SOURCES_SPEC["components"]["schemas"]["CreateSourceIn"]
    errors = dryrun.validate_body(schema, {"name": "x", "connector": "y", "description": None})
    assert errors == []


def test_validate_body_anyof_ref_field_accepts_dict() -> None:
    # anyOf: [{$ref: ...}, {type: null}] — an optional nested object. The
    # $ref branch can't be reduced to a literal type, so the field must be
    # left unconstrained; a real dict must NOT be rejected as "expected
    # null" (regression: mcp-servers attach --auth-type ... dry-run).
    schema = {
        "type": "object",
        "required": ["server_name"],
        "properties": {
            "server_name": {"type": "string"},
            "auth": {"anyOf": [{"$ref": "#/components/schemas/ExternalMcpAuth"}, {"type": "null"}]},
        },
    }
    assert dryrun.validate_body(schema, {"server_name": "s", "auth": {"type": "none"}}) == []
    assert dryrun.validate_body(schema, {"server_name": "s", "auth": None}) == []


# ---- create category (sources create) --------------------------------------


def test_sources_create_dry_run_valid_body_exits_0_and_fires_no_mutating_call(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _SOURCES_SPEC)
    mutating = respx_mock.post(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(
        cli_app,
        ["sources", "create", "--name", "n", "--connector", "s3", "--dry-run"],
    )
    assert result.exit_code == 0
    assert mutating.called is False
    payload = json.loads(result.stdout)
    assert payload["valid"] is True
    assert payload["body"]["schedule"] == "recurring"


def test_sources_create_dry_run_invalid_type_exits_2(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _SOURCES_SPEC)
    mutating = respx_mock.post(f"{BASE_URL}/nexla/sources").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(
        cli_app,
        [
            "sources",
            "create",
            "--name",
            "n",
            "--connector",
            "s3",
            "--params",
            "credential_id=not-an-int",
            "--dry-run",
        ],
    )
    assert result.exit_code == 2
    assert mutating.called is False
    errors = json.loads(result.stderr)
    assert errors["valid"] is False


# ---- input-handling bugs (2.1 malformed JSON, 2.6 default clobber, 2.7) -----


def test_create_malformed_named_json_exits_2_no_traceback(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Bug 2.1: a malformed `--config` value fails cleanly (exit 2) instead
    of leaking a raw Python traceback (exit 1). The parse happens before any
    request, so no HTTP call fires."""
    result = runner.invoke(
        cli_app,
        ["sources", "create", "--name", "x", "--connector", "shopify_api", "--config", "{bad", "--dry-run"],
    )
    assert result.exit_code == 2
    combined = result.stdout + (result.stderr or "")
    assert "Traceback" not in combined
    assert "is not valid JSON" in combined
    assert respx_mock.calls.call_count == 0


def test_create_json_value_survives_untyped_named_default(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Bug 2.6: an explicit `--json` field must not be clobbered by the
    DEFAULT of a named option the user never typed (`--schedule` defaults to
    'recurring')."""
    _mock_openapi(respx_mock, _SOURCES_SPEC)
    result = runner.invoke(
        cli_app,
        ["sources", "create", "--name", "x", "--connector", "s3", "--json", '{"schedule": "once"}', "--dry-run"],
    )
    assert result.exit_code == 0
    body = json.loads(result.stdout)["body"]
    assert body["schedule"] == "once"


def test_create_typed_named_still_wins_over_json(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Bug 2.6 (converse): a named option the user DID type keeps precedence
    over `--json`."""
    _mock_openapi(respx_mock, _SOURCES_SPEC)
    result = runner.invoke(
        cli_app,
        [
            "sources", "create", "--name", "x", "--connector", "s3",
            "--schedule", "once", "--json", '{"schedule": "recurring"}', "--dry-run",
        ],
    )
    assert result.exit_code == 0
    body = json.loads(result.stdout)["body"]
    assert body["schedule"] == "once"


def test_toolsets_create_dry_run_keeps_false_default_without_json(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _TOOLSETS_SPEC)
    mutating = respx_mock.post(f"{BASE_URL}/nexla/toolsets").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(
        cli_app,
        [
            "toolsets",
            "create",
            "--name",
            "t",
            "--nexset-id",
            "1",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert mutating.called is False
    body = json.loads(result.stdout)["body"]
    assert body["mcp_gateway_enabled"] is False


def test_create_param_without_equals_exits_2(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    """Bug 2.7: a `--params` entry with no `=` is rejected, not silently
    accepted as an empty-string-valued key."""
    result = runner.invoke(
        cli_app,
        ["sources", "create", "--name", "x", "--connector", "s3", "--params", "noequalskey", "--dry-run"],
    )
    assert result.exit_code == 2
    combined = result.stdout + (result.stderr or "")
    assert "key=value" in combined
    assert respx_mock.calls.call_count == 0


# ---- update category (sources update) --------------------------------------


def test_sources_update_dry_run_valid_body(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _SOURCES_SPEC)
    mutating = respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(cli_app, ["sources", "update", "1", "--name", "new-name", "--dry-run"])
    assert result.exit_code == 0
    assert mutating.called is False


def test_sources_update_dry_run_invalid_body(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _SOURCES_SPEC)
    mutating = respx_mock.patch(f"{BASE_URL}/nexla/sources/1").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(
        cli_app, ["sources", "update", "1", "--params", "config=not-a-dict", "--dry-run"]
    )
    assert result.exit_code == 2
    assert mutating.called is False


# ---- delete-style category (sources delete) ---------------------------------


def test_sources_delete_dry_run_fires_no_mutating_call(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _SOURCES_SPEC)
    mutating = respx_mock.delete(f"{BASE_URL}/nexla/sources/1").mock(return_value=httpx.Response(204))
    result = runner.invoke(cli_app, ["sources", "delete", "1", "--dry-run"])
    assert result.exit_code == 0
    assert mutating.called is False
    assert "deleted source" not in result.stdout


# ---- nested case (mcp-servers attach) ---------------------------------------


def test_mcp_servers_attach_dry_run_valid_body(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    _mock_openapi(respx_mock, _MCP_SPEC)
    mutating = respx_mock.post(f"{BASE_URL}/nexla/toolsets/1/mcp-servers").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(
        cli_app,
        [
            "mcp-servers",
            "attach",
            "1",
            "--server-name",
            "s",
            "--server-url",
            "https://example.com",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    assert mutating.called is False


def test_mcp_servers_attach_dry_run_invalid_body_missing_required(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # AttachMcpServerIn requires server_name+server_url; the CLI itself
    # requires --server-name/--server-url too, so simulate the "invalid
    # against the live schema" case via a schema that now also requires a
    # field the CLI doesn't send.
    spec = json.loads(json.dumps(_MCP_SPEC))
    spec["components"]["schemas"]["AttachMcpServerIn"]["required"].append("server_owner_id")
    _mock_openapi(respx_mock, spec)
    mutating = respx_mock.post(f"{BASE_URL}/nexla/toolsets/1/mcp-servers").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(
        cli_app,
        [
            "mcp-servers",
            "attach",
            "1",
            "--server-name",
            "s",
            "--server-url",
            "https://example.com",
            "--dry-run",
        ],
    )
    assert result.exit_code == 2
    assert mutating.called is False


def test_mcp_servers_attach_dry_run_auth_type_builds_valid_nested_auth(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    # --auth-type/--auth-value build a nested `auth: {type, value}` object,
    # which matches the ExternalMcpAuth schema. Regression: the shallow
    # validator used to collapse the anyOf-$ref/null `auth` field to
    # "must be null" and reject the dict with exit 2.
    _mock_openapi(respx_mock, _MCP_SPEC)
    mutating = respx_mock.post(f"{BASE_URL}/nexla/toolsets/1/mcp-servers").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    for extra in (["--auth-type", "none"], ["--auth-type", "bearer", "--auth-value", "tok"]):
        result = runner.invoke(
            cli_app,
            ["mcp-servers", "attach", "1", "--server-name", "s", "--server-url",
             "https://example.com", *extra, "--dry-run"],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["valid"] is True
        assert payload["body"]["auth"]["type"] == extra[1]
    assert mutating.called is False


# ---- body-less mutating command (e.g. sources activate) --------------------


def test_sources_activate_dry_run_no_body_schema_is_trivially_valid(
    runner: CliRunner, cli_app, respx_mock: respx.MockRouter
) -> None:
    spec = {
        "openapi": "3.1.0",
        "paths": {"/nexla/sources/{source_id}/activate": {"post": {"operationId": "activate"}}},
        "components": {"schemas": {}},
    }
    _mock_openapi(respx_mock, spec)
    mutating = respx_mock.post(f"{BASE_URL}/nexla/sources/1/activate").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    result = runner.invoke(cli_app, ["sources", "activate", "1", "--dry-run"])
    assert result.exit_code == 0
    assert mutating.called is False
