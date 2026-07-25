# mycelium-workflows

Centralized, parameterized reusable workflows for the **Mycelium Rust train**.

The train is 46 component repositories that all carried byte-identical copies of
the same four workflows — 45 of 46 `ci.yml` files were literally identical. Any
policy change meant 46 PRs. This repo makes it one commit.

See **[USAGE.md](USAGE.md)** for the full interface.

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

## Do not rename these jobs

`check`, `gitleaks`, and `trivy filesystem (vuln+secret+license)` are required
status-check contexts in the `protec-main` / `protec-dev` rulesets on all 46
repos. Renaming one silently un-gates every repo requiring it — and auto-merge is
armed fleet-wide.

## Scope groups

`scripts/scope.py` is the single definition of the groups, verified to sum to the
live train exactly:

| group | repos |
|---|--:|
| `compiler-core` | 5 |
| `stdlib` | 27 |
| `tooling` | 13 |
| `umbrella` | 1 |
| **`all`** | **46** |

## Status

Bootstrap. `reusable-rust-ci.yml`, `reusable-rust-security.yml` and
`control-panel.yml` are in place; component repos are **not** yet migrated to call
them — their existing in-repo workflows still run, so nothing regresses while the
migration lands. Migration is a per-repo PR via
`scripts/rollout-callers.sh`, deliberately gated behind `APPLY=1`.

Reusable-workflow support for the `*-myc` (self-hosted Mycelium) train comes once
that port is actively underway; nothing here presumes it.
