# Evidence contract, version 1

The normative shape is [manifest.schema.json](manifest.schema.json), JSON Schema
2020-12. The Python helper implements precisely the keywords used in this bundled
schema; it is not a general-purpose validator. Python 3.10+ and Git are required,
without third-party dependencies. Full lowercase 40-character Git SHAs are supported;
Git SHA-256 repositories are outside version 1's review-loop-compatible contract.

## Bundle and coverage

`schema_version`, `bundle_id`, `created_at`, `synthetic`, `repository` (owner/name),
`branch` (string or null), `head_sha`, `scope`, `required_targets`, `records`,
`artifacts`, `comparisons` and `caveats` are required. `contract_ref` is optional.
All timestamps include a timezone. Unknown fields and duplicate JSON keys are rejected.

Each target has an ID, requirement statement, evidence class and level. Exactly one
current record (`standalone` or `after`) must cover each target. Use distinct targets
for different scenarios or evidence levels; before records do not satisfy current
coverage. A record must match its target's requirement, class and level.

Levels are `focused`, `regression`, `protected_ci`; protected CI requires class `ci`.
The contract inventory determines which targets are required. Missing levels remain
`missing` in the report/export even if all declared targets pass. The verifier cannot
discover undeclared obligations or validate the authority of a supplied contract.

## Structured authoritative references

Optional `contract_ref` and `requirement_ref` are available on targets and records.
Bundle-level `contract_ref` supplies overall context. A record inherits a target
reference if omitted; if supplied on both, it must agree exactly.

```json
{
  "kind": "repository_contract",
  "locator": "contract:duplicate-delivery",
  "revision": "v1",
  "fragment": "single-durable-effect"
}
```

`kind` is `document | issue | decision | repository_contract`; `locator` is a safe
opaque identifier or public reference. `revision` and `fragment` are optional.
Resolve private identifiers through task-local configuration outside published files.
Never embed private contract contents or private filesystem/network locators.

## Records and observations

Records require ID, timestamp, repository, branch, commit SHA, target ID, requirement,
class, level, phase, preconditions, environment, procedure, exit code, expected result,
observed result, status, output excerpt, artifact IDs, caveats, provenance and details.
`reason` is mandatory for `blocked` and `untested`. Both have null exit codes; null
observations and details are permitted. A failed record may retain partial observations.

`procedure` contains a working directory and exactly one of an `argv` array or `steps`
array. Paths are safe relative descriptions; secrets must never appear in arguments.
`expected_exit_code` is optional, defaulting to zero. Remote/manual observations may
have null exit codes. Executed local/Testcontainers observations require an exit code.

Expected and observed results are JSON objects. A passing record requires exact object
equality and the expected process exit code where applicable. Encode only asserted
values in these objects; additional measurements belong in typed `details` or artifacts.
Represent tolerance checks as explicit expected/observed boolean outcomes and retain
measured values and procedure in supporting data. The verifier does not interpret
arbitrary prose as an executable assertion.

### Tool and runtime versions

`environment` requires `os` and `data` (`synthetic | sanitized | non_sensitive`), with
optional `description` and structured `versions`. The record also supports `versions`
for record-specific tools. Entries have required `name`, `version`, and `kind`
(`tool | runtime | service | image`), plus optional `digest`.

```json
{"name": "dotnet", "version": "10.0.100", "kind": "runtime"}
```

Record exact versions where available; omit unknown versions and explain material
reproducibility gaps in caveats. Never serialize the whole process environment.

## Closed, extensible provenance vocabulary

`provenance` has exactly `kind` and `metadata`. Version 1 accepts only the following
values, each with its own strict metadata schema:

| Kind | Required structured metadata |
|---|---|
| `local_process` | argv, working_directory, started_at, finished_at, start_sha, end_sha, worktree_clean=true |
| `github_actions` | repository, run_id, run_attempt, job, head_sha, url |
| `github_api` | repository, endpoint, retrieved_at, head_sha, url |
| `testcontainers` | Local-process fields plus images, each with name and immutable SHA-256 digest |
| `deployed_system` | system_ref, deployment_ref, build_sha, revision_source, observed_at |
| `manual_observation` | observer_ref, method, subject_sha, revision_source, observed_at |
| `synthetic` | fixture, description |

Fields ending in `_ref`, plus `revision_source`, use the structured reference shape.
An observer reference identifies a non-personal role or audit source, not personal
information. Local and Testcontainers start/end SHAs must match the record;
GitHub and deployed/manual revision metadata must also match. GitHub repository
identity must agree. A deployment's revision source must be independently checked by
the collector; a manifest assertion alone cannot authenticate it.

Synthetic bundles must use synthetic provenance throughout, and real bundles must
not. Unexecuted targets can use `manual_observation` to identify the source of a
blocker assessment; do not invent an executed process or GitHub run.

To add a source kind, increment the schema version and add a strict metadata schema,
revision-binding checks, tests, and migration documentation. Unknown kinds fail closed;
there is no unrestricted `other` kind or arbitrary metadata escape hatch.

## Evidence classes

| Class | Required details for executed records |
|---|---|
| `unit`, `integration` | project, suite, Debug/Release configuration, nullable filter, passed/failed/skipped counts, duration_ms |
| `postgresql` | exact role/database, catalog_query, expected_state, observed_state, nullable rls_result and transaction_context |
| `api` | scenario, request method/path and optional safe metadata, response_status/body, nullable retry_duplicate and timing_ms |
| `messaging` | event_id, revision, delivery_count, expected_disposition, durable_state, nullable retry_redelivery |
| `storage` | canonical_path_assertion, containment_assertion, operation_id, nullable idempotency, partial_write, restart_reconciliation |
| `ci` | workflow, run_id, job, head_sha, conclusion, url, required_checks, checks, requirements_ref |
| `ui` | scenario, assertions, nullable capture_skill, visual_review with reviewed and reviewer_ref |

Null class-specific fields mean that aspect was not measured; explain material gaps
in caveats and declare separate targets if the task requires those aspects.
Passing unit/integration suites require at least one executed test, no failures or
skips, and exit zero. Split intentionally unexecuted assertions into explicit targets.
Counts and duration come from the actual runner; the helper checks the sanitized
structured export and does not parse every native test format.

CI evidence requires GitHub Actions/API provenance (or synthetic fixture provenance).
Each check records name, exact SHA, conclusion and reference. Passing CI requires all
listed required checks to exist and succeed, with exact record SHA throughout. The
collector must enumerate actual protected requirements, including applicable legacy
statuses or merge-queue checks. Their authority is referenced by `requirements_ref`.
Pending/unavailable CI is untested/blocked with a reason, not passed.

## Artifacts and before/after

Each artifact requires ID, portable bundle-relative path, allowed media type, SHA-256,
role (`result | supporting | visual`), provenance, and safety metadata. Safety requires
`reviewed: true`, method (`allowlisted_export | synthetic_fixture | manual_redaction`)
and a structured `review_ref`. This is a producer declaration, not independent proof.

Every executed record requires a `result` artifact, UTF-8 JSON containing exactly:

```text
record_id, commit_sha, exit_code, observed_result, details
```

These values must equal the associated manifest record. Hashes cover the sanitized
bytes, never raw secrets. A result artifact belongs to exactly one record. Supporting
sanitized TRX/XML, plain text, JSON and reviewed PNG/JPEG/MP4/WebM are accepted.
The stored report must match deterministic rendering of the manifest, and unlisted
bundle files are rejected. All listed artifacts must be referenced; path traversal, links and reserved output
paths are rejected. Binary media is not semantically inspected by these helpers.

Each after record needs a comparison with target_id, after_id and before_id. A null
before_id requires a concrete reason. Otherwise the before record must match the
target and retain a different SHA. Historical failures are preserved but excluded
from current completeness. Before records must belong to a comparison.

## Guarantees and limits

Verification checks declared structure, coverage, consistency, hashes, obvious secrets,
and (in live mode) current Git SHA, branch, clean worktree, repository identity and
whether runtime evidence is ignored/untracked. Standard HTTPS and SSH GitHub remotes
are supported; custom host aliases need a future independently verified adapter.
No credentials are printed to explain a mismatch.

Checks are point-in-time and provenance is supplied by the collector, not a signed
attestation. Clean start/end SHAs alone cannot detect a transient mutation restored
during execution, ignored build inputs, or a falsely described deployment. Use isolated
immutable checkouts/builds and record tool/image identities. External services and
source URLs are not fetched by this offline helper. Hashes cannot prove truthfulness.
Scanning is heuristic and cannot guarantee detection of private identifiers or PII.
The skill never asserts architecture acceptance, merge readiness or final authority.
