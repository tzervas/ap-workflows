# Secret handling: terminal-, log-, and agent-safe

The goal is that no key or token is ever readable in a shell history, a CI log, a
committed file, a state file, or by an automated agent reading the repo.

## The five places secrets actually leak

| # | Leak path | Mitigation used here |
|---|---|---|
| 1 | committed `.tfvars` / `.tf` | secrets are **never** managed in Terraform; `.gitignore` covers `*.tfvars`, `*.tfstate*` |
| 2 | **Terraform state in plaintext** | OpenTofu **native state encryption** (below) — and, more fundamentally, nothing sensitive is a managed resource |
| 3 | CI logs | `::add-mask::` on every derived value; `sensitive = true` on variables |
| 4 | shell history / process args | secrets passed via env, never as argv; key material written to `mktemp` and `shred`ed |
| 5 | an agent or human reading the repo | only ciphertext or references are ever committed |

### 2 is the one people miss

Terraform state records resource attributes **in plaintext**, including sensitive
ones. `sensitive = true` only hides values from *console output* — it does nothing
for state. So a repo with committed state is a repo with committed secrets.

Two defences, applied together:

**a. Do not manage secrets in Terraform at all.** `terraform/README.md` says so
explicitly: no `github_actions_secret` resources. If state never contains a secret,
state cannot leak one. This is the primary defence and it is free.

**b. OpenTofu native state encryption.** This is a genuine reason to prefer
OpenTofu over Terraform here — Terraform has no equivalent. Verified working on
OpenTofu 1.8.5 (`tofu validate` → *Success*):

```hcl
terraform {
  encryption {
    key_provider "pbkdf2" "main" {
      passphrase = var.state_passphrase   # from TF_VAR_state_passphrase, never committed
    }
    method "aes_gcm" "main" {
      keys = key_provider.pbkdf2.main
    }
    state {
      method = method.aes_gcm.main
    }
    plan {
      method = method.aes_gcm.main
    }
  }
}
```

Encrypt the **plan** too: a saved plan file contains the same attribute values as
state, so an encrypted state with a plaintext plan artifact just moves the leak.

## Where each secret lives

| Secret | Storage | Never |
|---|---|---|
| App private key (PEM) | GitHub Actions secret on `mycelium-lang` | in a component repo, in git, on disk beyond one step |
| App installation token | minted per run, ≤1 h TTL | persisted anywhere |
| Terraform admin credential | env `TF_VAR_github_token` at apply time | in `.tfvars`, in state |
| State passphrase | env `TF_VAR_state_passphrase` | in git |

## What the code already does

- **`app-token` action** writes the PEM to `mktemp`, `trap`s `shred -u` on exit, and
  `::add-mask::`s the minted token *before* setting it as an output. A token that is
  masked only after being echoed is already leaked.
- **`fleet-propagate.py`** never prints a token; it shells out to `gh`, which reads
  `GH_TOKEN` from the environment rather than argv (argv is world-readable via
  `/proc`).
- **Redaction when reading config.** Fleet env files hold `GH_TOKEN`. Reading them
  for diagnosis is legitimate; printing them is not. The pattern used was:

  ```bash
  sed 's/\(TOKEN\|KEY\|SECRET\)=.*/\1=***REDACTED***/I' cpu.env
  ```

  **Redact at the source of the read, not before display** — otherwise the raw
  value has already reached the terminal, the scrollback, and any transcript.

## For an agent or assistant working in this repo

These are the rules that keep automated help from becoming an exfiltration path:

1. **Never `cat` a file that may hold credentials.** Filter at read time (above).
2. **Never echo a variable** that came from `secrets.*` or a `*_TOKEN` env var.
3. **Never commit state or plan files.** `.gitignore` enforces it; do not `-f`.
4. **Never pass a token as a command-line argument** — `/proc/<pid>/cmdline` is
   readable and argv often lands in logs. Use env.
5. **Prefer `gh api` over hand-rolled `curl -H "Authorization: ..."`** so the token
   stays in the environment instead of being interpolated into a command string.
6. If a secret is exposed, treat it as **compromised and rotate** — App tokens
   expire in an hour, which bounds the damage, and is a further argument for the
   App over PATs.

## Recommended addition: SOPS + age

For anything that must be *versioned* rather than injected — fleet env files,
per-host config — use **SOPS with an `age` key**. Ciphertext is committed, plaintext
never is, and structure stays diffable so review still works.

It fits this setup well: no server (unlike Vault), one key file kept off-repo, and
an agent reading the repository sees only ciphertext. That makes "AI-safe" a
property of the storage rather than a rule someone has to remember.

The natural first candidate is
`/home/gha-agent/.local/share/gha-runner-ctl/instances/*.env`, which currently holds
a plaintext `GH_TOKEN` on the host and is not versioned at all.
