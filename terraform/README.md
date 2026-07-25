# Repo config as code

Manages the Rust train's repo settings and tiered branch protection declaratively.

**Validated:** `tofu init` + `tofu validate` → *Success! The configuration is
valid.* against the real `integrations/github` v6 provider schema. 92 import
blocks generated from live state.

## Why this, and not more GitHub App permissions

Managing rulesets requires **Administration: write**. That is deliberately *not*
granted to the propagation App, because an automation credential able to rewrite
`protec-main` could disable the very required checks that make fleet-wide
auto-merge safe.

So the powerful capability is separated by blast radius and gated behind a
*reviewed plan* rather than handed to a long-running automation:

| Credential | Can do | Gate |
|---|---|---|
| propagation App | push branches, open PRs, arm auto-merge | required checks |
| this Terraform credential | rewrite protections | a human-reviewed `tofu plan` in a PR |

## Why this matters more on a personal account

**Organization-level rulesets require the GitHub Team plan.** A personal account —
even **GitHub Pro** — cannot have them, and Pro does **not** carry over to an org
you create (a new org starts on GitHub Free for organizations).

This config delivers the main practical benefit of org rulesets — *one reviewable
source of truth for 46 repos* — with no org and no plan change. It still creates 46
per-repo rulesets, but from one file, with a diff.

It also fixes a class of bug by construction. The hand-made `protec-dev` used
`refs/heads/"dev"` with **literal quotes**, which matches no ref, so dev looked
protected and was not. A typo like that survives indefinitely in click-ops; in code
it shows up in review and in every subsequent plan.

## Use

```bash
cd terraform
tofu init
tofu plan          # adopts existing rulesets via imports.tf
tofu apply
```

`tofu plan` on a correct adoption reports **0 to add, 0 to destroy**. Anything else
means code and live state disagree — investigate before applying rather than
accepting the diff.

Credential: a fine-grained PAT (or separate App) with **Administration: write** on
the train. Pass it as `TF_VAR_github_token`, never commit it.

## Adding a repo

1. Add it to `scripts/scope.py`.
2. Regenerate the locals and imports:
   ```bash
   python3 ../scripts/gen-imports.py > imports.tf
   ```
3. `tofu plan`.

## Moving to an organization later

`var.owner` is the only thing that changes. Sequence matters:

1. Transfer the repos.
2. Re-point `var.owner`.
3. `python3 ../scripts/gen-imports.py <new-org> > imports.tf` — **ruleset IDs do
   not survive a transfer**, so stale imports would fail.
4. `tofu plan` and confirm 0 to add / 0 to destroy.

Secrets are **not** transferred with a repo, and rulesets may need recreating.
Plan the migration as its own change, not as a side effect of an unrelated apply.

## State

Local backend by default: fine for one operator, but it does **not lock**. Move to
a remote backend before a second person or a CI job applies, or two concurrent
applies can corrupt state.

## Not managed here (on purpose)

- **Secrets** — Terraform state would record them. Set via `gh secret set` or the UI.
- **The App itself** — registration is a browser flow.
- **Fleet host config** — `gha-runner-ctl` env files and systemd units are host
  state, not GitHub state. Ansible or an idempotent installer is the right tool.
