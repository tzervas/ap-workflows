# Runner images: how they compose, and how a job selects one

The fleet's goal is a *small* number of static images that compose, not one image
per project. This file records how that works, the measured gap that made a
second image necessary, and how a workflow asks for one.

## The composition model already exists — use it, don't reinvent it

`gha-runner-ctl` (see its `docs/WORK_IMAGES.md`) resolves a work image from the
job's `runs-on` labels:

1. A job requests a label: `runs-on: [self-hosted, linux, x64, podman, rust]`
2. The listen pool maps that label to an OCI ref — built-in defaults for common
   distros, extended/overridden by `GHA_IMAGE_MAP` (`image-map.toml`/`.json`)
3. It forces `image-mode=external`, pulls per `GHA_PULL_POLICY` (default
   `missing` in external mode, so an image is pulled **once** and then cached)
4. It registers the ephemeral runner **with that label**, so GitHub routes the
   job to it

Two consequences worth internalising:

- **The job runs natively inside that rootfs.** There is no nested container, so
  the image is the job environment, full stop.
- **`actions/runner` is injected into a volume at spawn.** Images do NOT bake the
  runner in. That is the seam that makes images composable: any OCI rootfs can
  serve as a runner, so images only carry *tools*.

There are no long-lived bare runners. A persistent fleet manager allocates
ephemeral runners per job and tears them down, so "the runner" is whatever image
the labels selected.

## Why there is a second image (the measured gap)

Measured 2026-08-04 by running each image and probing for tools:

| tool | `ap-workflows/runner-base` | `scribe-cpu-build:dev` |
|---|---|---|
| `gh`, `trivy`, `sops`, `age`, `myc-check` | ✅ | ❌ |
| `cargo`, `rustc` | ❌ | ✅ |
| `shellcheck`, `python3`+`yaml`, `jq`, `git`, `curl` | ✅ | ✅ |
| `cc`, `musl-gcc`, `file` | ❌ | (partial) |

The two images were **complementary, and neither could run a mycelium CI job end
to end**. `GHA_IMAGE` pointed the CPU instance at `scribe-cpu-build:dev`, so
mycelium jobs got Rust but no `gh` — which is exactly why the `capability-matrix`
workflow died on `gh: command not found` and why several workflows grew
job-time downloads.

Under the fleet's egress posture — **deny by default**, allowances rare and
explicit — a job that fetches a tool at run time is a latent break, not a
convenience. The durable fix is an image where the whole job is already satisfied.

## `runner-rust` = `runner-base` + a pinned Rust toolchain

`images/runner-rust/Containerfile` derives from `runner-base` by **digest**, and
adds Rust 1.96.1 — deliberately the *same* pin `runner-base` already uses to build
`myc-check`, so the fleet has one Rust version rather than two that drift.

Why derived rather than more `apt` lines in the base: `runner-base` states the
rule itself — language toolchains belong in derived images so the common layer
stays fleet-wide and slow-moving. The base layer is shared by every derived
image, so the toolchain is the only incremental cost.

Non-obvious things that image build has to get right, all of which failed first:

- **`runner-base` has no C linker at all** — no `cc`, `gcc`, `ld`, `musl-gcc`.
  Copying in `cargo`/`rustc` alone yields a toolchain that compiles and then fails
  at link time, while `rustc --version` looks perfectly healthy.
- **`file` is absent from `ubuntu:24.04`.** The static-linkage assertion
  (`file … | grep static`) then fails because the *checker* is missing, reporting
  "not static" for a binary that is static — a false negative on a
  security-relevant gate. The build now fails loudly if `file` is missing.
- **`CARGO_HOME` must be world-writable.** Copied paths land root-owned; jobs run
  as a non-root uid under rootless podman and fail on first dependency fetch with
  an error that reads like a network problem.
- **glibc direction matters.** The base is `ubuntu:24.04` (glibc 2.39) and the
  pinned Rust image is bookworm (2.36). Copying 2.36-built binaries onto 2.39 is
  the *safe* direction; the reverse would break, and glibc is forward- but not
  backward-compatible.

The image proves itself at build time by **linking** a binary for both
`x86_64-unknown-linux-gnu` and `x86_64-unknown-linux-musl` and asserting the musl
one is static — version output alone would not have caught the missing-linker case.

## Selecting it from a workflow

Register the label once on the fleet host, in `image-map.toml`:

```toml
[images]
rust = "ghcr.io/tzervas/ap-workflows/runner-rust:<tag-or-digest>"
```

Then a job asks for it by label:

```yaml
jobs:
  build:
    runs-on: [self-hosted, linux, x64, podman, rust]
```

Prefer adding a label over editing every workflow's tool-install steps. The label
is the composition point; the image is an implementation detail behind it.

## Rules of thumb

- **Never fetch a tool at job time.** Put it in an image, vendor it, or fail
  loudly. A step that "usually works" because egress happened to be open is a
  latent break — and under deny-by-default it is simply broken.
- **Compiled job + follow-on checks should reuse the produced binary**, not
  rebuild it. Build once, then test and check against that artifact.
- **Don't shrink an image by deleting toolchain pieces a job might need.** That
  trades a fast pull for a mid-job failure. Specifically, do **not** try
  `rustup component remove rust-docs`: it is a measured no-op, because the upstream
  rust image already ships the minimal profile (`rustup component list --installed`
  returns only cargo, rust-std-gnu, rustc). Building with and without it gave the
  same 1.88 GB. The size lives in `/usr/local/rustup` (834M — musl std 219M, gnu std
  178M, plus rustc), and both stdlibs are load-bearing: gnu for `cargo test`, musl
  for static release binaries.
- **Pin bases by digest, not tag.** A moving `:main` silently changes the
  toolchain floor under every job that derives from it.
