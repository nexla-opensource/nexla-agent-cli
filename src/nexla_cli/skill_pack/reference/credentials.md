# Credentials — create, list, rotate, validate, explore

> **Standalone `nexla` CLI note.** This doc is vendored from express-code and its `curl "$API/..."` snippets describe the underlying agent-API shape. On a standalone `nexla` CLI install the same operations are `nexla-cli credentials list|get|create|update|delete` and `nexla-cli probe run`; the request bodies (`connector`, `auth_mode`, `config`) are identical. **OAuth credential creation via the `connect_oauth_credential` MCP tool and the `explore_credential` MCP-App below are sandbox-only** — they do not exist in a standalone install. Standalone installs create credentials with `nexla-cli credentials create` using static-secret (service-account / API-key) `config` shapes, and explore them with `nexla-cli probe run` instead of `explore_credential`. See AGENTS.md.

Paths relative to `${EXPRESS_PUBLIC_API_BASE}/nexla`. Reuse existing credentials where possible (list and pick) to save the user from re-entering secrets.

## CRUD

- `GET /credentials?connector=&kind=&page=&per_page=&access_role=` — list. `?connector=` works for both api and core kinds.
- `GET /credentials/{id}` — get. Sensitive values are scrubbed.
- `POST /credentials` — create. Body: `{name, description?, connector, auth_mode?, config}`.
  - `auth_mode` required when the connector exposes >1 supported mode; cores accept omitted (defaults to `default`). For **custom_rest** it's required and equals the auth type (`API_KEY`, `BASIC`, …) — see `rest-custom.md`.
  - `config` keys come straight from `describe/{name}/credential/{auth_mode}`.
- `PATCH /credentials/{id}` — update `{name?, description?, config?}`. `config` is **replaced**, not merged — supply the full shape. Connector/auth_mode aren't changeable (delete + recreate). Useful for rotating tokens without orphaning sources/sinks.
- `DELETE /credentials/{id}`

> **Standalone CLI:** the `connect_oauth_credential` flow below is a sandbox-only MCP tool. A standalone `nexla` CLI cannot run the interactive provider-consent flow — create non-OAuth (service-account / API-key) credentials with `nexla-cli credentials create` instead, or complete the OAuth grant in the Nexla web UI and reuse the resulting credential by id.

OAuth credentials use the **`connect_oauth_credential` MCP tool** — do not call `POST /credentials` with an OAuth auth_mode. When `GET /connectors/describe/{connector}/credential` lists an OAuth mode (`supported: true`), call:

```python
connect_oauth_credential(connector="gdrive", credential_name="My GDrive")
# API connector with a named OAuth template:
connect_oauth_credential(connector="shopify_api", auth_mode="shopify_api.oauth2")
```

The user completes provider consent in the UI; admin-api runs server-side OAuth; chat receives `!!EXPRESS_OAUTH_CREDENTIAL_CREATED` with the new credential id.

For static-secret credentials (non-OAuth), use `POST /credentials` as above.

## Probe — validate / explore / sample

`POST /probe` validates a credential, browses its structure, or pulls a sample. Body:

```json
{
  "credential_id": 30129,
  "credential": {"connector":"...","auth_mode":"...","config":{...}},
  "action": "validate" | "tree" | "sample",
  "params": { /* per action+kind */ }
}
```

Provide **either** `credential_id` (persisted) **or** an inline `credential` (auto-creates + deletes a temp credential — handy for validating config before persisting).

| action | api | db | file | rest (custom_rest) |
|--------|-----|----|----|----|
| `validate` | ✓ | ✓ | ✓ | ✓ |
| `tree` | n/a | ✓ `{path?}` | ✓ `{path?}` | n/a |
| `sample` | ✓ `{endpoint, config}` | ✓ default `{table, database}` / query `{db_query_mode:"Query", query}` | ✓ `{path}` | ✓ `{url, method?}` **or** `{ "rest.iterations":[...] }` |

- **api sample**: `params: {endpoint: "shopify_api.get_customers", config: {api_version: "2025-04"}}` — same field names as describe.
- **custom_rest sample**: pass a minimal `{url, method?}` (wrapped into a single `static.url` call) or a full `{ "rest.iterations":[...] }`. Encouraged before building a custom_rest source — custom configs are easy to get subtly wrong.
- **tree** returns one level at a time. Omit `path` for the root; pass a node id to drill. The `id`/`path` on each node is the exact value for `source_config.path` — **use what Nexla returned; never construct paths from display names.** For Google-style connectors it's an opaque ID; for s3/gcs/ftp a literal `bucket/prefix`.

Response (only fields relevant to the action): `validate` → `{ok, kind}`; `tree` → `+ nodes, next_path`; `sample` → `+ samples, schema, sample_format`. Errors → `{ok:false, error, detail, nexla_request_id}`.

`tree` nodes are a flat list with `parent_id` set; `has_children` is tri-state (`null` = unknown, drill in). `sample.sample_format` ∈ `records|csv|json|jsonl|unknown`; if empty + `raw_response_excerpt` present, the format wasn't auto-parseable — inspect the excerpt.

When you expect a hefty response, pipe it to a file and inspect with `jq`/`grep`/Python instead of pulling it into context.

## `explore_credential` — interactive MCP App

When the user wants to **interactively** explore a credential — pick an endpoint and fill params, run SQL, browse a file tree — call the MCP tool `explore_credential(credential_id, ...)` instead of chaining `/probe` calls. It opens a kind-aware UI tab: endpoint form + JSON viewer (API), tree+SQL tabs + table viewer (DB), drill-down tree with "Copy path" (files). Pre-fill when the conversation already gave specifics:

```python
explore_credential(credential_id=30164,
                   initial_endpoint="shopify_api.get_customers",
                   initial_params={"api_version": "2025-04"})

explore_credential(credential_id=30129,
                   initial_params={"query": "SELECT * FROM vedademo.us_tech_news LIMIT 50"})

explore_credential(credential_id=30132,
                   initial_path="1mZuyQt9DqasrvPhCiz3md_dvlbtoIE5P")  # opaque tree-node id IS the path
```

Use it for "show me what's in X" / "let me see a sample" / "help me pick a path". The panel renders on its own — don't echo its URL into chat.
