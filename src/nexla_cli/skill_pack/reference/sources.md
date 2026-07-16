# Sources — api / db / file / webhook / file_upload

> **Standalone `nexla` CLI note.** Vendored from express-code; the `curl "$API/..."` snippets show the underlying agent-API shape. On a standalone install use `nexla-cli sources create|get|list|activate|pause|delete` with the same request bodies. Use `nexla-cli sources get <id> --wait-until source_nexset_id` instead of the hand-rolled poll loops below. The **file-upload flow's `upload_files_to_sandbox` MCP tool and `/workspace/uploads/...` paths are sandbox-only** — on a standalone install point the file paths at real local files you control. See AGENTS.md.

Paths relative to `${EXPRESS_PUBLIC_API_BASE}/nexla`. For **custom REST** sources (raw HTTP, no template) see `rest-custom.md`.

- `GET /sources?connector=&flow_id=&page=&per_page=`
- `GET /sources/{id}` — `source_nexset_id` is null until materialization (~5–15s); poll for it.
- `POST /sources` — create + auto-activate. Body: `{name, description?, credential_id, connector, endpoint?, mode?, config, schedule?}`. `endpoint` required for api; `mode` is `default|query` for db. Webhook + file_upload omit `credential_id`.
- `PATCH /sources/{id}` — update name/description/config only.
- `POST /sources/{id}/activate` · `POST /sources/{id}/pause` · `DELETE /sources/{id}`

After create, poll until the source-nexset appears:

```bash
while true; do
  NEXSET_ID=$(curl -s "$API/sources/$SOURCE_ID" "${H[@]}" | jq -r '.source_nexset_id // empty')
  [ -n "$NEXSET_ID" ] && break; sleep 3
done
```

## Inline macros (API + DB sources)

Any string in `config` can be a `{name=default}` macro instead of a literal. When the nexset is later attached to a toolset, each distinct macro becomes an input parameter on the spawned `nexset_read` tool. One concept, one syntax — no parallel `macros:` field. Use macros when the user wants the source configurable from the eventual MCP tool; skip otherwise.

```bash
curl -s -X POST "$API/sources" "${H[@]}" -d '{
  "name": "News by topic", "credential_id": 30149, "connector": "newsapi_api",
  "endpoint": "newsapi_api.fetch_top_headlines_by_country",
  "config": { "country_code": "us", "category_code": "{news_topic=general}" }
}'   # → tool exposes `news_topic` (default "general")
```

## DB sources — the four cases

DB sources all *ingest* the same way, but the **shape of the resulting MCP tool's input** depends on what you write. Pick consciously. Macros require **query mode** (not default mode).

| # | `config` | Ingests | Tool params |
|---|---|---|---|
| 1 | `{table, database}` (mode `default`) | whole table | none |
| 2 | `{query: "SELECT a,b FROM t"}` (mode `query`) | that fixed query | none |
| 3 | `{query: "{query=SELECT a,b FROM t}"}` (mode `query`) | that query | one: `query` — caller substitutes any SQL. **Default to this when the user has no preference.** |
| 4 | `{query: "SELECT a FROM t WHERE x >= {min_x=10}"}` (mode `query`) | uses defaults | one per inline macro (`min_x`, default 10) |

**Don't mix cases 3 and 4** (nested macros aren't reliably supported). Pick one shape.

```bash
# Case 3 (recommended default)
curl -s -X POST "$API/sources" "${H[@]}" -d '{
  "name": "Generic BQ tool", "credential_id": 30129, "connector": "bigquery",
  "mode": "query", "config": { "query": "{query=SELECT * FROM vedademo.us_tech_news LIMIT 100}" }
}'
```

## Webhook sources

JSON POSTs to a Nexla-hosted URL — no credential. Use when the user pushes events from a custom app/script with no built-in connector.

- **Connector name is `webhook`** (not the internal `nexla_rest`).
- Default to **single schema enforced** (`enforce_single_schema: true`): first payload defines the schema, mismatches rejected.
- The nexset doesn't exist until the first payload. Send one via `POST /sources/{id}/sample` right after create.

```bash
SRC=$(curl -s -X POST "$API/sources" "${H[@]}" -d '{"name":"Stripe events","connector":"webhook","config":{"enforce_single_schema":true}}')
SID=$(echo "$SRC" | jq -r .id); URL=$(echo "$SRC" | jq -r .hosted_url)
curl -s -X POST "$API/sources/$SID/sample" "${H[@]}" -d '{"payload":{"event_id":"evt_1","amount":42.5}}'
echo "Webhook URL: $URL"   # give this to the user to paste upstream
```

If no sample is handy, invent a plausible payload and warn that the schema locks after the first POST (recreate to change it).

## File-upload sources

Ingest local files (CSV/JSON/Parquet…). Three steps.

> **Standalone CLI:** step 1's `upload_files_to_sandbox()` MCP tool does not exist on a standalone `nexla-cli` install, and the CLI does **not** upload local files. The `file-upload` `--path` values are resolved by the server *inside* a Nexla-managed sandbox, so you must name one: `nexla-cli sources file-upload <id> --sandbox <sandbox-id> --path /workspace/uploads/.../a.csv`. Without `--sandbox` the CLI exits `CONFIG` (3) and makes no call rather than letting the server pick an arbitrary sandbox. To ingest files that only exist on your local machine, host them somewhere the platform can reach and use a normal `file`/`s3`/etc. source instead.

1. **Open the upload UI** — call MCP tool `upload_files_to_sandbox()` (no args). A tab opens for drag-and-drop (≤20 files, ≤5 MB each, media/executables blocked). On submit, the chat receives an auto-sent follow-up listing files under `/workspace/uploads/<call_id>/`. **Don't read those files unless asked.** (The panel renders itself — don't echo its URL.)
2. **Create + upload + activate** — connector `file_upload`, no credential:

```bash
SRC=$(curl -s -X POST "$API/sources" "${H[@]}" -d '{"name":"Sales CSVs","connector":"file_upload","config":{},"schedule":"once"}')
SID=$(echo "$SRC" | jq -r .id)
curl -s -X POST "$API/sources/$SID/file_upload" "${H[@]}" -d "{\"files\": $(ls -1 /workspace/uploads/<call_id>/* | jq -R . | jq -s 'map({path: .})')}"
curl -s -X POST "$API/sources/$SID/activate" "${H[@]}"
```

3. **Wait for the nexset** (same poll). Use `POST /sources/{id}/file_upload` (handles per-file multipart) — don't POST to `hosted_url` yourself.

## Schedule — `recurring` vs `once`

`schedule` is a **top-level field on the create body**, not in `config`:

- `"recurring"` (default) — uses `config.start_cron` (Quartz, see `cron.md`). Keeps running on cadence.
- `"once"` — ingests a single batch ~60s after creation, then never again. `start_cron` ignored. Cheaper.

Default to `"once"` when the user only wants to **expose a nexset as an MCP server / toolset** (no ongoing pipeline). Stay on `"recurring"` for real syncs/ETL. Webhook sources reject `once`.
