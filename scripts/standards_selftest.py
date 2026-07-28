#!/usr/bin/env python3
"""Self-test for `standards_check.py` — proves each rule fires, and stays quiet when clean.

Why a self-test and not just "we ran it once": every rule here exists because the fleet paid
for the failure it detects, and a rule that silently stops firing is worse than no rule —
it is a gate that is off while looking on, which is the exact failure mode the contract
names. This asserts both directions for every rule: the dirty fixture produces the finding,
and the clean fixture produces nothing.

Run it::

    python3 scripts/standards_selftest.py

Exit 0 means every rule fired on its fixture and no rule fired on the clean one. Network is
never touched: the GitHub API calls in the checker are given an unreachable API base, and
the rules that depend on them are asserted to report UNKNOWN rather than a quiet pass.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "standards_check.py"

CLEAN_WORKFLOW = """\
name: ci
on:
  pull_request:
    branches: [dev]
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
permissions:
  contents: read
jobs:
  test:
    name: test
    runs-on: [self-hosted, linux, x64, podman]
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - name: pytest
        run: |
          set -euo pipefail
          python3 - <<'PY'
          print("indented heredoc: the terminator below is inside the block scalar")
          PY
          pytest -q
"""


def sh(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=str(cwd), capture_output=True, text=True, check=False
    )


def make_repo(root: Path, files: dict[str, str], with_dev: bool = True) -> None:
    """Write files and make `root` a git repo with an origin/main, optionally origin/dev.

    Why a real git repo: the trunk-divergence and branch-targeting rules shell out to git,
    and a fake would only prove the fake works. `with_dev=False` covers the repo that has no
    integration branch at all — where "feature PRs must target dev" has no valid target and
    must therefore report EMPTY rather than red.
    """
    for name, body in files.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@e",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@e",
    }
    os.environ.update(env)
    sh(["git", "init", "-q", "-b", "main"], root)
    sh(["git", "add", "-A"], root)
    sh(["git", "commit", "-qm", "chore: fixture"], root)
    # A self-referential remote gives origin/main and origin/dev without a network.
    sh(["git", "remote", "add", "origin", str(root)], root)
    if with_dev:
        sh(["git", "branch", "-f", "dev", "main"], root)
    sh(["git", "fetch", "-q", "origin"], root)


def run_checker(root: Path, event: dict | None, **modes: str) -> tuple[int, str]:
    env = dict(os.environ)
    env.update(
        {
            "STD_REPO_ROOT": str(root),
            "GITHUB_REPOSITORY": "tzervas/fixture",
            "GITHUB_EVENT_NAME": "pull_request" if event else "push",
            # Unreachable on purpose: no network in the self-test, and the checker must
            # report UNKNOWN rather than assume anything about repo settings.
            "GITHUB_API_URL": "http://127.0.0.1:1",
            "GITHUB_TOKEN": "",
            "STD_TOKEN": "",
        }
    )
    env.pop("GITHUB_STEP_SUMMARY", None)
    if event:
        ev = root / "_event.json"
        ev.write_text(json.dumps(event), encoding="utf-8")
        env["GITHUB_EVENT_PATH"] = str(ev)
    else:
        env.pop("GITHUB_EVENT_PATH", None)
    for k, v in modes.items():
        env[f"STD_MODE_{k.upper().replace('-', '_')}"] = v
    p = subprocess.run(
        [sys.executable, str(CHECKER)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return p.returncode, p.stdout + p.stderr


def pr_event(
    base: str = "dev",
    head: str = "feat/x",
    title: str = "feat: a thing",
    labels: list[str] | None = None,
    auto: str | None = None,
) -> dict:
    return {
        "pull_request": {
            "number": 1,
            "title": title,
            "labels": [{"name": n} for n in (labels or [])],
            "base": {"ref": base, "sha": ""},
            "head": {"ref": head, "sha": ""},
            "auto_merge": {"merge_method": auto} if auto else None,
        }
    }


FAILURES: list[str] = []
PASSES = 0


def expect(name: str, out: str, needle: str, present: bool = True) -> None:
    global PASSES
    ok = (needle in out) if present else (needle not in out)
    if ok:
        PASSES += 1
        print(f"  ok    {name}")
    else:
        FAILURES.append(name)
        print(
            f"  FAIL  {name}: expected {'to find' if present else 'NOT to find'} "
            f"{needle!r}"
        )


def expect_rc(name: str, rc: int, want: int, out: str = "") -> None:
    """Assert the process exit code. The exit code is the only thing GitHub reads."""
    global PASSES
    ok = (rc == want) if want == 0 else (rc != 0)
    if ok:
        PASSES += 1
        print(f"  ok    {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL  {name}: rc={rc}\n{out[-3000:]}")


def case(
    title: str,
    files: dict[str, str],
    event: dict | None,
    checks,
    with_dev: bool = True,
    **modes: str,
) -> None:
    print(f"\n== {title}")
    tmp = Path(tempfile.mkdtemp(prefix="std-selftest-"))
    try:
        make_repo(tmp, files, with_dev=with_dev)
        rc, out = run_checker(tmp, event, **modes)
        checks(rc, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    base_files = {
        ".github/workflows/ci.yml": CLEAN_WORKFLOW,
        ".cz.toml": '[tool.commitizen]\nversion = "0.1.0"\n',
        "VERSION": "0.1.0\n",
        "README.md": "# fixture\n",
    }

    # --- clean baseline: everything on, nothing found ---------------------------------
    def clean(rc: int, out: str) -> None:
        expect_rc("clean: rc==0", rc, 0, out)
        expect(
            "clean: every rule reported that it checked something", out, "  checked:"
        )
        expect("clean: no error annotations", out, "\n::error", present=False)
        expect("clean: no warning annotations", out, "\n::warning", present=False)

    case(
        "clean repo, every rule enforcing",
        base_files,
        pr_event(),
        clean,
        **{
            "version-drift": "enforce",
            "exit-contract": "enforce",
            "python-floor": "enforce",
            "docs-with-change": "off",
            "promote-merge-mode": "off",
        },
    )

    # --- rule 6: YAML validity, the column-0 heredoc trap -------------------------------
    broken = CLEAN_WORKFLOW.replace(
        "          python3 - <<'PY'\n          print(\"indented heredoc: the terminator "
        'below is inside the block scalar")\n          PY\n',
        "          python3 - <<'PY'\nprint(\"column zero\")\nPY\n",
    )

    def yaml_broken(rc: int, out: str) -> None:
        expect("yaml-validity fires", out, "standards/yaml-validity")
        expect(
            "yaml-validity is an error", out, "::error title=standards/yaml-validity"
        )
        expect("yaml-validity names the column-0 cause", out, "COLUMN 0")

    case(
        "workflow with a column-0 heredoc",
        {**base_files, ".github/workflows/ci.yml": broken},
        pr_event(),
        yaml_broken,
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    # --- rule 6b: heredoc opened and never closed --------------------------------------
    unterminated = CLEAN_WORKFLOW.replace("          PY\n", "")

    case(
        "unterminated heredoc",
        {**base_files, ".github/workflows/ci.yml": unterminated},
        pr_event(),
        lambda rc, out: expect(
            "unterminated heredoc fires", out, "unterminated heredoc"
        ),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    # --- rule 2: branch targeting -------------------------------------------------------
    case(
        "feature PR targeting main",
        base_files,
        pr_event(base="main", head="feat/x"),
        lambda rc, out: (
            expect("branch-targeting fires", out, "standards/branch-targeting"),
            expect(
                "branch-targeting is an error",
                out,
                "::error title=standards/branch-targeting",
            ),
            expect_rc("branch-targeting fails the job", rc, 1, out),
        ),
        **{
            "docs-with-change": "off",
            "promote-merge-mode": "off",
            "trunk-divergence": "off",
        },
    )

    case(
        "hotfix PR targeting main is allowed",
        base_files,
        pr_event(base="main", head="hotfix/urgent", title="fix: urgent"),
        lambda rc, out: expect(
            "hotfix allowed", out, "standards/branch-targeting", present=False
        ),
        **{
            "docs-with-change": "off",
            "promote-merge-mode": "off",
            "trunk-divergence": "off",
        },
    )

    case(
        "repo with no integration branch has no wrong target",
        base_files,
        pr_event(base="main", head="feat/x"),
        lambda rc, out: (
            expect_rc("no dev branch: rc==0", rc, 0, out),
            expect(
                "no dev branch: reported as empty, not red",
                out,
                "does not exist on origin",
            ),
        ),
        with_dev=False,
        **{
            "docs-with-change": "off",
            "promote-merge-mode": "off",
            "trunk-divergence": "off",
        },
    )

    # --- rule 1: promote merge mode -----------------------------------------------------
    case(
        "promote PR auto-merging with SQUASH",
        base_files,
        pr_event(base="main", head="dev", title="release: v0.1.1", auto="SQUASH"),
        lambda rc, out: (
            expect("promote squash fires", out, "auto-merge armed with SQUASH"),
            expect("promote message carries the measurement", out, "ace4fe3"),
            expect("promote message teaches the fix", out, "--merge"),
            expect(
                "unreachable API reports UNKNOWN, not a pass",
                out,
                "could not read repository merge settings",
            ),
        ),
        **{"docs-with-change": "off", "trunk-divergence": "off"},
    )

    case(
        "work-branch PR is never nagged about squash",
        base_files,
        pr_event(base="dev", head="feat/x"),
        lambda rc, out: expect(
            "no squash nag on the work edge",
            out,
            "standards/promote-merge-mode",
            present=False,
        ),
        **{"docs-with-change": "off", "trunk-divergence": "off"},
    )

    # --- rule 3: protected refs ---------------------------------------------------------
    force = CLEAN_WORKFLOW.replace(
        "          pytest -q\n", "          git push --force origin main\n"
    )
    case(
        "workflow force-pushes main",
        {**base_files, ".github/workflows/ci.yml": force},
        pr_event(),
        lambda rc, out: expect(
            "protected-refs fires", out, "::error title=standards/protected-refs"
        ),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    allowed = CLEAN_WORKFLOW.replace(
        "          pytest -q\n",
        "          git push --force origin HEAD:tmp/scratch  # standards-allow: "
        "protected-refs — disposable branch\n",
    )
    case(
        "suppression marker is honoured",
        {**base_files, ".github/workflows/ci.yml": allowed},
        pr_event(),
        lambda rc, out: expect(
            "suppressed force-push is silent",
            out,
            "standards/protected-refs",
            present=False,
        ),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    # --- rule 4: versioning -------------------------------------------------------------
    case(
        "repo declares 1.0.0 without authorization",
        {
            **base_files,
            "VERSION": "1.0.0\n",
            ".cz.toml": '[tool.commitizen]\nversion = "1.0.0"\n',
        },
        pr_event(),
        lambda rc, out: (
            expect(
                "version-policy fires", out, "::error title=standards/version-policy"
            ),
            expect("version-policy cites the label", out, "human-authorized-1x"),
        ),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    case(
        "1.0.0 with the human label is allowed",
        {
            **base_files,
            "VERSION": "1.0.0\n",
            ".cz.toml": '[tool.commitizen]\nversion = "1.0.0"\n',
        },
        pr_event(labels=["human-authorized-1x"]),
        lambda rc, out: expect(
            "label opens the 1.x gate", out, "standards/version-policy", present=False
        ),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    case(
        "manifest and .cz.toml disagree",
        {**base_files, "VERSION": "0.2.0\n"},
        pr_event(),
        lambda rc, out: expect("version-drift fires", out, "standards/version-drift"),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    # --- rule 5: exit contract ----------------------------------------------------------
    soft = CLEAN_WORKFLOW.replace(
        "          pytest -q\n", "          cargo geiger --output-format Json || true\n"
    )
    case(
        "gate swallows its failure",
        {**base_files, ".github/workflows/ci.yml": soft},
        pr_event(),
        lambda rc, out: (
            expect("exit-contract fires", out, "standards/exit-contract"),
            expect("exit-contract cites the measurement", out, "qlora-rs #27"),
        ),
        **{
            "exit-contract": "enforce",
            "docs-with-change": "off",
            "promote-merge-mode": "off",
        },
    )

    setuponly = CLEAN_WORKFLOW.replace(
        "          pytest -q\n",
        "          rustup component add rustfmt clippy 2>/dev/null || true\n"
        "          pytest -q\n",
    )
    case(
        "setup line with || true is not a gate",
        {**base_files, ".github/workflows/ci.yml": setuponly},
        pr_event(),
        lambda rc, out: expect(
            "no false positive on rustup", out, "standards/exit-contract", present=False
        ),
        **{
            "exit-contract": "enforce",
            "docs-with-change": "off",
            "promote-merge-mode": "off",
        },
    )

    # --- rule 7: scheduled + cancel-in-progress ------------------------------------------
    sched = CLEAN_WORKFLOW.replace(
        "on:\n  pull_request:\n    branches: [dev]\n",
        "on:\n  schedule:\n    - cron: '0 3 * * 1'\n",
    )
    case(
        "scheduled workflow cancels itself",
        {**base_files, ".github/workflows/ci.yml": sched},
        pr_event(),
        lambda rc, out: (
            expect(
                "schedule-cancel fires", out, "::error title=standards/schedule-cancel"
            ),
            expect(
                "schedule-cancel explains `cancelled` != `failed`", out, "not `failed`"
            ),
        ),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    # --- rule 8: python floor -------------------------------------------------------------
    old_py = CLEAN_WORKFLOW.replace('python-version: "3.13"', 'python-version: "3.9"')
    case(
        "python 3.9 in the matrix",
        {**base_files, ".github/workflows/ci.yml": old_py},
        pr_event(),
        lambda rc, out: expect("python-floor fires", out, "standards/python-floor"),
        **{
            "python-floor": "enforce",
            "docs-with-change": "off",
            "promote-merge-mode": "off",
        },
    )

    float_py = CLEAN_WORKFLOW.replace('python-version: "3.13"', "python-version: 3.10")
    case(
        "unquoted 3.10 becomes the float 3.1",
        {**base_files, ".github/workflows/ci.yml": float_py},
        pr_event(),
        lambda rc, out: expect("float python version fires", out, "parsed as a float"),
        **{
            "python-floor": "enforce",
            "docs-with-change": "off",
            "promote-merge-mode": "off",
        },
    )

    # --- rule 9: conventional title ---------------------------------------------------------
    case(
        "non-conventional PR title",
        base_files,
        pr_event(title="updated some stuff"),
        lambda rc, out: expect(
            "conventional-title fires",
            out,
            "::error title=standards/conventional-title",
        ),
        **{"docs-with-change": "off", "promote-merge-mode": "off"},
    )

    # --- driver: a bad mode value must refuse to run, not silently disable a rule ----------
    print("\n== bad mode value refuses to run")
    tmp = Path(tempfile.mkdtemp(prefix="std-selftest-"))
    try:
        make_repo(tmp, base_files)
        rc, out = run_checker(tmp, pr_event(), **{"yaml-validity": "enfroce"})
        expect("bad mode is rejected", out, "is not one of")
        expect_rc("bad mode fails the job", rc, 1, out)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{PASSES} assertion(s) passed, {len(FAILURES)} failed")
    for f in FAILURES:
        print(f"  FAILED: {f}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
