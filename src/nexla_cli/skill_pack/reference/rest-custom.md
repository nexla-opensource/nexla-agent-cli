# Custom REST — `custom_rest` credentials, sources & sinks

> **Standalone `nexla` CLI note.** Vendored from express-code; the `curl "$API/..."` snippets show the underlying agent-API shape. On a standalone install use `nexla-cli credentials create`, `nexla-cli probe run`, `nexla-cli sources create`, and `nexla-cli sinks create` with the same bodies. The `gcp_service_account` note about reading a `/workspace` file is sandbox-specific — on a standalone install inline the service-account JSON from a real local file path. See AGENTS.md.

`custom_rest` is Nexla's raw REST engine exposed directly: build a credential, source, or sink against **any** HTTP API with **no template**. Full control over auth, pagination, multi-step iteration, and request/response shaping.

**When to reach for it:** there's no templatized connector for the API, or you need control a template doesn't give you (custom pagination, multi-step calls, arbitrary auth/headers, a bespoke request body). **Prefer a templatized `api` connector when one exists** (search first) — it's less to configure. Reach for `custom_rest` when that's not enough.

Connector name is **`custom_rest`** everywhere in this API. Always `describe` first — the field names below are the live source of truth.

```bash
API="${EXPRESS_PUBLIC_API_BASE}/nexla"
H=(-H "Authorization: Bearer $(nexla-token)" -H "Content-Type: application/json")
curl -s "$API/connectors/describe/custom_rest?include=credential,source,sink" "${H[@]}"
```

## 1. Credential

Pick one `auth_mode`; v1 supports these (TOKEN, OAuth1/2 are deferred). `GET /connectors/describe/custom_rest/credential/{auth_mode}` lists each mode's fields.

| auth_mode | required fields | notes |
|---|---|---|
| `NONE` | — | public API, or auth via `request.headers` |
| `API_KEY` | `api.key.include.mode` (`HEADER`\|`URL_PARAMETER`), `api.key.auth.key`, `api.key.auth.value` | key in a header or query param |
| `BASIC` | `basic.username`, `basic.password` | sent as `Basic <base64(user:pass)>` — Nexla encodes |
| `AWS_SIGNATURE` | `aws.access.key`, `aws.secret.key`, `aws.region`, `aws.service` (+ optional `aws.session.token`) | AWS SigV4 |
| `gcp_service_account` | `gcp.service.account.credentials.json` (+ optional `gcp.service.account.oauth.scopes`) | paste the **full JSON string**. If the user has it as a `/workspace` file, read the file and inline its contents. |

Optional on every mode: `request.headers` (`"Name:val,Name2:val2"`), `ignore.ssl.cert.validation` (bool).

```bash
# API key in the Authorization header (a Bearer/Basic token goes in api.key.auth.value):
curl -s -X POST "$API/credentials" "${H[@]}" -d '{
  "name": "Acme API", "connector": "custom_rest", "auth_mode": "API_KEY",
  "config": { "api.key.include.mode": "HEADER",
              "api.key.auth.key": "Authorization",
              "api.key.auth.value": "Bearer sk_live_..." }
}'
```

We auto-fill the boilerplate (skip-validation, no JWT/HMAC/cert) — you only send the fields above. Validation-before-save isn't exposed in v1; **probe instead** (below).

## 2. Probe before building the source (recommended)

Custom configs are easy to get subtly wrong. Verify the credential reaches the endpoint and see what comes back:

```bash
curl -s -X POST "$API/probe" "${H[@]}" -d '{
  "credential_id": 30388, "action": "sample",
  "params": { "url": "https://api.acme.com/v1/items", "method": "GET" }
}'
```

`params` accepts the minimal `{url, method?}` (wrapped into one `static.url` call) or a full `{ "rest.iterations": [...] }` for testing pagination. Look at `sample_format` / `samples` / `raw_response_excerpt`.

## 3. Source — the `rest.iterations` model

A source is an ordered list of **iteration steps** under `config.rest.iterations`, plus a top-level `start_cron` (or `schedule: "once"`). Each step makes HTTP call(s); its `iteration.type` picks the pagination strategy and which extra fields it needs.

`GET /connectors/describe/custom_rest/source` returns `step_fields` (shared by every step), `iteration_types` (the catalog below, each with a copy-and-fill `example`), and the shared `start_cron`. **Most sources are a single step.** Start from the matching example and fill your values.

Shared step fields: `key` (req, unique e.g. `step1`), `url.template` (req), `method` (req: GET/POST/PUT), `iteration.type` (req), plus optional `response.format` (default `json`), `response.data.path` (JSONPath/XPath to the records array, e.g. `$.data[*]`), `response.data.path.additional` (metadata to merge into each record), `body.template` (request payload / GraphQL query), `request.headers`, `request.parallelism.count` (default 1; raising it risks rate-limits), `results.pass.through` (multi-step only), `date.format` + `date.time.unit` (only when you use a `{now}` date macro — pick from the enums describe returns).

### Supported iteration types (v1)

| type | extra fields | for |
|---|---|---|
| `static.url` | — | single request, no pagination |
| `paging.incrementing` | `param.id`, `start.page.from` (+ opt `end.page.to`, `param.page.size`, `page.expected.rows`) | page-number paging |
| `paging.incrementing.offset` | `param.offset`, `start.offset.from` (+ opt `end.offset.to`) | offset paging |
| `paging.next.token` | `response.next.token.data.path`, `param.id` (+ opt `end.token.to`) | cursor/token from each response |
| `paging.next.url` | `response.next.url.data.path` (+ opt `end.url.to`) | follow a next-page URL in the body |
| `link.header` | (opt `link`) | follow the `Link` response header |

Anything else (`graphql.*`, `async.poll`, …) is rejected in v1 with `rest_iteration_type_unsupported`.

```bash
# Single-step GET, token pagination
curl -s -X POST "$API/sources" "${H[@]}" -d '{
  "name": "Acme items", "connector": "custom_rest", "credential_id": 30388,
  "schedule": "once",
  "config": { "rest.iterations": [ {
    "key": "step1", "iteration.type": "paging.next.token", "method": "GET",
    "url.template": "https://api.acme.com/v1/items",
    "response.data.path": "$.items",
    "response.next.token.data.path": "$.next_cursor", "param.id": "cursor"
  } ] }
}'
```

Then activate happens automatically; **poll `GET /sources/{id}` for `source_nexset_id`** like any source.

### Macros → tool params

`{name=default}` macros work anywhere in an iteration's `url.template` or `body.template`, exactly like other sources. Each distinct macro becomes an input parameter on the MCP tool spawned from the resulting nexset (default = the value after `=`).

```jsonc
"url.template": "https://api.acme.com/v1/items?status={status=active}&limit={limit=100}"
// → the spawned tool exposes `status` (default "active") and `limit` (default 100)
```

Two practical notes:
- The macro's **default is substituted at ingestion**, so the target API must accept the substituted request (e.g. don't inject a query param an endpoint rejects) — otherwise the nexset won't materialize. Probe first if unsure.
- To see the macro as a tool parameter, read it from the **toolset** (`GET /toolsets/{id}` → `tools[].input_schema`, or the create response) — Nexla computes tool schemas at the toolset level. The standalone `GET /tools/{id}` returns a slim row without `input_schema`.

### Multi-step (advanced)

`rest.iterations` may hold several steps; a later step references an earlier one with `{step<key>.<path>}` (e.g. fetch a token in `step1`, use `{step_step1.access_token}` in `step2`). Set `results.pass.through: true` to keep every step's output instead of just the last. Keep it to a single step unless the task truly needs chaining.

## 4. Sink — POST/PUT records to any URL

`GET /connectors/describe/custom_rest/sink` for the fields. Required: `url.template`, `method`. Defaults injected if omitted: `content.type` → `application/json`, `body.template` → `{message.json}` (the whole record).

- `url.template` — supports `{record.<field>}` and date macros for dynamic URLs.
- `body.template` — shape the payload; `{message.json}` is the whole record.
- `batch.mode` (bool) → set `max.poll.records` (and optionally `body.transform.function`) to send records in batches.
- `create.datasource` (bool) — capture the API response back as a dataset.

The sink's credential is a `custom_rest` credential (often `API_KEY` with the key as a `URL_PARAMETER`, or `NONE` for an open webhook).

```bash
curl -s -X POST "$API/sinks" "${H[@]}" -d '{
  "name": "Push to Acme", "connector": "custom_rest",
  "nexset_id": 424876, "credential_id": 30389,
  "config": { "url.template": "https://api.acme.com/v1/ingest", "method": "POST" }
}'
```

## End-to-end

See `examples/custom-rest-flow.md` for a full credential → probe → source → nexset → sink walk-through.
