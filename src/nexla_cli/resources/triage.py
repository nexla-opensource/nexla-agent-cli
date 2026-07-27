"""`nexla-cli triage` — flow/log triage via the Nexla monitoring MCP server.

Talks to a separate server (`NEXLA_MONITORING_URL`, e.g.
``https://<your-nexla-monitoring-host>/monitoring/``) over MCP `tools/call`, not this
repo's own `/nexla/*` REST API -- see ``mcp_client.py``. Every subcommand
here maps 1:1 to one tool the server exposes (confirmed live via
`tools/list`); `--dry-run` validates your arguments against that tool's
own live `inputSchema` instead of firing the call, same contract as every
other command's `--dry-run` (0/valid, 2/invalid).

These are all read-only query tools -- there is no create/update body to
assemble, so unlike `sources`/`sinks`/etc. there's no `--json`/`--params`
raw-body passthrough here.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import typer

from .. import mcp_client, output
from ..errors import EXIT, CliError

app = typer.Typer(
    name="triage", help="Query flow/log triage data via the Nexla monitoring MCP server.", no_args_is_help=True
)

_DRY_RUN_OPT = typer.Option(
    False, "--dry-run", help="Validate arguments locally against the tool's live schema; call nothing"
)
_SINCE_OPT = typer.Option(
    None, "--since", help="Relative window resolved to from_date (UTC): 24h | 7d | today | YYYY-MM-DD"
)
_FLOW_ID_ARG = typer.Argument(..., help="Flow ID")
_RESOURCE_ID_OPT = typer.Option(..., help="ID of the source/nexset/sink named by --resource-type")


def _args(**kwargs: object) -> dict[str, object]:
    return {k: v for k, v in kwargs.items() if v is not None}


def _resolve_since(value: str) -> str:
    """Resolve a relative ``--since`` token to a UTC ``YYYY-MM-DD`` from_date.

    Accepts ``today``, an ``Nh``/``Nd`` offset (e.g. ``24h``, ``7d``), or an
    absolute ``YYYY-MM-DD`` (passed through after a format check). Anything
    else is a validation error (exit 2). Uses real wall-clock UTC — this is
    CLI runtime, not a pinned test clock.
    """
    now = datetime.now(UTC)
    v = value.strip().lower()
    if v == "today":
        return now.date().isoformat()
    if len(v) > 1 and v[-1] in ("h", "d") and v[:-1].isdigit():
        delta = timedelta(hours=int(v[:-1])) if v[-1] == "h" else timedelta(days=int(v[:-1]))
        return (now - delta).date().isoformat()
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError as e:
        raise CliError(
            EXIT.VALIDATION, f"invalid --since {value!r}; use 24h, 7d, today, or YYYY-MM-DD"
        ) from e
    return value


def _from_date(from_date: str | None, since: str | None) -> str | None:
    """Fold ``--from-date`` and ``--since`` into one effective from_date.

    ``--since`` is an alternative spelling, not an override: passing both is
    a validation error rather than silently letting one win.
    """
    if since is None:
        return from_date
    if from_date is not None:
        raise CliError(EXIT.VALIDATION, "pass either --from-date or --since, not both")
    return _resolve_since(since)


def _run(ctx: typer.Context, tool: str, arguments: dict[str, object], dry_run: bool) -> None:
    if dry_run:
        mcp_client.run_dry_run(tool=tool, arguments=arguments)
    output.emit(
        mcp_client.call_tool(tool, arguments),
        mode=output.ctx_mode(ctx),
        fields=output.ctx_fields(ctx),
    )


@app.command("errors")
def errors(
    ctx: typer.Context,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    since: str | None = _SINCE_OPT,
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    limit: int = typer.Option(50, help="Max flows returned"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """List flows in your org that had errors in a time window (default: today)."""
    from_date = _from_date(from_date, since)
    _run(ctx, "list_flows_with_errors", _args(from_date=from_date, to_date=to_date, limit=limit), dry_run)


@app.command("status")
def status(
    ctx: typer.Context,
    flow_id: int = _FLOW_ID_ARG,
    run_id: int | None = typer.Option(None, help="Pin a specific run instead of the latest"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Single-flow status with full source/nexset/sink chain breakdown."""
    _run(ctx, "get_flow_status", _args(flow_id=flow_id, run_id=run_id), dry_run)


@app.command("run")
def run(
    ctx: typer.Context,
    flow_id: int = _FLOW_ID_ARG,
    run_id: int = typer.Argument(..., help="Run ID"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """One flow run's execution timing (started_at/completed_at/duration_ms)."""
    _run(ctx, "get_flow_run", _args(flow_id=flow_id, run_id=run_id), dry_run)


@app.command("metrics")
def metrics(
    ctx: typer.Context,
    flow_id: int = _FLOW_ID_ARG,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    since: str | None = _SINCE_OPT,
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    granularity: str = typer.Option("daily", help="'daily' or 'monthly'"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Flow metrics (records/errors/size) bucketed by day or month."""
    from_date = _from_date(from_date, since)
    _run(
        ctx,
        "get_flow_metrics",
        _args(flow_id=flow_id, from_date=from_date, to_date=to_date, granularity=granularity),
        dry_run,
    )


@app.command("resource-status")
def resource_status(
    ctx: typer.Context,
    resource_type: str = typer.Option(..., help="'sources' | 'nexsets' | 'sinks'"),
    resource_id: int = _RESOURCE_ID_OPT,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Per-resource status with the owning flow's chain inline."""
    _run(
        ctx,
        "get_resource_status",
        _args(resource_type=resource_type, resource_id=resource_id, from_date=from_date, to_date=to_date),
        dry_run,
    )


@app.command("org-metrics")
def org_metrics(
    ctx: typer.Context,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    since: str | None = _SINCE_OPT,
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    granularity: str = typer.Option("daily", help="'daily' or 'monthly'"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Org-wide aggregate metrics. Daily rollup -- today's data lags by a day."""
    from_date = _from_date(from_date, since)
    _run(ctx, "get_org_metrics", _args(from_date=from_date, to_date=to_date, granularity=granularity), dry_run)


@app.command("user-metrics")
def user_metrics(
    ctx: typer.Context,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    since: str | None = _SINCE_OPT,
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    granularity: str = typer.Option("daily", help="'daily' or 'monthly'"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Aggregate metrics scoped to the calling user's own flows. Daily rollup."""
    from_date = _from_date(from_date, since)
    _run(ctx, "get_user_metrics", _args(from_date=from_date, to_date=to_date, granularity=granularity), dry_run)


@app.command("notifications")
def notifications(
    ctx: typer.Context,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    since: str | None = _SINCE_OPT,
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    level: str | None = typer.Option(None, help="DEBUG|INFO|WARN|ERROR|RECOVERED|RESOLVED"),
    limit: int = typer.Option(20, help="How many recent items to include"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Notification count + level/read breakdown + recent items (default: today)."""
    from_date = _from_date(from_date, since)
    _run(
        ctx,
        "notifications_summary",
        _args(from_date=from_date, to_date=to_date, level=level, limit=limit),
        dry_run,
    )


@app.command("search")
def search(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Name substring to search for"),
    limit: int = typer.Option(10, help="Max hits"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Find flows by name (matches flow/source/nexset/sink names)."""
    _run(ctx, "search_flows", _args(name=name, limit=limit), dry_run)


@app.command("logs")
def logs(
    ctx: typer.Context,
    flow_id: int = _FLOW_ID_ARG,
    run_id: int | None = typer.Option(None, help="Pin to one run; omit is noisy across all runs"),
    severity: str | None = typer.Option(None, help="ERROR|WARNING|INFO"),
    search: str | None = typer.Option(None, help="Free-text substring match on log message bodies"),
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    since: str | None = _SINCE_OPT,
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    size: int = typer.Option(50, help="Max log entries"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Raw data-plane log entries for a flow run (ES-indexed, `logs_v2`)."""
    from_date = _from_date(from_date, since)
    _run(
        ctx,
        "get_flow_logs",
        _args(
            flow_id=flow_id,
            run_id=run_id,
            severity=severity,
            search=search,
            from_date=from_date,
            to_date=to_date,
            size=size,
        ),
        dry_run,
    )


@app.command("quarantine")
def quarantine(
    ctx: typer.Context,
    resource_type: str = typer.Option(..., help="'sources' | 'nexsets' | 'sinks'"),
    resource_id: int = _RESOURCE_ID_OPT,
    sample_size: int = typer.Option(10, help="How many rejected records to return"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Sample of actual rejected records (72h retention -- older is metadata-only)."""
    _run(
        ctx,
        "get_quarantine_samples",
        _args(resource_type=resource_type, resource_id=resource_id, sample_size=sample_size),
        dry_run,
    )


# --- diagnose: client-side synthesis over the read-only tools ----------------

# Health/status tokens that mean "broken", matched case-insensitively. Includes
# RED/YELLOW to match the monitoring server's ribbon + errors-oracle vocabulary.
_BAD_STATUS = frozenset({"error", "errored", "failed", "fail", "red", "yellow", "unhealthy", "ko"})


def _is_bad(status: str) -> bool:
    return status.strip().lower() in _BAD_STATUS


def _status_of(obj: Any) -> str:
    """Best-effort read of a status/health string off a resource object."""
    if not isinstance(obj, dict):
        return ""
    for key in ("status", "last_run_status", "flow_status", "health", "state"):
        val = obj.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _flow_health(status: dict[str, Any]) -> str:
    """Read the flow's health string, incl. the nested ``status.healthStatus``.

    The live server nests health under a ``status`` object
    (``{originNodeId, healthStatus, affectedResources}``) and leaves the top
    level without a flat health string -- and leaves ``healthStatus`` null even
    for RED flows -- so this is only one of several health signals diagnose
    consults, never the sole gate.
    """
    nested = status.get("status")
    if isinstance(nested, dict):
        for key in ("healthStatus", "health_status", "health", "status", "state"):
            val = nested.get(key)
            if isinstance(val, str) and val:
                return val
    for key in ("healthStatus", "health_status", "last_run_status", "flow_status", "health", "state"):
        val = status.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _latest_run_id(status: dict[str, Any]) -> Any:
    """Best-effort latest run id used to scope the ERROR-log query."""
    latest = status.get("latest_run")
    if isinstance(latest, dict) and latest.get("run_id") is not None:
        return latest["run_id"]
    for key in ("run_id", "last_run_id"):
        if status.get(key) is not None:
            return status[key]
    recent = status.get("recent_runs")
    if isinstance(recent, list):
        for r in recent:
            if isinstance(r, dict) and r.get("run_id") is not None:
                return r["run_id"]
    return None


def _log_entries(logs: Any) -> list[dict[str, Any]]:
    """Flatten a get_flow_logs payload down to a list of entry dicts."""
    if isinstance(logs, dict):
        inner = logs.get("logs")
        if isinstance(inner, dict) and isinstance(inner.get("data"), list):
            return [e for e in inner["data"] if isinstance(e, dict)]
        for key in ("data", "entries", "items"):
            val = logs.get(key)
            if isinstance(val, list):
                return [e for e in val if isinstance(e, dict)]
    if isinstance(logs, list):
        return [e for e in logs if isinstance(e, dict)]
    return []


def _log_message(entry: dict[str, Any]) -> str:
    # Live log entries carry the message under ``log``; keep the other keys as
    # fallbacks for schema drift.
    for key in ("log", "message", "msg", "text", "error", "reason"):
        val = entry.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _summarize(msg: str, limit: int = 180) -> str:
    """Collapse whitespace and cap length for a one-line root-cause detail.

    A real ERROR log can be a multi-KB HTML error page (e.g. a Cloudflare 525);
    the raw text stays in ``evidence.logs``, but a root-cause ``detail`` -- and
    the human ``FAILED:`` one-liner built from it -- must stay readable.
    """
    flat = " ".join(msg.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _resources_from_logs(log_entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group ERROR log entries by (resource_type, resource_id).

    On the live server this is the reliable source of *which* resource broke --
    get_flow_status.affectedResources is empty even for RED flows, but each
    ERROR log line carries resource_type + resource_id + the message.
    """
    grouped: dict[tuple[Any, Any], dict[str, Any]] = {}
    for e in log_entries:
        key = (e.get("resource_type"), e.get("resource_id"))
        g = grouped.get(key)
        if g is None:
            grouped[key] = {
                "resource_type": e.get("resource_type"),
                "resource_id": e.get("resource_id"),
                "name": e.get("resource_name") or e.get("name"),
                "log_count": 1,
                "message": _log_message(e),
            }
        else:
            g["log_count"] += 1
            if not g["message"]:
                g["message"] = _log_message(e)
    return list(grouped.values())


def _affected_resources(status: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize ``status.affectedResources`` (nested or flat), when populated."""
    nested = status.get("status")
    raw = nested.get("affectedResources") if isinstance(nested, dict) else None
    if not isinstance(raw, list):
        top = status.get("affectedResources")
        raw = top if isinstance(top, list) else []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rid = item.get("resource_id")
        if rid is None:
            rid = item.get("id")
        out.append(
            {
                "resource_type": item.get("resource_type") or item.get("type"),
                "resource_id": rid,
                "name": item.get("name") or item.get("resource_name"),
                "message": "",
                "status": _status_of(item),
            }
        )
    return out


def _quarantine_samples(q: Any) -> list[dict[str, Any]]:
    if isinstance(q, dict):
        for key in ("samples", "records", "data", "items"):
            val = q.get(key)
            if isinstance(val, list):
                return [s for s in val if isinstance(s, dict)]
    if isinstance(q, list):
        return [s for s in q if isinstance(s, dict)]
    return []


def _quarantine_reason(sample: dict[str, Any]) -> str:
    for key in ("error", "reason", "message", "quarantine_reason"):
        val = sample.get(key)
        if isinstance(val, str) and val:
            return val
    return ""


def _best_effort(tool: str, arguments: dict[str, Any]) -> Any:
    """Call an evidence/health tool, treating any failure as 'no data'.

    diagnose has already (or is about to) confirm the flow is broken; a
    logs/quarantine/oracle query that itself errors (ES timeout, 72h-expired
    quarantine, transient 5xx) must not sink the whole diagnosis -- return
    empty and let the synthesis rank on whatever other signals came back.
    """
    try:
        return mcp_client.call_tool(tool, arguments)
    except CliError:
        return {}


def _in_error_oracle(flow_id: int) -> bool:
    """Tiebreaker: does list_flows_with_errors (default window) list this flow?

    Best-effort and default-window only -- the wider ``--since`` windows can
    ES-timeout, but the default window is reliable. A RED/YELLOW last run or a
    nonzero error count means the flow really failed even when get_flow_status
    and the logs are both silent.
    """
    data = _best_effort("list_flows_with_errors", {})
    flows = data.get("flows") if isinstance(data, dict) else None
    if not isinstance(flows, list):
        return False
    for f in flows:
        if not isinstance(f, dict) or f.get("flow_id") != flow_id:
            continue
        if _is_bad(str(f.get("last_run_status") or "")):
            return True
        errors = f.get("errors")
        if isinstance(errors, (int, float)) and not isinstance(errors, bool) and errors > 0:
            return True
    return False


@app.command("diagnose")
def diagnose(
    ctx: typer.Context,
    flow_id: int = _FLOW_ID_ARG,
    run_id: int | None = typer.Option(None, help="Pin a specific run instead of the latest"),
    log_size: int = typer.Option(10, help="Max ERROR log entries to pull as evidence"),
    sample_size: int = typer.Option(5, help="Max quarantined records to sample per errored resource"),
) -> None:
    """Diagnose why a flow failed by chaining status -> logs -> quarantine into a ranked root cause.

    Health is judged from three signals, not get_flow_status alone (which
    reports null even for RED flows): the nested ``healthStatus``, the presence
    of ERROR logs, and the errors oracle. Errored resources are read off the
    ERROR log lines. Human output is a short ``FAILED: <cause>; <evidence>;
    next: <cmd>`` line; ``-o json`` emits
    ``{flow_id, status, root_causes, evidence, next_commands}``.
    """
    status = mcp_client.call_tool("get_flow_status", _args(flow_id=flow_id, run_id=run_id))
    if not isinstance(status, dict):
        status = {"result": status}
    flow_name = status.get("flow_name") or status.get("name")
    # A non-existent flow_id doesn't error server-side -- get_flow_status just
    # echoes back the id with everything else null/empty. Without this a bogus
    # id would report a misleading "OK / healthy". A real flow always carries a
    # name or an owner, so their joint absence means "not found".
    if not flow_name and not status.get("owner_email"):
        raise CliError(EXIT.NOT_FOUND, f"flow {flow_id} not found")
    health = _flow_health(status)
    mode = output.ctx_mode(ctx)

    # Always pull ERROR logs (best-effort). healthStatus is null in practice
    # even for RED flows, so the logs are both a health signal and the
    # evidence -- never gate the fetch on the status object.
    eff_run_id = run_id or _latest_run_id(status)
    logs = _best_effort(
        "get_flow_logs", _args(flow_id=flow_id, run_id=eff_run_id, severity="ERROR", size=log_size)
    )
    log_entries = _log_entries(logs)

    # FAILED if health is bad, OR there are ERROR logs, OR the errors oracle
    # lists this flow (consulted only as a tiebreaker -- one extra round trip).
    failed = _is_bad(health) or bool(log_entries)
    if not failed:
        failed = _in_error_oracle(flow_id)

    if not failed:
        payload: dict[str, Any] = {
            "flow_id": flow_id,
            "status": health or "OK",
            "root_causes": [],
            "evidence": {"logs": [], "quarantine": {}},
            "next_commands": [],
        }
        if mode in ("json", "ndjson"):
            output.emit(payload, mode=mode, fields=output.ctx_fields(ctx))
        else:
            label = f"flow {flow_id}" + (f" ({flow_name})" if flow_name else "")
            typer.echo(f"HEALTHY: {label} status {health or 'OK'}; no ERROR logs; nothing to diagnose")
        return

    # Prefer resources named in the ERROR logs; fall back to affectedResources
    # when the logs carry no attribution.
    resources = _resources_from_logs(log_entries)
    attributed = [r for r in resources if r["resource_type"] is not None and r["resource_id"] is not None]
    if not attributed:
        affected = [r for r in _affected_resources(status) if r["resource_id"] is not None]
        if affected:
            attributed = affected

    quarantine: dict[str, Any] = {}
    root_causes: list[dict[str, Any]] = []
    next_commands: list[str] = []

    for r in attributed:
        rt, rid = r["resource_type"], r["resource_id"]
        q = _best_effort(
            "get_quarantine_samples", _args(resource_type=rt, resource_id=rid, sample_size=sample_size)
        )
        quarantine[f"{rt}:{rid}"] = q
        samples = _quarantine_samples(q)
        if samples:
            root_causes.append(
                {
                    "resource": r.get("name"),
                    "resource_type": rt,
                    "resource_id": rid,
                    "cause": "records rejected (quarantined)",
                    "detail": _summarize(_quarantine_reason(samples[0]))
                    or f"{len(samples)} rejected record(s) sampled",
                    "signal": "quarantine",
                }
            )
            next_commands.append(f"nexla-cli triage quarantine --resource-type {rt} --resource-id {rid}")
        elif r.get("message"):
            root_causes.append(
                {
                    "resource": r.get("name"),
                    "resource_type": rt,
                    "resource_id": rid,
                    "cause": f"errors on {rt} {rid}" if rt else "errors on failing resource",
                    "detail": _summarize(r["message"]),
                    "signal": "logs",
                }
            )
        else:
            root_causes.append(
                {
                    "resource": r.get("name"),
                    "resource_type": rt,
                    "resource_id": rid,
                    "cause": f"{rt} {rid} in error state" if rt else "resource in error state",
                    "detail": r.get("status") or "flagged by monitoring; no log/quarantine detail",
                    "signal": "status",
                }
            )

    # ERROR logs with no resource attribution -> a flow-level log cause.
    if not attributed and log_entries:
        root_causes.append(
            {
                "resource": flow_name,
                "resource_type": None,
                "resource_id": None,
                "cause": "ERROR log entries on the failing run",
                "detail": _summarize(_log_message(log_entries[0]))
                or f"{len(log_entries)} ERROR log line(s)",
                "signal": "logs",
            }
        )

    # Last resort: flagged failed (health/oracle) but nothing concrete surfaced.
    if not root_causes:
        root_causes.append(
            {
                "resource": flow_name,
                "resource_type": None,
                "resource_id": None,
                "cause": f"flow reported {health}" if health else "flow flagged with errors",
                "detail": "no ERROR logs or quarantined records for this run (may have rolled off)",
                "signal": "status",
            }
        )

    next_commands.append(f"nexla-cli triage logs {flow_id} --severity ERROR")

    # Rank: quarantine-backed > log-backed > status-only.
    priority = {"quarantine": 0, "logs": 1, "status": 2}
    root_causes.sort(key=lambda rc: priority.get(rc["signal"], 3))
    for i, rc in enumerate(root_causes, start=1):
        rc["rank"] = i
    next_commands = list(dict.fromkeys(next_commands))

    payload = {
        "flow_id": flow_id,
        "status": health or "ERROR",
        "root_causes": root_causes,
        "evidence": {"logs": log_entries, "quarantine": quarantine},
        "next_commands": next_commands,
    }

    if mode in ("json", "ndjson"):
        output.emit(payload, mode=mode, fields=output.ctx_fields(ctx))
        return

    primary = root_causes[0]
    res = f" ({primary['resource']})" if primary.get("resource") else ""
    nxt = next_commands[0] if next_commands else f"nexla-cli triage status {flow_id}"
    typer.echo(f"FAILED: {primary['cause']}{res}; {primary['detail']}; next: {nxt}")
    for rc in root_causes[1:]:
        res = f" ({rc['resource']})" if rc.get("resource") else ""
        typer.echo(f"  also: {rc['cause']}{res}; {rc['detail']}")
