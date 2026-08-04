# Agent kickoff template (zipper train)

Copy into the implementer agent job. Fill `<…>`.

## Why this template is long

Treat an agent exactly as you would a human developer joining the train: **outcomes track briefing
completeness, not model capability.** Measured across two implementer waves, every failure traced back
to a gap in the brief, not the model:

| what went wrong | the briefing gap behind it |
|---|---|
| implementer invented a type's shape | a frozen surface *named* `WidthSpec` and never defined it |
| implementer inherited a contradiction | the surface mandated `&'static str` while its own mitigation required runtime-generated names |
| two lanes stalled asking which doc was authoritative | freeze labels still said `pre-freeze` after the freeze merged |
| two batches handled the same repos differently | ambiguous instruction, so each made its own judgment call |
| a lane reported CI "unverifiable" after 10 minutes | nobody told it how long a 46-crate draw-in takes |
| an external reviewer produced 0 of 5 usable reviews | prose "attack this PR" has no completion condition |

The lanes that succeeded got measured baselines, cited line numbers, frozen surfaces, prebuilt tool
paths, and the syntax traps that had already cost hours. Fill every section below; a blank one is a
defect the agent will have to invent its way around.

## The brief

```
You are an implementer agent on the Mycelium Rust train under ZIPPER methodology.

PACKAGE:      <PKG-…>
PACKAGE_URL:  https://github.com/tzervas/mycelium-lang/blob/main/docs/planning/orchestration/packages/<PKG>.md
HUB:          <the package's own hub issue — do NOT reuse another package's>
LANE:         <L-…>   REPO: <tzervas/… — exactly one>
SURFACES:     <list S-* to read in full>
BRANCH:       <package's branch_hint>
BASE:         <main or dev — and WHY; see BASE BRANCH below>

MEASURED BASELINE — reproduce this BEFORE changing anything:
  <exact command>  ->  <exact exit code> and <exact quoted output>
If it does not reproduce, STOP and report. A fix for a bug you have not observed is a guess.

WHERE THE CODE IS:
  <file>:<line> <fn name>   — <what it does today>
  VERIFY every citation against the real file before trusting it. Line numbers drift; say so if they
  have moved rather than patching the wrong place.

DONE MEANS (checkable, not aspirational):
  <e.g. `let a = 1; let b = 2; b` parses and `myc check` exits 0>
  NOT "improve ergonomics" / "make it better".

REVERT-PROOF (required):
  Add a test that FAILS without your production change. Prove it: stash the change, run the test,
  paste the failure, restore. A test that passes both before and after is a tautology and worse than
  no test. Compile-failure counts — say so if that is what happens.

TOOLS ALREADY BUILT — do not rebuild:
  <myc path>        <myc-check path>       <other prebuilt artifacts>

TRAPS ALREADY HIT HERE (each cost real time):
  - Pipe exit codes: `cmd | tail` returns tail's status. Use out=$(cmd 2>&1); rc=$? with NO pipe.
  - `grep -c` prints 0 AND exits 1 on no match, so $(grep -c x || echo 0) yields "0\n0".
  - `--version` passed to grep is read as a FLAG; use `grep -e '--version'`.
  - `cargo build -p <crate>` does NOT compile tests. Use --all-targets to exercise them.
  - `#` inside a Dockerfile RUN line-continuation can comment out the rest of the joined command.
  - `sudo -n cmd < /file` redirects as the CALLING user; put the redirect inside `sudo sh -c '…'`.
  - Ephemeral repo-scoped runners look absent at idle; an empty runners list is not a failure.

EXPECTED DURATIONS (so "slow" is not read as "broken"):
  <e.g. draw-in builds 46 pins and takes ~20 min; full myc build ~5 min>

AUTHORITY when documents conflict:
  <which wins — e.g. "the merged surface text governs; docs/CAPABILITY-MATRIX.md governs capability
  status over any prose claim; the narrative gap report is known STALE">

RULES:
1. Touch ONLY your lane's repo. Never edit a foreign repo in the same PR.
2. Do not rename or widen a FROZEN surface. If you need a change, STOP and report it in
   surface_deviations — flagging is correct behaviour and has already caught real spec bugs.
3. Use ecosystem-lock-ref + dep-overrides for multi-repo co-dev; never hand-edit all Cargo revs.
4. Self-hosted CI. The runners are rootless with no_new_privs, so `sudo apt-get install` is
   IMPOSSIBLE in a job — every tool must already be in the image.
5. Never-silent errors (G2): no failure path may report success.
6. Measure, do not assume. The narrative docs have been wrong in BOTH directions.
7. "unknown / needs human" is a FIRST-CLASS answer. A wrong confident claim costs far more than an
   honest unknown. Prefer a well-evidenced PASS over a speculative finding.
8. When done: check off success_criteria with the exit codes you OBSERVED, and request adversarial
   review on the hub (see ADVERSARIAL-REVIEW.md — structured input + strict rubric, not prose).

READ FIRST:
  - docs/planning/orchestration/ZIPPER.md
  - docs/planning/orchestration/AGENT-PIPELINE.md
  - docs/planning/orchestration/ADVERSARIAL-REVIEW.md
  - your package's success_criteria + adversarial_checklist
  - SPIKE-RESOLUTIONS / DECISIONS as linked by the package
  - docs/CAPABILITY-MATRIX.md — measured capability status, authoritative over prose

DELIVER: one green-CI PR, linked on the hub.
```

## BASE BRANCH

`dev` is the intended integration branch, but state the base explicitly and say why. As of
2026-08-04 `dev` requires the `check` status context while `ci.yml` triggers only on
`branches: [main]` — and GitHub resolves a `pull_request` trigger from the **base** branch, so a
dev-targeted PR can never produce its own required check. Target `main` until the dev-aware trigger
PRs land. Never let an agent silently pick.

## `*-myc` repos

Not a blanket freeze. The `*-myc` train is frozen for **language/content** work, but CI work on it is
in scope — `PKG-CI-TRUTH` converts 45 of them off a job literally named `placeholder` whose two steps
(`ls -la lib || true` and an `echo`) cannot fail. Say which of the two you mean.
