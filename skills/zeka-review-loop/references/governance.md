# Governance and stop policy

| Role | Authority |
| --- | --- |
| Codex — Software Engineer | Domain, application and infrastructure application code; persistence behavior, messaging, storage, application tests, refactoring, software correctness. |
| Hephaestus — DevOps & Platform Engineer | CI/CD, GitHub Actions, Docker/Testcontainers infrastructure, Sonar integration, package/deployment/platform tooling, operational database bootstrap/reconciliation, Azure/AKS. |
| Greptile — Technical Reviewer | Independent defect, regression, architectural and cross-repository evidence. No disposition, scope, architecture or merge authority. |
| Chief — Coordinator and final technical/architecture reviewer | Accepted architecture context, finding adjudication, bounded scope, stop conditions and independent final technical review. |
| Hervé — Final authority | Consequential scope/architecture approvals and final merge decision. |

Classify by the behavior changed, not just file extension or directory. A Docker fixture
and an application integration assertion can share a test directory but have different
owners. Mixed or uncertain ownership needs adjudication and an explicit handoff.

Stop the correction phase for any of:

- Medium/High/Critical security sensitivity; unknown security severity is also a stop.
- Tenant isolation, authorization, data integrity, material persistence/transactional
  semantics, runtime privileges, accepted ADR/architecture boundaries.
- Issue/PR scope expansion, a newly revealed cross-service contract, or conflicting
  accepted requirements/findings.
- A finding that cannot be reproduced, missing necessary evidence, stale review results.

Report the finding, reproduction attempt, conflicting contracts where applicable, current
SHA, owner, and precise decision needed. Keep private decision sources as configurable
references; do not copy their contents into this skill or public reports.

A finding's `decision` records Chief's disposition, blocking status, action, scope and
the SHA at which correction is authorized. It is not supplied by Greptile. Mandatory
stops require a separate explicit `adjudication`, tied to the current SHA and scope,
listing each cleared stop and its decision reference before a bounded run resumes.
Consequential scope/architecture, contract, persistence or privilege changes also need
`final_authority_approval_ref`. Never invent approvals. Reproduction/evidence failures
cannot be waived by merely adding an approval field; establish the missing evidence.
An adjudication does not authorize automatic editing of accepted architecture documents.

| Disposition | Expected treatment |
| --- | --- |
| accepted/actionable | Chief-approved correction with focused evidence. |
| partially valid | Define the valid subset precisely; fix it or explicitly defer a nonblocking subset with rationale. |
| false positive | Reproduce the claimed scenario, show why the asserted defect is absent, and record Chief's dismissal. |
| informational | Record explanation/evidence and explicit dismissal; no manufactured change. |
| pre-existing debt | Demonstrate it predates the PR; Chief decides whether it blocks or may be deferred. |
| regression | Record reproducer and prior behavior; obtain bounded correction approval. |
| architecture decision required | Stop and present the contract question to Chief. |
| out of scope | Stop for scope adjudication; defer only on explicit nonblocking decision. |
| blocked pending evidence | Stop until evidence is supplied. |

`reproduced` means the claim has been investigated with an actual observable reproducer
or inspection evidence; for a false positive, evidence must establish the claimed scenario
and demonstrate that the alleged failure does not occur. Do not mark it true just because
the reviewer sounded convincing. If the scenario cannot be tested/established, stop.

The JSON ledger records decision references; it cannot authenticate Chief or Hervé.
The operating agent must verify those references against the session/authoritative
decision source. Never treat a reviewer comment requesting a fix as an approval.
