# Ledger, finding and evidence contracts (version 1)

Helpers use JSON, full lowercase 40-character SHAs and timezone-bearing timestamps.
This is a proposed adapter contract, not an existing zeka-evidence-gate schema. Map
actual evidence-gate output to this envelope and retain original artifact references.

A run contains `schema_version: 1`, `config`, optional active `stop_reason`, and
`iterations`. Each iteration embeds `snapshot`, `ticket`, `coverage`, accumulated
`findings`, `corrections` and `evidence`. Preserve raw snapshots/tickets and earlier
iterations. Artifacts are auditable records, not cryptographically signed attestations.

## Source coverage

Inventory source keys are `surface:id@SHA256_OF_BODY`. A changed body has a new key;
historical keys remain with their findings. Split prose into individual findings,
preserving source URLs, paths and lines. Deduplicate logical findings by retaining all
their source references. The helper does not infer severity or approval from prose.

Every current source needs an assessment:

```json
{
  "source_key": "reviews:42@BODY_HASH_FROM_INVENTORY",
  "finding_ids": ["F-001"],
  "rationale": "One behavior defect; remaining text describes reviewed changes."
}
```

An empty finding list needs an explicit no-findings rationale. Historical comments
must be accounted for too. Complete source coverage is checked mechanically; correctness
of the natural-language assessment remains the agent's responsibility.

## Finding contract

```json
{
  "id": "F-001",
  "source_keys": ["reviews:42@BODY_HASH_FROM_INVENTORY"],
  "summary": "An empty display label causes the formatter to throw.",
  "severity": "low",
  "component": "display formatter",
  "owner": "software",
  "flags": {
    "security": false,
    "tenant_isolation": false,
    "authorization": false,
    "data_integrity": false,
    "persistence_semantics": false,
    "runtime_privileges": false,
    "architecture_boundary": false,
    "scope_expansion": false,
    "cross_service_contract": false,
    "conflict": false
  },
  "reproduced": true,
  "disposition": "accepted/actionable",
  "state": "open",
  "evidence_refs": ["REPRODUCER_ARTIFACT_REFERENCE"],
  "decision": {
    "by": "Chief",
    "ref": "VERIFIED_DECISION_REFERENCE",
    "scope_ref": "APPROVED_SCOPE_REFERENCE",
    "head_sha": "FULL_SHA_AT_APPROVAL",
    "blocking": true,
    "action": "fix"
  }
}
```

Severity: `low|medium|high|critical|unknown`. Owner: `software|platform|mixed|unknown`.
All risk flags are required booleans. State: `open|corrected|dismissed|deferred`.
See governance.md for dispositions and reproduction requirements. Missing decisions
grant no correction authorization. Verify references against actual authority; JSON
fields cannot authenticate Chief or the final authority.

Mandatory stops require a separate `finding.adjudication` to resume:

```json
{
  "by": "Chief",
  "ref": "EXPLICIT_ADJUDICATION_REFERENCE",
  "scope_ref": "APPROVED_SCOPE_REFERENCE",
  "head_sha": "FULL_CURRENT_SHA",
  "cleared_stops": ["architecture_boundary"],
  "final_authority_approval_ref": "CONSEQUENTIAL_CHANGE_APPROVAL_REFERENCE"
}
```

Retain the original risk flags. Consequential changes need final-authority approval.
Missing reproduction/evidence cannot be overridden. Expanded scope needs a newly bounded
task approved outside the loop. Architecture documents are not automatically modified.

After correction, set `state: corrected`, add `correction_ref` and focused evidence
references. Record this in the next iteration's `corrections`:

```json
{
  "finding_id": "F-001",
  "from_sha": "FULL_PREVIOUS_SHA",
  "to_sha": "FULL_NEW_SHA",
  "owner": "Codex",
  "ref": "CORRECTION_ARTIFACT_REFERENCE",
  "focused_ref": "FOCUSED_EVIDENCE_ARTIFACT_REFERENCE"
}
```

The report rejects corrections without prior exact-SHA authorization, fresh prior
review, correct owner, a new SHA, and absence of global adjudication stops. Findings
cannot disappear. A first-iteration finding cannot be marked corrected without its
preceding correction record. Explain pre-existing fixes as evidenced dismissals instead.

False positives/informational findings may be dismissed with a matching Chief decision
and explanatory evidence. Debt/out-of-scope/partially-valid findings may be deferred only
with an explicit nonblocking decision and supporting references; they remain in reports.

## Evidence adapter

```json
{
  "repository": "OWNER/REPOSITORY",
  "pr": 123,
  "head_sha": "FULL_CURRENT_SHA",
  "focused": {
    "status": "passed",
    "head_sha": "FULL_CURRENT_SHA",
    "ref": "FOCUSED_GATE_ARTIFACT"
  },
  "regression": {
    "status": "passed",
    "head_sha": "FULL_CURRENT_SHA",
    "ref": "COMPLETE_REGRESSION_GATE_ARTIFACT"
  },
  "protected_ci": {
    "status": "passed",
    "head_sha": "FULL_CURRENT_SHA",
    "ref": "REQUIRED_PROTECTED_CHECKS_ARTIFACT"
  }
}
```

Statuses: `passed|failed|pending|missing|unavailable|not_required`. Passing results require
exact-SHA references. Focused and regression evidence cannot be waived. Without corrections,
focused evidence records targeted checks/inspection supporting the review dispositions.
Protected CI must enumerate all applicable required checks, including legacy statuses or
merge-queue checks when required. An unrelated green check or skipped required job is
insufficient. The producer/agent verifies referenced content; the helper validates the envelope.

If no protected CI applies, use `status: not_required` plus a `waiver` object containing
`by: Chief`, `ref`, `reason`, and current `head_sha`. This documents absence of a
requirement; it cannot waive failed checks or weaken existing requirements.
Unavailable evidence is never implicitly passing.

## Report

The report includes repository/PR/branch, starting/final SHAs, per-iteration SHA and
freshness, finding counts/dispositions, correction records, adjudication items,
focused/regression/protected CI statuses, unresolved findings, stop reason and
`READY_FOR_CHIEF_REVIEW`. Scores and unresolved-thread counts do not control readiness.
Chief's independent final verdict follows the report.
