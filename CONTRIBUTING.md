# Contributing

Thanks for your interest in contributing to `nexla-cli`
(https://github.com/nexla-opensource/nexla-agent-cli).

## Development setup

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency and
environment management. Install `uv`, then install the project with the `dev`
extra:

```bash
uv sync --extra dev
```

The CLI is exposed as the `nexla-cli` command. Run it from the checkout with:

```bash
uv run nexla-cli --help
```

## Running the gates

All of the following must pass before a change can merge. They are the same
checks CI runs:

```bash
uv run --extra dev pytest -q     # tests
uv run --extra dev ruff check .  # lint
uv run --extra dev mypy src      # type check
```

## Branch and PR conventions

- Branch off `main` and open a pull request against `main`.
- Keep pull requests focused; describe what changed and why.
- Add or update tests for behavior changes.
- Update `CHANGELOG.md` for user-visible changes.
- **CI must pass** (tests, lint, and type check on all supported Python
  versions) before a pull request will be merged.

## Reporting bugs and security issues

- File bugs and feature requests as GitHub issues.
- **Do not** report security vulnerabilities in public issues; see
  [SECURITY.md](SECURITY.md).

By contributing, you agree that your contributions are licensed under the
project's [MIT License](LICENSE).
