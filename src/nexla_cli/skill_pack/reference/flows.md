# Flows

Paths relative to `${EXPRESS_PUBLIC_API_BASE}/nexla`. A flow is the whole DAG: one source, its nexsets, and any sinks.

- `GET /flows?status=&q=&…` — list (sorted by `updated_at` desc).
- `GET /flows/{id}` — composed read: `{source, graph: [nexsets..., sinks...]}` in one call.
- `PUT /flows/{id}/activate` · `PUT /flows/{id}/pause` · `DELETE /flows/{id}` (cascades — deletes the source, nexsets, and sinks).

Get a source's `flow_id` from `GET /sources/{id}` (it's the source's `origin_node_id` upstream; we surface it as `flow_id`).

```bash
FLOW_ID=$(curl -s "$API/sources/$SOURCE_ID" "${H[@]}" | jq -r .flow_id)
curl -s "$API/flows/$FLOW_ID" "${H[@]}"
```
