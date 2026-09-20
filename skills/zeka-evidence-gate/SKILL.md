---
name: zeka-evidence-gate
description: Produce and verify behavior-first, immutable-revision evidence bundles for Zeka engineering work, with explicit test targets, provenance, artifacts, caveats, and separate focused, regression and protected CI evidence. Use when asked to substantiate engineering claims or prepare evidence for review.
---

# Zeka evidence gate

Produce evidence that Chief can consume during final review. State what was tested,
against which immutable revision, how, what happened, and what remains unproven.
Engineering claims are not evidence: a green exit code without expected and observed
behavior does not establish the claim. Hervé remains final authority. Do not adjudicate
architecture or Greptile findings, declare merge readiness, merge, or close issues.
Invoking this skill does not authorize external posting or new mutations.

## Establish the evidence contract

Read [evidence-contract.md](references/evidence-contract.md) before constructing the
manifest and [execution.md](references/execution.md) before using the helpers.
Identify repository, branch (null for detached HEAD), full commit SHA, scope, and
every required target. Attach structured `contract_ref` and `requirement_ref` values
where an authoritative source exists; reference private sources without copying their
contents or private locators into public files. Use configured opaque identifiers.

Keep focused, regression and protected CI obligations separate. Never replace one
with another unless the accepted task contract explicitly permits it. The helper
checks declared coverage; reconcile that inventory with the actual contract.

## Collect safe observations

1. Establish the exact source revision before collection. For local processes,
   record a clean source checkout and unchanged start/end SHA. Never attribute dirty
   code to clean HEAD. Do not commit, stash, discard, or switch branches merely to
   satisfy this rule without task authorization. For deployments, verify build identity
   through an authoritative source; local HEAD does not identify a running service.
2. For bug fixes, capture the old failure, then the fix's behavior at its own revision.
   If reproduction is unsafe or impossible, use an explicit comparison limitation.
   Never manufacture a before state or quietly omit an expected test.
3. Run authorized tests using existing project tooling. Capture configuration, filter,
   counts and duration for .NET tests; relevant database, API, messaging, storage or
   CI observations using the typed contract. Record structured tool/runtime versions
   when available. Account for every runner-reported skip in `details.skips`, with
   stable identity, reason, environment condition and explicit target relationships.
   Only expected, accounted skips outside a passing target's obligations may coexist
   with that target passing. Required skipped scenarios remain `untested` or `blocked`;
   never infer their harmlessness from names, prose or aggregate counts. See the
   contract's skip-accountability rules. Commands are data; helpers never execute them.
4. Use synthetic fixtures or explicitly allowlisted exports. Do not dump environment
   variables, connection strings, headers, raw production payloads, personal data or
   private file contents. Sanitize at the producer before writing evidence. If safe
   collection is impossible, record `blocked` with the reason. Heuristic scanning is
   a backstop, not permission to capture sensitive data and redact it later.
5. Record expected and observed structured results, exit code when a process ran,
   and structured provenance. Create a sanitized result JSON and reference it from
   the record. Preserve useful source artifacts such as sanitized TRX or query output;
   do not misrepresent a manually transcribed result as an authenticated attestation.
6. Record `untested` or `blocked` with a reason for every unexecuted target. Use honest
   null observations/details where no result exists. Never fill unknowns with success.

Screenshots/video are optional for behavior that benefits from visual evidence.
If a future `zeka-ui-evidence` skill is available, consume its captures and provenance
through the UI record instead of duplicating recording machinery. Review media for
sensitive content before inclusion. This skill does not automatically inspect media.

## Verify and hand off

Keep live bundles under ignored `.artifacts/<task>/` or outside the tracked tree.
Never commit runtime artifacts by default; only the shipped synthetic fixture is a
committed example. Use `init` to package a sanitized candidate, `verify --repo` for
current-revision verification, and `report` to render the report. `--offline` checks
integrity only and must not be presented as current evidence. Reverify immediately
before handoff; changed HEAD makes old evidence stale for the new revision.

Preserve failed, blocked and untested assertions and caveats in the handoff. Passing
schema validation is not a passing test or complete evidence. `--require-complete`
also requires current, real evidence for every declared target.

When requested, use `export-review-loop` for the existing review-loop adapter. It
does not create waivers, replace required checks, or grant review readiness. Report
the immutable SHA, three evidence levels, unresolved assertions, reproduction
limitations, artifact references and scope limits. Do not claim more than was tested.

Original implementation; conceptual attribution is in [upstream.md](references/upstream.md).
