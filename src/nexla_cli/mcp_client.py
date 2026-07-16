"""Thin JSON-RPC client for the Nexla monitoring MCP server (`nexla-cli triage`).

Separate from ``client.py`` because it's a different protocol (MCP
``tools/call`` over a stateless streamable-HTTP transport, no session
handshake needed against this server) and a different base URL
(``NEXLA_MONITORING_URL``), but reuses the same bearer token
(:func:`nexla_cli.client.auth_token`) and the same
:class:`~nexla_cli.errors.CliError`/``EXIT`` mapping so `triage` commands
fail the same way every other `nexla` command does.
"""

from __future__ import annotations

import json as jsonlib
import os
from typing import Any

import httpx
import typer

from . import client, dryrun
from .errors import EXIT, CliError

_HEADERS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def _base() -> str:
    url = os.environ.get("NEXLA_MONITORING_URL")
    if not url:
        raise CliError(EXIT.CONFIG, "NEXLA_MONITORING_URL is not set")
    return url


def _parse_rpc(r: httpx.Response) -> dict[str, Any]:
    """Decode a JSON-RPC envelope from either a plain JSON or SSE body.

    The server always answers with ``content-type: text/event-stream``
    (confirmed live) even for a single, non-streaming reply -- one
    ``data: {...}`` line. Handle a bare ``application/json`` body too
    rather than assuming the SSE framing is permanent.
    """
    ctype = r.headers.get("content-type", "")
    if "text/event-stream" in ctype:
        lines = [ln[len("data:") :].strip() for ln in r.text.splitlines() if ln.startswith("data:")]
        if not lines:
            raise CliError(EXIT.UPSTREAM, "empty response from monitoring MCP server")
        result: dict[str, Any] = jsonlib.loads(lines[-1])
        return result
    try:
        body: dict[str, Any] = r.json()
    except ValueError as e:
        raise CliError(EXIT.UPSTREAM, f"non-JSON response from monitoring MCP server: {e}") from e
    return body


def _raise_on_rpc_error(resp: dict[str, Any]) -> None:
    error = resp.get("error")
    if error:
        raise CliError(EXIT.ERROR, error.get("message", "MCP error"))


def _post(payload: dict[str, Any]) -> dict[str, Any]:
    headers = {**_HEADERS, "Authorization": f"Bearer {client.auth_token()}"}
    with httpx.Client(base_url=_base(), timeout=client.timeout(), headers=headers) as c:
        try:
            r = c.post("", json=payload)
        except httpx.HTTPError as e:
            raise CliError(EXIT.UPSTREAM, f"request failed: {e}") from e
    if not r.is_success:
        raise CliError(
            EXIT.from_status(r.status_code), f"HTTP {r.status_code} from monitoring MCP server"
        )
    resp = _parse_rpc(r)
    _raise_on_rpc_error(resp)
    return resp


def list_tools() -> list[dict[str, Any]]:
    """Fetch the live tool catalog (name + ``inputSchema``) via `tools/list`."""
    resp = _post({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
    tools: list[dict[str, Any]] = resp.get("result", {}).get("tools", [])
    return tools


def tool_schema(name: str) -> dict[str, Any] | None:
    """Look up one tool's live ``inputSchema`` by name, or ``None`` if unknown."""
    for tool in list_tools():
        if tool.get("name") == name:
            return tool.get("inputSchema")
    return None


def call_tool(name: str, arguments: dict[str, Any]) -> Any:
    """Call one MCP tool and return its decoded JSON payload.

    Unwraps the MCP envelope (``result.content[0].text``, itself a JSON
    string) down to the plain object every `triage` command renders via
    ``output.emit`` -- callers never see JSON-RPC/MCP framing.
    """
    resp = _post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }
    )
    result = resp.get("result", {})
    content = result.get("content") or []
    text = content[0].get("text") if content and isinstance(content[0], dict) else None
    if text is None:
        raise CliError(EXIT.UPSTREAM, "empty tool result from monitoring MCP server")
    try:
        payload = jsonlib.loads(text)
    except jsonlib.JSONDecodeError:
        payload = {"text": text}
    if result.get("isError"):
        message = payload.get("error") if isinstance(payload, dict) else str(payload)
        raise CliError(EXIT.ERROR, message or "tool reported an error")
    return payload


def run_dry_run(*, tool: str, arguments: dict[str, Any]) -> None:
    """Validate ``arguments`` against the tool's live ``inputSchema``, then exit.

    Mirrors ``dryrun.run_dry_run``'s contract (0/valid, 2/invalid,
    same ``{"valid": ..., "body"|"errors": ...}`` shape) but sources its
    schema from this server's own `tools/list` instead of
    `/openapi.json` -- every `triage` tool is a read-only query, so there
    is no mutating call to skip, only a local params check before the
    round trip. Always exits the process; the caller never falls through
    to the real ``call_tool`` after this returns.
    """
    schema = tool_schema(tool)
    if schema is None:
        raise CliError(EXIT.ERROR, f"unknown monitoring tool '{tool}' (server schema drift?)")
    errors = dryrun.validate_body(schema, arguments)
    if errors:
        typer.echo(jsonlib.dumps({"valid": False, "errors": errors}, indent=2), err=True)
        raise typer.Exit(EXIT.VALIDATION)
    typer.echo(jsonlib.dumps({"valid": True, "body": arguments}, indent=2, default=str))
    raise typer.Exit(EXIT.OK)
