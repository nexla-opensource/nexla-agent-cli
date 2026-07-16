# Example — custom REST end-to-end (credential → probe → source → sink)

Build a flow against an API that has no templatized connector. See `reference/rest-custom.md` for the full field surface.

```bash
API="${EXPRESS_PUBLIC_API_BASE}/nexla"
H=(-H "Authorization: Bearer $(nexla-token)" -H "Content-Type: application/json")

# 0. Always describe first
curl -s "$API/connectors/describe/custom_rest?include=credential,source,sink" "${H[@]}"

# 1. Credential — API key in the Authorization header
CRED=$(curl -s -X POST "$API/credentials" "${H[@]}" -d '{
  "name": "Acme API", "connector": "custom_rest", "auth_mode": "API_KEY",
  "config": { "api.key.include.mode": "HEADER",
              "api.key.auth.key": "Authorization",
              "api.key.auth.value": "Bearer sk_live_..." }
}')
CRED_ID=$(echo "$CRED" | jq -r .id)

# 2. Probe before building — confirm the credential reaches the endpoint
curl -s -X POST "$API/probe" "${H[@]}" -d "{
  \"credential_id\": $CRED_ID, \"action\": \"sample\",
  \"params\": { \"url\": \"https://api.acme.com/v1/items\", \"method\": \"GET\" }
}"

# 3. Source — single GET with token pagination. The {status=active} macro
#    becomes a tool parameter on the resulting nexset's MCP tool.
SRC=$(curl -s -X POST "$API/sources" "${H[@]}" -d "{
  \"name\": \"Acme items\", \"connector\": \"custom_rest\", \"credential_id\": $CRED_ID,
  \"schedule\": \"once\",
  \"config\": { \"rest.iterations\": [ {
    \"key\": \"step1\", \"iteration.type\": \"paging.next.token\", \"method\": \"GET\",
    \"url.template\": \"https://api.acme.com/v1/items?status={status=active}\",
    \"response.data.path\": \"\$.items\",
    \"response.next.token.data.path\": \"\$.next_cursor\", \"param.id\": \"cursor\"
  } ] }
}")
SRC_ID=$(echo "$SRC" | jq -r .id)

# 4. Wait for the source-nexset (this env can be slow — be patient)
while true; do
  NEXSET_ID=$(curl -s "$API/sources/$SRC_ID" "${H[@]}" | jq -r '.source_nexset_id // empty')
  [ -n "$NEXSET_ID" ] && break; sleep 5
done

# 5. (Optional) sink — POST each record to another API. Often a NONE or
#    URL_PARAMETER-key credential.
SINK_CRED=$(curl -s -X POST "$API/credentials" "${H[@]}" -d '{
  "name": "Acme webhook", "connector": "custom_rest", "auth_mode": "API_KEY",
  "config": { "api.key.include.mode": "URL_PARAMETER", "api.key.auth.key": "api_key", "api.key.auth.value": "wk_..." }
}' | jq -r .id)
curl -s -X POST "$API/sinks" "${H[@]}" -d "{
  \"name\": \"Push to Acme\", \"connector\": \"custom_rest\",
  \"nexset_id\": $NEXSET_ID, \"credential_id\": $SINK_CRED,
  \"config\": { \"url.template\": \"https://api.acme.com/v1/ingest\", \"method\": \"POST\" }
}"
```

The `{status=active}` macro becomes a `status` parameter (default `active`) on the MCP tool spawned from this nexset — callers can override it at tool-call time. Just make sure the target API accepts the substituted value (the default is sent at ingestion).
