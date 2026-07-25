# Token model

Three tokens, three different jobs, three different scopes. **They are not
interchangeable, and `FLEET_DISPATCH_TOKEN` must not mirror
`FLEET_PROPAGATE_TOKEN`.**

Permission requirements below are from GitHub's
[fine-grained PAT permissions reference](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens),
not from assumption.

| Token | Lives in | Repo access | Permissions | Copies |
|---|---|---|---|--:|
| `FLEET_PROPAGATE_TOKEN` | `mycelium-lang` **only** | all 46 train repos + `mycelium-lang` | **Contents: write** + **Pull requests: write** | **1** |
| `FLEET_DISPATCH_TOKEN` | each component repo | **`mycelium-lang` only** | **Contents: write** | up to 46 |
| `FLEET_ACTIONS_TOKEN` | `mycelium-workflows` **only** | the train repos you want to fan out to | **Actions: write** | **1** |

## Why `FLEET_DISPATCH_TOKEN` is the narrowest of the three

Its entire job is one API call, from `templates/fleet-notify.yml`:

```
POST /repos/tzervas/mycelium-lang/dispatches   {"event_type":"component-advanced"}
```

`POST /repos/{owner}/{repo}/dispatches` requires **Contents: write** — on the
**target** repo, which is `mycelium-lang`. That is all.

It specifically does **not** need:

- access to the component repo it is stored in (`fleet-notify.yml` does not even
  check out — it makes one `curl` call and exits),
- **Pull requests: write** — it never opens a PR,
- **Actions: write** — `repository_dispatch` is not a workflow dispatch,
- access to the other 45 component repos.

**Scope it to exactly one repository: `tzervas/mycelium-lang`. Contents: write.
Nothing else.**

### The reason this matters more than usual

`FLEET_DISPATCH_TOKEN` is copied into **up to 46 separate repository secret
stores**. If it mirrored `FLEET_PROPAGATE_TOKEN`, then every one of those 46 repos
would hold a credential that can **push branches to, and open pull requests on,
all 46 repos**. Anyone able to influence a workflow in any single component repo
could pivot to the entire train.

Meanwhile the narrow version can do exactly one thing if leaked: fire a
`component-advanced` event at the umbrella. That triggers a propagation run which
was going to happen on the 2-hourly schedule anyway. The blast radius is a
duplicate CI run.

That asymmetry — 46 copies of a train-wide write credential versus 46 copies of a
"ring the doorbell" credential — is the whole argument.

## Why `FLEET_PROPAGATE_TOKEN` is broad, and why that is acceptable

`scripts/fleet-propagate.py apply` clones each repo, rewrites `rev` pins, pushes a
branch, opens a PR, and arms auto-merge. That genuinely needs **Contents: write**
(push) and **Pull requests: write** (open PR; arming auto-merge is the GraphQL
`enablePullRequestAutoMerge` mutation, also Pull requests: write) across every
repo it touches. It also needs **Contents: write** on `mycelium-lang` itself for
the lock-sync PR.

It is broad by necessity — but it lives in **exactly one repository**. One broad
credential in one place is a much smaller surface than a broad credential in 46.

## Why `FLEET_ACTIONS_TOKEN` exists separately

`control-panel.yml`'s fan-out only calls `gh workflow run`, i.e.
`POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches`, which requires
**Actions: write** — not Contents, not Pull requests.

Reusing `FLEET_PROPAGATE_TOKEN` there would have put a
push-and-open-PRs-on-46-repos credential into a second repository to do a job that
needs neither permission. It was written that way in the first draft and is
corrected; the workflow now names `FLEET_ACTIONS_TOKEN` and refuses loudly if it
is absent.

## Preferred alternative: a GitHub App instead of 46 PAT copies

The best answer to "46 copies of a secret" is **not to have 46 copies**. A GitHub
App installed on the train gives short-lived installation tokens minted per run,
so nothing long-lived sits in 46 secret stores, and revocation is one place.

This fleet already runs a GitHub App for `gha-runner-ctl` (the `ghs_` stateless
token work), so the pattern is established here.

Until that is wired up, the ranked options are:

1. **No `FLEET_DISPATCH_TOKEN` at all** — skip `fleet-notify.yml` entirely and let
   the umbrella's 2-hourly schedule catch every advance. Costs latency (up to 2h),
   costs zero credentials. This is the default the rollout script assumes.
2. **`FLEET_DISPATCH_TOKEN` scoped to `mycelium-lang` + Contents: write** — instant
   propagation, minimal blast radius.
3. **A GitHub App** — instant propagation, no long-lived secrets. Best end state.

Option 1 is genuinely fine. Nothing about correctness depends on the instant
trigger; only promptness does.

## Rotation

- `FLEET_PROPAGATE_TOKEN` and `FLEET_ACTIONS_TOKEN`: one repo each, so rotation is
  two secret updates.
- `FLEET_DISPATCH_TOKEN`: rotation touches every repo that has it. That cost is
  another reason to prefer option 1 or 3 above.
