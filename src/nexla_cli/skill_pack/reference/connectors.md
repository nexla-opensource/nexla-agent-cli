# Connectors — search & describe

Paths are relative to `${EXPRESS_PUBLIC_API_BASE}/nexla`. **Always describe before creating** — the field names in describe are exactly what you put in `config`.

## Search

- `GET /connectors/search?q=&kind=&supports=&limit=` — fuzzy search.
  - `kind`: `api | db | file | rest`
  - `supports`: `credential | source | sink`
  - `?include_unsupported=true` to also see deferred connectors (e.g. `api_multi`).

Kinds:
- `api` — templatized REST connectors (shopify_api, stripe_api, newsapi_api…). You pick a vendor **endpoint** and fill its params.
- `db` — databases (postgres, bigquery, snowflake…). Modes: `default` (table) or `query`.
- `file` — file systems (gdrive, s3, gcs, dropbox, sharepoint…). You pick a path.
- `rest` — **custom_rest**: the raw REST engine, no template, for any HTTP API. See `rest-custom.md`.
- `webhook` / `file_upload` — credential-less sources. See `sources.md`.

## Describe (hierarchical)

- `GET /connectors/describe/{name}?include=credential,source,sink` — top-level; `?include=` bundles the next levels in one call.
- `GET /connectors/describe/{name}/credential` — list auth modes. Cores have one `default`; API connectors may have several (e.g. `github_api.pat`, `github_api.oauth2`). OAuth modes return `supported:false` — not usable yet. custom_rest lists `NONE|API_KEY|BASIC|AWS_SIGNATURE|gcp_service_account` (TOKEN/OAuth deferred).
- `GET /connectors/describe/{name}/credential/{auth_mode}` — fields for that mode.
- `GET /connectors/describe/{name}/source`:
  - `api` → `endpoints` list (drill via `/source/{endpoint}`)
  - `db` → inline `modes: [default, query]`
  - `file` → inline `fields`
  - `rest` → `step_fields` + `iteration_types` catalog (see `rest-custom.md`)
- `GET /connectors/describe/{name}/source/{endpoint}` — fields for one API source endpoint. Returns user-facing names (e.g. `api_version`, `owner`, `repo`); the server re-attaches the namespace prefix when building payloads.
- Same shape for sinks: `/connectors/describe/{name}/sink[/{endpoint}]`.

Source describes also return a `shared_fields` array (most notably `start_cron`, Quartz — see `cron.md`). Treat them like `fields`: drop straight into `config`. Sinks don't run on their own cadence, so sink describes carry no `start_cron`.

A connector folder may ship `instructions` — surfaced on each describe call. Read it when present.

Tip: `?include=credential,source,sink` on the top-level describe gets everything in one round-trip when you know you'll need all three.
