#!/usr/bin/env python3
"""Expand a control-panel scope name into a JSON array of repo full-names.

Kept as data + one function so the control panel, the rollout script, and any
future tooling agree on what "stdlib" means instead of each hardcoding a list.
"""
import json
import sys

COMPILER_CORE = [
    "mycelium-core",
    "mycelium-value",
    "mycelium-runtime",
    "mycelium-codegen",
    "mycelium-l1",
]

STDLIB = [
    "mycelium-std-cmp", "mycelium-std-collections", "mycelium-std-conformance",
    "mycelium-std-content", "mycelium-std-core", "mycelium-std-dense",
    "mycelium-std-diag", "mycelium-std-error", "mycelium-std-fmt",
    "mycelium-std-fs", "mycelium-std-io", "mycelium-std-iter",
    "mycelium-std-math", "mycelium-std-numerics", "mycelium-std-rand",
    "mycelium-std-recover", "mycelium-std-runtime", "mycelium-std-select",
    "mycelium-std-spore", "mycelium-std-swap", "mycelium-std-sys",
    "mycelium-std-sys-host", "mycelium-std-ternary", "mycelium-std-testing",
    "mycelium-std-text", "mycelium-std-time", "mycelium-std-vsa",
]

TOOLING = [
    "mycelium-bench", "mycelium-build", "mycelium-check", "mycelium-cli",
    "mycelium-cli-common", "mycelium-doc", "mycelium-fmt", "mycelium-lint",
    "mycelium-lsp", "mycelium-proj", "mycelium-sec", "mycelium-spore",
    "mycelium-transpile",
]

UMBRELLA = ["mycelium-lang"]

SCOPES = {
    "compiler-core": COMPILER_CORE,
    "stdlib": STDLIB,
    "tooling": TOOLING,
    "umbrella": UMBRELLA,
    "all": COMPILER_CORE + STDLIB + TOOLING + UMBRELLA,
}


def expand(scope: str, owner: str = "tzervas") -> list[str]:
    if scope not in SCOPES:
        raise KeyError(f"unknown scope {scope!r}; known: {', '.join(sorted(SCOPES))}")
    return [f"{owner}/{r}" for r in SCOPES[scope]]


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"usage: scope.py <{'|'.join(sorted(SCOPES))}>", file=sys.stderr)
        sys.exit(2)
    try:
        print(json.dumps(expand(sys.argv[1])))
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
