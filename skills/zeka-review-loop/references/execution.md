# Execution and prerequisites

Helpers require Python 3.10+, Git and authenticated `gh` with read access to the target
GitHub.com repository and permission to comment if triggering. Greptile must already be
installed/configured. No packages, hooks, credentials or permissions are installed.
GitHub Enterprise, GitLab and Perforce are not implemented. Network/API failure closes
the gate. Commands run in the target PR checkout, not this skill's repository.

Use a private artifact directory outside the target worktree. Output files are exclusive
create: use distinct names for every snapshot, trigger, poll result, ledger revision and
report. Keep preceding artifacts; do not overwrite history. These artifacts may contain
private review text. Do not commit them to this public repository.

Example configuration (replace placeholders and verify exact bot/app identities):

```json
{
  "repository": "OWNER/REPOSITORY",
  "pr": 123,
  "actor": "Codex",
  "scope_ref": "APPROVED_SCOPE_REFERENCE",
  "architecture_source": "AUTHORITATIVE_DECISION_SOURCE",
  "bot_logins": ["greptile-apps[bot]"],
  "check_app_slugs": ["greptile-apps"],
  "remote": "origin",
  "max_iterations": 3,
  "timeout_seconds": 600,
  "poll_seconds": 10,
  "normal_trigger": "@greptile review",
  "apps_trigger": null,
  "allow_unavailable_checks": false
}
```

`max_iterations` defaults to 3 review iterations, counting the initial review and fresh
verification reviews. This permits an initial assessment followed by up to two correction
rounds, each verified by the next review. Three is a practical budget choice, not an
empirically proven convergence threshold: it leaves room to catch defects introduced or
revealed by the first correction while bounding external review latency, cost, and repeated
rework. Stop earlier when ready or when a mandatory stop applies. At the cap, hand off
remaining findings; never apply another correction without a reserved verification review
or treat budget exhaustion as readiness. A bounded task may lower the cap to one or two;
the helper rejects caps above three. Do not reset the ledger or increase the cap to keep
a stalled loop running.

`apps_trigger` may be set to `@greptile-apps review` only after confirming that this
installation supports it. Size-limit detection examines trusted review comments/check
output for refusal text; do not infer a universal file-count threshold. The detector is
an English-text heuristic: other provider wording requires manual verified classification
or a maintained adapter update, not automatic stale acceptance. Historical refusal text
may conservatively suggest Apps even after the PR shrinks; inspect it before triggering.

`allow_unavailable_checks` permits collection when check runs cannot be read. It records
unavailability rather than an empty successful check set. This does not waive protected
CI. Keep it false unless the inability is understood; retrieve required CI evidence via
the evidence gate. The collector cannot distinguish missing permissions from an outage.

Run these commands with actual paths (the shell-neutral examples use filenames only):

```text
python SKILL/scripts/review_loop.py capture --config config.json --out before-1.json
python SKILL/scripts/review_loop.py trigger --config config.json --snapshot before-1.json --out ticket-1.json --send
python SKILL/scripts/review_loop.py poll --config config.json --ticket ticket-1.json --out poll-1.json
```

The poll output wraps `snapshot`, `freshness`, and `status`. Extract its `snapshot` object
to `snapshot-1.json`, retaining the wrapper. On `size_limit_requires_apps`, preserve
the normal ticket and use that returned snapshot with `trigger --mode apps --send`,
then poll the new ticket. At most one normal and one Apps request per iteration; a
fallback has its own bounded timeout. Do not restart expired tickets or issue repeated
requests to avoid the cap. Helpers make no retries for failed API mutations: a lost
response may mean the comment was posted; inspect existing comments before retrying.

```text
python SKILL/scripts/review_loop.py inventory --config config.json --snapshot snapshot-1.json --out sources-1.json
python SKILL/scripts/review_loop.py prepare --config config.json --snapshot snapshot-1.json --ticket ticket-1.json --out draft-1.json
```

Complete a new ledger revision from the draft: assess every source, record findings,
decisions and evidence using [contracts.md](contracts.md). The helper intentionally does
not guess severity, ownership, disposition or approval from reviewer prose. It preserves
the full text and produces stable source identifiers with body hashes. Multiple findings
from one source get distinct finding IDs; one finding may reference multiple sources.

```text
python SKILL/scripts/review_loop.py report --run run-1.json --out report-1.json
```

The report gives `correction_authorized` per finding. Respect the global adjudication
and freshness stops too. Missing final test evidence does not itself forbid an otherwise
authorized correction; passing focused/broader evidence is required before proceeding
to the next review/handoff. Make approved corrections, test, commit, push within existing
authorization, capture and trigger the new SHA, then append its returned snapshot/ticket:

```text
python SKILL/scripts/review_loop.py append --run run-1.json --snapshot snapshot-2.json --ticket ticket-2.json --out draft-2.json
```

`append` preserves earlier iterations and findings, resets source coverage and evidence,
and enforces the cap. Finish the new ledger revision, including correction provenance.
Before final report, recapture the live PR and reassess any changed source inventory in
a new revision of the last iteration. Do not count a same-SHA recapture as a fix iteration.
An unexpected external head/base change stops this run; Chief establishes a new scope/run.

## Freshness contract and limitations

Tickets contain immutable repository/PR/branch/head-repository/base/head identity,
server request timestamp, trigger URL/ID, mode, and a pre-request baseline of source
IDs, body hashes and timestamps. New baselines also record parsed Greptile review counts
and last-reviewed SHAs (or null when the supported footer is absent).
For an already triggered review, retain the original
ticket; simply observing a score now does not create a valid ticket retroactively.

A native submitted GitHub review must have `commit_id == head_sha`, a submitted
terminal state, and a timestamp strictly newer than the request. A trusted summary-only
provider/adapter must emit this marker as a completion assertion:

```text
<!-- zeka-review-complete sha=FULL_40_CHARACTER_COMMIT_SHA -->
```

This is this skill's adapter contract, **not a claim that stock Greptile emits the marker**.
Never append the marker locally to make a summary pass. Native GitHub review submissions
need no marker. Both existing paths retain precedence and their original semantics.
No-check large-PR polling still requires one of those paths; timestamp-only Apps results
remain insufficient. Seconds-resolution request timestamp ties are rejected.

### Stock Greptile check plus summary

When neither existing path completes, the adapter accepts only this conjunction:

1. The ticket has a positive integer trigger ID, its matching GitHub PR comment URL,
   normal/Apps mode, server request time, and the captured pre-request baseline.
   Snapshot repository, PR, branch, head repository, base and full head SHA still match.
2. Both `greptile-apps` and `greptile-apps[bot]` are in the configured exact identity
   allowlists. Only that app's `Greptile Review` check and that bot's summary qualify.
   Generic GitHub checks cannot opt in by merely adding their slug to the allowlist.
3. The latest check for that app/name has the exact requested `head_sha`, status
   `completed`, conclusion `success`, and an ID absent from the baseline. Its start
   is strictly after the request and no later than its completion. Reused checks,
   pre-request starts, missing times, neutral/skipped/failure/cancelled/timed-out
   results cannot establish this path. Pending/failed trusted checks still veto readiness.
4. Exactly one provider summary comment contains `<!-- greptile_summary -->`. Its
   terminal footer has the stock form below, with a single `Last reviewed commit:`
   declaration and a full lowercase 40-character SHA in a GitHub commit URL for the
   PR head repository. The URL's SHA must equal the requested SHA. Link text, incidental
   SHAs elsewhere in prose, confidence, file counts and zero-comment claims do not bind
   completion. Duplicate summaries, ambiguous declarations and unknown formats fail closed.

   ```text
   <sub>Reviews (N) · Last reviewed commit: ["COMMIT TITLE"](https://github.com/HEAD_OWNER/HEAD_REPOSITORY/commit/FULL_SHA)</sub>
   ```

5. The summary update is strictly after check completion. A baseline summary must have
   a changed body and a baseline timestamp at or before the request. Its positive review
   counter must advance from the parsed baseline counter, including same-SHA retries.
   An existing summary requires a successfully parsed baseline binding with a positive
   integer counter: missing, null or malformed bindings fail closed. Counter equality,
   decrease, missing values and invalid types cannot establish advancement.
   If no summary existed in the baseline, its creation must be after the request.
6. Check and summary times must fall within the ticket's original timeout and no later
   than the snapshot. The accepted finding window is `(requested_at,
   min(collected_at, requested_at + timeout_seconds)]`; later recaptures cannot extend it.

This conservative path deliberately rejects a pre-request check that finishes afterward,
a reused check ID, and a summary tied to the same second as check completion. Unsupported
provider formats need a tested adapter update, not a permissive SHA search.

Freshness output adds `completion` with the request, check, summary and exact-SHA
references, and `fresh_source_keys` for eligible finding provenance. The raw inventory
remains lossless for auditing: historical comments still require coverage, but are not
fresh findings. Newly introduced finding source keys must come from the accepted window;
unchanged baseline bodies, old-SHA sources and historical comments edited after the request
are excluded. Fresh inline comments require the exact commit ID. Previously recorded
findings and their provenance remain in the ledger and cannot disappear.

Existing tickets without the parsed summary baseline remain valid for marker/native
completion, but cannot retrospectively establish this new path for an existing summary.
Do not synthesize the missing baseline or restart an expired ticket. A newly authorized
request must retain the existing run budget; at the cap, stop and hand off.

The ticket and provider timestamps correlate independent observations; stock Greptile
does not echo the trigger ID. These artifacts are auditable evidence, not cryptographic
proof of causality. Keep raw snapshots and request responses for review.

### Release compatibility

This completion-path addition and baseline-integrity correction require a new skill
release. The expected version after independent acceptance is v0.1.2; do not replace
or retag v0.1.0 or v0.1.1. Schema version 1, legacy completion paths, source-key hashing, evidence envelopes,
Chief adjudication and strongest positive output remain unchanged. New freshness metadata
and baseline fields are additive. The explicit three-review ceiling also closes the prior
configuration loophole allowing larger caps. No release, installation or tag is produced
by implementing this change; the immutable implementation commit is the review checkpoint.

Check output is collected for findings and failures but never alone proves comments are
complete. Trustworthy summaries must change after the baseline and request; a reused old
summary with an unrelated edit and no completion binding is stale. Review scores are
neither parsed into readiness nor used to suppress findings.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Artifact created; for `report`, ready for Chief; for `poll`, fresh review obtained. |
| 2 | Valid report needs action/stop, or normal review needs Apps fallback. |
| 3 | Invalid input, timeout, API/command failure, changed PR, or artifact collision. Structured failure on stderr. |

Never interpret a failed command as zero findings. On failure, retain the last complete
ledger and error report. No helper edits code, commits, pushes, resolves threads or merges;
`trigger --send` is the only remote mutation. The agent coordinates bounded execution.
