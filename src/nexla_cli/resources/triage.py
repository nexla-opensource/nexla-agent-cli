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

import typer

from .. import mcp_client, output

app = typer.Typer(
    name="triage", help="Query flow/log triage data via the Nexla monitoring MCP server.", no_args_is_help=True
)

_DRY_RUN_OPT = typer.Option(
    False, "--dry-run", help="Validate arguments locally against the tool's live schema; call nothing"
)
_FLOW_ID_ARG = typer.Argument(..., help="Flow ID")
_RESOURCE_ID_OPT = typer.Option(..., help="ID of the source/nexset/sink named by --resource-type")


def _args(**kwargs: object) -> dict[str, object]:
    return {k: v for k, v in kwargs.items() if v is not None}


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
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    limit: int = typer.Option(50, help="Max flows returned"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """List flows in your org that had errors in a time window (default: today)."""
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
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    granularity: str = typer.Option("daily", help="'daily' or 'monthly'"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Flow metrics (records/errors/size) bucketed by day or month."""
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
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    granularity: str = typer.Option("daily", help="'daily' or 'monthly'"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Org-wide aggregate metrics. Daily rollup -- today's data lags by a day."""
    _run(ctx, "get_org_metrics", _args(from_date=from_date, to_date=to_date, granularity=granularity), dry_run)


@app.command("user-metrics")
def user_metrics(
    ctx: typer.Context,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    granularity: str = typer.Option("daily", help="'daily' or 'monthly'"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Aggregate metrics scoped to the calling user's own flows. Daily rollup."""
    _run(ctx, "get_user_metrics", _args(from_date=from_date, to_date=to_date, granularity=granularity), dry_run)


@app.command("notifications")
def notifications(
    ctx: typer.Context,
    from_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, inclusive"),
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    level: str | None = typer.Option(None, help="DEBUG|INFO|WARN|ERROR|RECOVERED|RESOLVED"),
    limit: int = typer.Option(20, help="How many recent items to include"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Notification count + level/read breakdown + recent items (default: today)."""
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
    to_date: str | None = typer.Option(None, help="YYYY-MM-DD, UTC, exclusive"),
    size: int = typer.Option(50, help="Max log entries"),
    dry_run: bool = _DRY_RUN_OPT,
) -> None:
    """Raw data-plane log entries for a flow run (ES-indexed, `logs_v2`)."""
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
