# Compatibility and proposed incremental integration

This implementation changes neither consumer. Their complete existing suites must
pass alongside the independent PR-state suite. Offline projection tests compare
review-loop PR identities and clean local-state facts, and evidence-gate local
revision/branch/remote acceptance on temporary repositories. This demonstrates the
tested overlap, not a completed adapter or live provider parity.

## Semantic differences to preserve

| Area | Difference and adapter requirement |
|---|---|
| Fork repository roles | Review-loop checks workspace remote against PR head repository; evidence-gate checks its manifest repository against that remote. Preserve both. Never substitute the new base repository for the evidence manifest repository. |
| Open PR | Review-loop requires open; PR-state can observe closed/merged and expects open only when requested. Adapter must keep the existing open assertion. |
| Detached HEAD | Evidence-gate can match a null manifest branch; review-loop requires its expected branch. Preserve the consumer-specific rule. |
| Base movement | Review-loop freshness includes base; PR-state classifies base independently. Keep review-loop's stricter unchanged-base requirement. |
| Bodies and tickets | Metadata cannot replace raw review content, request timestamps, completion markers or request-bound freshness. Review-loop must keep body collection and interpretation. |
| Hash encoding | Plain UTF-8 body hashes agree. PR-state check-output hash uses canonical ordered JSON; review-loop uses newline-joined title/summary/text. Adapter must compute both over the same raw tuple or retain its original hashes, never compare them as identical. |
| Check policy | PR-state requires explicit obligations, known identity and exact-SHA binding; defaults to unique attempts, with explicit latest-ID selection. Review-loop retains provider selectors, request timing and its acceptance of neutral review checks. A generic successful-CI assertion must not replace provider completion semantics. |
| Supported remotes | PR-state additionally understands standard ssh://git@github.com. Consumers currently accept narrower forms. Shadow comparison records that difference; migration must not silently broaden consumer acceptance. |
| New facts | Live refs, cached refs, ancestry and mergeability are separate facts. Do not add them as mandatory consumer gates without an accepted requirement. |
| Availability | PR-state preserves unavailable/unsupported/API categories and rejects incomplete inventories. Adapters must never turn them into empty success. Review-loop's configured check-source fallback remains its own policy. |
| Artifact/evidence safety | Evidence-gate retains artifact integrity, commit safety, provenance, skip accounting, target completeness and focused/regression/protected-CI semantics. Clean repository facts do not prove these. |

No new material conflict requires changing the approved standalone contract.
The fork-role and hash differences were already identified in the approved proposal.
Integration still needs an explicit mapping and authorization; no breaking consumer
schema change has been made or presumed.

## Proposed stages — not implemented

1. **Freeze the independent contract.** Review schemas, negative tests, source
   completeness and exact-SHA selection. Keep only synthetic fixtures public.
2. **Shadow equivalent facts.** At an authorized consumer invocation, collect the
   current consumer output and PR-state observations without letting PR-state change
   the result. Compare repository roles, PR/head/base/branch, local HEAD/remote and
   cleanliness. Bind observations to the same revision and bracket captures to
   distinguish capture movement from a real semantic mismatch. Store sanitized
   mismatches privately. Compare checks by repository/provider/ID/SHA and bodies by
   source IDs plus hashes computed from the same raw content; do not compare the
   incompatible check-output encodings directly.
3. **Classify and resolve differences.** Cover forks, detached HEAD, base-only
   movement, rewritten history, missing source binding, duplicate/pending checks,
   incomplete pagination and credential/custom remotes. A new material contract
   conflict stops migration for a scoped decision. Never relax an old rejection to
   obtain parity.
4. **Authorize one narrow adapter.** Start with evidence-gate's PR-less local facts,
   preserving manifest repository meaning, supported remote policy and all existing
   artifact safety checks. Alternatively choose review-loop identity projection
   first, but keep raw content, provider/ticket/finding semantics and governance there.
   Require explicit approval for the selected path.
5. **Migrate incrementally after parity.** Add adapter tests for the old failure
   paths. Keep rollback possible. Migrate the next collector only after the first
   remains stable; remove duplicate Git identity/cleanliness or GitHub identity
   reads only when parity is demonstrated. Never remove evidence or governance
   checks under the label of state deduplication.

No automatic merge, review request, workflow trigger or publication is part of these
stages. Chief and Hervé retain their existing authority.
