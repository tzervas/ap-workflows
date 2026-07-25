#!/usr/bin/env bash
# Replace each repo's copy-pasted fleet-ci.yml / fleet-security.yml with a thin
# caller into this repo. ONE PR PER REPO, never batched.
#
#   bash scripts/rollout-fleet-callers.sh                     # dry run, whole fleet
#   REPOS="a b c" bash scripts/rollout-fleet-callers.sh        # dry run, named repos
#   APPLY=1 REPOS="a b c" bash scripts/rollout-fleet-callers.sh
#
# WHY THIS EXISTS, MEASURED
# -------------------------
# 2026-07-25, 239 non-archived non-fork repos under tzervas:
#   * 225 carry fleet-ci.yml       in 15 distinct byte-variants
#   * 225 carry fleet-security.yml in  6 distinct byte-variants
# The variants are not intentional per-repo policy; they are snapshots of the
# same file at different dates. 124 repos still run the pre-hardening security
# scan that pulls `zricethezav/gitleaks:latest` unpinned and unauthenticated.
#
# WHAT IT PRESERVES
# -----------------
#   * job names — `detect stack`, `cargo check/test`, `python lint/test`,
#     `no stack detected`, `gitleaks`, `trivy filesystem (vuln+secret+license)`
#     are required contexts; renaming one un-gates the branch silently.
#   * every branch the repo currently builds on, plus its real dev-tier branch.
#     A repo whose PRs target `devel` gets `devel` in the trigger list — that
#     single omission is why 9 PRs in one repo had literally zero checks.
#   * repo-specific facts: GPU tests, benchmarks, and pinned toolchains are
#     detected and passed as inputs rather than dropped.
#
# WHAT IT REFUSES TO DO
# ---------------------
# It never removes a gate to make a repo fit the template. If a repo needs
# something the reusable workflow cannot express, add an input upstream.
#
# YOU ARE NOT DONE WHEN THESE PRs MERGE
# -------------------------------------
# A job reached through a reusable workflow reports as `<caller job> / <job>` —
# `fleet-ci / detect stack`, not `detect stack` — and the prefix cannot be
# suppressed. So merging a caller silently renames every required context in that
# repo. Run scripts/sync-required-contexts.sh immediately afterwards, per repo.
# The gap is fail-closed (PRs block rather than merge unverified), which is why
# the order is caller-first, ruleset-second.
set -euo pipefail

# NOTE: this script generates the caller bodies inline (heredocs below) rather
# than copying templates/, so it needs no $ROOT.
OWNER="${OWNER:-tzervas}"
APPLY="${APPLY:-0}"
BRANCH="${BRANCH:-ci/centralize-fleet-workflows}"
PIN="${PIN:-v0.1}"   # 0.x: the MINOR is the breaking position, so the moving tag is vMAJOR.MINOR
SLEEP="${SLEEP:-1}"
# Open the PRs as drafts. Use this while $PIN does not exist yet: a caller
# pinned at a tag that has not been published resolves to nothing, and the run
# fails with "unable to find reusable workflow". That red tick is correct — it
# is a gate doing its job — but the PR is not ready for a human either, so say
# so structurally rather than hoping someone reads the body.
DRAFT="${DRAFT:-0}"

command -v gh >/dev/null || { echo "error: gh required" >&2; exit 2; }
command -v jq >/dev/null || { echo "error: jq required" >&2; exit 2; }

api() { gh api "$@"; sleep "$SLEEP"; }

# ---------------------------------------------------------------------------
# Repo list
# ---------------------------------------------------------------------------
if [ -n "${REPOS:-}" ]; then
  repos="$REPOS"
else
  repos="$(gh api --paginate 'user/repos?affiliation=owner&per_page=100' \
    --jq '.[] | select(.archived==false) | select(.fork==false) | .name')"
fi

n=0 skipped=0 failed=0

for repo in $repos; do
  echo "----------------------------------------------------------------------"
  echo "repo: $repo"

  # -- idempotency: already calling us? ------------------------------------
  already=0
  for f in fleet-ci.yml fleet-security.yml; do
    if api "repos/$OWNER/$repo/contents/.github/workflows/$f" --jq '.content' 2>/dev/null \
        | base64 -d 2>/dev/null | grep -q "mycelium-workflows"; then
      already=$((already + 1))
    fi
  done
  if [ "$already" -ge 2 ]; then
    echo "  skip: already centralized"
    skipped=$((skipped + 1))
    continue
  fi

  # -- branch tiers --------------------------------------------------------
  # The trigger list must contain the branches this repo actually uses, or the
  # workflow never fires and the PR reports no checks at all.
  default_branch="$(api "repos/$OWNER/$repo" --jq '.default_branch' 2>/dev/null || echo main)"
  branches="$(api "repos/$OWNER/$repo/branches?per_page=100" --jq '.[].name' 2>/dev/null || true)"

  main_tier="$default_branch"
  dev_tier=""
  for b in dev devel development staging; do
    if printf '%s\n' "$branches" | grep -qx "$b"; then
      dev_tier="$dev_tier $b"
    fi
  done
  # A `main` alongside a default of `master` (or vice versa) is still main tier.
  for b in main master; do
    if [ "$b" != "$default_branch" ] && printf '%s\n' "$branches" | grep -qx "$b"; then
      main_tier="$main_tier $b"
    fi
  done

  trigger_list="$(printf '%s %s' "$main_tier" "$dev_tier" | tr ' ' '\n' | grep -v '^$' | sort -u | paste -sd, - | sed 's/,/, /g')"
  main_branches="$(printf '%s' "$main_tier" | tr ' ' '\n' | grep -v '^$' | sort -u | paste -sd, -)"
  echo "  triggers: [$trigger_list]   main-tier: $main_branches   dev-tier:${dev_tier:- none}"

  # -- repo-specific facts -------------------------------------------------
  root_entries="$(api "repos/$OWNER/$repo/contents" --jq '.[].name' 2>/dev/null || true)"
  has_cargo=0; printf '%s\n' "$root_entries" | grep -qx 'Cargo.toml' && has_cargo=1
  has_bench=0; printf '%s\n' "$root_entries" | grep -qx 'benches'    && has_bench=1

  # GPU: an existing gpu workflow, or a gpu/cuda feature in the manifest.
  has_gpu=0
  wf_entries="$(api "repos/$OWNER/$repo/contents/.github/workflows" --jq '.[].name' 2>/dev/null || true)"
  if printf '%s\n' "$wf_entries" | grep -qiE 'gpu|cuda'; then has_gpu=1; fi
  if [ "$has_cargo" = 1 ]; then
    manifest="$(api "repos/$OWNER/$repo/contents/Cargo.toml" --jq '.content' 2>/dev/null | base64 -d 2>/dev/null || true)"
    printf '%s' "$manifest" | grep -qE '^\s*(gpu|cuda)\s*=' && has_gpu=1
    printf '%s' "$manifest" | grep -qE '^\s*\[\[bench\]\]'  && has_bench=1
  fi

  # A pinned MSRV in the repo is repo-specific configuration, not something to
  # drop on the floor because the template has a default.
  rust_version=""
  if printf '%s\n' "$root_entries" | grep -qx 'rust-toolchain.toml'; then
    rust_version="$(api "repos/$OWNER/$repo/contents/rust-toolchain.toml" --jq '.content' 2>/dev/null \
      | base64 -d 2>/dev/null | grep -E '^\s*channel' | head -1 | sed -E 's/.*=\s*"?([^"]+)"?.*/\1/' || true)"
  fi
  echo "  cargo=$has_cargo gpu=$has_gpu bench=$has_bench rust-version=${rust_version:-<repo default>}"

  if [ "$APPLY" != "1" ]; then
    echo "  would migrate"
    n=$((n + 1))
    continue
  fi

  # -- build the two callers ----------------------------------------------
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' RETURN
  if ! git clone -q --depth 1 "https://github.com/$OWNER/$repo.git" "$tmp/$repo" 2>/dev/null; then
    echo "  FAIL: clone"
    failed=$((failed + 1))
    rm -rf "$tmp"
    continue
  fi
  mkdir -p "$tmp/$repo/.github/workflows"

  overrides=""
  [ "$has_gpu" = 1 ]      && overrides="$overrides      gpu: true"$'\n'
  [ "$has_bench" = 1 ]    && overrides="$overrides      bench: true"$'\n'
  [ -n "$rust_version" ]  && overrides="$overrides      rust-version: '$rust_version'"$'\n'

  cat > "$tmp/$repo/.github/workflows/fleet-ci.yml" <<EOF
# Fleet standard CI — thin caller. Policy lives in
# https://github.com/$OWNER/mycelium-workflows/blob/main/.github/workflows/reusable-fleet-ci.yml
#
# Strictness is chosen by the branch you are TARGETING:
#   dev tier  (-> ${dev_tier:-none}) check + test, one Python version, GPU/bench skipped
#   main tier (-> $main_branches) --all-features, clippy -D warnings, doc warnings-as-errors,
#             full Python matrix, and GPU jobs and benchmarks that RUN rather than skip.
# The reusable workflow resolves the tier itself, so this file cannot get it wrong.
#
# \`@$PIN\` is a MOVING tag. This repo is 0.x under \`major_version_zero = true\`,
# so the MINOR is the breaking position: central patch fixes land here
# automatically, and a breaking change is a deliberate, reviewed move to @v0.2.
name: fleet-ci

on:
  push:
    branches: [$trigger_list]
  pull_request:
    branches: [$trigger_list]
  workflow_dispatch:
    inputs:
      tier:
        description: 'Force a tier (otherwise derived from the target branch)'
        type: choice
        options: [auto, dev, main]
        default: auto

concurrency:
  group: fleet-ci-\${{ github.workflow }}-\${{ github.ref }}
  cancel-in-progress: true

permissions:
  contents: read

jobs:
  fleet-ci:
    uses: $OWNER/mycelium-workflows/.github/workflows/reusable-fleet-ci.yml@$PIN
    with:
      tier: \${{ inputs.tier || 'auto' }}
      main-branches: '$main_branches'
$overrides
EOF

  cat > "$tmp/$repo/.github/workflows/fleet-security.yml" <<EOF
# Fleet security scan — thin caller. Policy lives in
# https://github.com/$OWNER/mycelium-workflows/blob/main/.github/workflows/reusable-fleet-security.yml
#
# dev tier scans the working tree; main tier and the weekly schedule scan the
# full git history for secrets.
#
# The \`cancel-in-progress\` expression is load-bearing: a scheduled self-hosted
# scan under an unconditional \`true\` silently NEVER RUNS when the fleet is not
# polling this repo — it queues, the next tick cancels it, and it reports
# \`cancelled\` rather than \`failed\`, so nothing alerts.
name: fleet-security

on:
  push:
    branches: [$trigger_list]
  pull_request:
    branches: [$trigger_list]
  schedule:
    - cron: "17 7 * * 1"
  workflow_dispatch:

concurrency:
  group: fleet-security-\${{ github.workflow }}-\${{ github.ref }}-\${{ github.event_name }}
  cancel-in-progress: \${{ github.event_name != 'schedule' }}

permissions:
  contents: read

jobs:
  fleet-security:
    uses: $OWNER/mycelium-workflows/.github/workflows/reusable-fleet-security.yml@$PIN
    with:
      tier: auto
      main-branches: '$main_branches'
EOF

  # -- validate before pushing --------------------------------------------
  ok=1
  for f in fleet-ci fleet-security; do
    python3 -c "import yaml,sys;yaml.safe_load(open(sys.argv[1]))" \
      "$tmp/$repo/.github/workflows/$f.yml" >/dev/null 2>&1 || { echo "  FAIL: $f.yml does not parse"; ok=0; }
  done
  if [ "$ok" != 1 ]; then
    failed=$((failed + 1)); rm -rf "$tmp"; continue
  fi

  git -C "$tmp/$repo" checkout -q -b "$BRANCH"
  git -C "$tmp/$repo" add -A
  if git -C "$tmp/$repo" diff --cached --quiet; then
    echo "  skip: no change"
    skipped=$((skipped + 1)); rm -rf "$tmp"; continue
  fi

  git -C "$tmp/$repo" -c user.name=mycelium-workflows -c user.email=noreply@github.com \
    commit -q -F - <<EOF
ci: call centralized fleet workflows with branch-tier strictness

Replaces this repo's local copies of fleet-ci.yml and fleet-security.yml with
thin callers into tzervas/mycelium-workflows@$PIN.

Measured across 239 non-archived repos: 225 carried fleet-ci.yml in 15 distinct
byte-variants and fleet-security.yml in 6. The variants are drift, not policy.

Strictness is now chosen by the branch being targeted:
  dev tier  (-> ${dev_tier:-none}) check + test, one Python version (>= 3.11)
  main tier (-> $main_branches) --all-features, clippy -D warnings, doc
            warnings-as-errors, full Python matrix, and GPU jobs and benchmarks
            that RUN rather than report a green skip

Job names are unchanged — detect stack, cargo check/test, python lint/test,
no stack detected, gitleaks, trivy filesystem (vuln+secret+license) — because
they are required status-check contexts. Renaming one does not fail loudly; the
context simply stops reporting.

Also fixes the scheduled security scan: cancel-in-progress no longer applies to
schedule events. Under the previous unconditional setting a scheduled scan on an
unpolled repo queued, was cancelled by the next tick, and reported 'cancelled'
rather than 'failed' — so it never ran and nothing alerted.

@$PIN is a moving tag: central patch fixes propagate automatically. At 0.x the
MINOR is the breaking position, so a breaking change is a deliberate move to
@v0.2 and leaves @$PIN frozen.
EOF

  if ! git -C "$tmp/$repo" push -q -u origin "$BRANCH" 2>/dev/null; then
    echo "  FAIL: push"
    failed=$((failed + 1)); rm -rf "$tmp"; continue
  fi

  draft_flag=""
  staged_note=""
  if [ "$DRAFT" = "1" ]; then
    draft_flag="--draft"
    staged_note="> **Staged — do not merge yet.** This caller pins \`@$PIN\`, and that tag is published only once the central PR lands and \`release-tag.yml\` runs. Until then this PR's checks fail with *unable to find reusable workflow*, which is the gate working correctly. Mark it ready once \`@$PIN\` exists.

"
  fi

  url="$(gh pr create --repo "$OWNER/$repo" --base "$default_branch" --head "$BRANCH" $draft_flag \
    --title "ci: centralize fleet workflows with branch-tier strictness" \
    --body "${staged_note}Replaces this repo's local \`fleet-ci.yml\` and \`fleet-security.yml\` with thin callers into [\`mycelium-workflows\`](https://github.com/$OWNER/mycelium-workflows)\`@$PIN\`.

## Why

Measured 2026-07-25 across 239 non-archived, non-fork repos: **225 carry \`fleet-ci.yml\` in 15 distinct byte-variants** and \`fleet-security.yml\` in 6. That is drift, not per-repo policy — 124 repos still ran the pre-hardening scan that pulled \`zricethezav/gitleaks:latest\` unpinned and unauthenticated.

## Branch-tier strictness

| | dev tier (\`${dev_tier:-none}\`) | main tier (\`$main_branches\`) |
|---|---|---|
| cargo | \`check --workspace --all-targets\` + \`test --workspace\` | the above **plus** a separate \`--all-features\` gate: \`fmt --check\`, \`clippy -D warnings\`, \`test\`, \`doc\` with \`RUSTDOCFLAGS=-D warnings\` |
| python | ruff + pytest on 3.13 | ruff + \`ruff format --check\` + pytest on 3.11, 3.12, 3.13 |
| gpu | skipped | **runs** on \`[self-hosted, linux, x64, podman, gpu]\`, and fails if no device is present rather than reporting a green skip |
| benchmarks | skipped | **run fresh** (\`CARGO_INCREMENTAL=0\`), and fail if no bench target exists |
| secrets | working-tree scan | full git-history scan |

The tier is resolved centrally from \`github.base_ref\` / \`github.ref_name\`, so this caller cannot get it wrong.

## Job names are unchanged

\`detect stack\`, \`cargo check/test\`, \`python lint/test\`, \`no stack detected\`, \`gitleaks\`, \`trivy filesystem (vuln+secret+license)\` — these are required status-check contexts. Renaming one does not fail loudly; the context just stops reporting, and the PR either blocks forever or merges unguarded.

## Also fixes

\`cancel-in-progress\` no longer applies to \`schedule\` events on the security scan. Under the previous unconditional \`true\`, a scheduled scan on a repo the fleet was not polling queued, got cancelled by the next tick, and reported \`cancelled\` rather than \`failed\` — so it never ran and nothing alerted.

## Pin discipline

\`@$PIN\` is a **moving tag**. Central security and dependency fixes reach this repo with no PR here. This repo is \`0.x\` under \`major_version_zero = true\`, so the **minor** is the breaking position: a breaking change is a deliberate, reviewed move to \`@v0.2\`, and \`@$PIN\` freezes where it is.

CI configuration only — no source, no manifest touched." 2>&1)" || {
    echo "  FAIL: pr create: $url"
    failed=$((failed + 1)); rm -rf "$tmp"; continue
  }

  echo "  PR: $url"
  n=$((n + 1))
  rm -rf "$tmp"
  sleep "$SLEEP"
done

echo "======================================================================"
echo "migrated=$n already-centralized=$skipped failed=$failed apply=$APPLY"
[ "$APPLY" = "1" ] || echo "dry run — set APPLY=1 to push and open PRs"
