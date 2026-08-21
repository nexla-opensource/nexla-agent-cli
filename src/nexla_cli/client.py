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
import time
from collections.abc import Iterator
from typing import Any

import httpx
import typer

from . import config
from .errors import EXIT, CliError


def _base() -> str:
    # Precedence: NEXLA_API_URL env > stored config (from `login`).
    url = os.environ.get("NEXLA_API_URL") or config.load().get("api_url")
    if not url:
        raise CliError(
            EXIT.CONFIG,
            "no API URL: set NEXLA_API_URL or run `nexla-cli login --api-url ...`",
        )
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


def _stored_token() -> str | None:
    # Precedence: NEXLA_TOKEN env > cached bearer from `login`.
    return os.environ.get("NEXLA_TOKEN") or config.load().get("access_token")


def _token() -> str:
    tok = _stored_token()
    if not tok:
        raise CliError(
            EXIT.CONFIG, "not authenticated: set NEXLA_TOKEN or run `nexla-cli login`"
        )
    return tok


def auth_token() -> str:
    """Public accessor for the bearer token, for other transports (e.g. mcp_client)."""
    return _token()


def _refresh_window_seconds() -> int:
    """How close to expiry (seconds) we proactively refresh. Small on purpose."""
    return 60


def _maybe_refresh(token: str) -> str:
    """Rotate a config-sourced bearer that's about to expire, before it 401s.

    ``/auth/token/refresh`` is auth-gated -- it needs a *still-valid* bearer --
    so the only time it can be used is proactively, just before expiry. Doing
    this means the common path never 401s and never needs the service key at
    all. Best-effort: on any failure fall through with the old token and let
    the 401 path (:func:`_reauth`) decide.

    Never fires for an env-supplied ``NEXLA_TOKEN``: that token isn't ours to
    rotate, and rewriting the stored config from an env-var session would be
    surprising.
    """
    if os.environ.get("NEXLA_TOKEN"):
        return token
    exp = config.load().get("expires_at")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return token
    if exp - time.time() > _refresh_window_seconds():
        return token
    try:
        with httpx.Client(
            base_url=_base(), timeout=timeout(), headers={"Authorization": f"Bearer {token}"}
        ) as c:
            r = c.post("/auth/token/refresh", json={})
        if not r.is_success:
            return token
        data = r.json()
    except (httpx.HTTPError, ValueError):
        return token
    fresh = data.get("access_token")
    if not isinstance(fresh, str) or not fresh:
        return token
    config.save(access_token=fresh, expires_at=data.get("expires_at"))
    return fresh


def _reauth() -> str | None:
    """Mint a fresh bearer from the stored service key, or None if we can't.

    Last resort after a 401: the refresh endpoint needs a still-valid bearer,
    so an already-expired token can't rotate itself -- only the service key can
    re-mint, and only if the user opted into storing it
    (``login --store-service-key``). Not stored (the default), or env-supplied
    auth -> None, and the 401 surfaces as EXIT.AUTH.
    """
    if os.environ.get("NEXLA_TOKEN"):
        # An env-supplied token isn't ours to replace, and re-minting here would
        # silently rewrite the stored config during an env-var session.
        return None
    sk = config.load().get("service_key")
    if not sk:
        return None
    try:
        with httpx.Client(base_url=_base(), timeout=timeout()) as c:
            r = c.post("/login", json={"service_key": sk})
    except httpx.HTTPError:
        return None
    if not r.is_success:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    tok = data.get("access_token")
    if not isinstance(tok, str) or not tok:
        return None
    config.save(access_token=tok, expires_at=data.get("expires_at"))
    return tok


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
    def _send(token: str | None) -> httpx.Response:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(base_url=_base(), timeout=timeout(), headers=headers) as c:
            try:
                return c.request(method, path, params=params, json=json)
            except httpx.HTTPError as e:
                raise CliError(EXIT.UPSTREAM, f"request failed: {e}") from e

    token = _maybe_refresh(_token()) if require_auth else None
    r = _send(token)
    # The cached bearer expired -> transparently re-mint from the stored
    # service key and retry once (see `_reauth`). One retry only; if it still
    # 401s the error falls through to the normal AUTH mapping below.
    if r.status_code == 401 and require_auth:
        new_token = _reauth()
        if new_token is not None and new_token != token:
            r = _send(new_token)

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
