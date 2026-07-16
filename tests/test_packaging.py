"""Regression guard: `AGENTS.md`/`SKILL.md` must ship inside the built wheel.

Confirmed empirically (2026-07-08) that hatchling's default
package-directory inclusion already ships both files with zero
`pyproject.toml` changes -- `[tool.hatch.build.targets.wheel]
packages = ["src/nexla_cli"]` is enough since both docs live directly
inside `src/nexla_cli/`. This test guards against that regressing (e.g. a
future `include`/`exclude` list added for another reason that
accidentally drops them).

Builds via `uv build` (this repo's existing build tool, confirmed present
in dev workflows) rather than installing the separate PyPI `build`
package as a new dev dependency -- `uv` already provides an equivalent
build frontend. Skips gracefully if `uv` isn't on PATH.
"""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed; cannot build a wheel")
def test_docs_ship_in_wheel(tmp_path: Path) -> None:
    out_dir = tmp_path / "dist"
    result = subprocess.run(
        ["uv", "build", "--out-dir", str(out_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.skip(f"uv build failed in this environment: {result.stderr[-2000:]}")

    wheels = list(out_dir.glob("*.whl"))
    assert wheels, f"no wheel produced in {out_dir}"

    with zipfile.ZipFile(wheels[0]) as z:
        names = set(z.namelist())

    assert "nexla_cli/AGENTS.md" in names
    assert "nexla_cli/SKILL.md" in names
