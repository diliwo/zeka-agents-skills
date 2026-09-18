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
or treat budget exhaustion as readiness. Set a different cap when establishing the bounded
task if the authorized scope warrants it; do not reset the ledger or silently increase the
cap to keep a stalled loop running.

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
IDs, body hashes and timestamps. For an already triggered review, retain the original
ticket; simply observing a score now does not create a valid ticket retroactively.

A native submitted GitHub review must have `commit_id == head_sha`, a submitted
terminal state, and a timestamp strictly newer than the request. A trusted summary-only
provider/adapter must emit this marker as a completion assertion:

```text
<!-- zeka-review-complete sha=FULL_40_CHARACTER_COMMIT_SHA -->
```

This is this skill's adapter contract, **not a claim that stock Greptile emits the marker**.
Never append the marker locally to make a summary pass. Obtain provider-backed exact-head
metadata through a configured trusted adapter, or fail closed and ask Chief for the
missing review evidence. No-check large-PR polling works when that contract is available.
Otherwise timestamp-only Apps results remain insufficient. Native GitHub review
submissions need no marker. Seconds-resolution timestamp ties are conservatively rejected.

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
