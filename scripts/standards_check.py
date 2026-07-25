#!/usr/bin/env python3
"""Fleet development-standards checker — the executable form of BRANCH-AND-RELEASE-CONTRACT.md.

Why this exists: a rule nobody can violate beats a rule everyone knows. Every rule below was
written *after* the fleet paid for it, and each failure message carries the measurement that
justifies it, because a check that fails with "policy violation" trains people to bypass it.

Design notes that are load-bearing:

* **Every finding says WHAT is wrong, WHY it matters, and HOW to fix it.** That is enforced by
  the `Finding` dataclass — you cannot construct one without all three.
* **EMPTY is not UNKNOWN.** Contract 4a. A rule that correctly determines there is nothing to
  check has *succeeded* and contributes no findings (exit 0). A rule that could not tell —
  the API call failed, git could not fetch, a parser blew up — emits an ``unknown`` finding,
  which is ALWAYS error-level even when the rule's mode is ``warn``. Collapsing "could not
  tell" into "no output, so pass" is exactly how a gate silently stops gating.
* **Modes are per-rule** (``enforce`` / ``warn`` / ``off``) so a repo adopts incrementally
  rather than all-or-nothing. A repo that must start at ``warn`` everywhere still gets the
  annotations; only the exit code changes.

Run standalone for local checking::

    python3 scripts/standards_check.py --repo-root . --event-name pull_request

Args are read from the environment (``STD_*`` variables) so the workflow can pass a dozen
toggles without a dozen CLI flags. See ``docs/STANDARDS.md``.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover - the workflow installs it first
    print("::error title=standards: PyYAML missing::The checker cannot parse workflows "
          "without PyYAML. This is UNKNOWN, not empty — refusing to report green. "
          "Fix: pip install pyyaml")
    sys.exit(2)

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None  # type: ignore[assignment]


# --------------------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------------------

ERROR = "error"
WARNING = "warning"
NOTICE = "notice"


@dataclass
class Finding:
    """One thing the checker has to say.

    Why all three of what/why/how are required: a message that only says what is wrong
    teaches the reader to route around the check rather than fix the cause. The fleet's
    own contract calls this out — see 5a on stale docs being worse than missing ones.

    Args:
        rule: Rule id, matching the workflow input that toggles it.
        title: One-line summary, used as the annotation title.
        what: The concrete observation. Include file/line/value.
        why: The consequence, with the measurement where one exists.
        how: A command or edit the reader can copy.
        file: Repo-relative path the annotation attaches to, if any.
        line: 1-based line, if known.
        unknown: True when the rule could not determine the answer. Always error-level.
        cap: Ceiling on the severity this finding may reach, regardless of the rule's
            mode. Why it exists: some findings inside an `enforce` rule are advisories —
            "dev is behind main" is worth saying and is not worth blocking a PR over.
            Without a cap, the only way to say them would be to weaken the whole rule.
    """

    rule: str
    title: str
    what: str
    why: str
    how: str
    file: str | None = None
    line: int | None = None
    unknown: bool = False
    cap: str | None = None

    def level(self, mode: str) -> str:
        """Resolve the annotation level for this finding under a rule mode.

        Why `unknown` ignores the mode: contract 4a says an unknown result must fail
        loudly and must never be a quiet pass. A warn-mode rule whose tool crashed is
        not a warning about the repo, it is a broken measurement.
        """
        if self.unknown:
            return ERROR
        lvl = ERROR if mode == "enforce" else WARNING
        order = {NOTICE: 0, WARNING: 1, ERROR: 2}
        if self.cap is not None and order[self.cap] < order[lvl]:
            return self.cap
        return lvl


@dataclass
class RuleResult:
    findings: list[Finding] = field(default_factory=list)
    # Free-text lines describing what the rule *did* check, so an empty result is
    # visibly "checked and clean" rather than "did not run".
    checked: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

MODES = ("enforce", "warn", "off")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_list(name: str, default: str = "") -> list[str]:
    raw = env(name, default)
    return [p.strip() for p in raw.split(",") if p.strip()]


def env_mode(name: str, default: str) -> str:
    v = env(name, default).lower() or default
    if v not in MODES:
        # A typo'd mode must not silently disable a rule.
        raise SystemExit(
            f"::error title=standards: bad mode::{name}={v!r} is not one of {MODES}. "
            "Refusing to run rather than silently disabling a rule."
        )
    return v


@dataclass
class Config:
    repo_root: Path
    event_name: str
    event: dict[str, Any]
    repo_slug: str
    token: str
    trunk_branches: list[str]
    integration_branch: str
    release_branch: str
    main_allowed_heads: list[str]
    python_min: tuple[int, int]
    one_x_label: str
    commit_types: list[str]
    modes: dict[str, str]

    @property
    def pr(self) -> dict[str, Any] | None:
        pr = self.event.get("pull_request")
        return pr if isinstance(pr, dict) else None

    @property
    def pr_labels(self) -> set[str]:
        pr = self.pr
        if not pr:
            return set()
        return {str(x.get("name", "")).lower() for x in pr.get("labels") or []}


RULE_DEFAULTS = {
    # objective, mechanical, cheap to fix -> enforce
    "yaml-validity": "enforce",
    "promote-merge-mode": "enforce",
    "branch-targeting": "enforce",
    "protected-refs": "enforce",
    "trunk-divergence": "enforce",
    "version-policy": "enforce",
    "schedule-cancel": "enforce",
    "conventional-title": "enforce",
    # judgement involved, or likely to trip on pre-existing state -> warn
    "version-drift": "warn",
    "exit-contract": "warn",
    "python-floor": "warn",
    "docs-with-change": "warn",
    # needs a binary that may not be on the runner -> opt in
    "actionlint": "off",
}


def load_config() -> Config:
    root = Path(env("STD_REPO_ROOT", ".")).resolve()
    event: dict[str, Any] = {}
    ev_path = env("GITHUB_EVENT_PATH")
    if ev_path and Path(ev_path).is_file():
        try:
            event = json.loads(Path(ev_path).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:  # unknown, not empty
            print(f"::warning title=standards::could not read GITHUB_EVENT_PATH: {exc}")
    pymin = env("STD_PYTHON_MIN", "3.11")
    try:
        maj, mino = (int(x) for x in pymin.split(".")[:2])
    except ValueError:
        raise SystemExit(f"::error::STD_PYTHON_MIN={pymin!r} is not MAJOR.MINOR")
    return Config(
        repo_root=root,
        event_name=env("GITHUB_EVENT_NAME", "unknown"),
        event=event,
        repo_slug=env("GITHUB_REPOSITORY"),
        token=env("STD_TOKEN") or env("GITHUB_TOKEN"),
        trunk_branches=env_list("STD_TRUNK_BRANCHES", "main,dev,sec"),
        integration_branch=env("STD_INTEGRATION_BRANCH", "dev"),
        release_branch=env("STD_RELEASE_BRANCH", "main"),
        main_allowed_heads=env_list(
            "STD_MAIN_ALLOWED_HEADS", "dev,sec,release/**,hotfix/**,revert-*"
        ),
        python_min=(maj, mino),
        one_x_label=env("STD_ONE_X_LABEL", "human-authorized-1x").lower(),
        commit_types=env_list(
            "STD_COMMIT_TYPES",
            "feat,fix,docs,style,refactor,perf,test,build,ci,chore,revert,merge,release",
        ),
        modes={k: env_mode(f"STD_MODE_{k.upper().replace('-', '_')}", v)
               for k, v in RULE_DEFAULTS.items()},
    )


# --------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------

def run(args: Sequence[str], cwd: Path, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=str(cwd), capture_output=True, text=True, check=check
    )


def workflow_files(root: Path) -> list[Path]:
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        return []
    return sorted(p for p in wf.iterdir()
                  if p.is_file() and p.suffix in (".yml", ".yaml"))


def rel(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root))
    except ValueError:
        return str(p)


_PARSE_CACHE: dict[Path, tuple[dict[str, Any] | None, str | None]] = {}


def parse_workflow(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    """Parse a workflow, returning (doc, error_message).

    Why cached: five rules need the same parse and re-reading is the sort of thing that
    quietly turns a 10-second lint job into a minute on a micro runner.
    """
    if path in _PARSE_CACHE:
        return _PARSE_CACHE[path]
    try:
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        out = (doc if isinstance(doc, dict) else None,
               None if isinstance(doc, dict) else "top level is not a mapping")
    except yaml.YAMLError as exc:
        out = (None, str(exc))
    except OSError as exc:
        out = (None, f"unreadable: {exc}")
    _PARSE_CACHE[path] = out
    return out


def iter_steps(doc: dict[str, Any]) -> Iterable[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Yield (job_id, job, step) for every step in a parsed workflow."""
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict):
                yield str(job_id), job, step


def find_line(path: Path, needle: str, start: int = 0) -> int | None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for i, ln in enumerate(lines[start:], start=start + 1):
        if needle in ln:
            return i
    return None


def matches_any(value: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(value, pat) for pat in patterns)


# --------------------------------------------------------------------------------------
# Rule 1 — promote merge mode (the highest-value check)
# --------------------------------------------------------------------------------------

SQUASH_DAMAGE = (
    "Squashing the promote rewrites it into a NEW commit with no ancestry link, so `main` "
    "and `dev` end up with IDENTICAL TREES AND DISJOINT HISTORIES. Git then has no merge "
    "base between them, and every PR later retargeted at `dev` renders thousands of lines "
    "of already-merged work as conflict. Measured on this fleet from exactly this cause: "
    "gha-runner-ctl merge base stuck at ace4fe3 with ~3,600 lines of phantom diff; "
    "tg-agent-relay `dev` 17 commits / ~5,700 lines behind with ZERO unique content; "
    "four ML-rust repos left 14 PRs DIRTY, unable even to produce a merge ref. "
    "A merge commit costs one graph node and buys a true merge base forever — and that "
    "merge base is what lets parallel branches touching disjoint files merge cleanly "
    "instead of every branch conflicting with every other."
)


def github_api(cfg: Config, path: str) -> tuple[Any | None, str | None]:
    """GET a GitHub API path. Returns (payload, error). Error means UNKNOWN, not empty."""
    base = env("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    req = urllib.request.Request(f"{base}/{path.lstrip('/')}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if cfg.token:
        req.add_header("Authorization", f"Bearer {cfg.token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed https base
            return json.loads(resp.read().decode("utf-8")), None
    except (urllib.error.URLError, ValueError, OSError) as exc:
        return None, str(exc)


def ancestry_critical_edge(cfg: Config, base: str, head: str) -> str | None:
    """Name the ancestry-critical edge this PR sits on, or None.

    Why back-merges count too: contract 1 says `main` -> `dev`/`sec` is "merge, never reset
    or force". A squashed back-merge destroys the ancestry link in the same way a squashed
    promote does — same mechanism, same measured damage.
    """
    if base == cfg.release_branch and head == cfg.integration_branch:
        return "promote"
    if head == cfg.release_branch and base in (cfg.integration_branch, "sec"):
        return "back-merge"
    return None


def rule_promote_merge_mode(cfg: Config) -> RuleResult:
    res = RuleResult()
    pr = cfg.pr
    if not pr:
        res.checked.append("not a pull_request event — nothing to check (empty, not unknown)")
        return res
    base = str(pr.get("base", {}).get("ref", ""))
    head = str(pr.get("head", {}).get("ref", ""))
    edge = ancestry_critical_edge(cfg, base, head)
    if edge is None:
        res.checked.append(
            f"`{head}` -> `{base}` is a work-branch edge. Squash is the fleet standard here "
            "(contract 1) and is not flagged."
        )
        return res

    res.checked.append(f"`{head}` -> `{base}` is the **{edge}** edge — merge commit required.")

    # (a) auto-merge armed with the wrong method is a machine that will do the damage.
    auto = pr.get("auto_merge")
    if isinstance(auto, dict):
        method = str(auto.get("merge_method", "")).upper()
        if method and method != "MERGE":
            res.findings.append(Finding(
                rule="promote-merge-mode",
                title=f"auto-merge armed with {method} on the {edge} PR",
                what=(f"This PR is `{head}` -> `{base}` (the {edge} edge) and auto-merge is "
                      f"armed with merge_method={method}. When checks go green GitHub will "
                      f"{method.lower()} it without a human in the loop."),
                why=SQUASH_DAMAGE,
                how=(f"gh pr merge {pr.get('number')} --disable-auto\n"
                     f"gh pr merge {pr.get('number')} --merge --auto   # re-arm with a merge commit"),
            ))
        else:
            res.checked.append("auto-merge is armed with a merge commit — correct.")

    # (b) if the repo forbids merge commits, the correct button does not exist.
    data, err = github_api(cfg, f"repos/{cfg.repo_slug}")
    if err is not None or not isinstance(data, dict):
        res.findings.append(Finding(
            rule="promote-merge-mode",
            title="could not read repository merge settings",
            what=(f"GET /repos/{cfg.repo_slug} failed: {err}. The checker cannot tell whether "
                  "merge commits are allowed on this repo."),
            why=("This is UNKNOWN, not empty. Contract 4a: a result the checker could not "
                 "determine must fail loudly rather than pass quietly, because a gate that "
                 "cannot measure is a gate that is off while looking on."),
            how=("Give the workflow token `contents: read` on this repository, or pass a token "
                 "with repo metadata read via the `token` secret of the reusable workflow."),
            unknown=True,
        ))
        return res

    # A read-scoped token gets the repository object WITHOUT the `allow_*` merge fields.
    # Absent is not False: reporting "merge commits are disabled" because the token could not
    # see the setting is exactly the false alarm that trains people to ignore this check.
    if "allow_merge_commit" not in data:
        res.checked.append(
            "the workflow token cannot see this repo's merge-method settings (the `allow_*` "
            "fields are omitted for read-scoped tokens) — settings not asserted either way. "
            "Pass a token with repo admin read via the `token` secret to enable that half of "
            "this rule.")
        allow_merge, allow_squash, allow_rebase = True, True, False
    else:
        allow_merge = bool(data.get("allow_merge_commit"))
        allow_squash = bool(data.get("allow_squash_merge"))
        allow_rebase = bool(data.get("allow_rebase_merge"))
        res.checked.append(
            f"repo merge methods: merge={allow_merge} squash={allow_squash} rebase={allow_rebase}"
        )

    if not allow_merge:
        res.findings.append(Finding(
            rule="promote-merge-mode",
            title="merge commits are disabled — this PR cannot be merged correctly",
            what=(f"`{cfg.repo_slug}` has allow_merge_commit=false, so the only buttons on this "
                  f"{edge} PR are squash and/or rebase. Both rewrite the commit."),
            why=SQUASH_DAMAGE,
            how=(f"The operator must run:\n"
                 f"  gh api -X PATCH repos/{cfg.repo_slug} -F allow_merge_commit=true\n"
                 "This check does not change repository settings itself."),
        ))

    if allow_rebase:
        res.findings.append(Finding(
            rule="promote-merge-mode",
            title="rebase merging is enabled and also breaks the ancestry link",
            what=(f"`{cfg.repo_slug}` has allow_rebase_merge=true. Rebase replays `dev`'s commits "
                  f"onto `{cfg.release_branch}` as new objects — the same disjoint-history outcome "
                  "as squash, reached a different way."),
            why=SQUASH_DAMAGE,
            how=(f"gh api -X PATCH repos/{cfg.repo_slug} -F allow_rebase_merge=false\n"
                 "Squash stays enabled: it is the correct mode for work-branch -> dev."),
        ))

    # Teaching notice, always, on every ancestry-critical PR.
    res.findings.append(Finding(
        rule="promote-merge-mode",
        title=f"merge this {edge} with a MERGE COMMIT",
        what=(f"`{head}` -> `{base}` must land as a merge commit. Squash is enabled repo-wide "
              "because work-branch -> dev needs it, and GitHub has no per-branch merge-method "
              "setting — so on this edge the button choice is the only thing standing between "
              "the fleet and a disjoint history."),
        why=SQUASH_DAMAGE,
        how=(f"gh pr merge {pr.get('number')} --merge\n"
             "or press \"Create a merge commit\" — NOT \"Squash and merge\"."),
        # Informational by construction: this fires on every correct promote too, and a
        # rule that fails the PR it is only teaching would get switched off.
        cap=NOTICE,
    ))
    return res


# --------------------------------------------------------------------------------------
# Rule 2 — branch targeting
# --------------------------------------------------------------------------------------

def rule_branch_targeting(cfg: Config) -> RuleResult:
    res = RuleResult()
    pr = cfg.pr
    if not pr:
        res.checked.append("not a pull_request event — nothing to check")
        return res
    base = str(pr.get("base", {}).get("ref", ""))
    head = str(pr.get("head", {}).get("ref", ""))

    if base not in cfg.trunk_branches:
        res.checked.append(f"base `{base}` is not a trunk branch — stacked PR, allowed.")
        return res
    if base == cfg.integration_branch:
        res.checked.append(f"base `{base}` is the integration branch — correct target.")
        return res
    if base != cfg.release_branch:
        res.checked.append(f"base `{base}` is a trunk branch other than "
                           f"`{cfg.release_branch}` — not governed by this rule.")
        return res

    labels = cfg.pr_labels
    exempt_labels = {"hotfix", "promote", "release"}
    if labels & exempt_labels:
        res.checked.append(
            f"base `{base}` allowed by label {sorted(labels & exempt_labels)}.")
        return res
    if matches_any(head, cfg.main_allowed_heads):
        res.checked.append(f"head `{head}` matches an explicitly allowed pattern for "
                           f"`{cfg.release_branch}`.")
        return res

    res.findings.append(Finding(
        rule="branch-targeting",
        title=f"feature work must target `{cfg.integration_branch}`, not `{cfg.release_branch}`",
        what=(f"This PR is `{head}` -> `{base}`. Allowed heads for `{cfg.release_branch}` are "
              f"{cfg.main_allowed_heads} (or a `hotfix`/`promote`/`release` label). "
              f"`{head}` matches none of them."),
        why=("A repo where some PRs target `dev` and others target `main` has no integration "
             "point: two changes that conflict never meet until one is already on `main`, and "
             "the conflict surfaces at the worst possible moment. Measured across the six "
             "priority repos, PRs were split across both targets and 14 of 48 were already "
             "DIRTY — conflicting badly enough that GitHub could not build a merge ref, which "
             "is also why they reported zero CI checks. Contract 1."),
        how=(f"gh pr edit {pr.get('number')} --base {cfg.integration_branch}\n"
             f"If this really is a hotfix or a promote, say so explicitly rather than by "
             f"omission:  gh pr edit {pr.get('number')} --add-label hotfix"),
    ))
    return res


# --------------------------------------------------------------------------------------
# Rule 3 — trunk set is protected
# --------------------------------------------------------------------------------------

FORCE_PATTERNS = [
    (re.compile(r"git\s+push\b[^\n#]*\s(--force-with-lease\b|--force\b|-f\b)"), "force-push"),
    (re.compile(r"git\s+reset\s+--hard\b"), "hard reset"),
    (re.compile(r"git\s+push\b[^\n#]*\s--delete\b"), "branch delete"),
    (re.compile(r"git\s+push\b[^\n#]*\s:\S"), "refspec delete (`push origin :branch`)"),
    (re.compile(r"git\s+branch\s+-D\b"), "forced branch delete"),
]

ALLOW_MARK = "standards-allow"


def rule_protected_refs(cfg: Config) -> RuleResult:
    res = RuleResult()
    scan_dirs = [cfg.repo_root / ".github" / "workflows"]
    trunk_tokens = set(cfg.trunk_branches) | {"release/"}
    files: list[Path] = []
    for d in scan_dirs:
        if d.is_dir():
            files += [p for p in sorted(d.rglob("*")) if p.suffix in (".yml", ".yaml")]
    if not files:
        res.checked.append("no workflow files — nothing to scan (empty, not unknown)")
        return res
    res.checked.append(f"scanned {len(files)} workflow file(s) for destructive git on "
                       f"{sorted(trunk_tokens)}")

    for path in files:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            res.findings.append(Finding(
                rule="protected-refs", title="workflow unreadable",
                what=f"{rel(cfg.repo_root, path)}: {exc}",
                why="An unreadable workflow is UNKNOWN, not clean.",
                how="Fix file permissions or encoding.", unknown=True))
            continue
        for i, ln in enumerate(lines, start=1):
            if ALLOW_MARK in ln:
                continue
            for rx, kind in FORCE_PATTERNS:
                if not rx.search(ln):
                    continue
                hits_trunk = any(t in ln for t in trunk_tokens)
                # A bare force-push with no explicit refspec pushes the current branch,
                # which on a `push:` trigger for main IS main.
                bare = kind == "force-push" and not re.search(r"\borigin\s+\S", ln)
                if not (hits_trunk or bare):
                    continue
                res.findings.append(Finding(
                    rule="protected-refs",
                    title=f"{kind} touching the protected trunk set",
                    what=(f"{rel(cfg.repo_root, path)}:{i} contains a {kind} that reaches the "
                          f"trunk set ({', '.join(sorted(trunk_tokens))}):\n    {ln.strip()}"
                          + ("\n  (no explicit remote/refspec — this pushes whatever branch the "
                             "job is on, which on a trunk trigger is a trunk branch)"
                             if bare and not hits_trunk else "")),
                    why=("`main`, `dev`, `sec` and `release/**` must never be deleted or "
                         "force-pushed. Contract 1: back-merges are \"merge, never reset or "
                         "force\" — a force-push to a trunk discards the ancestry other "
                         "branches are measured against, which is the same disjoint-history "
                         "failure as a squashed promote but with no PR to review it."),
                    how=("Push to a work branch and open a PR instead. If this line genuinely "
                         "targets a disposable branch, make the refspec explicit and add a "
                         f"`# {ALLOW_MARK}: protected-refs — <reason>` comment on the same line."),
                    file=rel(cfg.repo_root, path), line=i,
                ))
    return res


# --------------------------------------------------------------------------------------
# Rules 4 — versioning
# --------------------------------------------------------------------------------------

def _toml_load(path: Path) -> dict[str, Any] | None:
    if tomllib is not None:
        try:
            with path.open("rb") as fh:
                return tomllib.load(fh)
        except (OSError, ValueError):
            return None
    return None


_VER_RX = re.compile(r'^\s*version\s*=\s*["\']([^"\']+)["\']', re.M)


def _toml_version_fallback(path: Path, table: str) -> str | None:
    """Regex fallback for pre-3.11 runners: first `version = "..."` after `[table]`."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    idx = text.find(f"[{table}]")
    if idx < 0:
        return None
    m = _VER_RX.search(text, idx)
    return m.group(1) if m else None


def collect_versions(root: Path) -> tuple[dict[str, str], list[str]]:
    """Map source-file -> declared version. Second element lists sources that failed to parse."""
    out: dict[str, str] = {}
    broken: list[str] = []

    cargo = root / "Cargo.toml"
    if cargo.is_file():
        doc = _toml_load(cargo)
        v = None
        if doc:
            pkg = doc.get("package") or {}
            v = pkg.get("version")
            if isinstance(v, dict):  # version.workspace = true
                v = ((doc.get("workspace") or {}).get("package") or {}).get("version")
            if not isinstance(v, str):
                v = ((doc.get("workspace") or {}).get("package") or {}).get("version")
        if not isinstance(v, str):
            v = _toml_version_fallback(cargo, "package")
        if isinstance(v, str):
            out["Cargo.toml"] = v
        elif doc is None:
            broken.append("Cargo.toml")

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        doc = _toml_load(pyproject)
        v = None
        if doc:
            v = (doc.get("project") or {}).get("version")
            if not isinstance(v, str):
                v = ((doc.get("tool") or {}).get("poetry") or {}).get("version")
        if not isinstance(v, str):
            v = _toml_version_fallback(pyproject, "project")
        if isinstance(v, str):
            out["pyproject.toml"] = v

    pkgjson = root / "package.json"
    if pkgjson.is_file():
        try:
            v = json.loads(pkgjson.read_text(encoding="utf-8")).get("version")
            if isinstance(v, str):
                out["package.json"] = v
        except (OSError, ValueError):
            broken.append("package.json")

    vfile = root / "VERSION"
    if vfile.is_file():
        try:
            v = vfile.read_text(encoding="utf-8").strip()
            if v:
                out["VERSION"] = v
        except OSError:
            broken.append("VERSION")

    cz = root / ".cz.toml"
    if cz.is_file():
        doc = _toml_load(cz)
        v = None
        if doc:
            v = ((doc.get("tool") or {}).get("commitizen") or {}).get("version")
        if not isinstance(v, str):
            v = _toml_version_fallback(cz, "tool.commitizen")
        if isinstance(v, str):
            out[".cz.toml"] = v

    return out, broken


SEMVER_RX = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def parse_semver(v: str) -> tuple[int, int, int] | None:
    m = SEMVER_RX.match(v.strip())
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def rule_version_policy(cfg: Config) -> RuleResult:
    res = RuleResult()
    versions, broken = collect_versions(cfg.repo_root)
    if not versions:
        res.checked.append("no version manifest found — nothing to check (empty, not unknown)")
        return res
    res.checked.append("versions: " + ", ".join(f"{k}={v}" for k, v in sorted(versions.items())))

    authorized = cfg.one_x_label in cfg.pr_labels
    for src, raw in sorted(versions.items()):
        sv = parse_semver(raw)
        if sv is None:
            continue
        if sv[0] >= 1 and not authorized:
            res.findings.append(Finding(
                rule="version-policy",
                title=f"{src} declares {raw} — 1.x requires explicit human authorization",
                what=(f"`{src}` is at `{raw}` (major {sv[0]}) and the "
                      f"`{cfg.one_x_label}` label is not present on this PR."),
                why=("Operator policy, global, no exceptions: every repo stays 0.x.x under "
                     "commitizen until a human explicitly authorizes a 1.x.x cut, and no agent "
                     "may cut or propose one. Authorizing 1.x requires full production "
                     "readiness, hardening, and a documented, met set of requirements, "
                     "deliverables, success criteria and definition of done — captured, not "
                     "asserted. Under `major_version_zero = true` the MINOR is the breaking "
                     "position, so a breaking change is 0.1 -> 0.2, never a jump to 1.0. "
                     "Contract 3."),
                how=(f"Set `{src}` back to a 0.x version (`cz bump --increment MINOR` for a "
                     "breaking change). If a human has genuinely authorized 1.x, they add the "
                     f"label: gh pr edit <n> --add-label {cfg.one_x_label}"),
                file=src,
            ))
    if authorized:
        res.checked.append(f"`{cfg.one_x_label}` label present — 1.x gate opened by a human.")
    for src in broken:
        res.findings.append(Finding(
            rule="version-policy", title=f"{src} could not be parsed",
            what=f"`{src}` exists but did not parse as valid TOML/JSON.",
            why="An unparseable manifest is UNKNOWN — the checker cannot confirm the repo is 0.x.",
            how=f"Fix the syntax in {src}.", file=src, unknown=True))
    return res


def rule_version_drift(cfg: Config) -> RuleResult:
    res = RuleResult()
    versions, _ = collect_versions(cfg.repo_root)
    if len(versions) < 2:
        res.checked.append("fewer than two version sources — nothing to cross-check")
        return res
    distinct = {v.lstrip("v") for v in versions.values()}
    res.checked.append("versions: " + ", ".join(f"{k}={v}" for k, v in sorted(versions.items())))
    if len(distinct) == 1:
        return res
    res.findings.append(Finding(
        rule="version-drift",
        title="version sources disagree",
        what=("This repo declares more than one version:\n"
              + "\n".join(f"    {k} = {v}" for k, v in sorted(versions.items()))),
        why=("Three sources with three answers is how a release ends up misrepresenting what it "
             "is. Measured in this fleet: one repo carried Cargo.toml 1.0.0, README 0.1 and tag "
             "v1.0.1 simultaneously. Contract 4: every release must carry correct semver and a "
             "changelog derived from it — which is impossible when the number itself is "
             "ambiguous, and a version that claims maturity the code has not earned transfers "
             "risk to whoever trusts it."),
        how=("Make `.cz.toml` the single source and list every other file in `version_files`, "
             "then re-bump so commitizen rewrites them together:\n"
             "    [tool.commitizen]\n"
             "    version_files = [\"VERSION\", \"Cargo.toml:^version\"]\n"
             "    cz bump --yes"),
    ))
    return res


# --------------------------------------------------------------------------------------
# Rule 5 — exit contract
# --------------------------------------------------------------------------------------

GATE_TOKENS = (
    "cargo", "clippy", "rustfmt", "pytest", "ruff", "mypy", "pyright", "bandit", "semgrep",
    "gitleaks", "trufflehog", "trivy", "grype", "syft", "audit", "geiger", "cargo-deny",
    "deny check", "npm test", "yarn test", "pnpm test", "eslint", "shellcheck", "actionlint",
    "go test", "go vet", "codeql", "safety", "pip-audit", "osv-scanner", "hadolint", "yamllint",
)

# The binaries whose exit status IS the gate. Matched against the FIRST word of the
# command `||` actually binds to — not anywhere on the line.
#
# Why so strict: matching a gate token anywhere on the line produced two false positives
# on the first real run, `rustup component add rustfmt clippy || true` (a toolchain
# install, not a lint) and `echo "... $(gitleaks version || true)"` (a banner). A check
# that cries wolf about setup lines is a check people mute, and then it is not catching
# the swallowed `cargo geiger` either.
GATE_BINARIES = (
    "cargo", "clippy-driver", "pytest", "ruff", "mypy", "pyright", "bandit", "semgrep",
    "gitleaks", "trufflehog", "trivy", "grype", "syft", "eslint", "shellcheck", "actionlint",
    "codeql", "safety", "pip-audit", "osv-scanner", "hadolint", "yamllint", "cargo-geiger",
    "cargo-deny", "cargo-audit", "tox", "nox", "pylint", "flake8", "black", "isort",
)
# Multi-word invocations: the gate is the tool these run, not the launcher.
GATE_PHRASES = (
    "uv run", "poetry run", "pipenv run", "python -m", "python3 -m", "npm test", "npm run",
    "yarn test", "pnpm test", "go test", "go vet", "npx",
)
SOFT_FAIL_RX = re.compile(r"\|\|\s*(true\b|:\s*$|:\s|exit\s+0\b|echo\b)")
_SUBST_RX = re.compile(r"\$\([^)]*\)|`[^`]*`")


def _swallowed_gate(line: str) -> str | None:
    """Return the gate command a `|| true`-style tail is swallowing, or None.

    Why it looks at only the last simple command: `||` binds to the pipeline immediately
    before it, so `mkdir -p out && cargo test || true` swallows `cargo test`, while
    `cargo test && echo done || true` swallows the `echo`. Command substitutions are
    stripped first because a tool named inside `$(...)` is being *reported*, not run as
    the gate.
    """
    if not SOFT_FAIL_RX.search(line):
        return None
    left = line.split("||", 1)[0]
    left = _SUBST_RX.sub(" ", left)
    # last simple command in the list/pipeline
    segment = re.split(r"&&|\||;", left)[-1].strip()
    segment = re.sub(r"^(sudo\s+|env\s+|\w+=\S+\s+)+", "", segment).strip()
    if not segment:
        return None
    words = segment.split()
    first = words[0].rsplit("/", 1)[-1]
    if first in GATE_BINARIES:
        return segment
    two = " ".join(words[:2])
    three = " ".join(words[:3])
    for phrase in GATE_PHRASES:
        if two.startswith(phrase) or three.startswith(phrase):
            tail = segment[len(phrase):].strip().split()
            if tail and tail[0].rsplit("/", 1)[-1] in GATE_BINARIES:
                return segment
            if any(t in segment for t in ("test", "lint", "audit", "check")):
                return segment
    return None


def logical_lines(script: str) -> list[tuple[int, str]]:
    """Join shell continuations into logical lines, keeping the first physical line number.

    Why: `cargo test \\` / `  || true` and a `||` on its own continuation line are the same
    command as far as the shell is concerned, and a scanner that reads physical lines sees
    only `|| true` with nothing before it and reports nothing.
    """
    out: list[tuple[int, str]] = []
    buf, start = "", 0
    for i, raw in enumerate(script.splitlines(), start=1):
        stripped = raw.strip()
        if buf:
            buf += " " + stripped
        else:
            start, buf = i, stripped
        cont = buf.endswith("\\") or buf.endswith("|") or buf.endswith("&&")
        if cont:
            buf = buf.rstrip("\\").rstrip()
            continue
        out.append((start, buf))
        buf = ""
    if buf:
        out.append((start, buf))
    # A leading `||` / `&&` continues the previous logical line.
    merged: list[tuple[int, str]] = []
    for ln_no, text in out:
        if merged and re.match(r"^(\|\||&&)", text):
            merged[-1] = (merged[-1][0], merged[-1][1] + " " + text)
        else:
            merged.append((ln_no, text))
    return merged


def _is_gatelike(*parts: Any) -> bool:
    blob = " ".join(str(p) for p in parts if p).lower()
    return any(tok in blob for tok in GATE_TOKENS) or any(
        w in blob for w in ("test", "lint", "security", "scan", "audit", "vulnerab")
    )


def rule_exit_contract(cfg: Config) -> RuleResult:
    res = RuleResult()
    files = workflow_files(cfg.repo_root)
    if not files:
        res.checked.append("no workflow files — nothing to check")
        return res
    res.checked.append(f"inspected {len(files)} workflow file(s) for gates that cannot go red")

    for path in files:
        doc, err = parse_workflow(path)
        if doc is None:
            # yaml-validity owns reporting the parse failure; do not double-report.
            continue
        fname = rel(cfg.repo_root, path)
        jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
        for job_id, job in (jobs or {}).items():
            if not isinstance(job, dict):
                continue
            jname = str(job.get("name") or job_id)
            if job.get("continue-on-error") is True and _is_gatelike(jname, job_id):
                res.findings.append(Finding(
                    rule="exit-contract",
                    title=f"job `{jname}` is a gate with continue-on-error: true",
                    what=(f"{fname}: job `{job_id}` has `continue-on-error: true` at job level, "
                          "so every failure inside it reports green."),
                    why=EXIT_WHY, how=EXIT_HOW,
                    file=fname, line=find_line(path, "continue-on-error"),
                ))
        for job_id, job, step in iter_steps(doc):
            sname = str(step.get("name") or step.get("uses") or "")
            script = step.get("run") if isinstance(step.get("run"), str) else ""
            if ALLOW_MARK in (script or "") or ALLOW_MARK in sname:
                continue
            gatelike = _is_gatelike(sname, script, step.get("uses"), job.get("name"), job_id)
            advisory = "(advisory)" in sname.lower()
            if step.get("continue-on-error") is True and gatelike and not advisory:
                res.findings.append(Finding(
                    rule="exit-contract",
                    title=f"gate step `{sname or job_id}` has continue-on-error: true",
                    what=(f"{fname}: step `{sname or '(unnamed)'}` in job `{job_id}` is a "
                          "security/lint/test step marked `continue-on-error: true`. If the tool "
                          "fails to build or crashes, the job still reports GREEN."),
                    why=EXIT_WHY, how=EXIT_HOW,
                    file=fname, line=find_line(path, sname) if sname else None,
                ))
            if script:
                for off, ln in logical_lines(script):
                    if ALLOW_MARK in ln:
                        continue
                    gate_cmd = _swallowed_gate(ln)
                    if gate_cmd is None:
                        continue
                    res.findings.append(Finding(
                        rule="exit-contract",
                        title="gate command swallows its own failure",
                        what=(f"{fname}: job `{job_id}`, step `{sname or '(unnamed)'}` line "
                              f"{off} of the script:\n    {ln.strip()}\n"
                              f"`{gate_cmd}` is the command the `||` tail binds to, so its "
                              "failure — including 'the tool would not run' — exits 0."),
                        why=EXIT_WHY, how=EXIT_HOW,
                        file=fname, line=find_line(path, ln.strip()) if ln.strip() else None,
                    ))
    return res


EXIT_WHY = (
    "This is a gate that is switched off while still looking on. Measured: qlora-rs #27 runs "
    "`cargo install cargo-geiger` with continue-on-error and then the scan itself with "
    "`|| true`, so \"the tool could not build\" reports GREEN and the unsafe-code scan has not "
    "run in months without anyone seeing red. Contract 4a: a skipped or swallowed required "
    "check is not a passing check."
)
EXIT_HOW = (
    "Separate EMPTY from UNKNOWN and handle them differently:\n"
    "    set -euo pipefail\n"
    "    if ! command -v cargo-geiger >/dev/null; then\n"
    "      echo '::error::cargo-geiger unavailable — cannot determine unsafe usage'; exit 1\n"
    "    fi\n"
    "    out=$(cargo geiger --output-format Json)   # tool failure -> non-zero -> job fails\n"
    "    if [ -z \"$out\" ]; then echo 'no unsafe usage found'; exit 0; fi   # empty IS an answer\n"
    "An empty result set is a real answer and must exit 0; a crashed tool is not, and must exit "
    "non-zero. If a step is genuinely advisory, put `(advisory)` in its name, or add a "
    f"`# {ALLOW_MARK}: exit-contract — <reason>` comment on the line."
)


# --------------------------------------------------------------------------------------
# Rule 6 — YAML validity
# --------------------------------------------------------------------------------------

HEREDOC_RX = re.compile(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?")


def rule_yaml_validity(cfg: Config) -> RuleResult:
    res = RuleResult()
    files = workflow_files(cfg.repo_root)
    if not files:
        res.checked.append("no workflow files — nothing to parse")
        return res
    res.checked.append(f"yaml.safe_load over {len(files)} workflow file(s)")

    for path in files:
        fname = rel(cfg.repo_root, path)
        doc, err = parse_workflow(path)
        if doc is None:
            hint = ""
            try:
                raw = path.read_text(encoding="utf-8")
            except OSError:
                raw = ""
            if re.search(r"^\s*\S+.*<<-?\s*['\"]?\w", raw, re.M) and re.search(r"^\w+$", raw, re.M):
                hint = ("\nLikely cause: a heredoc body or terminator written at COLUMN 0. A "
                        "line at column 0 dedents out of the enclosing `run: |` block scalar and "
                        "terminates it, so the rest of the script is parsed as YAML.")
            res.findings.append(Finding(
                rule="yaml-validity",
                title="workflow does not parse",
                what=f"{fname} failed yaml.safe_load:\n{err}{hint}",
                why=("A workflow that does not parse never runs. It reports `startup_failure`, "
                     "not a failed job — no steps, no logs, and nothing that looks like a broken "
                     "gate. Measured: exactly this `python3 <<'PY'` at column 0 broke "
                     "`reopen-issues-closed-off-main.yml` in 15 OF 22 repos in this fleet, and "
                     "the workflow appeared merely 'red for no reason' for weeks. Contract 4a."),
                how=("Indent the whole heredoc — opener, body and terminator — to the block "
                     "scalar's indentation. Everything inside `run: |` must be indented past the "
                     "`run:` key:\n"
                     "    - run: |\n"
                     "        python3 - <<'PY'\n"
                     "        print('hi')\n"
                     "        PY\n"
                     "Verify locally: python3 -c \"import yaml,sys;"
                     "yaml.safe_load(open(sys.argv[1]))\" " + fname),
                file=fname,
            ))
            continue

        # A file can parse and still have a truncated script: an unterminated heredoc.
        for job_id, _job, step in iter_steps(doc):
            script = step.get("run")
            if not isinstance(script, str):
                continue
            lines = script.splitlines()
            for i, ln in enumerate(lines):
                m = HEREDOC_RX.search(ln)
                if not m:
                    continue
                tag = m.group(1)
                if any(re.fullmatch(rf"\s*{re.escape(tag)}\s*", later)
                       for later in lines[i + 1:]):
                    continue
                res.findings.append(Finding(
                    rule="yaml-validity",
                    title=f"unterminated heredoc `{tag}`",
                    what=(f"{fname}: job `{job_id}`, step "
                          f"`{step.get('name') or step.get('uses') or '(unnamed)'}` opens a "
                          f"heredoc `<<{tag}` that is never closed inside the `run` script."),
                    why=("The terminator was almost certainly written at column 0, which dedents "
                         "out of the `run: |` block scalar. The YAML then either fails to parse "
                         "(permanent `startup_failure`) or silently truncates the script. This "
                         "broke 15 of 22 repos in this fleet."),
                    how=("Indent the terminator to the same level as the rest of the script "
                         "inside `run: |`. YAML strips the common indentation, so the shell "
                         "still sees it at column 0."),
                    file=fname, line=find_line(path, ln.strip()),
                ))
    return res


# --------------------------------------------------------------------------------------
# Rule 7 — scheduled + cancel-in-progress
# --------------------------------------------------------------------------------------

def rule_schedule_cancel(cfg: Config) -> RuleResult:
    res = RuleResult()
    files = workflow_files(cfg.repo_root)
    if not files:
        res.checked.append("no workflow files — nothing to check")
        return res
    checked = 0
    for path in files:
        doc, _ = parse_workflow(path)
        if doc is None:
            continue
        on = doc.get("on") if "on" in doc else doc.get(True)  # YAML 1.1 turns `on:` into True
        scheduled = isinstance(on, dict) and "schedule" in on
        if not scheduled:
            continue
        checked += 1
        fname = rel(cfg.repo_root, path)
        sites: list[str] = []
        conc = doc.get("concurrency")
        if isinstance(conc, dict) and conc.get("cancel-in-progress") is True:
            sites.append("workflow-level `concurrency`")
        jobs = doc.get("jobs") if isinstance(doc.get("jobs"), dict) else {}
        for job_id, job in (jobs or {}).items():
            if isinstance(job, dict) and isinstance(job.get("concurrency"), dict):
                if job["concurrency"].get("cancel-in-progress") is True:
                    sites.append(f"job `{job_id}` `concurrency`")
        if not sites:
            continue
        res.findings.append(Finding(
            rule="schedule-cancel",
            title="scheduled workflow with cancel-in-progress: true",
            what=(f"{fname} has an `on.schedule` trigger and `cancel-in-progress: true` at "
                  + " and ".join(sites) + "."),
            why=("On self-hosted runners a scheduled job queues when no runner is free. The next "
                 "scheduled tick then CANCELS the queued run, and a cancelled run reports "
                 "`cancelled` — not `failed`. Nothing alerts, no badge turns red, and the job "
                 "silently never runs again. This is the worst class of failure the contract "
                 "names: a gate that is off while looking on."),
            how=("Exempt the schedule from cancellation rather than dropping concurrency:\n"
                 "    concurrency:\n"
                 "      group: ${{ github.workflow }}-${{ github.ref }}\n"
                 "      cancel-in-progress: ${{ github.event_name != 'schedule' }}\n"
                 "PR pushes still supersede each other; scheduled runs are left to finish."),
            file=fname, line=find_line(path, "cancel-in-progress"),
        ))
    res.checked.append(f"{checked} scheduled workflow(s) checked for cancel-in-progress")
    return res


# --------------------------------------------------------------------------------------
# Rule 8 — python floor
# --------------------------------------------------------------------------------------

PY_KEYS = ("python-version", "python-versions", "python_version", "pyversion")


def _walk(node: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    yield path, node
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def rule_python_floor(cfg: Config) -> RuleResult:
    res = RuleResult()
    files = workflow_files(cfg.repo_root)
    if not files:
        res.checked.append("no workflow files — nothing to check")
        return res
    lo = cfg.python_min
    res.checked.append(f"floor is {lo[0]}.{lo[1]}; scanned {len(files)} workflow file(s)")

    for path in files:
        doc, _ = parse_workflow(path)
        if doc is None:
            continue
        fname = rel(cfg.repo_root, path)
        for keypath, node in _walk(doc):
            key = keypath.rsplit(".", 1)[-1].split("[")[0]
            if key not in PY_KEYS:
                continue
            values = node if isinstance(node, list) else [node]
            for raw in values:
                if isinstance(raw, float):
                    res.findings.append(Finding(
                        rule="python-floor",
                        title="unquoted python version parsed as a float",
                        what=(f"{fname}: `{keypath}` is the YAML float `{raw}`. Unquoted `3.10` "
                              "becomes 3.1 — you asked for Python 3.10 and specified 3.1."),
                        why=("A version that silently means something else is worse than a wrong "
                             "version, because the workflow file reads correct. The runner "
                             "resolves whatever 3.1x it can find, or fails with a message that "
                             "does not mention quoting."),
                        how=f"Quote it: `{key}: \"{raw}0\"`",
                        file=fname, line=find_line(path, key),
                    ))
                    continue
                if not isinstance(raw, str):
                    continue
                m = re.match(r"^(\d+)\.(\d+)", raw.strip())
                if not m:
                    continue
                ver = (int(m.group(1)), int(m.group(2)))
                if ver >= lo:
                    continue
                res.findings.append(Finding(
                    rule="python-floor",
                    title=f"Python {raw} is below the fleet floor {lo[0]}.{lo[1]}",
                    what=f"{fname}: `{keypath}` requests Python `{raw}`.",
                    why=("The fleet floor is 3.11 with 3.13 preferred. Below 3.11 there is no "
                         "`tomllib`, no exception groups and no `Self` type, so shared fleet "
                         "tooling either needs a compatibility shim per repo or breaks on the "
                         "one matrix cell nobody looks at. Testing a version the fleet does not "
                         "ship costs runner time and buys a guarantee nobody wants."),
                    how=(f"Raise it to \"{lo[0]}.{lo[1]}\" or higher — \"3.13\" preferred."),
                    file=fname, line=find_line(path, str(raw)),
                ))
    return res


# --------------------------------------------------------------------------------------
# Rule 9 — conventional commits on PR titles
# --------------------------------------------------------------------------------------

def rule_conventional_title(cfg: Config) -> RuleResult:
    res = RuleResult()
    pr = cfg.pr
    if not pr:
        res.checked.append("not a pull_request event — nothing to check")
        return res
    title = str(pr.get("title", ""))
    types = "|".join(re.escape(t) for t in cfg.commit_types)
    rx = re.compile(rf"^(?:{types})(\([^)]+\))?!?: .+")
    if rx.match(title) or re.match(r'^Revert ".+"$', title):
        res.checked.append(f"PR title is conventional: {title!r}")
        return res
    res.findings.append(Finding(
        rule="conventional-title",
        title="PR title is not a conventional commit",
        what=(f"Title: {title!r}\nExpected `type(scope)?: subject` where type is one of: "
              f"{', '.join(cfg.commit_types)}."),
        why=("Squash-merging a PR into `dev` uses the PR title as the commit subject — contract "
             "1 makes squash the standard on that edge — and the changelog is generated from "
             "those subjects by commitizen. A non-conventional title therefore does not just "
             "look untidy: it is dropped from the changelog and it cannot drive the version "
             "bump, so the release notes silently under-report what shipped. Contract 4 requires "
             "a real changelog readable by someone who did not write the code."),
        how=("gh pr edit <n> --title 'fix(scope): what changed'\n"
             "Add `!` after the type for a breaking change (`feat(api)!: ...`) — under "
             "`major_version_zero` that bumps the MINOR."),
    ))
    return res


# --------------------------------------------------------------------------------------
# Rule 10 — docs with the change
# --------------------------------------------------------------------------------------

SOURCE_SUFFIXES = {".rs", ".py", ".go", ".ts", ".tsx", ".js", ".jsx", ".sh", ".bash", ".c",
                   ".cc", ".cpp", ".h", ".hpp", ".java", ".rb", ".nix", ".tf"}
DOC_SUFFIXES = {".md", ".rst", ".adoc", ".txt"}
TEST_PARTS = ("tests/", "test/", "spec/", "__tests__/", "/testdata/", "benches/", "fixtures/")
DOC_LINE_RX = re.compile(r'^\+\s*(///|//!|#\'|"""|\'\'\'|/\*\*|\* @|#:)')


def changed_files(cfg: Config) -> tuple[list[str], str | None]:
    """Return (paths, error). Error means UNKNOWN."""
    pr = cfg.pr
    if not pr:
        return [], None
    base_sha = str(pr.get("base", {}).get("sha", ""))
    if base_sha:
        p = run(["git", "diff", "--name-only", f"{base_sha}...HEAD"], cfg.repo_root)
        if p.returncode == 0:
            return [ln for ln in p.stdout.splitlines() if ln.strip()], None
    # Fallback: the API knows even when the local clone is shallow.
    num = pr.get("number")
    data, err = github_api(cfg, f"repos/{cfg.repo_slug}/pulls/{num}/files?per_page=100")
    if isinstance(data, list):
        return [str(f.get("filename", "")) for f in data], None
    return [], err or "git diff and the API both failed"


def rule_docs_with_change(cfg: Config) -> RuleResult:
    res = RuleResult()
    pr = cfg.pr
    if not pr:
        res.checked.append("not a pull_request event — nothing to check")
        return res
    paths, err = changed_files(cfg)
    if err:
        res.findings.append(Finding(
            rule="docs-with-change", title="could not determine changed files",
            what=f"Neither `git diff` nor the pulls/files API produced a file list: {err}",
            why="UNKNOWN, not empty — the checker cannot claim the docs rule passed.",
            how="Ensure the caller checks out with `fetch-depth: 0` and grants `contents: read`.",
            unknown=True))
        return res
    if not paths:
        res.checked.append("PR changes no files — nothing to check (empty, not unknown)")
        return res

    behaviour = [p for p in paths
                 if Path(p).suffix in SOURCE_SUFFIXES
                 and not any(t in f"/{p}" for t in TEST_PARTS)]
    docs = [p for p in paths
            if Path(p).suffix in DOC_SUFFIXES or p.startswith("docs/")
            or Path(p).name.upper().startswith(("README", "USAGE", "CHANGELOG"))]
    res.checked.append(f"{len(paths)} changed file(s): {len(behaviour)} behavioural source, "
                       f"{len(docs)} doc")
    if not behaviour or docs:
        return res

    # Doc comments inside the source diff count. A `///` block added next to the code is
    # exactly the change-scoped documentation the contract asks for.
    base_sha = str(pr.get("base", {}).get("sha", ""))
    if base_sha:
        p = run(["git", "diff", "-U0", f"{base_sha}...HEAD", "--"] + behaviour, cfg.repo_root)
        if p.returncode == 0 and any(DOC_LINE_RX.match(ln) for ln in p.stdout.splitlines()):
            res.checked.append("doc comments added inside the source diff — counts as docs.")
            return res

    res.findings.append(Finding(
        rule="docs-with-change",
        title="behaviour changed and no documentation moved with it",
        what=("These source files changed with no doc comment, README/USAGE or `docs/` update in "
              "the same PR:\n" + "\n".join(f"    {p}" for p in behaviour[:20])
              + ("\n    ..." if len(behaviour) > 20 else "")),
        why=("Stale docs are actively worse than missing ones, because they are believed. This "
             "fleet has already produced three bugs where the documentation is what made them "
             "invisible: a `rust-version` input that was documented, surfaced as a dropdown and "
             "silently ignored; a `caller-ci.yml` comment asserting a job name that was wrong; "
             "and a sizing comment claiming \"clippy-only jobs are light\" while clippy was being "
             "OOM-killed. Contract 5a: docs are a required deliverable, in the same PR, scoped "
             "to exactly what changed."),
        how=("Update the doc comment on anything whose public behaviour moved, and the "
             "README/USAGE line for any documented flag, input or default. Google-style, and "
             "state the WHY — the signature already says what. If this PR genuinely changes no "
             "behaviour, this stays a warning and you can merge past it."),
    ))
    return res


# --------------------------------------------------------------------------------------
# Rule 11 — trunk divergence (the post-merge detector for a squashed promote)
# --------------------------------------------------------------------------------------

def rule_trunk_divergence(cfg: Config) -> RuleResult:
    res = RuleResult()
    root = cfg.repo_root
    a, b = cfg.release_branch, cfg.integration_branch

    if not (root / ".git").exists():
        res.checked.append("not a git checkout — skipped")
        return res

    fetch = run(["git", "fetch", "--quiet", "--no-tags", "origin", a, b], root)
    if fetch.returncode != 0:
        # Distinguish "the branch does not exist" (EMPTY) from "fetch broke" (UNKNOWN).
        exists = {}
        for br in (a, b):
            ls = run(["git", "ls-remote", "--exit-code", "--heads", "origin", br], root)
            exists[br] = ls.returncode == 0
        missing = [br for br, ok in exists.items() if not ok]
        if missing:
            res.checked.append(
                f"branch(es) {missing} do not exist on origin — no promote edge to measure "
                "yet (empty, not unknown)")
            return res
        res.findings.append(Finding(
            rule="trunk-divergence", title="could not fetch the trunk branches",
            what=f"`git fetch origin {a} {b}` failed:\n{fetch.stderr.strip()}",
            why=("UNKNOWN, not empty. Without both trunks the checker cannot tell whether the "
                 "promote ancestry is intact."),
            how="Check out with `fetch-depth: 0` and ensure the token can read the repository.",
            unknown=True))
        return res

    mb = run(["git", "merge-base", f"origin/{a}", f"origin/{b}"], root)
    if mb.returncode != 0:
        ahead = run(["git", "rev-list", "--count", f"origin/{a}"], root).stdout.strip()
        res.findings.append(Finding(
            rule="trunk-divergence",
            title=f"`{a}` and `{b}` have NO MERGE BASE — disjoint histories",
            what=(f"`git merge-base origin/{a} origin/{b}` found nothing. The two trunks share "
                  f"no common ancestor at all ({a} has {ahead} commits)."),
            why=SQUASH_DAMAGE,
            how=(f"One-time reconciliation, as a MERGE (contract 1: `main` -> `dev` is merge, "
                 f"never reset or force):\n"
                 f"    git checkout {b} && git pull\n"
                 f"    git merge --no-ff --allow-unrelated-histories origin/{a}\n"
                 f"    # resolve, keeping {a}'s content where the trees already agree\n"
                 f"    git switch -c chore/reconcile-{b} && git push -u origin HEAD\n"
                 f"    gh pr create --base {b} --title 'chore(sync): back-merge {a} into {b}'\n"
                 f"Merge that PR with a MERGE COMMIT. Do not force-push {b}."),
        ))
        return res

    base = mb.stdout.strip()
    a_only = run(["git", "rev-list", "--count", f"{base}..origin/{a}"], root).stdout.strip() or "?"
    b_only = run(["git", "rev-list", "--count", f"{base}..origin/{b}"], root).stdout.strip() or "?"
    same_tree = run(["git", "diff", "--quiet", f"origin/{a}", f"origin/{b}"], root).returncode == 0
    res.checked.append(
        f"merge base {base[:8]}: `{a}` +{a_only}, `{b}` +{b_only}, trees "
        f"{'identical' if same_tree else 'differ'}")

    # `main` carrying commits `dev` has never seen is the state a squashed promote leaves
    # behind, and also the ordinary state between a promote and its back-merge. It is worth
    # measuring either way, because the phantom-diff number below is exactly what every
    # branch cut from `dev` will be asked to resolve.
    if a_only not in ("0", "?") and not same_tree:
        stat = run(["git", "diff", "--shortstat", f"origin/{b}", f"origin/{a}"],
                   root).stdout.strip()
        res.findings.append(Finding(
            rule="trunk-divergence",
            title=f"`{b}` is {a_only} commit(s) behind `{a}`",
            what=(f"`origin/{a}` has {a_only} commit(s) not reachable from `origin/{b}`; the "
                  f"merge base is {base[:8]}. Diff `{b}` -> `{a}`: {stat or 'unavailable'}."),
            why=("Contract 1: lowers update off `main` after a release lands, *then* continue. "
                 "Until the back-merge happens, every branch cut from `dev` is built on a "
                 "pre-release base and is manufacturing a future conflict — the diff measured "
                 "above is what it will be asked to resolve. This is an advisory, not a block: "
                 "the window between a promote and its back-merge is legitimate. It becomes the "
                 "expensive failure only when the promote was squashed, which the checks above "
                 "detect separately."),
            how=(f"gh pr create --base {b} --head {a} \\\n"
                 f"  --title 'chore(sync): back-merge {a} into {b}'\n"
                 f"Merge it with a MERGE COMMIT — never reset or force-push `{b}`."),
            cap=WARNING,
        ))

    if same_tree and a_only != "0" and b_only == "0":
        stat = run(["git", "diff", "--shortstat", base, f"origin/{a}"], root).stdout.strip()
        res.findings.append(Finding(
            rule="trunk-divergence",
            title=f"`{b}` has identical content to `{a}` but is {a_only} commits behind it",
            what=(f"`origin/{a}` and `origin/{b}` have IDENTICAL TREES, yet the merge base is "
                  f"{base[:8]} — {a_only} commits back — and `{b}` carries zero unique commits. "
                  f"That is the fingerprint of a squashed promote. Phantom diff against the "
                  f"merge base: {stat or 'unavailable'}."),
            why=SQUASH_DAMAGE,
            how=(f"Restore the ancestry link with a back-merge, not a reset:\n"
                 f"    gh pr create --base {b} --head {a} \\\n"
                 f"      --title 'chore(sync): back-merge {a} into {b} — restore the merge base'\n"
                 f"Merge it with a MERGE COMMIT. Then merge every promote with "
                 f"`gh pr merge <n> --merge`."),
        ))
    return res


# --------------------------------------------------------------------------------------
# Rule 12 — actionlint (opt-in)
# --------------------------------------------------------------------------------------

def rule_actionlint(cfg: Config) -> RuleResult:
    res = RuleResult()
    files = workflow_files(cfg.repo_root)
    if not files:
        res.checked.append("no workflow files — nothing to lint")
        return res
    probe = run(["bash", "-lc", "command -v actionlint"], cfg.repo_root)
    if probe.returncode != 0:
        res.findings.append(Finding(
            rule="actionlint", title="actionlint is enabled but not installed",
            what="`actionlint` is not on PATH on this runner, so no workflow was linted.",
            why=("UNKNOWN, not empty: the rule was switched on and produced no measurement. "
                 "Reporting green here would be a gate that is off while looking on."),
            how=("Install it on the runner image, or set the `actionlint` input to `off`:\n"
                 "    go install github.com/rhysd/actionlint/cmd/actionlint@latest"),
            unknown=True))
        return res
    p = run(["actionlint", "-oneline"] + [str(f) for f in files], cfg.repo_root)
    res.checked.append(f"actionlint over {len(files)} workflow file(s)")
    for ln in p.stdout.splitlines():
        if not ln.strip():
            continue
        m = re.match(r"^([^:]+):(\d+):(\d+): (.*)$", ln)
        res.findings.append(Finding(
            rule="actionlint", title="actionlint",
            what=ln.strip(),
            why=("actionlint catches expression, context and shell errors that `yaml.safe_load` "
                 "cannot see — a valid YAML file can still reference a context that does not "
                 "exist, which fails only at runtime."),
            how="Fix the reported line; run `actionlint` locally to iterate.",
            file=m.group(1) if m else None,
            line=int(m.group(2)) if m else None,
        ))
    return res


# --------------------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------------------

RULES: dict[str, Callable[[Config], RuleResult]] = {
    "yaml-validity": rule_yaml_validity,
    "promote-merge-mode": rule_promote_merge_mode,
    "branch-targeting": rule_branch_targeting,
    "protected-refs": rule_protected_refs,
    "trunk-divergence": rule_trunk_divergence,
    "version-policy": rule_version_policy,
    "version-drift": rule_version_drift,
    "exit-contract": rule_exit_contract,
    "schedule-cancel": rule_schedule_cancel,
    "python-floor": rule_python_floor,
    "conventional-title": rule_conventional_title,
    "docs-with-change": rule_docs_with_change,
    "actionlint": rule_actionlint,
}

RULE_TITLES = {
    "yaml-validity": "every workflow parses",
    "promote-merge-mode": "dev -> main lands as a merge commit",
    "branch-targeting": "feature work targets dev",
    "protected-refs": "no force-push / reset of the trunk set",
    "trunk-divergence": "main and dev still share a merge base",
    "version-policy": "repo stays 0.x until a human says otherwise",
    "version-drift": "one version, one answer",
    "exit-contract": "gates can actually go red",
    "schedule-cancel": "scheduled runs are not cancelled by the next tick",
    "python-floor": "no Python below the fleet floor",
    "conventional-title": "PR title drives the changelog",
    "docs-with-change": "docs move with behaviour",
    "actionlint": "workflow linting",
}


def annotate(level: str, f: Finding) -> None:
    """Emit a GitHub Actions annotation. Newlines must be percent-encoded."""
    body = f"WHAT: {f.what}\n\nWHY:  {f.why}\n\nHOW:  {f.how}"
    body = body.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    props = [f"title=standards/{f.rule}: {f.title}"]
    if f.file:
        props.append(f"file={f.file}")
        if f.line:
            props.append(f"line={f.line}")
    print(f"::{level} {','.join(props)}::{body}")


def main() -> int:
    cfg = load_config()
    print(f"standards: repo={cfg.repo_slug} event={cfg.event_name} root={cfg.repo_root}")

    summary: list[str] = [
        "## Development standards",
        "",
        "Enforcing `BRANCH-AND-RELEASE-CONTRACT.md`. Every finding below says what is wrong, "
        "why it matters, and how to fix it.",
        "",
        "| rule | mode | result |",
        "|---|---|---|",
    ]
    detail: list[str] = []
    failed = False
    counts = {ERROR: 0, WARNING: 0}

    for rule_id, fn in RULES.items():
        mode = cfg.modes.get(rule_id, "off")
        if mode == "off":
            summary.append(f"| {rule_id} — {RULE_TITLES[rule_id]} | off | skipped |")
            continue
        print(f"\n--- {rule_id} ({mode}) ---")
        try:
            result = fn(cfg)
        except Exception as exc:  # noqa: BLE001 - a crashed rule is UNKNOWN, never a pass
            result = RuleResult(findings=[Finding(
                rule=rule_id, title="rule crashed",
                what=f"{type(exc).__name__}: {exc}",
                why=("A rule that crashed measured nothing. Contract 4a: unknown must fail "
                     "loudly rather than pass quietly."),
                how="Report this against tzervas/mycelium-workflows scripts/standards_check.py.",
                unknown=True)])

        for line in result.checked:
            print(f"  checked: {line}")

        errs = warns = notes = 0
        for f in result.findings:
            lvl = f.level(mode)
            annotate(lvl, f)
            if lvl == ERROR:
                counts[ERROR] += 1
                errs += 1
                failed = True
            elif lvl == WARNING:
                counts[WARNING] += 1
                warns += 1
            else:
                notes += 1
            tag = {ERROR: "FAIL", WARNING: "warn", NOTICE: "note"}[lvl]
            detail.append(
                f"### {tag} — {rule_id}: {f.title}\n\n"
                + (f"`{f.file}`" + (f":{f.line}" if f.line else "") + "\n\n" if f.file else "")
                + f"**What:** {f.what}\n\n**Why:** {f.why}\n\n**How:**\n```\n{f.how}\n```\n")

        if errs:
            verdict = f"❌ {errs} error(s)" + (f", {warns} warning(s)" if warns else "")
        elif warns:
            verdict = f"⚠️ {warns} warning(s)"
        elif notes:
            verdict = f"ℹ️ {notes} note(s) — nothing to fix"
        else:
            verdict = "✅ clean — " + (result.checked[0] if result.checked else "nothing to check")
        summary.append(f"| {rule_id} — {RULE_TITLES[rule_id]} | {mode} | {verdict} |")

    summary.append("")
    if not failed and not counts[WARNING]:
        summary.append("Everything checked is clean. An empty result set is a real answer: "
                       "this job passes because nothing was found, not because nothing ran.")
    if detail:
        summary.append("")
        summary += detail
    summary.append("")
    summary.append("Rules, toggles and the operator settings commands: "
                   "[`docs/STANDARDS.md`](https://github.com/tzervas/mycelium-workflows/blob/"
                   "main/docs/STANDARDS.md)")

    out = env("GITHUB_STEP_SUMMARY")
    text = "\n".join(summary) + "\n"
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text)

    print(f"\nstandards: {counts[ERROR]} error(s), {counts[WARNING]} warning(s)")
    if failed:
        print("::error title=standards: contract violations::One or more enforced rules failed. "
              "Each annotation above says what, why and how. Full detail is in the job summary.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
