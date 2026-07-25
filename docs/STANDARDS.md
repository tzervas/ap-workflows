# The development-standards gate

`reusable-standards.yml` is the executable form of
[`BRANCH-AND-RELEASE-CONTRACT.md`](https://github.com/tzervas/gha-runner-ctl). The contract is
written down and still gets violated, because a written rule depends on everyone remembering it
at the moment it matters. **A rule nobody can violate beats a rule everyone knows.** This is the
"cannot" half.

One job, one status context, thirteen rules, each individually toggleable so a repo adopts
incrementally instead of all-or-nothing.

---

## Quick start

Install `.github/workflows/standards.yml` in the target repo — copy
[`templates/caller-standards.yml`](../templates/caller-standards.yml):

```yaml
name: standards

on:
  pull_request:
    branches: [main, dev, sec]
  push:
    branches: [main, dev, sec]
  workflow_dispatch:

concurrency:
  group: standards-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name != 'schedule' }}

permissions:
  contents: read
  pull-requests: read

jobs:
  standards:
    uses: tzervas/mycelium-workflows/.github/workflows/reusable-standards.yml@main
```

That reports one status context: **`standards / standards`**. Read the next section before you
put that name in a ruleset.

---

## Read this before touching a ruleset

Adopting a reusable workflow **silently renames the status check**. The caller's job id is
prefixed onto the reusable workflow's job name and **the prefix cannot be suppressed**:

| where the job lives | context name |
|---|---|
| in-repo workflow with `jobs.standards.name: standards` | `standards` |
| via a caller with `jobs.standards: {uses: ...}` | `standards / standards` |

A ruleset that requires the bare `standards` will, the moment the caller lands, require a context
that **never reports**. The PR does not go red — it waits forever with nothing to diagnose.

**Migration order is fixed:**

1. Land the caller workflow. Let it run once and confirm the context name in
   `gh pr checks <n>`.
2. *Then* add that exact name to the ruleset.

That order leaves a window where a required context is missing, which blocks merges — the safe
direction. The reverse order leaves a window where nothing is required at all, and PRs merge
unverified.

```bash
# 1. find the exact context name after the caller has run once
gh pr checks <n> --repo tzervas/<repo>

# 2. inspect the current ruleset before editing it
gh api repos/tzervas/<repo>/rulesets --jq '.[] | {id, name, target}'
gh api repos/tzervas/<repo>/rulesets/<id> \
  --jq '.rules[] | select(.type=="required_status_checks")'
```

---

## The rules

Mode is per rule: `enforce` (fails the job), `warn` (annotates only), `off` (does not run).
Mechanical, objectively-checkable rules default to `enforce`; rules where judgement is involved
or where pre-existing repo state is likely to trip them default to `warn`.

| # | input | default | what it checks |
|---|---|---|---|
| 1 | `promote-merge-mode` | **enforce** | `dev` → `main` (and `main` → `dev`/`sec`) must land as a **merge commit** |
| 2 | `branch-targeting` | **enforce** | feature/fix PRs base `dev`; promotes, hotfixes and releases are allowed *explicitly* |
| 3 | `protected-refs` | **enforce** | no workflow force-pushes, hard-resets or deletes `main`/`dev`/`sec`/`release/**` |
| 4a | `version-policy` | **enforce** | repo stays `0.x.x`; major ≥ 1 requires the `human-authorized-1x` label |
| 4b | `version-drift` | warn | manifest version and `.cz.toml` version must agree |
| 5 | `exit-contract` | warn | no `continue-on-error` / `\|\| true` on a security, lint or test gate |
| 6 | `yaml-validity` | **enforce** | every workflow parses with `yaml.safe_load`, and every heredoc closes |
| 7 | `schedule-cancel` | **enforce** | a scheduled workflow must not carry `cancel-in-progress: true` |
| 8 | `python-floor` | warn | no `python-version` below `python-min` (default 3.11) |
| 9 | `conventional-title` | **enforce** | PR titles are conventional commits |
| 10 | `docs-with-change` | warn | behaviour changed and no docs moved with it |
| 11 | `trunk-divergence` | **enforce** | `main` and `dev` still share a merge base |
| 12 | `actionlint` | off | runs `actionlint` if the binary is on the runner |

### 1. Promote merge mode — the one that matters

```
work branch  --SQUASH-->  dev  --MERGE COMMIT-->  main
```

**Squash on the work-branch edge is the fleet standard and is deliberately never flagged.** A
check that nags about standard practice gets disabled, and then it is not checking the thing that
matters either.

The `dev` → `main` promote is different, and it is the single most expensive mistake in the flow.
Squashing it rewrites the promote into a *new* commit with no ancestry link, so `main` and `dev`
end up with **identical trees and disjoint histories**. Git then has no merge base between them,
and every PR later retargeted at `dev` renders thousands of lines of already-merged work as
conflict.

Measured on this fleet, from exactly this cause:

| repo | damage |
|---|---|
| gha-runner-ctl | merge base stuck at `ace4fe3`, ~3,600 lines of phantom diff |
| tg-agent-relay | `dev` 17 commits / ~5,700 lines behind, with **zero unique content** |
| four ML-rust repos | 14 PRs left `DIRTY` — unable even to produce a merge ref |

A merge commit costs one extra node in the graph and buys a true merge base forever. It is also
what makes **parallel work** possible: with a real merge base, two branches cut from `dev` that
touch disjoint files merge cleanly. Without one, *every* branch conflicts with every other,
because git believes they share no history.

What the rule does on an ancestry-critical PR:

* **fails** if auto-merge is armed with `SQUASH` or `REBASE` — that is a machine that will do the
  damage unattended;
* **fails** if the repo has `allow_merge_commit=false`, because the correct button does not exist;
* **fails** if `allow_rebase_merge=true`, which reaches the same disjoint history a different way;
* always emits a **notice** telling the merger to press "Create a merge commit". The notice never
  fails the job — it fires on correct promotes too.

The repo-settings half needs a token that can see the `allow_*` fields. The default
`GITHUB_TOKEN` cannot, and the checker says **"settings not asserted"** rather than guessing —
absent is not `false`. Pass `secrets: {token: ...}` with repo-admin read to enable it.

### 2. Branch targeting, and the repo with no `dev`

Feature/fix PRs base `dev`. Exceptions for `main` are listed **explicitly** rather than
tolerated by omission: heads matching `main-allowed-heads` (default `dev`, `sec`, `release/**`,
`hotfix/**`, `revert-*`) or a `hotfix` / `promote` / `release` label.

If the integration branch **does not exist on origin**, the rule reports *empty* and passes. A
rule demanding a target that does not exist is red for a reason nobody can act on, and that is
how red stops meaning anything. `mycelium-workflows` itself is such a repo — verified when this
gate failed its own first PR for targeting `main`, which was the only branch available. Point
`integration-branch` elsewhere if your repo integrates somewhere other than `dev`.

### 11. Trunk divergence — the post-merge detector

This is the backstop for rule 1: it measures the damage rather than the intent, so it catches a
squashed promote that happened before this gate existed, or on a repo that has not adopted it.

* **no merge base at all** → error, with the one-time `--allow-unrelated-histories` reconciliation;
* **identical trees, `dev` behind, zero unique commits on `dev`** → error. That is the squashed-
  promote fingerprint;
* **`main` ahead of `dev`** → warning with the measured phantom diff. That is the ordinary window
  between a promote and its back-merge, and it is worth stating because the number shown is
  exactly what every branch cut from `dev` will be asked to resolve.

Because it measures repository state rather than the PR, it runs on `push` too. That is why the
caller template triggers on both.

### 5. Exit contract — empty is not unknown

A gate that cannot go red is a gate that is off while looking on. Measured: qlora-rs #27 runs
`cargo install cargo-geiger` with `continue-on-error` and then the scan itself with `|| true`, so
"the tool could not build" reports **green**.

The rule flags `|| true`, `|| :`, `|| exit 0` and `|| echo` **only when the command the `||`
actually binds to is a gate binary**. `rustup component add rustfmt clippy || true` and
`echo "$(gitleaks version || true)"` are setup and banner lines, not gates, and are not flagged —
that precision is the difference between a check people act on and a check people mute.

The fix is always the same shape:

```bash
set -euo pipefail
command -v cargo-geiger >/dev/null || { echo "::error::tool unavailable"; exit 1; }  # UNKNOWN
out=$(cargo geiger --output-format Json)              # tool failure -> non-zero -> job fails
[ -n "$out" ] || { echo "no unsafe usage found"; exit 0; }   # EMPTY is a real answer
```

### 6. YAML validity — the column-0 heredoc

A `python3 <<'PY'` heredoc whose body or terminator sits at **column 0** dedents out of the
enclosing `run: |` block scalar and terminates it. The workflow then reports `startup_failure`:
no steps, no logs, and nothing that looks like a broken gate. This broke
`reopen-issues-closed-off-main.yml` in **15 of 22 repos** in this fleet, and it read as merely
"red for no reason" for weeks.

Indent the whole heredoc — opener, body and terminator — to the block scalar's indentation. YAML
strips the common indentation, so the shell still sees the terminator at column 0.

### 7. Scheduled + `cancel-in-progress`

On self-hosted runners a scheduled job **queues** when no runner is free. The next scheduled tick
then cancels the queued run, and a cancelled run reports `cancelled`, not `failed`. Nothing
alerts, no badge turns red, and the job silently never runs again.

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name != 'schedule' }}
```

### 10. Docs with the change — warn by design

If a PR changes source outside tests and touches no docs, this **warns**. It does not hard-fail,
because judgement is involved. Doc comments added inside the source diff (`///`, `//!`, a
docstring) count as docs — that is exactly the change-scoped documentation the contract asks for.

It warns rather than passes silently because stale docs are actively worse than missing ones:
they are *believed*. This fleet has produced three bugs where the documentation is what made them
invisible — a `rust-version` input that was documented, surfaced as a dropdown and silently
ignored; a `caller-ci.yml` comment asserting a job name that was wrong; and a sizing comment
claiming "clippy-only jobs are light" while clippy was being OOM-killed.

---

## Suppressing a finding

Two mechanisms, both deliberately visible in the diff:

* **`# standards-allow: <rule> — <reason>`** on the offending line. Works for `protected-refs`
  and `exit-contract`.
* **`(advisory)` in a step name** exempts that step from the `continue-on-error` half of
  `exit-contract`.

There is no global ignore file. A suppression that is not next to the thing it suppresses stops
being read.

---

## Runner sizing

`gha-runner-ctl::pool::size_for_job` checks `runs-on` **labels before** the job-name heuristic, so
an explicit size token in `runs-on` wins outright.

The default `runner-labels` here carries **no size token on purpose**. Verified 2026-07-25 against
`GET /repos/tzervas/gha-runner-ctl/actions/runners`: the fleet's only registered runner advertises
exactly `[self-hosted, Linux, X64, podman]`. Requiring `small` today would queue this job against
a label nothing serves — the same "waits forever with nothing red" failure this document opens
with.

Without a size label the job name `standards` matches none of the Micro name signals in
`src/pool.rs` and lands on the Medium catch-all (2 CPU / 4 GiB), which is ample for a Python
linter. **Once workers register size labels**, pass:

```yaml
with:
  runner-labels: '["self-hosted","linux","x64","podman","small"]'
```

Do not name the caller's job `lint` or give it a name containing `lint`, `fmt`, `security` or
`sbom` unless you also pass a size label: those names route to Micro (0.25 CPU / 512 MiB).

---

## Commands left for the operator

This workflow **never changes a repository setting**. Repo settings are the real lever for the
merge-mode rule, and they are the operator's to pull.

### Allowed merge methods

GitHub has **no per-target-branch merge-method setting**. The fleet needs squash for
work-branch → `dev` *and* merge commits for `dev` → `main`, so both must be enabled repo-wide and
the promote is protected by this check plus discipline, not by settings alone. Say that out loud
rather than pretending a settings command solves it.

What settings *can* do is remove the third, silently-damaging option and guarantee the correct
button exists:

```bash
# per repo — merge commits available, squash kept for the work-branch edge,
# rebase removed because it rewrites commits the same way squash does
gh api -X PATCH repos/tzervas/<repo> \
  -F allow_merge_commit=true \
  -F allow_squash_merge=true \
  -F allow_rebase_merge=false \
  -F delete_branch_on_merge=true

# verify
gh api repos/tzervas/<repo> \
  --jq '{merge: .allow_merge_commit, squash: .allow_squash_merge, rebase: .allow_rebase_merge}'
```

Apply across the fleet, pacing the calls (the search API is 30/hour; these are REST, but pace
anyway):

```bash
for r in gha-runner-ctl tg-agent-relay; do
  gh api -X PATCH "repos/tzervas/$r" \
    -F allow_merge_commit=true -F allow_squash_merge=true -F allow_rebase_merge=false
  sleep 1
done
```

### Protecting the trunk set

Rule 3 catches a workflow that *would* force-push a trunk. Only a ruleset stops a human:

```bash
gh api -X POST repos/tzervas/<repo>/rulesets \
  -f name='protec-trunk' -f target=branch -f enforcement=active \
  -f 'conditions[ref_name][include][]=refs/heads/main' \
  -f 'conditions[ref_name][include][]=refs/heads/dev' \
  -f 'conditions[ref_name][include][]=refs/heads/sec' \
  -f 'rules[][type]=deletion' \
  -f 'rules[][type]=non_fast_forward'
```

`non_fast_forward` is the force-push block; `deletion` is the delete block.

### Requiring this check

**Only after the caller has landed and reported once** (see the trap above):

```bash
gh api -X PUT repos/tzervas/<repo>/rulesets/<id> --input - <<'JSON'
{
  "rules": [
    {"type": "required_status_checks",
     "parameters": {"strict_required_status_checks_policy": true,
                    "required_status_checks": [{"context": "standards / standards"}]}}
  ]
}
JSON
```

### The 1.x authorization label

No agent may add this label. Create it so a human can:

```bash
gh label create human-authorized-1x --repo tzervas/<repo> \
  --description 'A human has authorized a 1.x.x version for this repo' --color B60205
```

---

## Running it locally

```bash
git clone https://github.com/tzervas/mycelium-workflows /tmp/mw
cd /path/to/your/repo
STD_REPO_ROOT=$PWD GITHUB_REPOSITORY=tzervas/your-repo \
  python3 /tmp/mw/scripts/standards_check.py
```

Every workflow input maps to an `STD_*` environment variable: `STD_MODE_<RULE_WITH_UNDERSCORES>`
for modes, `STD_TRUNK_BRANCHES` / `STD_PYTHON_MIN` / `STD_ONE_X_LABEL` / `STD_COMMIT_TYPES` /
`STD_MAIN_ALLOWED_HEADS` / `STD_INTEGRATION_BRANCH` / `STD_RELEASE_BRANCH` for parameters.

The self-test asserts every rule fires on a dirty fixture and stays silent on a clean one:

```bash
python3 scripts/standards_selftest.py
```

---

## Known limits

State these rather than let the gate imply more coverage than it has.

* **The merge button is not observable.** GitHub exposes the *armed auto-merge* method and the
  repo's *allowed* methods; it does not expose which button a human is about to press. Rule 1
  therefore closes the unattended path and teaches the attended one, and rule 11 detects the
  damage afterwards. It cannot prevent a determined human click.
* **Repo-settings assertions need a privileged token.** With the default `GITHUB_TOKEN` the
  `allow_*` fields are absent, and the checker reports "not asserted" instead of guessing.
* **`docs-with-change` cannot judge whether the docs are *right*.** It only sees that some moved.
* **`protected-refs` scans `.github/workflows` only** — not `scripts/`, not composite actions in
  other repos.
* **The exit-contract scanner is a shell heuristic, not a shell parser.** It joins continuation
  lines and resolves the command a `||` binds to, which covers the real cases measured here, but
  a sufficiently baroque one-liner can slip past.
* **`actionlint` 1.7.7 does not know `github.job_workflow_sha`** and reports
  `property "job_workflow_sha" is not defined` against `reusable-standards.yml`. The property is
  real and documented; the checker uses it so the script can never drift from the workflow that
  calls it. Lint this repo with:

  ```bash
  actionlint -ignore 'property "job_workflow_sha" is not defined'
  ```

  The **caller template lints clean with no ignores** — adopting repos are unaffected.

---

## Verification status

What was actually run, and what was not, stated plainly rather than implied.

**Verified locally** (2026-07-25):

* `yaml.safe_load` over every workflow and template in this repo — all parse.
* `actionlint 1.7.7` — clean with the single documented ignore above; the caller template is
  clean with none.
* `ruff check scripts/standards_check.py scripts/standards_selftest.py` — clean.
* `python3 scripts/standards_selftest.py` — 35 assertions, 0 failures. Every rule fires on its
  dirty fixture and stays silent on the clean one.
* The checker run against real clones of `gha-runner-ctl` and `tg-agent-relay`, where it
  reproduced known damage independently: `tg-agent-relay` `dev` measured **19 commits / 67 files
  / 5,865 insertions behind `main`**, and `gha-runner-ctl`'s merge base measured at **`ace4fe32`**
  — the same numbers the contract records.

**Verified in GitHub Actions** — `standards-selftest.yml` ran on `ubuntu-latest`
([run 30180007075](https://github.com/tzervas/mycelium-workflows/actions/runs/30180007075)):
the fixture suite passed, the checker ran against this repo, and `::error` annotations rendered
with their WHAT/WHY/HOW bodies intact. It **correctly failed its own first PR** under
`branch-targeting` — this repo has no `dev` branch, which is the bug that produced the
empty-not-red handling above.

**Not verified:**

* The **reusable** workflow (`reusable-standards.yml`) has never executed. Job-name prefixing
  into `standards / standards`, the `github.job_workflow_sha` checkout and the PyYAML install
  fallback chain are reasoned from documentation, not observed. Only the direct-invocation path
  in `standards-selftest.yml` has run.
* The fleet's only registered runner was **offline**, so no self-hosted execution path was
  exercised.
* The repo-settings half of rule 1 has never run against a token that can see the `allow_*`
  fields.
