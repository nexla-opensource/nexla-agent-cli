"""Guard: pyproject.toml and npm/package.json versions must stay in lockstep.

The npm installer derives the GitHub release tag from package.json's version,
so any drift from the Python package version causes 404s when downloading the
prebuilt binary at install time. This test fails loudly if they diverge.
"""

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_and_npm_versions_match() -> None:
    pyproject = tomllib.loads(
        (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_json = json.loads(
        (REPO_ROOT / "npm" / "package.json").read_text(encoding="utf-8")
    )

    py_version = pyproject["project"]["version"]
    npm_version = package_json["version"]

    assert py_version == npm_version, (
        f"Version drift: pyproject.toml is {py_version!r} but "
        f"npm/package.json is {npm_version!r}. These must match so the npm "
        f"installer resolves the correct GitHub release tag."
    )
