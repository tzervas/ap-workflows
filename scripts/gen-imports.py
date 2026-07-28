#!/usr/bin/env python3
"""Regenerate terraform/imports.tf from the rulesets that currently exist.

Import blocks let `tofu plan` ADOPT live rulesets instead of trying to create
duplicates. Run this after any manual ruleset change, or when onboarding a new
repo, then confirm with `tofu plan` that it reports 0 to add / 0 to destroy.

    python3 scripts/gen-imports.py > terraform/imports.tf
    cd terraform && tofu plan

Usage: gen-imports.py [owner]     (default owner: tzervas)
"""

import json
import subprocess
import sys

OWNER = sys.argv[1] if len(sys.argv) > 1 else "tzervas"
UMBRELLA = "mycelium-lang"

# Same grouping the control panel and rollout use.
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from scope import expand  # noqa: E402


def rulesets(repo: str) -> list[dict]:
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{OWNER}/{repo}/rulesets"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return json.loads(r.stdout or "[]") if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return []


def address(repo: str, name: str) -> str | None:
    umbrella = repo == UMBRELLA
    if name == "protec-main":
        res = "umbrella_main" if umbrella else "component_main"
    elif name == "protec-dev":
        res = "umbrella_dev" if umbrella else "component_dev"
    else:
        return None
    return (
        f"github_repository_ruleset.{res}"
        if umbrella
        else f'github_repository_ruleset.{res}["{repo}"]'
    )


def main() -> int:
    print("""# Generated import blocks so `tofu plan` ADOPTS the rulesets that already exist
# instead of trying to create duplicates. Regenerate after any manual change:
#   python3 ../scripts/gen-imports.py > imports.tf
#
# Verify with `tofu plan`: a correct adoption shows "0 to add, 0 to destroy".
# Anything else means the code and the live state disagree — investigate before
# applying, do not just accept the diff.
""")
    n = 0
    for full in expand("all", OWNER):
        repo = full.split("/", 1)[1]
        for rs in rulesets(repo):
            addr = address(repo, rs["name"])
            if not addr:
                continue
            print(f'import {{\n  to = {addr}\n  id = "{repo}:{rs["id"]}"\n}}\n')
            n += 1
    print(f"# {n} import blocks", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
