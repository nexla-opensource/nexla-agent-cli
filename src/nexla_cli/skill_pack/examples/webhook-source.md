# Example — webhook source (push events into Nexla)

No credential. The nexset materializes only after the first payload.

```bash
API="${EXPRESS_PUBLIC_API_BASE}/nexla"
H=(-H "Authorization: Bearer $(nexla-token)" -H "Content-Type: application/json")

# 1. Create + auto-activate (single schema enforced by default)
SRC=$(curl -s -X POST "$API/sources" "${H[@]}" -d '{
  "name": "Stripe events", "connector": "webhook",
  "config": { "enforce_single_schema": true }
}')
SID=$(echo "$SRC" | jq -r .id)
URL=$(echo "$SRC" | jq -r .hosted_url)

# 2. Send one sample payload to materialize the nexset + schema
curl -s -X POST "$API/sources/$SID/sample" "${H[@]}" -d '{
  "payload": { "event_id": "evt_1", "user": "alice", "amount": 42.5 }
}'

# 3. Surface the URL — the user pastes it into the upstream system
echo "Webhook URL: $URL"
```

The schema locks after that first POST — recreate to change it. Webhook sources reject `schedule: "once"`.
