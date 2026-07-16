# Vendored Nexla skill pack

The `reference/` and `examples/` markdown in this directory is **vendored** —
copied from the canonical Nexla domain skill maintained in express-code. This
keeps one canonical domain source instead of two skills drifting apart. The
`nexla` CLI's own `SKILL.md` + `AGENTS.md` (one level up) are the thin
CLI-specific adapter that sits *on top* of this pack.

## Source

- Repo: `github.com/nexla/express-code`
- Path: `skills/nexla/` (the `reference/` and `examples/` subdirectories)
- Commit: `14b1a28485983005c46556a98d57d296febaa643`
- Branch: `feat/nexla-cli-phase-1b-2` (the pack is identical on `main`)

## Regenerate / check for drift

Run `scripts/check_skill_pack_drift.py` (from the repo root) against a local
express-code checkout:

```bash
EXPRESS_CODE_PATH=/path/to/express-code python scripts/check_skill_pack_drift.py
# or: python scripts/check_skill_pack_drift.py /path/to/express-code
```

## How drift detection works (and how it tolerates our adaptations)

A few vendored files were **lightly adapted** for standalone-CLI use (see the
table below) — they add a leading blockquote note mapping the express-sandbox
surface (`connect_oauth_credential`, `upload_files_to_sandbox`, the
`nexla-monitoring` MCP tools, `/workspace` paths, the `nexla-token` shim) onto
standalone `nexla` CLI commands. The **domain knowledge** (connector configs,
Quartz cron, probe shapes, transform rules, iteration types) is kept verbatim
because it is API-accurate regardless of install.

So a naive `diff` of the vendored copy against upstream would always show our
intentional adaptations as "drift". To separate *intentional adaptation* from
*upstream moved*, the checker compares upstream's **current** content against
the **pristine upstream baseline hash** recorded below — the SHA-256 of each
express file at the moment it was vendored. If upstream's current hash matches
the baseline, upstream has **not** moved and our local adaptations are ignored.
If it differs, upstream moved and the checker reports the change so the pack can
be re-synced (and this manifest's hashes + the adaptation notes refreshed).

When you intentionally re-vendor from a newer express commit, update the
`Commit`/`Branch` above and regenerate the baseline hashes:

```bash
cd /path/to/express-code/skills/nexla && shasum -a 256 reference/*.md examples/*.md
```

## Baseline (pristine upstream SHA-256, at the vendored commit)

| File | Upstream baseline SHA-256 | Adapted for standalone CLI |
|------|---------------------------|----------------------------|
| `reference/connectors.md` | `f5a3bf8189bf39b7b655c38627896ef57ad778185590126d28754a350872797a` | verbatim |
| `reference/credentials.md` | `7331137a94ebee977b6f5a4875b04df83396f4f6eae3d713ab20bc0762be4975` | adapted (OAuth / explore_credential sandbox note) |
| `reference/cron.md` | `7b5cfd5d01112dd4a36965269750dae8d1807141cefd908b06756a95af4d0858` | verbatim |
| `reference/flows.md` | `179a6c2eb1ca84a4ccad6da2980c18b8a0d22876d15ef18ad33439a8a0f7415f` | verbatim |
| `reference/monitoring.md` | `8a0b7107868d10bbc2ff7636e468195972fb0efec75a5b27fcc86f6bbf66ad84` | adapted (nexla-monitoring MCP → `nexla triage`) |
| `reference/rest-custom.md` | `293cc9c4fb81a2def90a0baa79c28e76396db0a992f41007a2fe70cbb603a572` | adapted (`/workspace` gcp-file note) |
| `reference/sinks.md` | `d6065d546e182c9c0f7bce6e74659915329d5e5133669ff01b190786f8145cf3` | verbatim |
| `reference/sources.md` | `844274f291381bc5c6065f6521bdba0165d614bbaef8a58823d748af93404ba6` | adapted (file-upload sandbox note) |
| `reference/toolsets.md` | `8b3a77fbe2c2e43e8b5ccb2ca862e1f114e29fbd9a1385a74a8b71ec271fa658` | adapted (CLI command-mapping note) |
| `reference/transforms.md` | `308e28b32b281db98ae32d58be5516309a6a6cfb2761e2d09ec2f2f68326200e` | verbatim |
| `examples/custom-rest-flow.md` | `e8aa6113f96f20ca9e243f9e47d935edffd1121f7a1ff7f0ddee33b04f03f266` | verbatim |
| `examples/nexset-to-mcp.md` | `1ae82c31eb868a70e0287450d3b994e736e5b6598b9ced0729efcbc2391a96f3` | verbatim |
| `examples/shopify-to-bigquery.md` | `96538056d069eb9b717d180a920fd1a8ce2c01968b6d1c7fa897422c4f5b67cf` | verbatim |
| `examples/webhook-source.md` | `a561412a24046a2a43499d633337b4f716445cc90808d2f8c72aa85c04c6de88` | verbatim |
