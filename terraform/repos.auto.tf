# Generated from components.lock — the 45 component repos plus the umbrella.
# Regenerate with: python3 ../scripts/scope.py all
locals {
  component_repos = [
    "mycelium-bench",
    "mycelium-build",
    "mycelium-check",
    "mycelium-cli",
    "mycelium-cli-common",
    "mycelium-codegen",
    "mycelium-core",
    "mycelium-doc",
    "mycelium-fmt",
    "mycelium-l1",
    "mycelium-lint",
    "mycelium-lsp",
    "mycelium-proj",
    "mycelium-runtime",
    "mycelium-sec",
    "mycelium-spore",
    "mycelium-std-cmp",
    "mycelium-std-collections",
    "mycelium-std-conformance",
    "mycelium-std-content",
    "mycelium-std-core",
    "mycelium-std-dense",
    "mycelium-std-diag",
    "mycelium-std-error",
    "mycelium-std-fmt",
    "mycelium-std-fs",
    "mycelium-std-io",
    "mycelium-std-iter",
    "mycelium-std-math",
    "mycelium-std-numerics",
    "mycelium-std-rand",
    "mycelium-std-recover",
    "mycelium-std-runtime",
    "mycelium-std-select",
    "mycelium-std-spore",
    "mycelium-std-swap",
    "mycelium-std-sys",
    "mycelium-std-sys-host",
    "mycelium-std-ternary",
    "mycelium-std-testing",
    "mycelium-std-text",
    "mycelium-std-time",
    "mycelium-std-vsa",
    "mycelium-transpile",
    "mycelium-value"
  ]

  umbrella_repo = "mycelium-lang"

  all_repos = concat(local.component_repos, [local.umbrella_repo])

  # Required status-check contexts. These are JOB NAMES from the workflows; the
  # names are load-bearing — renaming a job silently un-gates every repo that
  # requires it, and auto-merge is armed fleet-wide.
  component_main_checks = [
    "check",
    "cargo check/test",
    "detect stack",
    "gitleaks",
    "trivy filesystem (vuln+secret+license)",
  ]

  # dev requires only the GitHub-hosted gate, so a self-hosted fleet outage
  # cannot wedge dev. It still enforces fmt + clippy -D warnings + tests.
  component_dev_checks = ["check"]

  umbrella_main_checks = [
    "components.lock format (Rust train)",
    "required OS/arch draw-in gate",
    "gitleaks",
    "trivy filesystem (vuln+secret+license)",
  ]

  umbrella_dev_checks = ["components.lock format (Rust train)"]
}
