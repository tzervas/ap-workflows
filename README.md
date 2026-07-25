# mycelium-workflows

Centralized, parameterized reusable workflows for the **Mycelium Rust train**.

The train is 46 component repositories that all carried byte-identical copies of
the same four workflows — 45 of 46 `ci.yml` files were literally identical. Any
policy change meant 46 PRs. This repo makes it one commit.

See **[USAGE.md](USAGE.md)** for the full interface and **[TOKENS.md](TOKENS.md)** for the
three-token model (they are *not* interchangeable — `FLEET_DISPATCH_TOKEN` is far
narrower than `FLEET_PROPAGATE_TOKEN`), **[GITHUB_APP.md](GITHUB_APP.md)** for the App
that replaces both, and **[SECRETS.md](SECRETS.md)** for the terminal-, log- and
agent-safe secret handling rules.

## Quick start

A component repo replaces its `ci.yml` with a single call:

```yaml
name: ci
on:
  push: { branches: [main, dev] }
  pull_request: { branches: [main, dev] }
jobs:
  check:
    uses: tzervas/mycelium-workflows/.github/workflows/reusable-rust-ci.yml@main
    with:
      depth: check+test
```

## Selector surface

Actions → **Fleet control panel** → Run workflow gives dropdowns for scope,
action, depth, runner and toolchain, plus checkboxes for `--all-features`,
`-D warnings` and `dry_run`.

Worth knowing up front, because it shapes the design: GitHub supports `type:
choice` (dropdown) and `type: boolean` (checkbox) **only on
`workflow_dispatch`** — `workflow_call` accepts just
string/number/boolean/environment, and there is no radio-button type at all. So
the dropdowns live in the dispatch surfaces and the reusable workflows take
validated strings that refuse loudly on a bad value. Details in USAGE.md.

## Branch-tier strictness

Strictness is chosen by **the branch a change is targeting**, not by anything a
caller sets. `reusable-fleet-ci.yml` resolves the tier once, centrally, in the
`detect stack` job — from `github.base_ref` on a pull request, `github.ref_name`
otherwise — against the `main-branches` input (default `main,master`). A caller
cannot get the policy wrong, because a caller does not compute it.

| | **dev tier** (`dev`, `devel`, `staging`, …) | **main tier** (`main` / `master`) |
|---|---|---|
| cargo | `check --workspace --all-targets`, `test --workspace` | the above **plus** a separate `--all-features` gate: `fmt --check`, `clippy -D warnings`, `check`, `test`, `doc` with `RUSTDOCFLAGS=-D warnings` |
| python | ruff + pytest on 3.13 | ruff + `ruff format --check` + pytest on 3.11, 3.12, 3.13 |
| GPU | skipped | **runs** on `[self-hosted, linux, x64, podman, gpu]` |
| benchmarks | skipped | **run fresh**, `CARGO_INCREMENTAL=0` |
| secrets | working-tree scan | full git-history scan |

The two rows that matter most are GPU and benchmarks. At main tier they must
**complete**, not skip — so both jobs assert they have something real to do and
fail loudly if not:

- `gpu tests` runs `nvidia-smi -L` first. No usable device and `gpu-required:
  true` (the default) is an **error**, not a green skip. A GPU gate that
  silently no-ops is worse than no gate, because it reads as coverage.
- `benchmarks` refuses to pass when it finds no `benches/` directory and no
  `[[bench]]` target.

Both are opt-in per repo (`gpu: true`, `bench: true`) because most repos have
neither, and a gate that fails on every repo is a gate everyone learns to ignore.

The `gpu` label is what routes to `SizeTier::Gpu` (4 CPU / 8 GiB + device
attach) in `gha-runner-ctl`; it is a real fleet tier, not a convention invented
here.

## Tag discipline

**Callers pin `@v1`, a moving major tag.** That single decision is what makes
"centrally keep the base workflows up to date" true in practice:

```yaml
uses: tzervas/mycelium-workflows/.github/workflows/reusable-fleet-ci.yml@v1
```

| change | what happens | who decides |
|---|---|---|
| patch / minor (`1.2.3` → `1.2.4`, `1.3.0`) | `v1` is repointed; every caller picks it up on its next run, with no PR in any repo | automatic, once `self-test` is green |
| **major** (`1.x` → `2.0.0`) | `v2` is created; **`v1` freezes exactly where it is** | a human, per repo, by editing one line |

`release-tag.yml` moves `v1` on every push to `main` whose `VERSION` still has
major 1 — and only after `self-test` has passed **for that exact commit**. It
polls rather than assumes, because for a tag that ~225 repos follow, "I could not
tell" has to behave like "no".

So a breaking change is not "a commit on `main`". It is an edit to `VERSION`
that raises the major. That edit is the gate, and it costs downstream repos
nothing until they choose to move.

Dependency bumps follow the same split (`.github/dependabot.yml` plus
`dependabot-automerge.yml`): minor and patch are grouped and auto-merged behind
`self-test`; **majors get their own PR, the `major-bump` label, and never
auto-merge** — they are both the breaking class and the only class that can
force a `v2`.

## Do not rename these jobs

Required status-check contexts in the `protec-main` / `protec-dev` rulesets:

| workflow | contexts |
|---|---|
| `reusable-fleet-ci.yml` | `detect stack`, `cargo check/test`, `python lint/test`, `no stack detected` |
| `reusable-fleet-security.yml` | `gitleaks`, `trivy filesystem (vuln+secret+license)` |
| `reusable-rust-ci.yml` | `check` |

Renaming one silently un-gates every repo requiring it — the context never
reports, so the PR either blocks forever or, if the requirement is then dropped,
merges unguarded. Auto-merge is armed on part of the fleet, which makes this
sharp. `self-test.yml` asserts these names on every push, so the failure is loud
here instead of silent there.

### …but centralizing renames them anyway. Read this before rolling out.

A job that runs **inside** a repo reports its own name as the check context:

```
detect stack
```

The same job reached **through a reusable workflow** is reported with the
*caller's* job name prefixed, and there is no way to suppress it:

```
fleet-ci / detect stack
```

Verified live on `tzervas/Multi-Enclave-Management-System_MEMS`, run
`30175067628`:

```
jobs=1
  fleet-ci / detect stack: queued  labels=self-hosted,linux,x64,podman
jobs=2
  fleet-security / gitleaks: queued
  fleet-security / trivy filesystem (vuln+secret+license): queued
```

So **the act of centralizing renames every required context**, whether or not
anyone intended it. `mycelium-core`'s `protec-main` currently requires `check`,
`cargo check/test`, `detect stack`, `gitleaks`,
`trivy filesystem (vuln+secret+license)` — after the caller lands, not one of
those ever reports again, and PRs wait forever on a context that no longer
exists.

This applies to `templates/caller-ci.yml` too: a caller job named `check`
invoking a reusable job named `check` reports **`check / check`**, not `check`.

`scripts/sync-required-contexts.sh` is the other half of the migration. Run it
**after** a repo's caller PR merges:

```
mycelium-core/protec-main:
    'check'  (unchanged)
    'cargo check/test'  ->  'fleet-ci / cargo check/test'
    'detect stack'  ->  'fleet-ci / detect stack'
    'gitleaks'  ->  'fleet-security / gitleaks'
    'trivy filesystem (vuln+secret+license)'  ->  'fleet-security / trivy filesystem (vuln+secret+license)'
```

The gap between merging the caller and syncing the ruleset is **fail-closed** —
old contexts stop reporting, new ones are not yet required, PRs block. Blocked is
the safe direction, and it is why the order is caller-first, ruleset-second.

Job names are **also** the fleet's sizing signal:
`gha-runner-ctl::pool::size_for_job` derives the container CPU/RAM tier from the
job name and `runs-on` labels. `cargo check/test` → Large, `cargo all-features
gate` → Xlarge, `benchmarks` → Large, `gitleaks` / `trivy …` → Micro. Renaming a
job silently changes its memory cap.

## Never put `cancel-in-progress: true` on a scheduled scan

A scheduled self-hosted workflow with an unconditional `cancel-in-progress: true`
will silently **never run** if the fleet is not polling that repo: the run queues
waiting for a runner, the next scheduled tick cancels it, and it reports
`cancelled` — not `failed`. Nothing alerts, and the repo looks scanned. Observed
live on this fleet (`tzervas/aNa`, `fleet-security` schedule runs reporting
`cancelled`). The caller template therefore uses:

```yaml
cancel-in-progress: ${{ github.event_name != 'schedule' }}
```

## The fleet, measured

The Mycelium train is 46 repos. The **fleet** is larger, and it had the same
problem one level up. Measured 2026-07-25 across 239 non-archived, non-fork
repos under `tzervas`:

| | repos | distinct byte-variants |
|---|--:|--:|
| carry `fleet-ci.yml` | 225 | **15** |
| carry `fleet-security.yml` | 225 | **6** |
| carry neither | 14 | — |

The variants are not per-repo policy; they are snapshots of the same file at
different dates. The two dominant `fleet-ci.yml` variants cover 212 repos and
differ only in the Rust-detection heuristic. On the security side the split is
material: **124 repos still ran the pre-hardening scan that pulled
`zricethezav/gitleaks:latest` unpinned and unauthenticated**, while 97 ran the
pinned-and-checksummed version.

`scripts/rollout-fleet-callers.sh` replaces both files with thin callers, one PR
per repo, dry-run by default. It preserves each repo's real branch list — a repo
whose PRs target `devel` gets `devel` in the trigger list, because that single
omission is why one repo had nine open PRs with literally zero checks — and it
detects GPU tests, benchmarks and pinned toolchains and passes them as inputs
rather than dropping them.

## Scope groups

`scripts/scope.py` is the single definition of the Rust train's groups, verified
to sum to the live train exactly:

| group | repos |
|---|--:|
| `compiler-core` | 5 |
| `stdlib` | 27 |
| `tooling` | 13 |
| `umbrella` | 1 |
| **`all`** | **46** |

## Status

`reusable-fleet-ci.yml` and `reusable-fleet-security.yml` are the fleet-wide
source of truth and are what `scripts/rollout-fleet-callers.sh` installs.
`reusable-rust-ci.yml` / `reusable-rust-security.yml` remain the Mycelium train's
narrower Rust-only gate (`check`) and are unchanged in contract.

Reusable-workflow support for the `*-myc` (self-hosted Mycelium) train comes once
that port is actively underway; nothing here presumes it.
