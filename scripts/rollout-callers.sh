#!/usr/bin/env bash
# Migrate component repos to call the centralized reusable CI, one PR per repo.
#
# Dry-run by default. APPLY=1 to push and open PRs. Idempotent: skips any repo
# whose ci.yml already calls mycelium-workflows.
#
#   bash scripts/rollout-callers.sh                          # show the plan
#   SCOPE=stdlib bash scripts/rollout-callers.sh             # one group
#   APPLY=1 SCOPE=compiler-core bash scripts/rollout-callers.sh
#
# Migrate a small group first and let it go green before the whole train: the job
# name `check` is a required context in protec-main/protec-dev on all 46 repos, so
# a broken caller does not fail softly — it blocks merges.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OWNER=tzervas
SCOPE="${SCOPE:-all}"
APPLY="${APPLY:-0}"
BRANCH="${BRANCH:-ci/centralize-workflows}"
TEMPLATE="${TEMPLATE:-$ROOT/templates/caller-ci.yml}"

[ -f "$TEMPLATE" ] || { echo "error: missing $TEMPLATE" >&2; exit 2; }
command -v gh >/dev/null || { echo "error: gh required" >&2; exit 2; }

repos=$(python3 "$ROOT/scripts/scope.py" "$SCOPE" | python3 -c 'import json,sys; [print(r) for r in json.load(sys.stdin)]')

n=0 skipped=0
for full in $repos; do
  repo="${full#*/}"

  if gh api "repos/$OWNER/$repo/contents/.github/workflows/ci.yml" --jq '.content' 2>/dev/null \
      | base64 -d 2>/dev/null | grep -q "mycelium-workflows"; then
    echo "skip  $repo (already centralized)"
    skipped=$((skipped + 1))
    continue
  fi

  if [ "$APPLY" != "1" ]; then
    echo "would migrate -> $repo"
    n=$((n + 1))
    continue
  fi

  tmp=$(mktemp -d)
  git clone -q --depth 1 "https://github.com/$OWNER/$repo.git" "$tmp/$repo"
  mkdir -p "$tmp/$repo/.github/workflows"
  cp "$TEMPLATE" "$tmp/$repo/.github/workflows/ci.yml"

  git -C "$tmp/$repo" checkout -q -b "$BRANCH"
  git -C "$tmp/$repo" add -A
  if git -C "$tmp/$repo" diff --cached --quiet; then
    echo "skip  $repo (no change)"
    skipped=$((skipped + 1))
    rm -rf "$tmp"
    continue
  fi

  git -C "$tmp/$repo" -c user.name=mycelium-workflows -c user.email=noreply@github.com \
    commit -q -m "ci: call the centralized reusable Rust CI

Replaces this repo's local copy of the train's ci.yml with a single call to
tzervas/mycelium-workflows reusable-rust-ci.yml. 45 of 46 component repos
carried byte-identical copies, so any policy change previously meant 46 PRs.

The job name stays \`check\` because that is the required status-check context in
this repo's protec-main and protec-dev rulesets. Renaming it would silently
un-gate the branch, and auto-merge is armed fleet-wide.

Adds workflow_dispatch depth and runner dropdowns; push/PR keeps the previous
default gate (fmt + clippy -D warnings + test on ubuntu-latest)."
  git -C "$tmp/$repo" push -q -u origin "$BRANCH"

  gh pr create --repo "$OWNER/$repo" --base main --head "$BRANCH" \
    --title "ci: call the centralized reusable Rust CI" \
    --body "Replaces this repo's local \`ci.yml\` with one call to [\`mycelium-workflows\`](https://github.com/$OWNER/mycelium-workflows) \`reusable-rust-ci.yml@main\`.

45 of 46 component repos carried byte-identical \`ci.yml\` files, so a policy change meant 46 PRs. This makes it one commit in the central repo.

**The job name stays \`check\`** — that is the required status-check context in this repo's \`protec-main\` and \`protec-dev\` rulesets. Renaming it would silently un-gate the branch, which matters because auto-merge is armed fleet-wide.

Same gate as before on push/PR (fmt + \`clippy -D warnings\` + test on \`ubuntu-latest\`), plus \`workflow_dispatch\` dropdowns for depth and runner. CI-only; no source or manifest touched." >/dev/null

  gh pr merge --repo "$OWNER/$repo" --auto --squash "$BRANCH" >/dev/null 2>&1 ||
    echo "  warn: auto-merge not armed for $repo"
  echo "opened PR -> $repo"
  n=$((n + 1))
  rm -rf "$tmp"
done

echo
echo "scope=$SCOPE processed=$n already-centralized=$skipped apply=$APPLY"
[ "$APPLY" = "1" ] || echo "dry run — set APPLY=1 to push and open PRs"
