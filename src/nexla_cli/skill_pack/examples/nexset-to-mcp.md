# Example — expose a nexset as an MCP server

```bash
API="${EXPRESS_PUBLIC_API_BASE}/nexla"
H=(-H "Authorization: Bearer $(nexla-token)" -H "Content-Type: application/json")

# 1. Create a toolset from a nexset
TS=$(curl -s -X POST "$API/toolsets" "${H[@]}" -d "{
  \"name\": \"Daily News MCP\",
  \"description\": \"Daily news headlines as an MCP server\",
  \"nexset_ids\": [$NEXSET_ID],
  \"mcp_gateway_enabled\": false
}")
TS_ID=$(echo "$TS" | jq -r .id)
TOOL_ID=$(echo "$TS" | jq -r '.tools[0].id')

# 2. (Optional) pin the spawned tool to a specific credential
curl -s -X PATCH "$API/tools/$TOOL_ID/runtime-config" "${H[@]}" -d '{
  "strategy": "auto", "connector_name": "newsapi_api", "connector_type": "templatized_api"
}'

# 3. Surface the MCP URL — prefer the Google-OAuth variant
echo "$TS" | jq -r '.recommended_mcp_url'
# Tell the user: "Paste this URL into Claude / ChatGPT / your MCP client. It uses Google OAuth."
```

To extend with an external MCP server (gateway required):

```bash
curl -s -X PATCH "$API/toolsets/$TS_ID" "${H[@]}" -d '{"mcp_gateway_enabled": true}'
ATT=$(curl -s -X POST "$API/toolsets/$TS_ID/mcp-servers" "${H[@]}" -d '{
  "server_name": "my_internal_api", "server_url": "https://example.internal/mcp/",
  "auth": {"type": "bearer", "value": "<secret>"},
  "tool_filter": {"mode": "include", "patterns": ["list_*", "get_*"]}
}')
EXT_ID=$(echo "$ATT" | jq -r .id)
curl -s -X POST "$API/toolsets/$TS_ID/mcp-servers/$EXT_ID/sync" "${H[@]}"   # REQUIRED
```

Tip: if the user only wants the nexset queryable as an MCP server (no ongoing pipeline), create the source with `schedule: "once"` (see `reference/sources.md`).
