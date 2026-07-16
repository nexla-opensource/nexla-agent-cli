# nexla-cli

[![npm version](https://img.shields.io/npm/v/@nexla/nexla-cli.svg)](https://www.npmjs.com/package/@nexla/nexla-cli)
[![npm downloads](https://img.shields.io/npm/dm/@nexla/nexla-cli.svg)](https://www.npmjs.com/package/@nexla/nexla-cli)
[![PyPI](https://img.shields.io/pypi/v/nexla-cli.svg?label=PyPI)](https://pypi.org/project/nexla-cli/)
[![License: MIT](https://img.shields.io/npm/l/@nexla/nexla-cli.svg)](https://github.com/nexla-opensource/nexla-agent-cli/blob/main/LICENSE)

Command-line client for the [Nexla](https://nexla.com) agent API — list,
inspect, and build data pipelines straight from a shell or an agent
environment, without writing a line of code: sources, sinks, nexsets,
credentials, flows, transforms, toolsets, and MCP servers.

This package installs a **prebuilt native binary** — no Python interpreter
required on the machine running it. Prefer a Python-native install
instead? See [`nexla-cli` on PyPI](https://pypi.org/project/nexla-cli/).

## Install

```bash
npm install -g @nexla/nexla-cli
```

Or run it once-off with no global install:

```bash
npx @nexla/nexla-cli sources list
```

`postinstall` (`scripts/install.js`) downloads the binary matching your
OS/architecture from the matching GitHub release; `bin/nexla.js` execs it
and forwards argv/stdio/exit code transparently — you get a real,
statically-linked binary, not a Python subprocess.

| Platform | Support |
|---|:---:|
| macOS (Apple Silicon) | ✅ `darwin-arm64` |
| Linux (x64) | ✅ `linux-x64` |
| Windows (x64) | ✅ `win32-x64` |

The supported platform list is enforced by `scripts/install.js` (its
`ASSETS` map is the single source of truth). `package.json` deliberately
omits `os`/`cpu` fields: those advertise a Cartesian product of every
listed OS × CPU, which would wrongly pass npm's gate for combinations we
don't actually publish binaries for (e.g. `darwin-x64`, `linux-arm64`).
`install.js` fails with a clear, accurate message on an unsupported
platform instead.

## Quick start

```bash
export NEXLA_API_URL=https://<your-deployed-api>
export NEXLA_TOKEN=$(nexla-cli login --service-key <your-service-key>)
nexla-cli sources list
```

`nexla-cli login` prints a bearer token to stdout only (safe for the command
substitution above) — everything else it reports goes to stderr.

## What you can do with it

```bash
nexla-cli connectors search shopify              # find a connector
nexla-cli credentials list --connector shopify_api
nexla-cli sources create --name my-source --connector shopify_api --credential-id 123 --dry-run
nexla-cli nexsets transform <parent_id> --name cleaned --language python --code '...'
nexla-cli sinks create --name my-sink --nexset-id <id> --connector supabase --config '{...}'
```

- **`--dry-run` on every mutating command** — a shallow structural lint of the
  request body (required fields present + top-level types) that fires nothing,
  before you touch anything real. The live API still fully validates on the real
  call.
- **`--json`/`--params` on every create/update command** — pass a raw
  request body alongside named flags, so you're never blocked waiting on
  a new flag to ship.
- **Agent-friendly output by default** — a human table on a TTY, JSON
  everywhere else (piped, scripted, or run by an agent).
- **Ships a [Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills)** —
  run `nexla-cli skill install` once and Claude Code picks up invariants an
  agent can't infer from `--help` alone.

See the [full command reference and design notes on
GitHub](https://github.com/nexla-opensource/nexla-agent-cli#readme) for
the complete picture: every resource and subcommand, exit codes, response
sanitization, and more.

## License

MIT
