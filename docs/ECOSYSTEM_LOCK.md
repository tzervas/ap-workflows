# Ecosystem lock materialization (mycelium-*)

**Decision (2026-08-01):** adopt lock materializer now; accept
`ecosystem_lock_ref` + `dep_overrides` + package map as proposed.

## Precedence

1. **`dep-overrides`** (JSON, keyed by **lock pin / repo name**, not package name)
2. **`components.lock`** at `ecosystem-lock-ref` on `tzervas/mycelium-lang`
3. **Crate `Cargo.toml` git rev** (default when materializer is off)

## Package ≠ repo

Multi-crate pins (see `tzervas/mycelium-lang` `docs/PACKAGE_REPO_MAP.json`):

| Repo pin | Packages |
|----------|----------|
| mycelium-value | mycelium-value, dense, numerics, vsa |
| mycelium-runtime | interp, sched, cert, diag, select, vsa-decode, rt-abi |
| mycelium-core | core, stack, workstack |
| mycelium-codegen | codegen, mycelium-mlir |

Overrides apply to the **repo pin** and rewrite **all packages** from that rev.

## Caller usage (Tier-0 / multi-repo feature work)

```yaml
jobs:
  check:
    uses: tzervas/ap-workflows/.github/workflows/reusable-ci-rust.yml@v0.1
    with:
      depth: check+test
      ecosystem-lock-ref: main   # or a train tag / branch
      dep-overrides: '{"mycelium-runtime":"<wip-sha>","mycelium-l1":"<wip-sha>"}'
      train-version: v0.464.0
```

Empty `ecosystem-lock-ref` preserves pre-materializer behaviour.

## GPU / bench (decision: require GPU for bench=run)

For VSA/dense heavy suites on main:

```yaml
bench: run
bench-runner-labels: '["self-hosted","linux","x64","podman","gpu"]'
# or set gpu: true for the gpu job
```

Missing device is `FAIL_ENV`, never a green pass.

## Local

```bash
python3 scripts/materialize-ecosystem-deps.py \
  --lock-ref main \
  --overrides '{"mycelium-runtime":"..."}' \
  --out .cargo/config.toml
cargo check
```
