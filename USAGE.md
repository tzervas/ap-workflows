# Usage

Centralized, parameterized workflows for the **Mycelium fleet** (249 non-archived
repos; the 7 archived ones are out of scope). Change policy once here instead of
opening a PR per repo.

## What lives where

| File | Kind | Purpose |
|---|---|---|
| `.github/workflows/reusable-rust-ci.yml` | `workflow_call` | fmt / clippy / check / test / doc / release build / bench / GPU |
| `.github/workflows/reusable-python-ci.yml` | `workflow_call` | ruff / ruff format / type check / pytest / coverage / build |
| `.github/workflows/reusable-shell-ci.yml` | `workflow_call` | shellcheck / parse / bats / shfmt |
| `.github/workflows/reusable-mycelium-ci.yml` | `workflow_call` | **prepped, NOT adopted** — myc-check real, build/test are failing placeholders |
| `.github/workflows/reusable-rust-security.yml` | `workflow_call` | gitleaks + trivy filesystem |
| `.github/workflows/control-panel.yml` | `workflow_dispatch` | the human-facing selector surface |
| `.github/dependabot.yml` | config | keeps the pinned actions here fresh for every caller at once |
| `templates/caller-ci.yml` | template | 1-call Rust wrapper a component repo installs |
| `templates/caller-python-ci.yml` | template | 1-call Python wrapper |
| `templates/caller-shell-ci.yml` | template | 1-call Shell wrapper |
| `templates/caller-security.yml` | template | scheduled security caller (no `cancel-in-progress` — see below) |
| `scripts/scope.py` | helper | single definition of `compiler-core` / `stdlib` / `tooling` / `all` |
| `scripts/rollout-callers.sh` | helper | install callers across the train, one PR per repo |

## One input vocabulary across languages

A caller reads the same regardless of language. Where a concept has no exact
analogue the name changes but the *position* does not:

| Rust | Python | Shell | Mycelium | meaning |
|---|---|---|---|---|
| `rust-version` | `python-version` | `shellcheck-version` | `mycelium-version` | the one pinned tool version |
| `depth` | `depth` | `depth` | `depth` | `lint` / `check` / `check+test` / `full` |
| `runner-labels` | `runner-labels` | `runner-labels` | `runner-labels` | JSON array for `runs-on` |
| `cargo-jobs` | `test-jobs` | — | `build-jobs` | parallelism; `0` = inherit |
| `all-features` | `all-extras` | `all-shells` | `all-features` | widen the checked surface |
| `deny-warnings` | `deny-warnings` | `deny-warnings` | `deny-warnings` | warnings are errors |
| `timeout-minutes` | `timeout-minutes` | `timeout-minutes` | `timeout-minutes` | job timeout |

Every one of them names its required job **`check`**, and every one **validates
`depth` and refuses loudly** on a bad value.

### What `depth` means per language

| depth | Rust | Python | Shell |
|---|---|---|---|
| `lint` | fmt + clippy | ruff + ruff format | shellcheck |
| `check` | + `cargo check` | + type check (only if configured) + byte-compile | + `bash -n` parse |
| `check+test` | + `cargo test` | + pytest | + bats where a suite exists |
| `full` | + `cargo doc -D warnings` | + coverage + `uv build` | + `shfmt -d` |

### Python version floor

`reusable-python-ci.yml` refuses any interpreter at or below **3.10** — the
single `python-version` and every cell of the optional `python-versions` matrix.
Supported: 3.11+; the default and the preference is **3.13**. An EOL matrix cell
is a green check that proves nothing about a supported runtime, so it is rejected
rather than quietly run.

The required context stays the single `check` job even when a matrix is
requested; matrix cells report as `check (py3.12)` and are advisory breadth.

### Languages deliberately not covered

**Go (4 repos)** and **TypeScript (2 repos)** have no reusable workflow here.
That is 6 repos out of 249 — the centralization payoff is what justifies the
maintenance surface, and at 6 repos it does not. Their existing in-repo
workflows keep running untouched. Adding them later is mechanical: copy the shape
of `reusable-shell-ci.yml`, which is the simplest sibling.

`Makefile` (2), `Dockerfile` (2), `HCL` (1) and `Batchfile` (1) repos likewise
keep whatever gate they have.

## Tiering: dev light, main stringent

The caller derives the tier from the branch under test — a PR's **base** branch,
or the pushed branch — so a PR *into* `main` is gated at main strength **before**
it merges, not after:

| tier | Rust depth | runner | bench | GPU |
|---|---|---|---|---|
| `dev` | `check+test` | GitHub-hosted | `compile` | off |
| `main` | `full` | self-hosted fleet | `run` | on where a GPU path exists |

`bench: run` at the main tier is the point: a benchmark that only *compiles* is
not a fresh benchmark. `bench: compile` (`cargo bench --no-run`) is the cheap dev
proof that the benches still build.

The GPU job asserts `nvidia-smi` **and** a visible `/dev/nvidia*` or `/dev/dxg`
device node, and fails `FAIL_ENV` when either is absent. Absent hardware never
reads as a passing GPU suite.

## Scheduled security scans do not cancel in progress

`templates/caller-security.yml` sets a `concurrency.group` and deliberately omits
`cancel-in-progress`. Cancelling an in-flight scheduled scan kills the run that
was going to find something and leaves a *cancelled* security status — neither
pass nor fail. Cancellation is right for CI on a fast-moving branch and wrong for
a scan whose whole value is that it finishes.

## Dependabot lives here, not in 249 repos

`.github/dependabot.yml` watches `github-actions` at the repo root **and** at
`.github/actions/app-token` (Dependabot does not recurse into composite actions
from the root entry), plus `terraform` under `terraform/`. Because every caller
resolves through this repo, one stale pinned action here is stale everywhere at
once — which is exactly why the bot belongs here rather than in each component.

## The selector story, stated honestly

GitHub Actions offers exactly **two** selector widgets, and neither is a radio button:

| Want | You get | Where it works |
|---|---|---|
| drop-down select | `type: choice` with `options:` | **`workflow_dispatch` only** |
| radio / toggle | `type: boolean` → a checkbox | dispatch and `workflow_call` |
| free text | `type: string` | both |
| number | `type: number` | both |

There is no radio-button input type. A `choice` renders as a dropdown, so
mutually-exclusive selection is served by `choice`; on/off is served by
`boolean`.

Critically, **`workflow_call` does not support `choice`** — only
string/number/boolean/environment. That is why:

- the **dropdowns live in `control-panel.yml`** (and in each caller's own
  `workflow_dispatch`), and
- the **reusable workflows take validated strings**. `reusable-rust-ci.yml`
  checks `depth` against `lint|check|check+test|full` and **refuses loudly** on a
  bad value instead of silently falling back to a default.

`runs-on` cannot be a plain string when you need a label *array*, so runner
selection is passed as a JSON array string and expanded with
`runs-on: ${{ fromJSON(inputs.runner-labels) }}`.

## Control panel

Actions → **Fleet control panel** → Run workflow:

| Input | Widget | Options |
|---|---|---|
| `scope` | dropdown | `this-repo-only`, `compiler-core`, `stdlib`, `tooling`, `entire-rust-train` |
| `action` | dropdown | `ci`, `security`, `ci+security`, `propagate-pins` |
| `depth` | dropdown | `lint`, `check`, `check+test`, `full` |
| `runner` | dropdown | `github-hosted`, `self-hosted-fleet` |
| `rust_version` | dropdown | `1.96.1`, `stable`, `beta`, `nightly` |
| `all_features` | checkbox | |
| `deny_warnings` | checkbox | |
| `dry_run` | checkbox | defaults **on** |

`dry_run` defaults to on: fan-out across 46 repos should be a deliberate second
click, not the first thing that happens on a mis-set dropdown.

Fanning out beyond `this-repo-only` needs **`FLEET_ACTIONS_TOKEN`** (Actions:
write) — *not* `FLEET_PROPAGATE_TOKEN`, because dispatching a workflow needs
neither Contents nor Pull requests. The workflow-scoped `GITHUB_TOKEN` cannot
reach other repositories at all, so without the secret the job **fails loudly**
rather than reporting a successful no-op.

Token scoping is not interchangeable across the three fleet tokens — see
**[TOKENS.md](TOKENS.md)**.

## Adding a repo to the train

Install `templates/caller-ci.yml` as `.github/workflows/ci.yml`:

```yaml
jobs:
  check:
    uses: tzervas/mycelium-workflows/.github/workflows/reusable-rust-ci.yml@v1
    with:
      depth: check+test
```

Then add the repo to the right list in `scripts/scope.py`.

Pin **`@v1`**, a moving major tag: minor and patch policy changes propagate
without a PR per repo, while a breaking change lands on `v2` and every caller
must opt in. `@main` is for developing this repo, not for callers.

## Preserving a required context when you centralize

A caller job that `uses:` a reusable workflow does **not** report a check named
after the caller job alone. If a repo's ruleset already requires a context by a
particular name (`gha-runner-ctl` requires `build`; `peft-rs` requires `Format
Check`, `Test Suite …` and others), keep a small job **with that exact name** in
the caller that `needs:` the reusable call and fails when it failed:

```yaml
jobs:
  ci:
    uses: tzervas/mycelium-workflows/.github/workflows/reusable-rust-ci.yml@v1
  build:                      # the name the ruleset requires
    name: build
    needs: [ci]
    if: always()
    runs-on: ubuntu-latest
    steps:
      - run: |
          [ "${{ needs.ci.result }}" = "success" ] || exit 1
```

This is the same aggregate-gate pattern `fleet-ci.yml` already uses for its
`gate` job. Without it, the required context never reports and the branch either
blocks forever or — if someone then drops the requirement — merges unguarded.
Auto-merge is armed fleet-wide, which makes this sharp.

## The rule that overrides the template

**Never weaken a check to fit the template.** If a repo's existing gate does
something the reusable workflow does not (cargo-audit, cargo-deny, cargo-geiger,
llvm-cov + Codecov, an MSRV job, a GPU suite), the PR that centralizes it
replaces **only the overlapping portion** and leaves the rest in place. Losing a
gate is not a refactor, it is a regression.

## Two names you must not change

`protec-main` and `protec-dev` require status-check **contexts** by name across
all 46 repos:

- `check` — the job in `reusable-rust-ci.yml`
- `gitleaks` and `trivy filesystem (vuln+secret+license)` — in
  `reusable-rust-security.yml`

Renaming a job silently un-gates every repo that requires it: the required
context never reports, so PRs either block forever or, if the requirement is
dropped, merge unguarded. Auto-merge is armed fleet-wide, which makes this sharp.

## Stringency ladder

| Branch | Required checks | Rationale |
|---|---|---|
| `dev` | `check` | GitHub-hosted, so a fleet outage cannot wedge dev |
| `main` | `check`, `cargo check/test`, `detect stack`, `gitleaks`, `trivy filesystem (vuln+secret+license)` | full fleet + security |

## Cargo parallelism

Leave `cargo-jobs: 0` (inherit). `gha-runner-ctl` exports `CARGO_BUILD_JOBS` equal
to the container's CPU quota, because `nproc` reports **host** cores inside a
cpu-limited container — cargo would otherwise spawn one rustc per host core (28
here) and blow the memory cap. Measured on `mycelium-codegen`: 333 MiB at `-j2`
versus **1848 MiB** at the unpinned default. Only set `cargo-jobs` explicitly if
you are overriding that deliberately.

## Inputs that exist so centralizing never costs coverage

| input | workflow | why it exists |
|---|---|---|
| `setup-command` | rust | some repos must patch sister-project git deps before cargo can resolve at all (`axolotl-rs/.github/scripts/patch-dependencies.sh`). Without the hook those repos cannot be centralized. |
| `clippy-extra-args` | rust | carries a repo's existing `-A clippy::…` allow-list across verbatim. Centralizing must not silently *raise* a repo's lint bar and break it; tighten it afterwards in a visible PR. |
| `release-build` | rust | `gha-runner-ctl`'s gate builds a release binary. Dropping that on migration would be a regression. |
| `test-env` | python | `tg-agent-relay`'s `tests/run-tests.sh` needs `RELAY_PYTHON` pointing at the synced venv. Literal `KEY=VALUE` lines with `$PWD` substituted; the value is never `eval`'d. |
| `test-command` | python | a repo's suite is not always bare `pytest`. |

## Fixed: `rust-version` was accepted and ignored

`reusable-rust-ci.yml` declared a `rust-version` input, documented it, and
`control-panel.yml` surfaced it as a dropdown (`1.96.1` / `stable` / `beta` /
`nightly`) and passed it through — but the toolchain step pinned the *action ref*
(`dtolnay/rust-toolchain@1.96.1`), which installs 1.96.1 regardless of any input.
Selecting `nightly` in the control panel silently ran 1.96.1.

It now uses `dtolnay/rust-toolchain@master` with `toolchain: ${{ inputs.rust-version }}`,
so the input and the dropdown behind it mean what they say. Default is unchanged
at `1.96.1`.
