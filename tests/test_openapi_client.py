from __future__ import annotations

import respx

from nexla_cli import openapi_client

from .conftest import mock_openapi

_FIXTURE_SPEC = {
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
            "get": {"operationId": "get_source_nexla_sources__source_id__get"},
            "patch": {
                "operationId": "update_source_nexla_sources__source_id__patch",
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/UpdateSourceIn"}}
                    }
                },
            },
        },
        "/health": {"get": {"operationId": "health"}},
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
                },
            },
            "UpdateSourceIn": {"type": "object", "properties": {"name": {"type": "string"}}},
        }
    },
}


def _mock_openapi(respx_mock: respx.MockRouter) -> respx.Route:
    return mock_openapi(respx_mock, _FIXTURE_SPEC)


def test_fetch_openapi_makes_one_unauthenticated_get(
    runner, respx_mock: respx.MockRouter
) -> None:
    route = _mock_openapi(respx_mock)
    spec = openapi_client.fetch_openapi()
    assert route.called
    assert route.calls.last.request.headers.get("authorization") is None
    assert spec["openapi"] == "3.1.0"


def test_nexla_paths_filters_non_nexla_routes() -> None:
    paths = openapi_client.nexla_paths(_FIXTURE_SPEC)
    assert set(paths) == {"/nexla/sources", "/nexla/sources/{source_id}"}


def test_resolve_finds_create_route() -> None:
    match = openapi_client.resolve(_FIXTURE_SPEC, "sources", "create")
    assert match is not None
    assert match["method"] == "POST"
    assert match["path"] == "/nexla/sources"


def test_resolve_finds_get_route_by_id_placeholder() -> None:
    match = openapi_client.resolve(_FIXTURE_SPEC, "sources", "update")
    assert match is not None
    assert match["method"] == "PATCH"
    assert match["path"] == "/nexla/sources/{source_id}"


def test_resolve_returns_none_for_unknown_pair() -> None:
    assert openapi_client.resolve(_FIXTURE_SPEC, "sources", "not-a-verb") is None


def test_resolve_returns_none_when_route_missing_from_live_doc() -> None:
    # 'sources'/'delete' is in ROUTES but this fixture spec never defines a
    # DELETE method on /nexla/sources/{source_id} -- must not raise.
    assert openapi_client.resolve(_FIXTURE_SPEC, "sources", "delete") is None


def test_request_schema_dereferences_single_level_ref() -> None:
    schema = openapi_client.request_schema(_FIXTURE_SPEC, "#/components/schemas/CreateSourceIn")
    assert schema["required"] == ["name", "connector"]
    assert "connector" in schema["properties"]


def test_request_body_schema_from_operation() -> None:
    match = openapi_client.resolve(_FIXTURE_SPEC, "sources", "create")
    assert match is not None
    schema = openapi_client.request_body_schema(_FIXTURE_SPEC, match["operation"])
    assert schema is not None
    assert schema["required"] == ["name", "connector"]


def test_request_body_schema_none_when_no_body() -> None:
    match = openapi_client.resolve(_FIXTURE_SPEC, "sources", "list")
    assert match is not None
    assert openapi_client.request_body_schema(_FIXTURE_SPEC, match["operation"]) is None
