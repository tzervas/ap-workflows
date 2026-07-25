# Repo settings and branch protection as code, for the Mycelium Rust train.
#
# WHY THIS EXISTS
# Rulesets and repo settings were applied to 46 repos with ad-hoc API loops.
# That works once and then rots: there is no diff, no review, no record of intent,
# and no way to tell whether repo 31 drifted. Codifying it makes the fleet's
# protection posture reviewable in a PR and re-appliable from scratch.
#
# It also buys the main practical benefit of ORGANIZATION rulesets — one source of
# truth for 46 repos — WITHOUT needing an organization. Org-level rulesets require
# the GitHub Team plan; a personal account (even Pro) cannot have them. This gives
# central management on a personal account, at no plan cost.
#
# CREDENTIALS
# Managing rulesets needs "Administration: write", which is deliberately NOT
# granted to the propagation App. Use a SEPARATE credential here, and gate apply
# behind a reviewed plan. Separating by blast radius is the point: the propagation
# App can push branches and open PRs but cannot rewrite the protections that make
# auto-merge safe.
#
# WORKFLOW
#   tofu init
#   tofu plan      # on PR, posted for review
#   tofu apply     # only after that PR merges
#
# STATE AND SECRETS
# Uses a local backend by default: fine for a single operator, but it does NOT
# lock. Move to a remote backend before a second person or a CI job applies.
#
# Terraform state records resource attributes IN PLAINTEXT, and `sensitive = true`
# hides values from console output only — it does nothing for state. Two defences,
# used together:
#   a. No secret is a managed resource here. Nothing sensitive enters state.
#   b. OpenTofu native state encryption (see ../SECRETS.md for the exact block).
#      This is a real reason to prefer OpenTofu over Terraform for this repo —
#      Terraform has no equivalent. Encrypt the PLAN as well as the state; a saved
#      plan carries the same values, so encrypting only state moves the leak.

terraform {
  required_version = ">= 1.6"
  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

variable "owner" {
  description = "Account (user or org) that owns the train"
  type        = string
  default     = "tzervas"
}

variable "github_token" {
  description = "Token with Administration: write on the train repos. Do not commit."
  type        = string
  sensitive   = true
  default     = null
}

provider "github" {
  owner = var.owner
  token = var.github_token
}
