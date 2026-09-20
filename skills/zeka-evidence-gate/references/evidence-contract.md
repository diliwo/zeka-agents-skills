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
optional `description`, structured `versions`, and `prerequisites` (see skip accounting). The record also supports `versions`
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
| `unit`, `integration` | project, suite, Debug/Release configuration, nullable filter, passed/failed/skipped counts, duration_ms; structured skips when skipped > 0 |
| `postgresql` | exact role/database, catalog_query, expected_state, observed_state, nullable rls_result and transaction_context |
| `api` | scenario, request method/path and optional safe metadata, response_status/body, nullable retry_duplicate and timing_ms |
| `messaging` | event_id, revision, delivery_count, expected_disposition, durable_state, nullable retry_redelivery |
| `storage` | canonical_path_assertion, containment_assertion, operation_id, nullable idempotency, partial_write, restart_reconciliation |
| `ci` | workflow, run_id, job, head_sha, conclusion, url, required_checks, checks, requirements_ref |
| `ui` | scenario, assertions, nullable capture_skill, visual_review with reviewed and reviewer_ref |

Null class-specific fields mean that aspect was not measured; explain material gaps
in caveats and declare separate targets if the task requires those aspects.
Passing unit/integration suites require at least one executed test, zero failures,
exit zero, and accountability for every skipped test as described below. Skips do not
satisfy required targets. Split unexecuted required scenarios into explicit targets.
Counts and duration come from the actual runner; the helper checks the sanitized
structured export and does not parse every native test format.

CI evidence requires GitHub Actions/API provenance (or synthetic fixture provenance).
Each check records name, exact SHA, conclusion and reference. Passing CI requires all
listed required checks to exist and succeed, with exact record SHA throughout. The
collector must enumerate actual protected requirements, including applicable legacy
statuses or merge-queue checks. Their authority is referenced by `requirements_ref`.
Pending/unavailable CI is untested/blocked with a reason, not passed.


## Skip accountability (compatible v1 extension)

`details.skips` is optional for unit/integration records only when `skipped` is zero.
Omission means an empty inventory. Existing zero-skip manifests, result artifacts and
reports remain valid unchanged. If counts are recorded, the inventory must have
exactly `skipped` entries, even when the record is failed, blocked, untested or historical.

Each entry has exactly five required fields:

```json
{
  "test": "Backend.Tests::WindowsVolumeTests.Read",
  "reason": "Requires Windows volume APIs; unavailable on Linux.",
  "expected_for_environment": true,
  "target_ids": [],
  "condition": {"kind": "platform", "supported_os": ["Windows"]}
}
```

Use a stable, unique identity for each runner-counted test, including project/suite
and parameterized case identity where necessary. Duplicate identities, blank identities
or reasons, placeholder reasons, unknown target IDs, and duplicate target references
are rejected. A prose caveat cannot replace inventory. Inventory remains inside the
hashed structured result, so changing it also requires an updated source artifact.

`target_ids` must list every declared target whose required scenario was left unexecuted
by this skip. An explicit empty array declares that no required target depends on that
scenario for this execution environment. It is not an unknown mapping or a waiver.
If the producer cannot establish this relationship, record the affected suite obligation
as blocked and resolve the mapping before presenting it as passing evidence.

For current records, every referenced target must have its own `untested` or `blocked`
record with a reason. It cannot be passed, even if another aggregate suite is green.
A suite may pass for its own independently executed obligations while another target
is explicitly untested/blocked; the bundle remains incomplete. If the suite target
itself requires the skipped scenario, that suite target cannot pass either. Historical
before records keep their own SHA and do not invalidate current after evidence; a
historical passing suite still cannot list its own target as skipped.

### Deterministic environment conditions

| `condition` | Meaning and verification |
|---|---|
| `{"kind":"platform","supported_os":["Windows"]}` | The test can run on the listed OS families. The skip is expected only when the recorded OS is outside this list. |
| `{"kind":"prerequisite","id":"disposable-database"}` | The skip is expected only when this prerequisite is recorded as unavailable. Missing/ambiguous prerequisite declarations are rejected. |
| `{"kind":"explicit_exclusion","ref":{"kind":"decision","locator":"decision:optional-stress-exclusion"}}` | The producer has verified an intentional exclusion in the referenced execution contract/decision. It cannot override required targets. |
| `null` | No understood condition is recorded; `expected_for_environment` must be false and the suite cannot pass. |

For platform conditions, both `environment.os` and `supported_os` use canonical,
case-sensitive `Windows`, `Linux`, `macOS` or `FreeBSD`. Put distribution/version text
in `description` or structured versions. Unknown values such as `Windows 11` fail
closed rather than being guessed to mean a different platform. The supported list
must be nonempty and contain no duplicates. Tests requiring another OS can use an
explicitly recorded prerequisite until a canonical platform is added to the contract.

For prerequisite conditions, record the same environment's observations using optional
`environment.prerequisites`, a strict array of `{ "id": "disposable-database",
"available": false }` objects with unique IDs. The verifier checks the referenced
availability boolean; it does not probe services or interpret prose preconditions.

The verifier evaluates the condition and requires `expected_for_environment` to agree.
A passing suite permits only expected skips. Unexpected skips can be documented in
failed/blocked/untested evidence, but cannot produce a passing suite obligation.
The producer verifies exclusion authority and prerequisite observations; the helper
does not authenticate a decision reference or inspect the machine remotely.

Example: 573 passed, zero failed, and two uniquely identified Windows-only tests
skipped on Linux can pass regression evidence if both skips are fully accounted for
and outside that record's required obligations. All declared targets must independently
pass for the bundle to be complete. Associating either skip with a passed target is
rejected; making that target explicitly untested/blocked preserves a valid but
incomplete bundle.

The report exposes counts, identities, reasons, conditions, expected flags, target
relationships and completeness effects. Zero-skip reports keep their existing format.
The review-loop adapter continues to export passing independent evidence normally;
untested targets map to missing and blocked targets map to unavailable at their level.

The producer declares test-to-target relationships. Neither test names, prose reasons,
nor parsing TRX automatically establish architectural or requirement coverage. The
verifier checks declared consistency and does not discover dishonest or omitted mappings.

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
