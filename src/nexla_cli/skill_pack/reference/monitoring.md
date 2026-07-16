# Monitoring — flow health, metrics, runs, logs, notifications & charts

> **Standalone `nexla` CLI note.** The `nexla-monitoring` MCP tools named below (`get_org_metrics`, `list_flows_with_errors`, `get_flow_status`, `get_flow_logs`, `get_quarantine_samples`, …) and the `visualize_metrics` chart MCP-App are the express-sandbox surface. On a standalone install the same monitoring server is reached through `nexla-cli triage` subcommands — `nexla-cli triage org-metrics|user-metrics|metrics|errors|status|run|resource-status|logs|quarantine|notifications|search` — which requires `NEXLA_MONITORING_URL` to be set (it is not inferred from `NEXLA_API_URL`). There is no standalone chart renderer; use the JSON output of `nexla-cli triage` directly. The tool→subcommand mapping is 1:1 (e.g. `list_flows_with_errors`→`nexla-cli triage errors`, `get_flow_status`→`nexla-cli triage status <flow_id>`). See AGENTS.md.

Answer monitoring questions with the read-only `nexla-monitoring` MCP tools
(already wired — no auth needed from you) plus **`visualize_metrics`** for chart
UIs. Reach for these for: org/flow health, throughput & errors, run outcomes,
log diagnostics, notifications, rejected-record samples, or any chart-like ask
("how's my org doing", "which flows are erroring", "why did this run fail",
"show me a chart of records ingested", "any unread alerts").

Each tool's own description + input schema is authoritative for arguments — this
file is the map of **which** tool to use and **how to chart** it. Dates are
`YYYY-MM-DD` (omit to default to a recent window).

## Pick the tool by intent

**State / trends** — each returns `{ totals:{records,size,errors}, buckets:[{bucket,records,size,errors}] }` over the window at the chosen `granularity`:
- `get_org_metrics` — org-wide totals + a RED/YELLOW/GREEN status ribbon. "How's my org doing?"
- `get_user_metrics` — same, scoped to the caller's own flows. "My account."
- `get_flow_metrics({flow_id})` — one flow's summary + day/month trend.

**Triage — "what's broken?"**:
- `list_flows_with_errors` — the entry point. Flows with errors in a window → `{ flows:[{flow_id, flow_name, owner_email, errors, records, last_run_id, last_run_status, last_run_at}] }`.
- `get_flow_status({flow_id, run_id?})` — canonical "did this flow run OK?", with the full source→…→sink chain.
- `get_resource_status({resource_type, resource_id})` — same, for a single named source / nexset / sink.

**Find & drill in**:
- `search_flows({name})` — resolve a flow name → id. Use whenever the user names a flow instead of giving the id.
- `get_flow_run({flow_id, run_id})` — one run's details + execution timing.
- `get_flow_logs({flow_id, run_id?, severity?, search?})` — raw data-plane log lines, after `get_flow_status` shows a bad run.
- `get_quarantine_samples({resource_type, resource_id})` — a sample of the actual records the data plane rejected.

**Notifications**:
- `notifications_summary` — one call returns `{ count, by_level:{ERROR,WARN,INFO,…}, by_read:{read,unread}, recent:[…] }`.

`resource_type` is the `data_sources` / `data_sets` / `data_sinks`-style string —
check the tool's schema for the exact value.

## "Why did X fail?" ladder

`list_flows_with_errors` (or `search_flows` → `get_flow_status`) → `get_flow_logs`
on the failing run → `get_quarantine_samples` if records were rejected →
`get_flow_run` for timing. Summarize findings inline.

## Charting — `visualize_metrics`

Hand it a **spec, never the data** — the iframe re-fetches the metric and renders
client-side (cheap on tokens regardless of size). It opens an inline panel;
**don't echo its URL into chat.**

```jsonc
visualize_metrics({
  title: "Org records ingested per day (last 30 days)",   // complete sentence
  chart_type: "line" | "bar" | "pie" | "kpi",
  monitoring_tool: "get_org_metrics",                     // any tool above
  monitoring_args: { granularity: "daily" },
  x_path: "$.buckets.*.bucket",
  y_path: "$.buckets.*.records",
})
```

**Paths**: `$` root; `.field` drills; `.*` is the iteration anchor (both paths
must share the same `.*` index). Common shapes:
- metric tools (`get_org_metrics` / `get_user_metrics` / `get_flow_metrics`):
  trend = `x: $.buckets.*.bucket`, `y: $.buckets.*.records` (or `.errors` / `.size`).
  A single total (`$.totals.records`) → `kpi`, omit paths.
- `list_flows_with_errors` → **bar**: `x: $.flows.*.flow_name`, `y: $.flows.*.errors`.
- `notifications_summary` by level (object map → key is `x`, value is `y`) →
  **pie**: `x: $.by_level.*`, `y: $.by_level.*`.

| Chart | Use when |
|---|---|
| `line` | a metric over time (buckets) |
| `bar`  | a metric across labeled entities (flows) |
| `pie`  | composition (notification levels, status mix) |
| `kpi`  | a single total |

## Tips

- Don't bake metric data into your prompt — read a metric only to fill
  `monitoring_args`, or skip the read entirely and let the iframe fetch.
- Default windows to ~30 days; widen only on request.
