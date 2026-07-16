# Toolsets — expose nexsets as an MCP server

> **Standalone `nexla` CLI note.** Vendored from express-code; the `curl "$API/..."` snippets show the agent-API shape. On a standalone install these map to `nexla-cli toolsets ...`, `nexla-cli tools ...` (incl. `nexla-cli tools set-runtime-config`), and `nexla-cli mcp-servers ...` with identical request bodies. See AGENTS.md.

A **toolset** turns one or more nexsets into MCP tools (one `nexset_read` tool per nexset) and gives the user a single MCP URL to paste into Claude / ChatGPT / any MCP client. Paths relative to `${EXPRESS_PUBLIC_API_BASE}/nexla`.

Every toolset has two MCP URLs:
- `mcp_url_google_oauth` (= `recommended_mcp_url`) — **echo this by default.**
- `mcp_url_service_key` — only surface when the user explicitly asks for the non-OAuth variant.

- `GET /toolsets` — list.
- `GET /toolsets/{id}` — composed read: `{tools, external_mcp_servers, mcp_url_google_oauth, recommended_mcp_url, …}`.
- `POST /toolsets` — create. Body: `{name, description?, nexset_ids: [int], mcp_gateway_enabled?: bool}`. `mcp_gateway_enabled` defaults false — set true only for the gateway's search-over-all-tools capability or to attach external MCP servers.
- `PATCH /toolsets/{id}` — rename / change description / toggle `mcp_gateway_enabled`.
- `POST /toolsets/{id}/nexsets` — add nexsets. Body: `{nexset_ids: [int]}`. Idempotent.
- `DELETE /toolsets/{id}` — delete the toolset (tools survive; delete separately if you want them gone).

When a source's nexset carries macros (incl. `custom_rest` url/body macros), the spawned `nexset_read` tool exposes each macro as an input parameter. **Read the tool's `input_schema` from the toolset** — `GET /toolsets/{id}` → `tools[].input_schema` (also present on the create response). Nexla computes tool schemas at the toolset layer, so the standalone `GET /tools/{id}` returns a slim row with `input_schema: null`.

## Tools — runtime credential config

Tools work without further config when called via the MCP server. But if a tool must call Nexla data-plane endpoints on the user's behalf, give it a runtime credential strategy.

- `GET /tools` · `GET /tools/{id}` (detail: `input_schema`, `output_schema`, `runtime_config`).
- `PATCH /tools/{id}/runtime-config`:
  ```jsonc
  {
    "strategy": "auto" | "mapped",
    "connector_name": "newsapi_api",
    "connector_type": "templatized_api",
    "credential_mappings": [ {"user_id": 2031, "credential_id": 29497} ]  // required for "mapped"
  }
  ```
  `auto` = gateway picks the caller's latest matching credential; `mapped` = pin `{user_id → credential_id}`.
- `DELETE /tools/{id}/runtime-config` (disable) · `DELETE /tools/{id}` (delete the tool).

## External MCP servers (gateway only)

When `mcp_gateway_enabled=true`, attach external MCP servers; their tools become discoverable through the gateway's search tool.

- `GET /toolsets/{id}/mcp-servers` — list.
- `POST /toolsets/{id}/mcp-servers` — attach. Body: `{server_name, server_url, server_description?, auth?, tool_filter?}`.
  - `auth`: `{type: "bearer"|"basic"|"headers"|"none", value}`.
  - `tool_filter`: `{mode: "include"|"exclude", tool_names: [...], patterns: [glob…]}`.
- `POST /toolsets/{id}/mcp-servers/{server_id}/sync` — **required second step** after attach; triggers tool discovery/indexing. Without it the gateway can't see the external tools.
- `DELETE /toolsets/{id}/mcp-servers/{server_id}` — detach.

See `examples/nexset-to-mcp.md` for the full create-toolset-and-surface-URL flow.
