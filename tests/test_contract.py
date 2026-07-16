"""Opt-in, live-HTTP drift guard between the CLI's command tree and the
real deployed API's OpenAPI document.

The CLI
and API now live in two entirely separate git repos with independent
venvs, so a single test process can no longer import both
``nexla_cli.app`` and an in-process FastAPI app object. This test instead
fetches the real, live ``/openapi.json`` over HTTP (the same call
``nexla-cli schema`` itself makes) and checks it against the CLI's own
registered command groups -- a loose, but real, drift guard.

Gated on ``NEXLA_API_URL`` being set, mirroring the existing
deferred-live-test convention used elsewhere in this repo's tests
(a plain ``pytest -q`` run with no env vars must SKIP this test cleanly,
not fail or error) -- this is the one test in the suite allowed to make a
real network call.
"""

from __future__ import annotations

import os

import pytest

from nexla_cli import app, openapi_client

pytestmark = pytest.mark.skipif(
    not os.environ.get("NEXLA_API_URL"),
    reason="opt-in live contract test: set NEXLA_API_URL to run",
)

# `schema` is a callback-only sub-app, not one of the 17
# resource modules the deployed API's surface covers -- it has no
# `/nexla/schema` route to check against. `skill` is a purely local
# filesystem operation (installs SKILL.md to ~/.claude/skills/) that makes
# no HTTP call at all -- same reasoning, no live route to check.
_NON_RESOURCE_GROUPS = {"schema", "skill"}

# These resources are fully stubbed
# (every route 501s) and their sub-router is deliberately hidden from
# `/docs`/`/openapi.json` via `_STUB_SUBROUTERS` -- none of these four
# appear in the deployed API's OpenAPI paths
# at all. Their CLI groups legitimately have no matching live route; this
# is documented, expected behavior, not drift.
_HIDDEN_STUB_RESOURCES = {"code-containers", "metrics", "users", "notifications"}

# `triage` doesn't talk to this deployed API at all -- it's a client for a
# wholly separate server (the monitoring MCP server, `NEXLA_MONITORING_URL`),
# not a `/nexla/*` REST resource, so it has no live path here to match by
# design, not by drift.
_NON_NEXLA_API_RESOURCES = {"triage"}


def _registered_resource_names() -> list[str]:
    names = []
    for group in app.registered_groups:
        name = group.typer_instance.info.name
        if name and name not in _NON_RESOURCE_GROUPS:
            names.append(name)
    return names


def _has_matching_live_path(name: str, paths: dict) -> bool:
    """True if ``name`` appears as a literal path segment in any live path.

    Most resources are mounted directly under ``/nexla/<name>``, but
    ``mcp-servers`` is nested (``/nexla/toolsets/{toolset_id}/mcp-servers``)
    -- checking path *segments* rather than a fixed ``/nexla/<name>``
    prefix handles both shapes without a resource-specific special case.
    """
    for p in paths:
        segments = p.strip("/").split("/")
        if name in segments:
            return True
    return False


def test_every_registered_resource_group_has_a_live_route() -> None:
    spec = openapi_client.fetch_openapi()
    paths = openapi_client.nexla_paths(spec)
    resource_names = _registered_resource_names()

    # Brittle by design: this is a drift alarm. If it fails because a resource
    # group was added or removed, update the expected count / ROUTES surface —
    # do NOT loosen the assertion.
    assert len(resource_names) == 18, (
        f"expected 18 registered resource groups (17 per the deployed API's "
        f"resource surface, plus `triage`), found {len(resource_names)}: {resource_names}"
    )

    checkable = [
        n for n in resource_names if n not in _HIDDEN_STUB_RESOURCES | _NON_NEXLA_API_RESOURCES
    ]
    missing = [n for n in checkable if not _has_matching_live_path(n, paths)]
    assert not missing, f"resource groups with no matching live /nexla/* route: {missing}"


def test_sources_create_route_matches_hardcoded_table() -> None:
    """Narrower, verb-level sanity check for one well-known route.

    Not exhaustive verb-by-verb coverage across all 61 routes -- that
    would duplicate `ROUTES` itself as a second hand-maintained table.
    This is a real, live-fetched spot check that the shared
    `openapi_client.ROUTES` entry used by both `schema` and `--dry-run`
    still resolves against the deployed API.
    """
    spec = openapi_client.fetch_openapi()
    match = openapi_client.resolve(spec, "sources", "create")
    assert match is not None
    assert match["method"] == "POST"
