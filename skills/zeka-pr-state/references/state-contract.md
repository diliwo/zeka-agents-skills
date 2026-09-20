# State contract — v1

The JSON schemas are normative for field names and types:
[snapshot](snapshot.schema.json), [expectation](expectation.schema.json).
The bundled validator additionally checks cross-field consistency. Unknown fields,
duplicate JSON keys, non-finite numbers, malformed SHAs and unzoned timestamps fail.
All SHA values are lowercase full 40-character Git commit IDs.

## Observation envelopes and provenance

Each observation contains `availability`, `reason_code`, `source_ids`, and `data`.
Availability is closed: `available`, `not_requested`, `unavailable`,
`unsupported_environment`, `api_failure`. Nonavailable data is null. An available
empty collection is a completed collection with no items, not a failed request.

Every available observation references complete source records. Sources distinguish
`git_command`, `github_rest`, and `synthetic`, with a closed operation vocabulary,
timestamp, status, reason and structured metadata: repository, PR, SHA, ref, safe
endpoint, opaque workspace ID, API version, pages, completeness and boundary hash.
No command output, raw URL, filesystem root or raw body is serialized. Numeric
actor/app IDs and app slugs are retained; personal profile fields are not.

Capture records start/end times and before/after PR identity and optional workspace
fingerprints. `consistency` is `stable`, `changed` or `unknown`. Changed or unknown
captures cannot pass verification. Equal boundary reads prove bounded consistency,
not an atomic transaction: intermediate changes followed by a return may escape
detection. Check and comment pages can change during collection even with stable PR
identity; duplicate page IDs and page limits fail closed, but all races cannot be
detected. Source timestamps identify individual observations.

## Repository and revision identities

Root `repository` identifies the PR's base repository. PR base and head contain
separate repository, branch and SHA values. A deleted/inaccessible head repository
is null and makes live-ref verification unavailable.

Workspace records an opaque caller-assigned identity, local HEAD, branch or detached
HEAD, normalized selected remote, cached tracking ref/SHA, cleanliness flags,
shallow state and observation time. The opaque ID does not authenticate a path.
Supported remotes are standard github.com HTTPS, scp-style git SSH and ssh://git
forms. Credential-bearing, Enterprise, custom-host and SSH-alias forms are rejected
without echoing their values. Nested unavailable remote/tracking fields do not erase
independently established HEAD facts.

`remote_branch` is a separate live GitHub ref observation from the head repository.
PR head, live ref and cached tracking SHA are never aliases. Cached tracking is
available only for the standard selected-remote fetch mapping. Agreement additionally
checks the selected remote repository and full tracking ref; equality of SHA alone
does not establish the identity of a cached ref.

The worktree fingerprint hashes sorted porcelain status entries, not file bytes.
Cleanliness checks staged, unstaged, untracked and unmerged state, including visible
submodule changes. Ignored files, external services, deployed binaries and environment
inputs remain outside this observation. Do not attribute dirty bytes to clean HEAD.

## Ancestry

Ancestry records contain ancestor/descendant SHAs, method `git_merge_base`,
availability, source ID, boolean result, merge bases and reason. Descendant must be
the captured PR head. Git graph queries establish ancestry; history prose does not.
Missing objects or a negative result in shallow history are unavailable, never a
proven non-ancestor. Grafts are rejected and replacement objects disabled. No fetch,
deepen, checkout or repair occurs.

## Observed checks and explicit obligations

Checks carry kind, repository, numeric ID, context/name, source identity, status,
conclusion, exact revision binding, safe URL and available timestamps.
Check runs use payload `head_sha`. Legacy statuses use a complete GET scoped to
`repos/{repository}/commits/{full-sha}/statuses`, recorded as
`exact_sha_endpoint`; mutable branch endpoints cannot establish this binding.
Missing payload binding stays unavailable. Merge/queue/test-merge SHAs are not
silently mapped to a PR head.

`required_check_contract` is a separate envelope and is `not_requested` in this
collector. V1 does not synthesize protection/ruleset policy. Only explicit
`required_checks` expectations create check obligations.

A required check selects kind/name and optionally a source selector. Missing source
identity, ambiguous providers or unbound attempts fail closed. Default `unique`
selection rejects duplicate attempts at the PR SHA. Explicit `latest_id` chooses
the greatest numeric ID within the same repository/provider/name/kind/SHA group.
A newer pending or failing check cannot be replaced by an older green attempt.
Selected and superseded IDs appear in results. `must_be_successful` requires both
completed status and the literal success conclusion; neutral/skipped are not success.
No checks requested means no implicit check policy.

## Review-source metadata and mergeability

PR bodies, issue comments, inline comments, reviews and check output have stable
typed IDs, actor metadata, timestamps, state and content hashes. A body hash is
SHA-256 of UTF-8 text (null becomes empty). Check output hashes canonical compact
JSON of the ordered [title, summary, text] strings (null becomes empty).

Only native review/inline commit IDs and check payload SHAs supply associated
revision binding. Issue comments and PR bodies are unbound; text markers are not
interpreted here. No raw content, findings, tickets or provider adjudication is stored.
A complete review inventory requires all requested surfaces, including check output.

Mergeability is observed once at the final PR boundary. Nullable mergeable and
unknown state remain honest; no polling or merge authorization follows from them.

## Expectations and verification

Expectations independently choose identity, workspace, live ref, agreement,
ancestors, required checks and previous snapshot assertions. At least one active
assertion is required. Base SHA is optional. Disabled cleanliness/agreement flags do
not create assertions. Detached HEAD can be expected with a null branch.

Verification includes capture ID, repository/PR, expected and observed head,
source-linked assertions, failure categories, unavailable assertions, mismatch
reasons, overall result and proof scope. `snapshot_only` is offline verification of
one captured observation; `compared_snapshots` additionally uses a supplied previous
snapshot. `synthetic` is never live proof.

Failed categories remain distinct. Capture consistency is always required. Optional
unrelated collection failures do not veto assertions whose facts remain established.
Consumers must request every surface they rely on.

## Structural comparison

Comparison classifies head/base/branch/repository/PR-state movement, worktree,
local head/branch, live/cached refs, checks, reviews, mergeability, required policy,
workspace identity/remote and availability. Collections include added/removed/changed
IDs only when both are complete. Unavailable collections do not imply deletions.
Transport timestamps, capture IDs and per-capture source IDs do not themselves
change domain facts. Item timestamps and body hashes do.

Comparison does not declare stale evidence automatically. An expectation can require
specific dimensions unchanged against a named previous capture and optional old
head. A base-only movement leaves a head-only claim valid unless its consumer also
requires unchanged base. Consumers retain their stricter policies.

## Limitations

Snapshots are unsigned observations; hashes detect consistency and change, not
truthfulness or authenticity. A caller can fabricate data. Captures require current
authenticated read access and GitHub.com; live API behavior is not proven by offline
tests. API page limits and timeouts are bounded. No exhaustive ruleset evaluation,
native test-runner coverage inference, body interpretation or automatic merge
readiness belongs in this contract.
