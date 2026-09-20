# zeka-agents-skills

Engineering skills developed while building Zeka with coding agents.

## Skills

- [zeka-pr-state](skills/zeka-pr-state/SKILL.md): standalone, read-only Git/GitHub
  observations, explicit expectations, exact-revision verification, ancestry and
  structural snapshot comparison. Keeps PR head, live branch and cached tracking
  refs distinct. Requires Python 3.10+, Git and authenticated GitHub CLI for live
  capture. See its [execution reference](skills/zeka-pr-state/references/execution.md)
  and [incremental integration plan](skills/zeka-pr-state/references/integration-plan.md).
  Neither existing consumer has been refactored.

- [zeka-evidence-gate](skills/zeka-evidence-gate/SKILL.md): behavior-first evidence
  manifests, reports and verification bound to an immutable revision, with structured
  provenance, explicit skipped-test accounting and a review-loop adapter. Requires
  Python 3.10+ and Git. See its
  [execution reference](skills/zeka-evidence-gate/references/execution.md).

- [zeka-review-loop](skills/zeka-review-loop/SKILL.md): bounded GitHub/Greptile review
  and correction with Zeka governance, SHA-bound evidence and a Chief handoff.
  Requires Python 3.10+, Git and an authenticated GitHub CLI for live collection.
  See its [execution reference](skills/zeka-review-loop/references/execution.md) for
  configuration, commands and provider limitations.

## PR-state workflow

Capture to a new ignored runtime path, verify explicit expectations, then compare
fresh captures before dependent work. Observed checks are separate from required
check obligations. Unavailable revision binding or incomplete collection fails
closed for assertions that need it. Base movement is classified separately from
head movement, leaving each consumer's freshness policy intact.

Inspect the synthetic fork example offline:

```text
python skills/zeka-pr-state/scripts/pr_state.py verify --snapshot skills/zeka-pr-state/tests/fixtures/fork-snapshot.json --expectations skills/zeka-pr-state/tests/fixtures/expectations.json
```

The result is explicitly synthetic, not live PR evidence. PR-state does not replace
review-loop governance or evidence-gate completeness and skip accounting.

## Evidence workflow

`zeka-evidence-gate` packages sanitized observations into `manifest.json` and a
human-readable `report.md`. It keeps focused, regression and protected CI evidence
separate and binds observations to an immutable commit SHA. Required targets define
what the bundle claims to prove; untested or blocked targets remain incomplete.

For passing unit/integration evidence, zero failures, at least one executed test and
a successful exit remain mandatory. Skipped tests may coexist with passing evidence
when every skip is accounted for by a stable test identity, reason, environment
condition and explicit relationship to required targets. The inventory must match
the runner's skipped count. A required scenario that was skipped must be represented
as untested or blocked, never passed. Reports show the skips and their completeness
effects; the review-loop adapter preserves those distinctions.

The producer declares test-to-target relationships. The verifier checks their
consistency; test names and TRX files do not automatically establish requirement
coverage. See the [evidence contract](skills/zeka-evidence-gate/references/evidence-contract.md)
and [manifest schema](skills/zeka-evidence-gate/references/manifest.schema.json).

Inspect the shipped synthetic example without asserting current-revision evidence:

```text
python skills/zeka-evidence-gate/scripts/evidence_gate.py verify skills/zeka-evidence-gate/tests/fixtures/synthetic-backend --offline
```

The [example report](skills/zeka-evidence-gate/tests/fixtures/synthetic-backend/report.md)
is intentionally incomplete and uses synthetic data. For real bundles, use
`verify <bundle> --repo <repository>` to check current Git identity and artifact
safety, adding `--require-complete` to require all declared targets to pass.
The [execution reference](skills/zeka-evidence-gate/references/execution.md) covers
packaging, reporting, exit codes and review-loop export.

Evidence supports Chief's final review; it does not grant merge readiness or replace
Hervé's final authority. Secret scanning is heuristic, and artifact hashes establish
consistency rather than authenticating the observations.

## Installation

Install by copying the desired folder from `skills/` into the skill directory
supported by your coding agent. Keep its scripts and references together.

## Validation

Run offline behavioral tests without installing dependencies:

```text
python -m unittest discover -s skills/zeka-pr-state/tests -v
python -m unittest discover -s skills/zeka-review-loop/tests -v
python -m unittest discover -s skills/zeka-evidence-gate/tests -v
```

Live evidence/review artifacts and environment-specific configuration must stay out
of this public repository. Store runtime evidence in ignored `.artifacts/` directories
or outside the tracked tree; only explicitly synthetic fixtures belong in source control. Helpers do not install dependencies, merge or force-push.
