# V6 delivery and gap register

Project: **An automated multi-agent web crawler system for collecting job-specific technology stack requirements and conducting high-volume resume submissions**

Report date: 2026-11-07 (Asia/Shanghai). This report supersedes V5 status statements, not its historical evidence. English and Chinese documents use matching section and requirement IDs.

## 1. Acceptance standard

“100% implemented” means every requirement in an explicitly bounded scope has implementation, reproducible tests, deployment evidence and accepted operational metrics. Unit-test success is not proof of production readiness, universal ATS compatibility, application delivery or market coverage. No employer application or HR message was sent during this work.

## 2. Delivered functionality

| ID | Capability | Implementation and qualification |
|---|---|---|
| D01 | Source registry and imports | Consent/review/partner-contract references, enable/disable, atomic daily quotas; CSV/JSON/JSONL use the same ingestion gate. |
| D02 | Data lineage and canonicalization | Immutable raw versions, skill evidence offsets, exact company/title/city grouping, bounded fuzzy review candidates and audited manual merge. |
| D03 | Coverage and observability | Conditional Chapman estimate, zero-overlap lower bound, source/city/time scope; UTC health, 429/CAPTCHA/blocked metrics, invocation log. Independent reference-sample benchmark adds Wilson 95% confidence interval. |
| D04 | Tenant API and dashboard | Token-bound tenant, reader/operator roles, SQLite file isolation, mobile dashboard, source/health/coverage/application/audit/skill-shift views. Legacy API remains single-user. |
| D05 | Application workflow | Draft, version/hash-bound approval, expiry, atomic claim, Idempotency-Key gateway submission, uncertain-outcome hold and manual reconciliation. Real platform integration pending. |
| D06 | ATS and feeds | Greenhouse, Lever, SmartRecruiters pagination/details, RSS/Atom, authorized JSON feed and JobPosting JSON-LD. Workday supports public JSON-LD/export only. Most adapter contracts use fixtures. |
| D07 | Playwright | Real Chromium executes dynamic JobPosting rendering and mobile dashboard tests in CI. This is controlled test content, not a live ATS compatibility certification. |
| D08 | PostgreSQL | psycopg backend, hashed schema per tenant, serialized write transactions, immutable audit/version triggers, legacy SQLite migration integration tests. Service database role is trusted across schemas; this is not PostgreSQL RLS. |
| D09 | Model orchestration | Configurable real HTTPS Chat Completions-compatible transport, analyst/reviewer calls, exact-source evidence checks, disagreement output and usage/hash traces. Missing credentials fail explicitly; fixture-tested, no real provider call yet. |
| D10 | Project generation | Builder/reviewer pipeline, path/extension/size limits, Python AST validation and review rejection. Generated code is saved but never automatically executed; sandbox build/test pending. |
| D11 | Supporting workflows | Deterministic matching/learning plan, HR reply drafts with sensitive-message handoff, timezone-aware ICS export, last-observed cohort skill drift. |
| D12 | Deployment | Railway Docker configuration, private PostgreSQL reference, environment-based access token, health endpoint and same-device local launcher. Operational result is recorded separately below. |

## 3. Verification evidence

Local regression: `python3 -m unittest discover -s tests` — 109 tests passed before the access-token bootstrap addition. GitHub Verify run 42261823131 passed on commit `057568aabeaffc9c86021ba7eb8cd2c619ed6ffc`, including that addition. Chromium job 128042403335 passed two real browser tests on commit `3218ea7c226891ad9247c7a806932831289fd565`. PostgreSQL integration and deployment results are recorded in `OPERATIONS_V6.md` after verification. Earlier failures remain visible in Actions; they are not hidden or counted as passes.

Baseline was the verified 64-file archive with 54 tests. The reported V4 commit `30e91a9` and claimed 107-test package were unavailable; their reported results were not reused as evidence.

## 4. Remaining requirements and closure criteria

| ID | Gap | Required work / external input | Acceptance criterion |
|---|---|---|---|
| G01 | Real recruitment submission | Authorized platform account, approved resume, target platform fields and controlled test destination; implement per-platform mapping and receipt reconciliation. | Approved submission produces a platform receipt; timeout/retry cannot duplicate it; approval expiry and field errors tested. |
| G02 | General Workday support | Representative tenant URLs, permitted access and actual form/API contracts; handle pagination, locale, attachments and custom questions per tenant. | Supported tenant/version matrix passes live read and controlled submission tests; unsupported variants fail explicitly. |
| G03 | Real multi-model execution | Provider endpoints/models, funded credentials via environment secrets; configure independent providers where required. | Real requests, usage/cost trace, evidence validation and timeout/error cases pass. Separate prompts alone do not establish statistical independence. |
| G04 | Executable generated projects | Isolated disposable runner, resource/network limits, dependency review and generated-project acceptance tests. | Build/test artifacts and reproducible results; no untrusted code executes in the application process. |
| G05 | Cloud-native suite | Kafka/Flink/ClickHouse/K8s/APISIX/OPA require real pipeline wiring, deployment, failure recovery and load tests. Railway app+PostgreSQL does not complete this suite. | Measured throughput/latency, replay/idempotency, policy decisions and recovery evidence against agreed targets. |
| G06 | Market coverage >=90% | Define market/time/job universe, acquire authorized feeds and independent representative reference data; validate entity resolution. | Representative benchmark and uncertainty support target. Wilson interval alone cannot fix selection bias; capture-recapture assumptions must hold. |
| G07 | Production hardening | Ingress connection/rate limits, enforced network egress, credential rotation, backup/restore drill, retention/deletion and external immutable audit sink. | Security tests and recovery objectives pass; database administrator tampering addressed independently. |
| G08 | Product completeness | Merge reversal, billing/quotas lifecycle, self-service tenant management and real calendar/HR provider integrations remain. | Requirement-specific integration and failure-path tests; enterprise SLA supported by measurements. |
| G09 | Repository URL rename | Full English display name is applied. Current connector has no repository administration rename operation. | Owner renames URL in GitHub Settings and updates Railway source/remote references; display title remains the full requested name. |

## 5. Access and credentials

`127.0.0.1:8771` points to the device opening the browser. On a phone it requires a server running on that phone. Connection refusal does not identify VPN failure or OpenAI blocking. Run `python scripts/start_local.py` on the same device, or use the verified Railway HTTPS address in `OPERATIONS_V6.md`.

Railway Variables contains `DZ_ACCESS_TOKEN`; reveal/copy it into the dashboard token field. It is not an OpenAI API key. `DZ_DATABASE_URL` references the private database. Never commit credentials. Model configuration is `examples/models.json`; replace placeholder endpoint/model values and supply the named environment secrets. No API key should be pasted into public issues or code.

GitHub manages source/history/CI; Railway hosts runtime/database; OpenAI Developers can assist API integration but does not by itself grant funded API access. A “work usage” notice cannot be attributed to Railway without identifying the service that displayed it.
