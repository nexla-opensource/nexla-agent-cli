"""Thin, synchronous httpx wrapper shared by every CLI command.

The CLI is short-lived (one process per invocation) so there's no need for
an async client or connection pooling across calls. Mirrors the API's own
``{detail: {error, detail, nexla_request_id}}`` failure envelope and maps
failures to :class:`nexla_cli.errors.CliError` / exit codes instead of
raising ``httpx`` or FastAPI exceptions.
"""

from __future__ import annotations

import json as jsonlib
import os
from collections.abc import Iterator
from typing import Any

import httpx
import typer

from .errors import EXIT, CliError


def _base() -> str:
    url = os.environ.get("NEXLA_API_URL")
    if not url:
        raise CliError(EXIT.CONFIG, "NEXLA_API_URL is not set")
    return url.rstrip("/")


def timeout() -> float:
    """HTTP timeout in seconds, overridable via ``NEXLA_TIMEOUT`` (default 30)."""
    raw = os.environ.get("NEXLA_TIMEOUT")
    if not raw:
        return 30.0
    try:
        value = float(raw)
    except ValueError:
        raise CliError(EXIT.CONFIG, f"NEXLA_TIMEOUT must be a number, got {raw!r}") from None
    if value <= 0:
        raise CliError(EXIT.CONFIG, f"NEXLA_TIMEOUT must be positive, got {raw!r}")
    return value


def _token() -> str:
    tok = os.environ.get("NEXLA_TOKEN")
    if not tok:
        raise CliError(EXIT.CONFIG, "NEXLA_TOKEN is not set")
    return tok


def auth_token() -> str:
    """Public accessor for the bearer token, for other transports (e.g. mcp_client)."""
    return _token()


def _envelope(r: httpx.Response) -> dict[str, Any]:
    """Extract the ``{error, detail, nexla_request_id}`` failure envelope.

    ``/nexla/*`` routes raise ``HTTPException(detail=...)``, which FastAPI
    serializes as ``{"detail": <whatever was passed>}``. ``detail`` may
    itself be a dict (our common shape), a plain string, or (for 422s) a
    list of Pydantic error objects.
    """
    try:
        body = r.json()
    except ValueError:
        return {"error": r.text[:512]}
    if not isinstance(body, dict):
        return {"error": str(body)[:512]}
    detail = body.get("detail", body)
    if isinstance(detail, dict):
        return detail
    return {"error": str(detail)[:512] if detail is not None else r.text[:512]}


def _message_from_envelope(envelope: dict[str, Any], *, fallback: str) -> str:
    for key in ("detail", "error"):
        val = envelope.get(key)
        if isinstance(val, str) and val:
            return val
    return fallback


def request(
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json: Any = None,
    require_auth: bool = True,
) -> Any:
    """Fire one HTTP request against ``NEXLA_API_URL`` and return decoded JSON.

    Raises :class:`CliError` (never a raw ``httpx``/network exception) on
    any non-2xx response, with ``EXIT.from_status`` mapping the upstream
    status code to a stable CLI exit code.
    """
    headers: dict[str, str] = {}
    if require_auth:
        headers["Authorization"] = f"Bearer {_token()}"

    with httpx.Client(base_url=_base(), timeout=timeout(), headers=headers) as c:
        try:
            r = c.request(method, path, params=params, json=json)
        except httpx.HTTPError as e:
            raise CliError(EXIT.UPSTREAM, f"request failed: {e}") from e

    if r.is_success:
        if r.status_code == 204 or not r.content:
            return None
        try:
            return r.json()
        except ValueError:
            # A non-empty 2xx body that won't parse as JSON is a real upstream
            # problem, not a legitimately-empty 204. Surface it instead of
            # silently returning None (which is indistinguishable from an empty
            # 204 to the caller). Bound the echoed excerpt — the body is
            # untrusted and may be large.
            excerpt = r.text[:200]
            raise CliError(
                EXIT.UPSTREAM,
                f"non-JSON response from {path} (HTTP {r.status_code}): {excerpt}",
            ) from None

    envelope = _envelope(r)
    message = _message_from_envelope(envelope, fallback=f"HTTP {r.status_code}")
    raise CliError(EXIT.from_status(r.status_code), message, envelope=envelope)


def paginate(
    path: str,
    *,
    params: dict[str, Any] | None = None,
    per_page: int = 100,
) -> Iterator[Any]:
    """Stream every item across all pages without ever buffering the full set.

    Drives the loop off the ``Page[T]`` envelope's own ``next_page`` key
    (falsy means done) rather than a length heuristic on ``items`` — a
    ``len(batch) < per_page`` check is wrong (a last page can legitimately
    be exactly ``per_page`` long) and was flagged as a bug in review.
    Forwards the full ``params`` dict on every call, only overriding
    ``page``/``per_page``, so resource-specific filters (e.g. ``sources
    list``'s ``connector``/``flow_id``) stay applied under ``--page-all``.

    The server may cap a filtered/expensive query (e.g. credential-based
    access filtering only walks a bounded number of upstream pages) and flag
    the ``Page[T]`` envelope with ``truncated: true`` — possibly on *any*
    page, not just the last. Streaming those items as if complete would
    silently hide the cap, so the flag is latched across all pages and
    surfaced once the stream ends: a WARNING on stderr, plus a final
    ``{"_meta": "truncation", ...}`` NDJSON record on stdout so machine
    consumers of ``--page-all`` see the signal without scraping stderr. The
    item stream itself is left untouched — every fetched item is still
    yielded in order, and the meta record comes strictly last.
    """
    page: int = 1
    truncated = False
    while True:
        data = request(
            "GET", path, params={**(params or {}), "page": page, "per_page": per_page}
        )
        yield from data.get("items", [])
        truncated = truncated or bool(data.get("truncated"))
        next_page = data.get("next_page")
        if not next_page:
            if truncated:
                typer.echo(
                    f"warning: results from {path} were truncated server-side "
                    "and may be incomplete",
                    err=True,
                )
                typer.echo(
                    jsonlib.dumps(
                        {
                            "_meta": "truncation",
                            "truncated": True,
                            "path": path,
                            "message": "results were truncated server-side "
                            "and may be incomplete",
                        }
                    )
                )
            return
        page = next_page
