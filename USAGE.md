# Usage

Centralized, parameterized workflows for the **Mycelium Rust train** (46 repos).
Change policy once here instead of opening 46 PRs.

## What lives where

| File | Kind | Purpose |
|---|---|---|
| `.github/workflows/reusable-rust-ci.yml` | `workflow_call` | fmt / clippy / check / test / doc, parameterized |
| `.github/workflows/reusable-rust-security.yml` | `workflow_call` | gitleaks + trivy filesystem |
| `.github/workflows/control-panel.yml` | `workflow_dispatch` | the human-facing selector surface |
| `templates/caller-ci.yml` | template | 1-call wrapper a component repo installs |
| `scripts/scope.py` | helper | single definition of `compiler-core` / `stdlib` / `tooling` / `all` |
| `scripts/rollout-callers.sh` | helper | install callers across the train, one PR per repo |

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
    uses: tzervas/mycelium-workflows/.github/workflows/reusable-rust-ci.yml@main
    with:
      depth: check+test
```

Then add the repo to the right list in `scripts/scope.py`.

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
