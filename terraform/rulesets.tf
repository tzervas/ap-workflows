# Tiered branch protection: main is the most stringent, dev is lighter.
#
# The ladder is deliberate. `main` requires the full fleet CI + security set.
# `dev` requires only the GitHub-hosted `check` job, so that a self-hosted fleet
# outage cannot wedge development — it still enforces fmt, clippy -D warnings and
# tests, just without depending on fleet capacity.
#
# These required checks are what make fleet-wide auto-merge safe. With no required
# checks, GitHub auto-merge merges a PR as soon as it is armed, regardless of CI.

# ---------------------------------------------------------------- component main

resource "github_repository_ruleset" "component_main" {
  for_each = toset(local.component_repos)

  name        = "protec-main"
  repository  = each.key
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      required_approving_review_count   = 0
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_review_thread_resolution = false
    }

    required_status_checks {
      # false on purpose: strict mode forces branch-up-to-date, which would
      # serialise every merge behind a rebase. With 42 propagation PRs in flight
      # that turns a 9-wave cascade into a queue.
      strict_required_status_checks_policy = false

      dynamic "required_check" {
        for_each = local.component_main_checks
        content {
          context = required_check.value
        }
      }
    }
  }
}

# ----------------------------------------------------------------- component dev

resource "github_repository_ruleset" "component_dev" {
  for_each = toset(local.component_repos)

  name        = "protec-dev"
  repository  = each.key
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      # NOTE: the hand-made version of this ruleset used refs/heads/"dev" with
      # LITERAL QUOTES, which matches no ref, so dev was entirely unprotected
      # while appearing configured. Codifying it is how that stops recurring.
      include = ["refs/heads/dev"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      required_approving_review_count   = 0
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_review_thread_resolution = false
    }

    required_status_checks {
      strict_required_status_checks_policy = false

      dynamic "required_check" {
        for_each = local.component_dev_checks
        content {
          context = required_check.value
        }
      }
    }
  }
}

# -------------------------------------------------------------- umbrella (differs)

resource "github_repository_ruleset" "umbrella_main" {
  name        = "protec-main"
  repository  = local.umbrella_repo
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["~DEFAULT_BRANCH"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      required_approving_review_count   = 0
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_review_thread_resolution = false
    }

    required_status_checks {
      strict_required_status_checks_policy = false

      dynamic "required_check" {
        for_each = local.umbrella_main_checks
        content {
          context = required_check.value
        }
      }
    }
  }
}

resource "github_repository_ruleset" "umbrella_dev" {
  name        = "protec-dev"
  repository  = local.umbrella_repo
  target      = "branch"
  enforcement = "active"

  conditions {
    ref_name {
      include = ["refs/heads/dev"]
      exclude = []
    }
  }

  rules {
    deletion         = true
    non_fast_forward = true

    pull_request {
      required_approving_review_count   = 0
      dismiss_stale_reviews_on_push     = false
      require_code_owner_review         = false
      require_last_push_approval        = false
      required_review_thread_resolution = false
    }

    required_status_checks {
      strict_required_status_checks_policy = false

      dynamic "required_check" {
        for_each = local.umbrella_dev_checks
        content {
          context = required_check.value
        }
      }
    }
  }
}
