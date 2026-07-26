# ap-workflows

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
    uses: tzervas/ap-workflows/.github/workflows/reusable-rust-ci.yml@v0.1
    with:
      depth: check+test
```

Swap `reusable-rust-ci.yml` for `reusable-python-ci.yml` or
`reusable-shell-ci.yml` and the caller is otherwise identical — the input names
and semantics are the same across languages on purpose.

## Version pin: `@v0.1` is the moving tag

Callers pin `@v0.1`, not `@main` and not a SHA. Full rules in
[Tag discipline](#tag-discipline) below; the short form:

* **patch changes propagate automatically.** `v0.1` is force-moved to each new
  `v0.1.x` release commit, so a policy fix reaches every caller without a PR per
  repo — the entire reason this repo exists.
* **breaking changes do not.** They land on `v0.2`; `v0.1` freezes, and every
  caller opts in deliberately. That is the gate.

`@main` is for development of this repo only; a caller pinning `@main` gets
un-reviewed policy.

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

Versioning is **semver via commitizen**, configured in
[`.cz.toml`](.cz.toml) — the same shape as `tzervas/gha-runner-ctl/.cz.toml`, so
there is one fleet convention rather than one per repo:

```toml
[tool.commitizen]
name = "cz_conventional_commits"
version = "0.1.0"
tag_format = "v$version"
version_scheme = "semver"
major_version_zero = true
```

### `major_version_zero = true` moves the breaking position

This repo is **0.x**, and under `major_version_zero = true` the **MINOR is the
breaking position**, not the major. `cz bump` maps a `feat!:` / `BREAKING
CHANGE:` commit to `0.1.x -> 0.2.0` and leaves the major at 0.

Everything downstream follows from that one fact:

**Callers pin `@v0.1`** — a moving `MAJOR.MINOR` tag, not a bare major.

```yaml
uses: tzervas/ap-workflows/.github/workflows/reusable-fleet-ci.yml@v0.1
```

| change | what happens | who decides |
|---|---|---|
| patch (`0.1.0` → `0.1.1`) | `v0.1` is repointed; every caller picks it up on its next run, with no PR in any repo | automatic, once `self-test` is green |
| **breaking** (`0.1.x` → `0.2.0`) | `v0.2` is created; **`v0.1` freezes exactly where it is** | a human, per repo, by editing one line |

**There is no `v1`, and there is not meant to be one.** A `v1` tag would assert a
stable interface this repo has not earned yet; leaving 0.x means editing
`.cz.toml` deliberately, not drifting into it. `release-tag.yml` refuses to
create a tag outside the `v0.*` series while `VERSION` is 0.x, and refuses to run
at all if `VERSION` and `.cz.toml` disagree. `self-test.yml` refuses a bare-major
pin anywhere in the tree.

**The repo currently has zero tags.** `v0.1.0` and the moving `v0.1` are cut by
`release-tag.yml` on the first push to `main` after this lands and after
`self-test` is green for that commit. Until then a caller pinned at `@v0.1` fails
with "unable to find reusable workflow" — which is why
`scripts/rollout-fleet-callers.sh` opens its PRs as drafts by default. That red
tick is correct: it is a caller pointing at policy that has not been published
yet, and it turns green by itself once the tag exists.

`release-tag.yml` moves `v0.1` on every push to `main` whose `VERSION` is still
in the 0.1 series — and only after `self-test` has passed **for that exact
commit**. It polls rather than assumes, because for a tag that ~225 repos follow,
"I could not tell" has to behave like "no".

So a breaking change is not "a commit on `main`". It is an edit to `VERSION`
that raises the breaking position. That edit is the gate, and it costs downstream
repos nothing until they choose to move.

Dependency bumps follow the same split (`.github/dependabot.yml` plus
`dependabot-automerge.yml`): minor and patch are grouped and auto-merged behind
`self-test`; **a dependency's major gets its own PR, the `major-bump` label, and
never auto-merges** — it is the breaking class, and the only class that can force
a `v0.2` of this interface.

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

| workflow | scope | state |
|---|---|---|
| `reusable-fleet-ci.yml` | fleet-wide (~225 repos) | source of truth; installed by `scripts/rollout-fleet-callers.sh` |
| `reusable-fleet-security.yml` | fleet-wide (~225 repos) | source of truth; installed by `scripts/rollout-fleet-callers.sh` |
| `reusable-rust-ci.yml` | Mycelium Rust train | in use; narrower Rust-only gate (`check`); rollout underway |
| `reusable-rust-security.yml` | Mycelium Rust train | in use |
| `reusable-python-ci.yml` | Python repos | ready; rollout underway |
| `reusable-shell-ci.yml` | Shell repos | ready; not yet rolled out |
| `reusable-mycelium-ci.yml` | `*-myc` train | **prepped, NOT adopted — see below** |
| `control-panel.yml` | this repo | in use |
| `self-test.yml` / `release-tag.yml` | this repo | this repo's own gate and tag mover |

The fleet-wide pair and the Rust-train pair coexist deliberately: the fleet pair
is the broad, language-detecting gate installed everywhere, and the Rust pair is
the train's narrower, deeper gate. The Rust pair's contract (`check`) is
unchanged.

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
