# V5 delivery and verification — 2026-11-06

## Baseline

Source: uploaded 64-file dz-project-full.zip, SHA-256 ba752c6035c5a880c46b26203411330574652e8682f6d718faeb32314c788ab9. Baseline tests: 54. Claimed V4 commit 30e91a9 was not available in remote; this build reconstructs capabilities on the verified older code. Historical reports do not prove the current runtime.

## Implemented and locally verified

- Source registry, enable/disable, consent/review references, partner contract references, daily record quotas.
- CSV/JSON/JSONL import through the same transactional gate; validation failure rolls back the complete batch.
- Immutable raw record versions; original text skill evidence with character offsets; exact cross-source canonical grouping and explicit fuzzy review candidates/merge audit.
- Conditional Chapman estimator, no market estimate when overlap is zero; source/city/time scope and assumptions recorded.
- UTC daily request health, 429, CAPTCHA, blocked responses, latency and CLI invocation records.
- Tenant-per-file SQLite isolation, hashed token registry, reader/operator API roles, tenant selection from server token binding.
- Mobile-width web dashboard for jobs/sources/health/coverage/application status/audit/skill shifts; draft preparation and version-specific approval.
- Resume reference validation, approval bound to resume hash and job version, expiration, atomic claim, idempotency-key gateway submission, uncertain-result hold, manual reconciliation.
- Deterministic skill analysis / match / learning plan / evidence audit pipeline; HR reply templates and sensitive-message handoff; local timezone-aware ICS export.
- Read-only legacy migration with chunk transactions and version uniqueness; rerun and incremental import tested. Legacy eligibility flags are not compliance violations.
- Old PG canonical-job primary-key mismatch fixed; SQLite identity-link type aligned to TEXT.

## Adapter implementation and limits

| Adapter | Implementation | Verification |
|---|---|---|
| Greenhouse | full board response parsing | local fixture; live DNS probe failed |
| Lever | description and list section parsing | local fixture |
| SmartRecruiters | bounded pagination plus per-posting details; refuses incomplete result | local fixtures |
| RSS / Atom | namespaces, alternate links, descriptions, DTD rejection | local fixtures |
| JSON / partner | normalized array ingestion; partner reference gate | local ingestion tests |
| JobPosting JSON-LD | object/list/graph parsing | local fixture |
| Workday | public JobPosting pages / authorized normalized export | **partial**; not general Workday CXS crawler |
| Playwright | optional same-origin GET renderer behind source/robots gate | **not run**, dependency/browser absent |

Sources used for API contracts: https://docs.greenhouse.io/job-board and https://developers.smartrecruiters.com/docs/endpoints . No live correctness claim is inferred from documentation.

## Validation evidence

`python3 -m unittest discover -s tests`: **100 tests, all pass**, including 54 legacy tests and 46 new tests. Local HTTP integration, parallel quota race, authorization denial and uncertain delivery paths included. `python3 -m compileall -q dz`: passed. Live Greenhouse network probe: DNS resolution failed (`gaierror`), no fetched-job count claimed. HTML served in HTTP integration; no browser visual/JS execution test in this environment.

## Remaining work / cannot claim complete

1. No actual employer submissions or HR messages were sent. Gateway contract tested with fixtures; real account/credentials, platform mapping and receipts still required. Resume evidence references are not independent verification that experiences are true.
2. No real LLM invocation without user API credentials. Existing compatibility client remains; new specialists are explicitly deterministic, not a claimed autonomous multi-LLM system. No project code generation agent was implemented.
3. No server deployment, PG runtime backend, PG migration execution, Kafka/Flink/ClickHouse/K8s/APISIX/OPA integration, billing or SLA/load certification. Compose reference is present but Docker unavailable. Historical PG SQL is not the new runtime's migration.
4. No domestic whole-market feed, business partner, or 90% coverage proof. Authorized imports work; acquiring data still requires real sources.
5. Audit triggers/hash chain detect or reject ordinary mutation, not a malicious database administrator. No separately operated external immutable audit sink.
6. API needs production TLS, ingress rate/connection limits and network egress enforcement. DNS validation alone has a rebinding TOCTOU gap. No production security certification.
7. Canonical exact matches can conflate identical postings; fuzzy candidates are bounded to 500 postings per company/city group and need human review. No merge reversal command yet.
8. Source registry flags record a review decision; they do not automatically determine legality or validity of consent.
9. Skill drift reports compare last-observed cohorts, not historical market snapshots; no causal or market-wide inference.
10. Repository full English display title updated. GitHub connector exposes no repository rename operation; URL name remains unchanged.

## Operational boundaries

Use only `dz.cli platform` for new authenticated multi-user functions. Legacy CLI/API are retained for compatibility and single-user analysis; they do not acquire the new gates automatically. Tokens are local files; never commit them. User data, collected real datasets and generated reports are excluded from this commit.
