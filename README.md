# nexla-cli

[![PyPI](https://img.shields.io/pypi/v/nexla-cli.svg?label=PyPI)](https://pypi.org/project/nexla-cli/)
[![npm version](https://img.shields.io/npm/v/@nexla/nexla-cli.svg)](https://www.npmjs.com/package/@nexla/nexla-cli)
[![License: MIT](https://img.shields.io/github/license/nexla-opensource/nexla-agent-cli.svg)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/nexla-cli.svg)](https://pypi.org/project/nexla-cli/)

Command-line client for the Nexla agent API. Depends on only `typer` and
`httpx` — no FastAPI, Daytona, Supabase, or other backend dependencies.

## Install

### PyPI (recommended)

Requires Python 3.12+. Installs a self-contained package — nothing to approve,
works out of the box:

```bash
uv tool install nexla-cli      # or: pipx install nexla-cli  /  pip install nexla-cli
```

Run once-off without installing:

```bash
uvx nexla-cli sources list
```

### npm (native binary, no Python required)

```bash
npm install -g @nexla/nexla-cli
```

This installs a prebuilt native binary behind a thin `npm/` wrapper — no
Python interpreter needed on the target machine.

> **Note (npm 11+):** npm now blocks package install scripts by default, and
> this package fetches its binary in a `postinstall` step. If the `nexla-cli`
> command isn't found right after install, approve the script and reinstall:
>
> ```bash
> npm approve-scripts @nexla/nexla-cli
> npm install -g @nexla/nexla-cli --foreground-scripts
> ```
>
> The PyPI install above has no install script and isn't affected.

### From source

```bash
uv tool install "git+https://github.com/nexla-opensource/nexla-agent-cli.git"
```

## Quick start

```bash
export NEXLA_API_URL=https://<your-deployed-api>
export NEXLA_TOKEN=$(nexla-cli login --service-key <your-service-key>)
nexla-cli sources list
```

`nexla-cli login` prints a bearer token to stdout (see command substitution
above); alternatively, set the following environment variables directly:

- `NEXLA_API_URL` — base URL of the deployed Nexla agent API
- `NEXLA_TOKEN` — bearer token to authenticate requests

## Using this CLI from Claude Code

The package ships a [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) in two layers, both installed alongside the `nexla_cli` package:

- **`SKILL.md` + `AGENTS.md`** — the thin CLI-specific adapter: output modes, `--dry-run`, `--json`/`--params` precedence, `--wait-until`, exit codes, response sanitization, and the DB-sink table preflight — invariants an agent can't infer from `--help` alone.
- **`skill_pack/reference/` + `skill_pack/examples/`** — the canonical Nexla *domain* docs (connector configs and probe shapes, credential/OAuth modes, Quartz cron, DB query macros, custom REST iteration types, transforms, toolsets/MCP, monitoring, and worked end-to-end examples), vendored from [`nexla/express-code`](https://github.com/nexla/express-code) so there's one canonical domain source. See `skill_pack/VENDORED_FROM.md`.

Claude Code only discovers skills placed at `~/.claude/skills/<name>/SKILL.md` (global) or `.claude/skills/<name>/SKILL.md` (project-local) — a file merely present inside an installed package isn't picked up automatically. Install it once, after installing the CLI (works the same way regardless of whether you installed via `uv tool`, `pipx`, `pip`, or the npm-wrapped binary):

```bash
nexla-cli skill install
# or, for a project-local install instead of the global default:
nexla-cli skill install --target .claude/skills/nexla-cli
```

`skill install` copies all three parts (`SKILL.md`, `AGENTS.md`, and the whole `skill_pack/` tree). Re-run it after upgrading `nexla-cli` to pick up any content changes. Restart Claude Code (or start a new session) afterward for it to be picked up.

### Install targets — Claude Code, Codex, OpenCode, and others

`--target` accepts **any** directory — it just copies the skill tree there. Point it at whatever directory your agent discovers skills in:

```bash
# Claude Code — global (default) or project-local:
nexla-cli skill install                                   # ~/.claude/skills/nexla-cli
nexla-cli skill install --target .claude/skills/nexla-cli # project-local

# Any other agent — point --target at that agent's skills directory, e.g.:
nexla-cli skill install --target ~/.codex/skills/nexla-cli      # Codex
nexla-cli skill install --target ~/.config/opencode/skills/nexla-cli  # OpenCode
```

The Codex / OpenCode paths above are examples — if your install discovers skills elsewhere, pass that directory instead. The content is plain Markdown, so it's useful to any agent that reads a skills/instructions directory.

### Standalone OAuth limitation

The vendored domain docs describe a `connect_oauth_credential` flow and an `explore_credential` UI that only exist inside the Express agent sandbox. A **standalone `nexla` CLI cannot run the interactive OAuth consent flow.** For OAuth-only connectors, complete the grant in the Nexla web UI and reuse the resulting credential by id, or use a non-OAuth (service-account / API-key) auth mode with `nexla-cli credentials create`. Each affected vendored doc carries a note mapping the sandbox surface onto standalone CLI commands.

## Global flags

Available on every command except `login` and `schema` (both always print raw output regardless of these flags):

| Flag | Effect |
|------|--------|
| `--output` / `-o` `table\|json\|ndjson` | Force an output mode. Defaults to `table` on a TTY, `json` otherwise (also settable via `NEXLA_OUTPUT`/`OUTPUT_FORMAT`). |
| `--fields id,name,...` | Mask output down to just these keys, on any `list`/`get`. |
| `--page-all` | Stream every page of a `list` command as NDJSON instead of returning one page. |

These can be placed before or after the subcommand, e.g. both `nexla-cli --output json sources list` and `nexla-cli sources list --output json` work.

Because these flags are hoisted from anywhere in the command line, `-o`, `--output`, `--fields`, and `--page-all` are reserved: an argument or value that must be one of those literal strings has to come after a `--` end-of-options separator, which stops the hoisting (everything after `--` is passed through untouched), e.g. `nexla-cli sources get -- --output`.

Every mutating command also accepts `--dry-run`: runs a shallow structural lint of the request body (required fields present + top-level types) and prints `{"valid": ...}` without making the real (mutating) call. It does not check enums, patterns, formats, numeric bounds, or nested objects — the live API still fully validates those on the real call.

## Raw JSON payloads

`create`/`update`-style commands (`sources`, `sinks`, `credentials`, `toolsets`, `nexsets transform`, `mcp-servers attach`, `tools set-runtime-config`) accept the full request body directly, not just their named flags:

```bash
nexla-cli sources create --name my-source --connector s3 --json '{"credential_id": 123}'
nexla-cli sources update 42 --params description="updated via params"
```

Precedence when a key is given more than one way: named CLI flags win, then `--json`, then `--params` (lowest). This lets you set a field the CLI hasn't added a dedicated flag for yet, without waiting on a CLI release.

## Response sanitization

Every response is passed through a sanitizer before rendering, in every output mode: ANSI escape sequences, control characters, and invisible Unicode (zero-width spaces, byte-order marks, bidirectional overrides) are stripped unconditionally — always on, no flag. This defends against a malicious API response field hijacking a human's terminal, or hiding text from a human while an agent still reads it. It is not a semantic filter — API response *content* should still be treated as untrusted data (see `AGENTS.md`), this only strips characters no legitimate field value would ever need.

## Full command reference

```bash
nexla-cli --help
nexla-cli <resource> --help
```

| Resource | Commands |
|----------|----------|
| `login` | `login --service-key <key> [--api-url <url>]` — exchanges a service key for a bearer token, printed to stdout |
| `schema` | `schema [<resource>.<verb>]` — machine-readable JSON signature of one command or the whole `/nexla/*` surface, fetched live from the deployed API's OpenAPI doc |
| `sources` | `list`, `get`, `create`, `update`, `activate`, `pause`, `delete`, `sample`, `file-upload` |
| `sinks` | `list`, `get`, `create`, `update`, `activate`, `pause`, `delete` |
| `nexsets` | `list`, `get`, `transform`, `activate` |
| `credentials` | `list`, `get`, `create`, `update`, `delete` |
| `flows` | `list`, `get`, `activate`, `pause`, `delete` |
| `transforms` | `test` |
| `connectors` | `search`, `describe`, `describe-credential`, `describe-credential-mode`, `describe-source`, `describe-source-endpoint`, `describe-sink`, `describe-sink-endpoint` |
| `probe` | `run` |
| `toolsets` | `list`, `get`, `create`, `update`, `delete`, `add-nexsets` |
| `tools` | `list`, `get`, `set-runtime-config`, `clear-runtime-config`, `delete` |
| `mcp-servers` | `list`, `attach`, `sync`, `detach` (nested under a toolset) |
| `triage` | `errors`, `status`, `run`, `metrics`, `resource-status`, `org-metrics`, `user-metrics`, `notifications`, `search`, `logs`, `quarantine` — flow/log triage via the Nexla monitoring MCP server, not the main API |
| `context` | `get` |
| `orgs` | `list`, `get` |
| `code-containers` | `list` |
| `metrics` | `catalog`, `for-resource`, `get` |
| `users` | `list`, `get` |
| `notifications` | `list` |

`code-containers`, `metrics`, `users`, and `notifications` proxy resources the API hasn't implemented yet (they return HTTP 501 until it does). `orgs get` (unlike `orgs list`) is also currently unimplemented, returning the same stub response for any id.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 2 | bad local input (validation, `--dry-run` failure) |
| 3 | `NEXLA_API_URL`/`NEXLA_TOKEN` not set |
| 4 | 401/403 from the API |
| 5 | 404 |
| 6 | 5xx from the API |

## License

MIT — see [LICENSE](LICENSE).
