"""Shared live-schema fetch + resource/verb -> route lookup.

Both ``nexla-cli schema`` (``schema.py``) and ``--dry-run`` (``dryrun.py``) need
the same thing: fetch ``/openapi.json`` (unauthenticated), filter to
``/nexla/*`` paths, and resolve a ``(resource, verb)`` pair to its
``(method, path, request_schema | None)``. Built once here so neither
module duplicates the fetch-and-filter logic — if you find yourself
writing a second ``client.request("GET", "/openapi.json", ...)`` call site
outside this module, route it through :func:`fetch_openapi` instead.

The live doc's ``operationId`` is FastAPI's verbose auto-generated form
(e.g. ``create_source_nexla_sources_post``), not a clean ``sources.create``
token — :data:`ROUTES` is a hand-maintained
``(resource, verb) -> (method, path template)`` table instead, mirroring
the exhaustive resource/verb surface of the deployed ``/nexla/*`` API
(17 resources, ~61 routes). Path templates use ``{id}`` (or a named
placeholder for nested resources) purely as a human-readable token — they
are matched against the live doc's own ``{...}`` path-parameter names
positionally (see :func:`resolve`), not by exact placeholder-name string
match, since the live doc may spell a given path parameter differently
(e.g. ``{source_id}`` vs ``{id}``).
"""

from __future__ import annotations

from typing import Any

from . import client

# (resource, verb) -> (HTTP method, path template). Hand-maintained against
# the deployed ``/nexla/*`` API's resource/verb surface -- do NOT derive this
# from `operationId` parsing (see module docstring for why).
ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("sources", "list"): ("GET", "/nexla/sources"),
    ("sources", "get"): ("GET", "/nexla/sources/{id}"),
    ("sources", "create"): ("POST", "/nexla/sources"),
    ("sources", "update"): ("PATCH", "/nexla/sources/{id}"),
    ("sources", "activate"): ("POST", "/nexla/sources/{id}/activate"),
    ("sources", "pause"): ("POST", "/nexla/sources/{id}/pause"),
    ("sources", "delete"): ("DELETE", "/nexla/sources/{id}"),
    ("sources", "sample"): ("POST", "/nexla/sources/{id}/sample"),
    ("sources", "file-upload"): ("POST", "/nexla/sources/{id}/file_upload"),
    ("sinks", "list"): ("GET", "/nexla/sinks"),
    ("sinks", "get"): ("GET", "/nexla/sinks/{id}"),
    ("sinks", "create"): ("POST", "/nexla/sinks"),
    ("sinks", "update"): ("PATCH", "/nexla/sinks/{id}"),
    ("sinks", "activate"): ("POST", "/nexla/sinks/{id}/activate"),
    ("sinks", "pause"): ("POST", "/nexla/sinks/{id}/pause"),
    ("sinks", "delete"): ("DELETE", "/nexla/sinks/{id}"),
    ("nexsets", "list"): ("GET", "/nexla/nexsets"),
    ("nexsets", "get"): ("GET", "/nexla/nexsets/{id}"),
    ("nexsets", "transform"): ("POST", "/nexla/nexsets/{id}/transform"),
    ("nexsets", "activate"): ("PUT", "/nexla/nexsets/{id}/activate"),
    ("credentials", "list"): ("GET", "/nexla/credentials"),
    ("credentials", "get"): ("GET", "/nexla/credentials/{id}"),
    ("credentials", "create"): ("POST", "/nexla/credentials"),
    ("credentials", "update"): ("PATCH", "/nexla/credentials/{id}"),
    ("credentials", "delete"): ("DELETE", "/nexla/credentials/{id}"),
    ("flows", "list"): ("GET", "/nexla/flows"),
    ("flows", "get"): ("GET", "/nexla/flows/{id}"),
    ("flows", "activate"): ("PUT", "/nexla/flows/{id}/activate"),
    ("flows", "pause"): ("PUT", "/nexla/flows/{id}/pause"),
    ("flows", "delete"): ("DELETE", "/nexla/flows/{id}"),
    ("transforms", "test"): ("POST", "/nexla/transforms/test"),
    ("probe", "run"): ("POST", "/nexla/probe"),
    ("connectors", "search"): ("GET", "/nexla/connectors/search"),
    ("connectors", "describe"): ("GET", "/nexla/connectors/describe/{name}"),
    ("connectors", "describe-credential"): ("GET", "/nexla/connectors/describe/{name}/credential"),
    ("connectors", "describe-credential-mode"): (
        "GET",
        "/nexla/connectors/describe/{name}/credential/{auth_mode}",
    ),
    ("connectors", "describe-source"): ("GET", "/nexla/connectors/describe/{name}/source"),
    ("connectors", "describe-source-endpoint"): (
        "GET",
        "/nexla/connectors/describe/{name}/source/{endpoint}",
    ),
    ("connectors", "describe-sink"): ("GET", "/nexla/connectors/describe/{name}/sink"),
    ("connectors", "describe-sink-endpoint"): (
        "GET",
        "/nexla/connectors/describe/{name}/sink/{endpoint}",
    ),
    ("toolsets", "list"): ("GET", "/nexla/toolsets"),
    ("toolsets", "get"): ("GET", "/nexla/toolsets/{id}"),
    ("toolsets", "create"): ("POST", "/nexla/toolsets"),
    ("toolsets", "update"): ("PATCH", "/nexla/toolsets/{id}"),
    ("toolsets", "delete"): ("DELETE", "/nexla/toolsets/{id}"),
    ("toolsets", "add-nexsets"): ("POST", "/nexla/toolsets/{id}/nexsets"),
    ("tools", "list"): ("GET", "/nexla/tools"),
    ("tools", "get"): ("GET", "/nexla/tools/{id}"),
    ("tools", "set-runtime-config"): ("PATCH", "/nexla/tools/{id}/runtime-config"),
    ("tools", "clear-runtime-config"): ("DELETE", "/nexla/tools/{id}/runtime-config"),
    ("tools", "delete"): ("DELETE", "/nexla/tools/{id}"),
    ("mcp-servers", "list"): ("GET", "/nexla/toolsets/{toolset_id}/mcp-servers"),
    ("mcp-servers", "attach"): ("POST", "/nexla/toolsets/{toolset_id}/mcp-servers"),
    ("mcp-servers", "sync"): ("POST", "/nexla/toolsets/{toolset_id}/mcp-servers/{id}/sync"),
    ("mcp-servers", "detach"): ("DELETE", "/nexla/toolsets/{toolset_id}/mcp-servers/{id}"),
    ("context", "get"): ("GET", "/nexla/context"),
    ("orgs", "list"): ("GET", "/nexla/orgs"),
    ("orgs", "get"): ("GET", "/nexla/orgs/{id}"),
    ("code-containers", "list"): ("GET", "/nexla/code-containers"),
    ("metrics", "catalog"): ("GET", "/nexla/metrics/catalog"),
    ("metrics", "for-resource"): ("GET", "/nexla/metrics/{resource_type}/{resource_id}"),
    ("metrics", "get"): ("GET", "/nexla/metrics/{resource_type}/{resource_id}/{metric_type}"),
    ("users", "list"): ("GET", "/nexla/users"),
    ("users", "get"): ("GET", "/nexla/users/{id}"),
    ("notifications", "list"): ("GET", "/nexla/notifications"),
}


def fetch_openapi() -> dict[str, Any]:
    """Fetch the live, unauthenticated ``/openapi.json`` document.

    One ``client.request(...)`` call site for the whole CLI — ``schema``
    and ``--dry-run`` both go through this, never a second direct fetch.
    """
    spec: dict[str, Any] = client.request("GET", "/openapi.json", require_auth=False)
    return spec


def nexla_paths(spec: dict[str, Any]) -> dict[str, Any]:
    """Filter ``spec['paths']`` down to the ``/nexla/*`` subset."""
    paths: dict[str, Any] = spec.get("paths", {})
    return {p: m for p, m in paths.items() if p.startswith("/nexla")}


def _placeholder_shape(path: str) -> tuple[str, int]:
    """Reduce a path to (literal-segments-joined, placeholder-count).

    Used to match our hand-maintained ``ROUTES`` template against the live
    doc's actual path string regardless of the exact placeholder name the
    live doc happens to use (e.g. ``{id}`` vs ``{source_id}``) — only the
    literal segments and the *position*/count of ``{...}`` placeholders
    need to agree.
    """
    segments = path.strip("/").split("/")
    literal = "/".join(s if not (s.startswith("{") and s.endswith("}")) else "\0" for s in segments)
    count = sum(1 for s in segments if s.startswith("{") and s.endswith("}"))
    return literal, count


def resolve(spec: dict[str, Any], resource: str, verb: str) -> dict[str, Any] | None:
    """Resolve ``(resource, verb)`` to its live path item + method.

    Returns ``{"method": ..., "path": ..., "operation": <path-item's
    method entry from the live doc>}`` or ``None`` if the (resource, verb)
    pair isn't in :data:`ROUTES`, or the templated path can't be matched
    against any path actually present in the live doc (drift between this
    table and the deployed API).
    """
    key = (resource, verb)
    if key not in ROUTES:
        return None
    method, template = ROUTES[key]
    want_shape = _placeholder_shape(template)
    paths = nexla_paths(spec)
    for live_path, methods in paths.items():
        if _placeholder_shape(live_path) != want_shape:
            continue
        operation = methods.get(method.lower())
        if operation is not None:
            return {"method": method, "path": live_path, "operation": operation}
    return None


def request_schema(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Dereference a single-level ``#/components/schemas/<Name>`` ``$ref``.

    Only single-level dereferencing is implemented — the generated
    schemas observed on the live API are flat with ``anyOf``-for-optional
    fields rather than deeply nested ``$ref`` chains (e.g.
    ``CreateSourceIn``). If a future schema nests
    a ``$ref`` inside a property, this returns that property's raw
    ``{"$ref": ...}`` object unresolved rather than silently guessing —
    extend this function if/when that shape shows up for real.
    """
    name = ref.rsplit("/", 1)[-1]
    schemas: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    result: dict[str, Any] = schemas.get(name, {})
    return result


def request_body_schema(spec: dict[str, Any], operation: dict[str, Any]) -> dict[str, Any] | None:
    """Extract + dereference an operation's JSON request-body schema, if any."""
    body = operation.get("requestBody")
    if not isinstance(body, dict):
        return None
    content = body.get("content", {}).get("application/json", {})
    schema = content.get("schema")
    if not isinstance(schema, dict):
        return None
    ref = schema.get("$ref")
    if isinstance(ref, str):
        return request_schema(spec, ref)
    return schema
