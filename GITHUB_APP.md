# GitHub App for the Rust-train automation suite

**Recommendation: yes, use one App for the whole Rust side.** It replaces
`FLEET_PROPAGATE_TOKEN` and `FLEET_ACTIONS_TOKEN`, and removes the need for
`FLEET_DISPATCH_TOKEN` to exist at all.

## Why, specifically

### 1. It is the only option that makes the propagation cascade work

Verified against GitHub's docs, not assumed:

> "events triggered by the `GITHUB_TOKEN` will not create a new workflow run"
> … "If you do want to trigger a workflow from within a workflow run, you can use
> a GitHub App installation access token or a personal access token instead"

The cascade depends on each wave's PR **actually running its checks** so auto-merge
can fire and move the HEAD for the next wave. With `GITHUB_TOKEN` the propagation
would open 42 PRs whose checks never run — they would sit forever, looking like a
fleet stall. An App token triggers them natively.

### 2. It removes the 46-copy secret problem — but not the way you'd guess

An App still has a secret: its private key. The win is *where it lives*. Keep the
key in `mycelium-lang` (and `ap-workflows` if you use the control panel),
mint a token per run, and **drop `fleet-notify.yml` entirely** — the umbrella's
2-hourly schedule already catches every advance.

Result: **zero credentials in any component repo.** Compare the alternative, where
`FLEET_DISPATCH_TOKEN` sits in up to 46 secret stores.

Do **not** push the private key into component repos to let them mint their own
tokens. That is strictly worse than a narrow PAT: it would put a train-wide
credential-minting key in 46 places.

### 3. Short-lived tokens

Installation tokens expire in **≤1 hour**. A leaked App token is time-boxed; a
leaked PAT is valid until someone notices and rotates it.

### 4. A separate rate-limit pool

Baseline **5,000 requests/hour per installation**, independent of your user
account's pool.

This is not theoretical here — during this work the *user* GraphQL pool was
exhausted (**5,979 used against a 5,000 limit**), which broke `gh pr list` and
`gh pr comment` mid-session and forced a fall back to REST. Fleet automation and
interactive use were competing for one budget. An App separates them.

**Honest caveat:** the "+50 requests/hour per repository above 20" scaling that
lifts the cap toward 12,500/hr applies to installations **on organizations**.
`tzervas` is a **user** account, so plan on the **5,000/hr baseline**, not more.
The benefit is isolation, not a bigger number.

### 5. One revocation point, clean attribution

Revoke or rotate in one place. Audit entries are attributed to the App rather than
to a human PAT, so automated pin bumps are distinguishable from your own commits.

## Create it

App registration is a browser flow — it cannot be done from the API, so this part
is yours.

**Settings → Developer settings → GitHub Apps → New GitHub App**

- **Name:** `mycelium-rust-fleet`
- **Homepage:** `https://github.com/tzervas/mycelium-lang`
- **Webhook:** uncheck **Active** (nothing receives webhooks yet)

**Repository permissions — grant exactly these:**

| Permission | Level | Needed for |
|---|---|---|
| **Contents** | write | push propagation branches; the lock-sync commit; `repository_dispatch` |
| **Pull requests** | write | open PRs; arm auto-merge (`enablePullRequestAutoMerge`) |
| **Actions** | write | control-panel fan-out; re-running failed jobs |
| **Checks** | read | confirm a wave is green before advancing |
| **Metadata** | read | mandatory, auto-selected |

**Deliberately NOT granted:**

- **Administration** — ruleset and branch-protection edits stay human-driven. An
  automation credential that can rewrite `protec-main` could disable the very
  gates that make auto-merge safe.
- **Workflows** — nothing here needs to rewrite workflow files.
- **Secrets / Actions variables** — never.

Then: **Install App → Only select repositories → the 46 train repos.** Not "All
repositories".

Finally **generate a private key** and record the **App ID**.

## Wire it up

Two secrets, in `mycelium-lang` (and `ap-workflows` only if you use the
control panel):

| Secret | Value |
|---|---|
| `MYCELIUM_APP_ID` | the numeric App ID |
| `MYCELIUM_APP_PRIVATE_KEY` | full PEM contents, including the BEGIN/END lines |

Then mint per run with the local composite action — **no third-party actions**,
matching the posture `release.yml` already states:

```yaml
      - id: app
        uses: tzervas/ap-workflows/.github/actions/app-token@main
        with:
          app-id: ${{ secrets.MYCELIUM_APP_ID }}
          private-key: ${{ secrets.MYCELIUM_APP_PRIVATE_KEY }}

      - env:
          GH_TOKEN: ${{ steps.app.outputs.token }}
        run: python3 scripts/fleet-propagate.py apply --wave 1 --automerge
```

`.github/actions/app-token/action.yml` signs the RS256 JWT with `openssl` and
exchanges it with `curl`. It backdates `iat` 60s for clock skew, uses a 9-minute
`exp` (GitHub caps App JWTs at 10 minutes), `shred`s the key file on exit, and
`::add-mask::`s the token before setting it as an output. The JWT construction was
verified end-to-end: header and payload decode to the expected JSON and the
signature checks out (`openssl dgst -verify` → `Verified OK`).

It refuses loudly when the App ID or key is missing, and when no installation
exists on the target account, rather than emitting an empty token that fails later
as an opaque 401.

## What it replaces

| Was | Becomes |
|---|---|
| `FLEET_PROPAGATE_TOKEN` on `mycelium-lang` | App token (Contents + Pull requests: write) |
| `FLEET_ACTIONS_TOKEN` on `ap-workflows` | same App (Actions: write) |
| `FLEET_DISPATCH_TOKEN` in up to 46 repos | **not created** — the schedule covers it |

## What an App does not solve

- **Ruleset and settings changes** need Administration, which is deliberately
  withheld. Those stay manual.
- **Merging into protected `main`** still requires the required checks to pass. The
  App does not and should not bypass `protec-main`.
- **Instant triggering** still needs either the schedule (current), or a webhook
  receiver. The App can subscribe to `push` across all installed repos, which is
  the App-native way to get sub-minute propagation later — but it needs a service
  to receive the webhook, so it is deliberately out of scope for now.
