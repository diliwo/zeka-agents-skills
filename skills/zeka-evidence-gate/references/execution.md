# Execution

Use Python 3.10+ and Git. No dependencies are installed and no manifest command is
executed. Examples use repository-relative paths; substitute safe task-specific values.

## Prepare and package

1. Inventory requirements and collect authorized evidence using project tooling.
2. Reconcile runner skip counts with a structured inventory and declared targets.
   Verify conditional skips against the recorded environment; required skipped scenarios
   need explicit untested/blocked records. Never substitute prose caveats for this mapping.
3. Produce a sanitized candidate `manifest.json` and its referenced artifacts in a
   private, ignored staging directory. Apply allowlisted export/redaction before disk
   capture. The helper does not consume raw logs to clean them afterward.
4. Hash sanitized artifact bytes with SHA-256 and record structured source results.
5. Ensure `.artifacts/` is ignored in the tested repository. Do not commit artifacts.
6. Package into a new directory:

```text
python skills/zeka-evidence-gate/scripts/evidence_gate.py init --input .artifacts/staging/manifest.json --output .artifacts/task-001 --repo .
```

`init` validates input and artifact bytes before writing, checks Git binding before
and after packaging, and creates both `manifest.json` and `report.md`. It refuses
existing output directories. File-system errors may leave an incomplete bundle;
never treat it as successful, and retry into a new directory after diagnosis.
The stored report records integrity-only freshness; run live verification immediately
before delivery to establish the current point-in-time state.

The helper does not invent measurements, collect native runner output, authenticate
external sources, execute arbitrary commands, modify ignore rules, commit or publish.

## Verify and report

```text
python skills/zeka-evidence-gate/scripts/evidence_gate.py verify .artifacts/task-001 --repo .
python skills/zeka-evidence-gate/scripts/evidence_gate.py verify .artifacts/task-001 --repo . --require-complete
python skills/zeka-evidence-gate/scripts/evidence_gate.py report .artifacts/task-001 --repo .
```

`verify` returns JSON. Exit 0 means valid evidence under the selected verification
mode, even if tests failed or were blocked. Exit 1 means invalid/unsafe/stale input
or an I/O failure. With `--require-complete`, exit 2 means valid input but incomplete
or not usable as current real evidence. Required-target completeness does not silently
fill a missing hierarchy level. The adapter reports any absent level as missing.

`report` prints deterministic Markdown; `--output` writes a new file only and requires
`--repo` to check output commit safety. Existing reports are never overwritten. A
report with current freshness is a point-in-time observation, not a perpetual guarantee.

For historical bundles or the shipped synthetic fixture:

```text
python skills/zeka-evidence-gate/scripts/evidence_gate.py verify skills/zeka-evidence-gate/tests/fixtures/synthetic-backend --offline
python skills/zeka-evidence-gate/scripts/evidence_gate.py report skills/zeka-evidence-gate/tests/fixtures/synthetic-backend --offline
```

Offline mode validates schema, artifacts and consistency, but does not claim current
Git freshness or protection from accidental commits. It cannot satisfy the review-loop
adapter or `--require-complete`. Only synthetic fixture files belong in source control.

## Review-loop adapter

```text
python skills/zeka-evidence-gate/scripts/evidence_gate.py export-review-loop .artifacts/task-001 --repo . --pr 123 --reference .artifacts/task-001/report.md
```

The reference identifies the generated human-readable report (a safe local or
published reference). Output is JSON for the existing `zeka-review-loop` envelope:
repository, PR, head SHA, focused, regression and protected_ci. Each level includes
status, head_sha, and a report-section reference. The producer binds the requested PR
to this repository/task; the helper does not fetch GitHub PR identity.

Mapping: passed→passed, failed→failed, blocked→unavailable,
untested→missing, absent level→missing. The export neither invents `not_required`
waivers nor promotes incomplete evidence. It rejects synthetic, stale and offline-only
evidence. Accounted expected skips outside a target's obligations do not change its
passing status; required targets left untested/blocked by skips still map to
missing/unavailable. Full required-check enumeration remains the collector's responsibility.

## Offline tests

```text
python -m unittest discover -s skills/zeka-evidence-gate/tests -v
```

Tests use temporary Git repositories and synthetic data, without live APIs, databases
or credentials. Run the existing review-loop suite when changing the adapter.
