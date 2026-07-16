#!/usr/bin/env python3
"""Detect drift between the vendored Nexla skill pack and its upstream source.

The pack under ``src/nexla_cli/skill_pack/{reference,examples}`` is vendored
from express-code's ``skills/nexla/{reference,examples}`` (see the pack's
``VENDORED_FROM.md``). A few vendored files are *intentionally* adapted for
standalone-CLI use (a leading blockquote note), so a naive diff against
upstream would always look "drifted".

To tell *intentional adaptation* apart from *upstream moved*, this script does
NOT diff the vendored copy against upstream directly. Instead it compares
upstream's **current** content against the **pristine upstream baseline hash**
recorded in ``VENDORED_FROM.md`` (the SHA-256 of each express file at the
moment it was vendored):

  - upstream hash == recorded baseline  -> upstream unchanged, our local
    adaptations are irrelevant  -> IN SYNC.
  - upstream hash != recorded baseline  -> upstream moved  -> DRIFT: the pack
    should be re-vendored and the baseline refreshed.

It also flags files that exist upstream but not in the baseline (upstream added
a file) or in the baseline but not upstream (upstream removed/renamed a file).

Usage:
    python scripts/check_skill_pack_drift.py /path/to/express-code
    EXPRESS_CODE_PATH=/path/to/express-code python scripts/check_skill_pack_drift.py

Exit codes: 0 = in sync, 1 = drift detected, 2 = usage/setup error.
"""

from __future__ import annotations

import hashlib
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PACK_DIR = REPO_ROOT / "src" / "nexla_cli" / "skill_pack"
MANIFEST = PACK_DIR / "VENDORED_FROM.md"
UPSTREAM_SUBPATH = Path("skills") / "nexla"
SUBDIRS = ("reference", "examples")

# Rows look like: | `reference/foo.md` | `<64-hex>` | verbatim / adapted (...) |
_ROW = re.compile(r"^\|\s*`([^`]+\.md)`\s*\|\s*`([0-9a-f]{64})`\s*\|\s*([^|]+?)\s*\|")


def _sha256(text: bytes) -> str:
    return hashlib.sha256(text).hexdigest()


def load_baseline() -> dict[str, tuple[str, bool]]:
    """Parse the manifest table → {relative-path: (baseline_sha, adapted)}.

    ``adapted`` is True when the "Adapted for standalone CLI" column is
    anything other than ``verbatim`` — those files intentionally differ
    from the upstream baseline (leading blockquote note), so their local
    copy is NOT expected to match ``baseline_sha``.
    """
    baseline: dict[str, tuple[str, bool]] = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        m = _ROW.match(line)
        if m:
            adapted = m.group(3).strip().lower() != "verbatim"
            baseline[m.group(1)] = (m.group(2), adapted)
    return baseline


def resolve_express(argv: list[str]) -> Path:
    raw = argv[1] if len(argv) > 1 else os.environ.get("EXPRESS_CODE_PATH")
    if not raw:
        sys.stderr.write(
            "error: pass an express-code checkout path as arg 1 "
            "or set EXPRESS_CODE_PATH.\n"
        )
        raise SystemExit(2)
    root = Path(raw).expanduser().resolve()
    nexla = root / UPSTREAM_SUBPATH
    if not nexla.is_dir():
        sys.stderr.write(f"error: {nexla} not found (is {root} an express-code checkout?).\n")
        raise SystemExit(2)
    return nexla


def main(argv: list[str]) -> int:
    if not MANIFEST.is_file():
        sys.stderr.write(f"error: manifest not found at {MANIFEST}.\n")
        return 2

    upstream_nexla = resolve_express(argv)
    baseline = load_baseline()
    if not baseline:
        sys.stderr.write(f"error: no baseline hashes parsed from {MANIFEST}.\n")
        return 2

    # Enumerate upstream files under reference/ + examples/.
    upstream: dict[str, str] = {}
    for sub in SUBDIRS:
        d = upstream_nexla / sub
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            rel = f"{sub}/{f.name}"
            upstream[rel] = _sha256(f.read_bytes())

    drifted: list[str] = []
    added = sorted(set(upstream) - set(baseline))
    removed = sorted(set(baseline) - set(upstream))
    for rel in sorted(set(baseline) & set(upstream)):
        if upstream[rel] != baseline[rel][0]:
            drifted.append(rel)

    # Local-copy integrity: a file marked "verbatim" must still match its
    # recorded baseline on disk. Catches a vendored file edited/corrupted
    # locally (or an "adapted" file mislabeled verbatim) — the manifest's
    # verbatim claim is otherwise never enforced. Adapted files are skipped
    # (they intentionally differ) but must at least still exist.
    local_bad: list[str] = []
    local_missing: list[str] = []
    for rel, (base_sha, adapted) in sorted(baseline.items()):
        local = PACK_DIR / rel
        if not local.is_file():
            local_missing.append(rel)
        elif not adapted and _sha256(local.read_bytes()) != base_sha:
            local_bad.append(rel)

    if not (drifted or added or removed or local_bad or local_missing):
        print(f"skill pack in sync with upstream ({len(baseline)} files checked).")
        return 0

    print("SKILL PACK DRIFT DETECTED")
    print(f"  upstream: {upstream_nexla}")
    for rel in drifted:
        print(f"  CHANGED upstream: {rel}")
        print(f"    baseline sha : {baseline[rel][0]}")
        print(f"    upstream sha : {upstream[rel]}")
    for rel in added:
        print(f"  ADDED upstream (not vendored): {rel}")
    for rel in removed:
        print(f"  REMOVED upstream (still vendored): {rel}")
    for rel in local_bad:
        print(f"  LOCAL COPY CHANGED (marked verbatim but differs from baseline): {rel}")
    for rel in local_missing:
        print(f"  LOCAL COPY MISSING (in manifest, absent from skill_pack/): {rel}")
    if drifted or added or removed:
        print(
            "\nUpstream moved. Re-vendor the changed files into "
            "src/nexla_cli/skill_pack/, re-apply the standalone adaptations, and "
            "refresh the baseline hashes + commit/branch in VENDORED_FROM.md."
        )
    if local_bad or local_missing:
        print(
            "\nLocal pack no longer matches the manifest. Restore the file from "
            "upstream (or, if the edit was intentional, mark it 'adapted' in "
            "VENDORED_FROM.md)."
        )
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
