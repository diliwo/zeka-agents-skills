---
name: zeka-pr-state
description: Capture and verify exact GitHub PR and repository state, ancestry and structural snapshot changes before engineering work. Use for PR head/local/live-remote agreement, clean-worktree assertions, exact-SHA check expectations and stale-snapshot detection. Does not authorize corrections, establish evidence completeness or declare merge readiness.
---

# Zeka PR state

Use this standalone foundation to establish repository facts. Read
[the state contract](references/state-contract.md) and
[execution reference](references/execution.md) before live capture.

1. Identify the base repository and PR. For local observations, select the workspace,
   its opaque public-safe identifier and the remote to inspect. Keep base repository,
   fork head repository and workspace remote separate.
2. Write explicit expectations for the claims needed now. Use full immutable SHAs.
   Do not derive required checks from observed green checks.
3. Capture with the bundled CLI into a new ignored runtime path or outside a Git tree.
   Create the output directory first. Capture only reads Git/GitHub; it never repairs state.
4. Verify the snapshot against expectations. A nonzero result stops any claim that
   depends on the failed assertion. Inspect the structured failure category.
5. Recapture before a later action that requires current state. Compare snapshots,
   and explicitly select which changes invalidate that consumer's work. An offline
   passing snapshot does not prove the PR remains unchanged now.

Keep snapshots and expectations private unless reviewed for publication. Persist no
credentials, private paths, raw bodies or personal profile data. Only explicitly
synthetic fixtures belong in source control. Secret scanning is heuristic.
Never convert unavailable/incomplete collection into an empty successful gate.
Never treat synthetic verification as live proof.

Use `scripts/git_state.py` for PR-less local observations when appropriate; this
does not add PR requirements to evidence workflows.

## Boundaries

This skill owns observations, expectations, deterministic verification, graph
observations and structural comparison. It does not interpret Greptile, collect
review request tickets, normalize findings, authorize corrections, adjudicate
Chief decisions or manage iterations. Those remain in `zeka-review-loop`.

Targets, expected/observed behavior, provenance, artifact hashes, skip accounting,
completeness and focused/regression/protected-CI semantics remain in
`zeka-evidence-gate`. Chief performs final technical/architecture review; Hervé
retains final authority. Do not merge automatically.

Do not refactor either consumer through this skill without separate authorization.
Stop for a scoped decision if integration requires breaking a consumer schema,
changing governance, weakening a fail-closed assertion, assuming unavailable
revision binding or persisting sensitive data.

The [integration plan](references/integration-plan.md) records compatibility
observations and the proposed incremental shadow comparison.
