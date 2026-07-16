# Sinks

Paths relative to `${EXPRESS_PUBLIC_API_BASE}/nexla`. For **custom REST** sinks (raw HTTP, no template) see `rest-custom.md`.

- `GET /sinks?connector=&nexset_id=&flow_id=&…`
- `GET /sinks/{id}`
- `POST /sinks` — create + auto-activate. Body: `{name, nexset_id, credential_id, connector, endpoint?, config}`. `endpoint` required for api connectors.
- `PATCH /sinks/{id}` — update `{name?, description?, config?}`. Runs the full **pause → update → reactivate** cycle in one call (idempotent; safe to repeat). Connector/endpoint/credential aren't changeable — delete + recreate.
- `POST /sinks/{id}/activate` · `POST /sinks/{id}/pause` · `DELETE /sinks/{id}`

`config` field names come from `GET /connectors/describe/{name}/sink[/{endpoint}]`. Sinks don't run on their own cadence (the flow follows the source's cron), so there's no `start_cron`.

**API sinks often need a transform first** to shape records into the endpoint's expected payload. The endpoint's `description` from describe is the only signal — read it; we don't auto-detect this.

```bash
curl -s -X POST "$API/sinks" "${H[@]}" -d "{
  \"name\": \"BQ Sink\", \"nexset_id\": $NEXSET_ID, \"credential_id\": 30129,
  \"connector\": \"bigquery\",
  \"config\": {\"table\": \"customers\", \"database\": \"vedademo\", \"insert.mode\": \"INSERT\"}
}"
```
