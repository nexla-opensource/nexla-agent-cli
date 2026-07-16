# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.1]

Documentation-only release (refreshes the npm package page).

- Lead the install docs with the PyPI/uv path (no install script).
- Scope the npm badges and install commands to `@nexla/nexla-cli` in both
  READMEs.
- Correct the npm 11 install-script note: npm warns but still runs the
  postinstall, so the CLI works after a plain `npm i -g`.

## [0.3.0]

Initial public release under the Nexla open-source organization.

- Renamed the command and package to `nexla-cli`.
- Hardened the machine-facing contract for stable, scriptable output.
- Added sink preflight validation before mutating calls.
- Distributed via npm and prebuilt native binaries (GitHub Releases), in
  addition to PyPI.

[0.3.1]: https://github.com/nexla-opensource/nexla-agent-cli/releases/tag/v0.3.1
[0.3.0]: https://github.com/nexla-opensource/nexla-agent-cli/releases/tag/v0.3.0
