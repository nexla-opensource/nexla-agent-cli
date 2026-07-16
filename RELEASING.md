# Releasing

This repo ships to three places from one tag push: GitHub Releases (binaries),
PyPI (sdist/wheel), and npm (wrapper around the binaries). Maintainer-only —
none of this belongs in `README.md`/`npm/README.md`, since both render on
public package pages (PyPI's long description and the npm package page).

## Cutting a release

1. Bump the version in both `pyproject.toml` and `npm/package.json` (and run
   `uv lock` so `uv.lock` matches) — they must match, since
   `npm/scripts/install.js` derives the GitHub release tag it downloads from
   `npm/package.json`'s version.
2. `git tag vX.Y.Z && git push --tags`. This triggers two workflows:
   - `.github/workflows/release-binaries.yml` — three jobs: `build` (macOS
     arm64, Linux x64, Windows x64 via PyInstaller), `release` (attaches
     those binaries to a new GitHub Release), and `publish-npm` (`needs:
     release` — publishes the npm wrapper via Trusted Publishing, only
     *after* the binaries it depends on are actually live; publishing
     first would give anyone installing in that window a broken
     `postinstall`).
   - `.github/workflows/publish-pypi.yml` — builds the sdist+wheel and
     publishes to PyPI via Trusted Publishing (OIDC).

   Nothing else to run manually — both npm and PyPI publish automatically
   once the tag is pushed.

## One-time Trusted Publishing setup (repo owner only, once per registry)

Required once before the first release to each registry — see each
workflow's own comments for the exact steps (project/package name,
trusted-publisher owner/repo/workflow filename/environment), kept there
since they live right next to the `id-token: write` permission they
configure:
- PyPI: `.github/workflows/publish-pypi.yml`
- npm: the `publish-npm` job in `.github/workflows/release-binaries.yml`

## Binary release matrix

Supported platforms: `darwin-arm64`, `linux-x64`, `win32-x64` — see
`npm/scripts/install.js`'s `ASSETS` map. To support another platform, add an
entry there and a matching matrix row in `release-binaries.yml`.

Intel Mac (`macos-13`) was dropped from the matrix: GitHub's Intel-macOS
runner capacity is shrinking as it's phased out, and that job was sitting
queued 15+ minutes with zero progress while the other three platforms
finished in under 90s each. Re-add a `macos-13` row + a `darwin-x64` entry
in `ASSETS` if Intel Mac support is actually needed again.
