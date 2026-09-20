# Evidence report

Scope: Demonstrate focused evidence and explicit gaps for duplicate event delivery.
Repository: example/backend
Branch: fix/duplicate\-delivery
Immutable SHA: 1111111111111111111111111111111111111111
Bundle: synthetic\-duplicate\-delivery
Created: 2026\-09\-20T10:00:00Z

Synthetic demonstration: true
Freshness: not_checked
Required-target completeness: incomplete (1/3 passed)

Synthetic data cannot substantiate a real engineering claim.

Contract reference: \{"kind": "repository\_contract", "locator": "contract:duplicate\-delivery", "revision": "v1"\}

## Focused

Result: passed

### E\-001: Delivering the same event twice creates one durable effect.

Status: passed
Target: T\-001
Class: integration
SHA: 1111111111111111111111111111111111111111
Expected: \{"delivery\_count": 2, "durable\_effect\_count": 1\}
Observed: \{"delivery\_count": 2, "durable\_effect\_count": 1\}
Exit code: 0
Procedure: \{"argv": \["dotnet", "test", "tests/Backend.IntegrationTests", "\-\-configuration", "Release", "\-\-filter", "FullyQualifiedName~DuplicateDelivery", "\-\-logger", "trx"\], "working\_directory": "."\}
Environment: \{"data": "synthetic", "os": "Linux", "versions": \[\{"kind": "runtime", "name": "dotnet", "version": "10.0.100"\}, \{"kind": "service", "name": "PostgreSQL", "version": "17.0"\}\]\}
Tool/runtime versions: \[\{"kind": "tool", "name": "test\-runner", "version": "1.0.0"\}\]
Preconditions: \["Disposable database initialized", "Synthetic event fixture loaded"\]
Source: \{"kind": "synthetic", "metadata": \{"description": "Invented demonstration; no backend or CI run was executed.", "fixture": "synthetic\-backend"\}\}
Output excerpt: Synthetic example: one selected test passed; durable effect count was one.
Artifacts: A\-001
contract_ref: \{"kind": "repository\_contract", "locator": "contract:duplicate\-delivery", "revision": "v1"\}
requirement_ref: \{"fragment": "T\-001", "kind": "repository\_contract", "locator": "contract:duplicate\-delivery", "revision": "v1"\}
Caveats: Sequential duplicate delivery only; concurrent delivery remains untested.

## Regression

Result: untested

### E\-002: The complete regression suite passes.

Status: untested
Target: T\-002
Class: integration
SHA: 1111111111111111111111111111111111111111
Expected: \{"success": true\}
Observed: null
Exit code: None
Procedure: \{"steps": \["Assess the synthetic demonstration target."\], "working\_directory": "."\}
Environment: \{"data": "synthetic", "os": "Linux", "versions": \[\{"kind": "runtime", "name": "dotnet", "version": "10.0.100"\}, \{"kind": "service", "name": "PostgreSQL", "version": "17.0"\}\]\}
Tool/runtime versions: \[\]
Preconditions: \[\]
Source: \{"kind": "synthetic", "metadata": \{"description": "Invented demonstration; no backend or CI run was executed.", "fixture": "synthetic\-backend"\}\}
Output excerpt:
Artifacts: none
Reason: Not executed in this synthetic demonstration.
contract_ref: \{"kind": "repository\_contract", "locator": "contract:duplicate\-delivery", "revision": "v1"\}
requirement_ref: \{"fragment": "T\-002", "kind": "repository\_contract", "locator": "contract:duplicate\-delivery", "revision": "v1"\}
Caveats: none recorded

## Protected Ci

Result: blocked

### E\-003: All required protected CI checks succeed at the target SHA.

Status: blocked
Target: T\-003
Class: ci
SHA: 1111111111111111111111111111111111111111
Expected: \{"success": true\}
Observed: null
Exit code: None
Procedure: \{"steps": \["Assess the synthetic demonstration target."\], "working\_directory": "."\}
Environment: \{"data": "synthetic", "os": "Linux", "versions": \[\{"kind": "runtime", "name": "dotnet", "version": "10.0.100"\}, \{"kind": "service", "name": "PostgreSQL", "version": "17.0"\}\]\}
Tool/runtime versions: \[\]
Preconditions: \[\]
Source: \{"kind": "synthetic", "metadata": \{"description": "Invented demonstration; no backend or CI run was executed.", "fixture": "synthetic\-backend"\}\}
Output excerpt:
Artifacts: none
Reason: This synthetic demonstration has no GitHub Actions run.
contract_ref: \{"kind": "repository\_contract", "locator": "contract:duplicate\-delivery", "revision": "v1"\}
requirement_ref: \{"fragment": "T\-003", "kind": "repository\_contract", "locator": "contract:duplicate\-delivery", "revision": "v1"\}
Caveats: none recorded

## Before/after observations

- T\-001: before untested: No historical failure exists: this is an invented demonstration, not a bug\-fix claim.; after E\-001 at 1111111111111111111111111111111111111111 (passed).

## Failed, blocked and untested assertions

- E\-002: untested; Not executed in this synthetic demonstration.
- E\-003: blocked; This synthetic demonstration has no GitHub Actions run.

## Artifact inventory

- A\-001: results.json; SHA-256 3f5e033876620de3ed629e477ef07d7839b8af389ea610e5c4316c8d717d6467

## Caveats and limits

- All revisions, measurements, and source details in this fixture are synthetic.
- Regression and protected CI evidence remain incomplete.
- Concurrent delivery and production behavior are not proved.
- Completeness covers declared targets only; it does not establish an omitted requirement.
- Hashes establish consistency with the manifest, not authenticity of observations.
- Sensitive-data scanning is heuristic; binary media requires separate review.
- Focused, regression and protected CI evidence are separate obligations.
- This report grants no architecture, review-readiness, merge or issue-closure decision.
