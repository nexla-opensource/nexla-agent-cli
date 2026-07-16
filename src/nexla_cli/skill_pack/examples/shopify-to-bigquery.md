# Example — Shopify → BigQuery flow

Reuse existing creds where possible (list and pick) to save the user re-entering secrets.

```bash
API="${EXPRESS_PUBLIC_API_BASE}/nexla"
H=(-H "Authorization: Bearer $(nexla-token)" -H "Content-Type: application/json")

# 1. Find the connector + endpoint
curl -s "$API/connectors/search?q=shopify&kind=api" "${H[@]}"
curl -s "$API/connectors/describe/shopify_api/source" "${H[@]}"
curl -s "$API/connectors/describe/shopify_api/source/shopify_api.get_customers" "${H[@]}"

# 2. Pick or create a credential
curl -s "$API/credentials?connector=shopify_api" "${H[@]}"   # CRED_ID = 30127

# 3. Probe before persisting (optional but recommended)
curl -s -X POST "$API/probe" "${H[@]}" -d '{
  "credential_id": 30127, "action": "sample",
  "params": {"endpoint": "shopify_api.get_customers", "config": {"api_version": "2025-04"}}
}'

# 4. Create source — returns immediately
SOURCE=$(curl -s -X POST "$API/sources" "${H[@]}" -d '{
  "name": "Shopify Customers", "credential_id": 30127, "connector": "shopify_api",
  "endpoint": "shopify_api.get_customers", "config": {"api_version": "2025-04"}
}')
SOURCE_ID=$(echo "$SOURCE" | jq -r .id)

# 5. Wait for the source-nexset
while true; do
  NEXSET_ID=$(curl -s "$API/sources/$SOURCE_ID" "${H[@]}" | jq -r '.source_nexset_id // empty')
  [ -n "$NEXSET_ID" ] && break; sleep 3
done

# 6. (Optional) transform — uppercase last_name (Jython 2.7)
TX_NEXSET=$(curl -s -X POST "$API/nexsets/$NEXSET_ID/transform" "${H[@]}" -d '{
  "name": "Customers (uppercased)", "language": "python",
  "code": "def transform(input, metadata, args):\n    o = input.copy()\n    ln = o.get(\"last_name\")\n    if isinstance(ln, basestring): o[\"last_name\"] = ln.upper()\n    return o"
}' | jq -r .id)

# 7. BigQuery sink (BQ cred 30129 already exists)
curl -s -X POST "$API/sinks" "${H[@]}" -d "{
  \"name\": \"BQ Sink\", \"nexset_id\": $TX_NEXSET, \"credential_id\": 30129,
  \"connector\": \"bigquery\",
  \"config\": {\"table\": \"customers\", \"database\": \"vedademo\", \"insert.mode\": \"INSERT\"}
}"

# 8. Inspect the full flow
FLOW_ID=$(curl -s "$API/sources/$SOURCE_ID" "${H[@]}" | jq -r .flow_id)
curl -s "$API/flows/$FLOW_ID" "${H[@]}"
```
