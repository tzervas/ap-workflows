# Compose-down action pins

**Package:** PKG-ORCH-WORKFLOWS  
**Source of truth:** [`pins/actions.yml`](../pins/actions.yml)

## Why

Component repos should not each maintain `actions/checkout@vN`. They call
`tzervas/ap-workflows` reusables at `@v0.1`. Changing a major once here updates
the composed surface for the fleet.

## How to bump a major

1. Edit `pins/actions.yml`
2. Update every `uses:` in this repo to match
3. Run `python3 scripts/check-action-pins.py`
4. Merge; dependabot continues minor/patch hygiene

## Callers

```yaml
jobs:
  check:
    uses: tzervas/ap-workflows/.github/workflows/reusable-ci-rust.yml@v0.1
```

Do **not** re-pin checkout in callers for routine CI — the reusable already did.

## Rootless / minimal packages

Runner **images** (GHCR `runner-base`, etc.) apply rootless + no extra packages
**late** in image build workflows. Reusable CI assumes tools already present
(python3, curl, rustup via dtolnay action, etc.). Do not `apt-get` in component
CI lanes.
