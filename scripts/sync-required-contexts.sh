#!/usr/bin/env bash
# Re-point each repo's required status checks at the contexts a reusable workflow
# actually reports.
#
# THE PROBLEM THIS EXISTS TO SOLVE — verified live, 2026-07-25
# ------------------------------------------------------------
# When a job runs *inside* a repo, it reports its own name as the check context:
#
#     detect stack
#
# When the same job runs via a reusable workflow, GitHub prefixes the context
# with the CALLER's job name, and there is no way to suppress it:
#
#     fleet-ci / detect stack
#
# Measured on tzervas/Multi-Enclave-Management-System_MEMS, run 30175067628:
#
#     jobs=1
#       fleet-ci / detect stack: queued  labels=self-hosted,linux,x64,podman
#     jobs=2
#       fleet-security / gitleaks: queued
#       fleet-security / trivy filesystem (vuln+secret+license): queued
#
# So centralizing renames every required context, whether or not anyone meant to.
# tzervas/mycelium-core's `protec-main` requires exactly:
#
#     check, cargo check/test, detect stack, gitleaks,
#     trivy filesystem (vuln+secret+license)
#
# After the caller lands, not one of those ever reports again. The PR does not
# fail — it waits forever for a context that no longer exists. That is precisely
# the silent un-gating the README warns about, and the centralization itself is
# what triggers it. This script is the other half of the migration.
#
# ORDERING — this matters
# -----------------------
# Run this AFTER the repo's caller PR merges, not before. The window between the
# two is fail-CLOSED: the old contexts stop reporting, the new ones are not yet
# required, and PRs block. Blocked is the safe direction.
#
#   bash scripts/sync-required-contexts.sh                    # dry run, all repos
#   REPOS="a b c" bash scripts/sync-required-contexts.sh       # dry run, named
#   APPLY=1 REPOS="a b c" bash scripts/sync-required-contexts.sh
set -euo pipefail

OWNER="${OWNER:-tzervas}"
APPLY="${APPLY:-0}"
SLEEP="${SLEEP:-1}"
CI_JOB="${CI_JOB:-fleet-ci}"
SEC_JOB="${SEC_JOB:-fleet-security}"

command -v gh >/dev/null || { echo "error: gh required" >&2; exit 2; }
command -v jq >/dev/null || { echo "error: jq required" >&2; exit 2; }

# bare context -> context once it is reached through a caller job
map_context() {
  case "$1" in
    "detect stack"|"cargo check/test"|"python lint/test"|"no stack detected")
      printf '%s / %s' "$CI_JOB" "$1" ;;
    "gitleaks"|"trivy filesystem (vuln+secret+license)")
      printf '%s / %s' "$SEC_JOB" "$1" ;;
    *)
      # Anything else is repo-local and must be left exactly as it is. This
      # script only renames contexts it is certain it moved.
      printf '%s' "$1" ;;
  esac
}

if [ -n "${REPOS:-}" ]; then
  repos="$REPOS"
else
  repos="$(gh api --paginate 'user/repos?affiliation=owner&per_page=100' \
    --jq '.[] | select(.archived==false) | select(.fork==false) | .name')"
fi

changed=0 untouched=0 norules=0

for repo in $repos; do
  rulesets="$(gh api "repos/$OWNER/$repo/rulesets" --jq '.[]|"\(.id)\t\(.name)"' 2>/dev/null || true)"
  sleep "$SLEEP"
  if [ -z "$rulesets" ]; then
    echo "$repo: no rulesets"
    norules=$((norules + 1))
    continue
  fi

  while IFS=$'\t' read -r id name; do
    [ -n "$id" ] || continue
    rs="$(gh api "repos/$OWNER/$repo/rulesets/$id" 2>/dev/null)" || continue
    sleep "$SLEEP"

    contexts="$(printf '%s' "$rs" | jq -r '[.rules[]?|select(.type=="required_status_checks")
      |.parameters.required_status_checks[]?.context] | .[]' 2>/dev/null || true)"
    if [ -z "$contexts" ]; then
      echo "$repo/$name: no required status checks — nothing to re-point"
      echo "  note: a ruleset with zero required checks gates nothing. Auto-merge on top of it merges unverified."
      norules=$((norules + 1))
      continue
    fi

    dirty=0
    new_list=""
    while IFS= read -r ctx; do
      [ -n "$ctx" ] || continue
      mapped="$(map_context "$ctx")"
      [ "$mapped" != "$ctx" ] && dirty=1
      new_list="$new_list$mapped"$'\n'
    done <<< "$contexts"

    if [ "$dirty" = 0 ]; then
      echo "$repo/$name: already correct"
      untouched=$((untouched + 1))
      continue
    fi

    echo "$repo/$name:"
    while IFS= read -r ctx; do
      [ -n "$ctx" ] || continue
      m="$(map_context "$ctx")"
      if [ "$m" != "$ctx" ]; then
        echo "    '$ctx'  ->  '$m'"
      else
        echo "    '$ctx'  (unchanged)"
      fi
    done <<< "$contexts"

    if [ "$APPLY" != "1" ]; then
      changed=$((changed + 1))
      continue
    fi

    ctxs_json="$(printf '%s' "$new_list" | jq -R -s 'split("\n")|map(select(length>0))|map({context:.})')"
    payload="$(printf '%s' "$rs" | jq --argjson ctxs "$ctxs_json" '
      {
        name: .name,
        target: .target,
        enforcement: .enforcement,
        conditions: .conditions,
        bypass_actors: (.bypass_actors // []),
        rules: [ .rules[] |
          if .type == "required_status_checks"
          then .parameters.required_status_checks = $ctxs
          else . end ]
      }')"

    if printf '%s' "$payload" | gh api -X PUT "repos/$OWNER/$repo/rulesets/$id" --input - >/dev/null 2>&1; then
      echo "    updated"
      changed=$((changed + 1))
    else
      echo "    FAILED to update — leaving the ruleset alone rather than half-applying it" >&2
    fi
    sleep "$SLEEP"
  done <<< "$rulesets"
done

echo "======================================================================"
echo "rulesets-changed=$changed already-correct=$untouched without-required-checks=$norules apply=$APPLY"
[ "$APPLY" = "1" ] || echo "dry run — set APPLY=1 to write"
