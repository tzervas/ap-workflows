#!/usr/bin/env python3
"""Fail if .github workflows/actions use a uses: ref that drifts from pins/actions.yml."""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "pins" / "actions.yml"


def load_pins() -> dict[str, str]:
    text = PINS.read_text(encoding="utf-8")
    actions: dict[str, str] = {}
    in_actions = False
    for line in text.splitlines():
        if line.strip().startswith("actions:"):
            in_actions = True
            continue
        if not in_actions:
            continue
        if line.strip().startswith("#") or not line.strip():
            continue
        if re.match(r"^[A-Za-z]", line):
            break
        m = re.match(r"^\s+([A-Za-z0-9_./-]+):\s+(\S+)", line)
        if m:
            actions[m.group(1)] = m.group(2)
    return actions


def major_of(ref: str) -> str:
    if ref in {"master", "main"}:
        return ref
    m = re.match(r"v(\d+)", ref)
    if m:
        return f"v{m.group(1)}"
    return ref


def main() -> int:
    pins = load_pins()
    if not pins:
        print("::error::no pins loaded from", PINS)
        return 2
    bad: list[str] = []
    for path in list((ROOT / ".github").rglob("*.yml")) + list(
        (ROOT / ".github").rglob("*.yaml")
    ):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            m = re.search(r"uses:\s*([^\s#]+)", line)
            if not m:
                continue
            u = m.group(1).strip().strip("\"'`")
            if not u or u.startswith("./") or u.startswith("docker://"):
                continue
            if u.startswith("tzervas/ap-workflows"):
                continue
            if "@" not in u:
                bad.append(f"{path.relative_to(ROOT)}:{i}: missing @ref: {u}")
                continue
            action, ref = u.rsplit("@", 1)
            if action not in pins:
                bad.append(
                    f"{path.relative_to(ROOT)}:{i}: action not in pins/actions.yml: {action}@{ref}"
                )
                continue
            want = pins[action]
            if ref != want and major_of(ref) != major_of(want):
                bad.append(
                    f"{path.relative_to(ROOT)}:{i}: {action}@{ref} does not match pin {want}"
                )
    if bad:
        print("::error::action pin drift detected")
        for b in bad:
            print(b)
        return 1
    print(f"ok: {len(pins)} pins; all workflow uses: match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
