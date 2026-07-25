# mycelium-workflows

Centralized, parameterized reusable workflows for the **whole Mycelium fleet** —
not just the Rust train.

The Rust train is 46 component repositories that all carried byte-identical
copies of the same four workflows — 45 of 46 `ci.yml` files were literally
identical. Any policy change meant 46 PRs. This repo makes it one commit.

The fleet is larger than the train. Measured 2026-07-25 across **249
non-archived** repositories (the 7 archived repos are out of scope):

| primary language | repos | reusable workflow |
|---|--:|---|
| Rust | 93 | `reusable-rust-ci.yml` |
| Shell | 49 | `reusable-shell-ci.yml` |
| *(none detected)* | 48 | — no code gate to centralize |
| Python | 47 | `reusable-python-ci.yml` |
| Go | 4 | not covered — see USAGE.md |
| TypeScript | 2 | not covered — see USAGE.md |
| Makefile | 2 | — |
| Dockerfile | 2 | — |
| HCL | 1 | — |
| Batchfile | 1 | — |

47 of those non-archived repos are the `*-myc` native-language train.
`reusable-mycelium-ci.yml` is **prepped and deliberately not adopted** — see
below and the header of the file itself.

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
    uses: tzervas/mycelium-workflows/.github/workflows/reusable-rust-ci.yml@v1
    with:
      depth: check+test
```

Swap `reusable-rust-ci.yml` for `reusable-python-ci.yml` or
`reusable-shell-ci.yml` and the caller is otherwise identical — the input names
and semantics are the same across languages on purpose.

## Version pin: `@v1` is a moving major tag

Callers pin `@v1`, not `@main` and not a SHA:

* **minor / patch changes propagate automatically.** A policy fix reaches every
  caller without a PR per repo — the entire reason this repo exists.
* **major changes do not.** A breaking change lands on `v2`; every caller opts in
  deliberately. That is the gate.

`v1` is force-moved to each new `v1.x.y` release commit. `@main` is for
development of this repo only; a caller pinning `@main` gets un-reviewed policy.

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

| workflow | state |
|---|---|
| `reusable-rust-ci.yml` | in use; rollout underway |
| `reusable-rust-security.yml` | in use |
| `reusable-python-ci.yml` | ready; rollout underway |
| `reusable-shell-ci.yml` | ready; not yet rolled out |
| `reusable-mycelium-ci.yml` | **prepped, NOT adopted — see below** |
| `control-panel.yml` | in use |

Component repos migrate one PR at a time; their existing in-repo workflows keep
running until a PR replaces the overlapping portion, so nothing regresses while
the migration lands.

### `reusable-mycelium-ci.yml` is not a working gate

It is committed so adoption later is a one-line caller change, and it refuses to
run unless the caller passes `acknowledge-not-adopted: true`.

Per the project's own status, ordinary multi-statement Mycelium programs that
contact the host cannot yet compile and run end-to-end — the accept↔instantiate
frontier of DN-50, and the `Declared` posture of every `*-myc` `DELIVERY.md`. So:

* the **checker** step (`myc-check --project lib`) is real — it is what the train
  already runs by hand;
* the **build** and **test** steps are explicit placeholders that **fail loudly**.
  They are not `echo ok`, because a fabricated green gate on 47 repos is worse
  than no gate at all.

Do not roll this out. Do not wire its `check` job into branch protection.
