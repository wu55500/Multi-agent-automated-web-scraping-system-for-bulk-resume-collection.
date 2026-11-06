# V6 operational verification / V6 运行核验

Date / 日期: 2026-11-07 Asia/Shanghai.

## Evidence / 证据

- Commit `fbe61b6342d0fa3c8703b77b76313af00441a3ea`: [109 regression tests](https://github.com/wu55500/Multi-agent-automated-web-scraping-system-for-bulk-resume-collection./actions/runs/42262229553) passed. / 109 项回归测试通过。
- Same commit: [runtime integration](https://github.com/wu55500/Multi-agent-automated-web-scraping-system-for-bulk-resume-collection./actions/runs/42262229603) passed: 5 PostgreSQL 16 tests and 2 Chromium tests. / 同一提交的运行时集成通过：5 项 PostgreSQL 16 测试、2 项 Chromium 测试。
- PostgreSQL tests cover ingestion/version idempotency, approval/claim/audit immutability, tenant/health boundaries, concurrent quota and legacy migration. / PostgreSQL 测试覆盖导入/版本幂等性、批准/领取/审计不可变性、租户/健康边界、并发配额及旧库迁移。
- Railway PostgreSQL 18 deployment `8d793c70-1f09-47fe-bfb0-f287336cd381`: SUCCESS. / Railway PostgreSQL 18 部署成功。
- Initial application deployment `2f4cc77b-579f-4978-bfb0-1a9e5d987b0b`: SUCCESS; public dashboard visibly opened in cloud browser. This initial revision precedes the quota fix; use the subsequent pinned revision recorded by Railway. / 首次应用部署成功；已在云浏览器中实际打开公网看板。首次版本早于配额修复，应使用 Railway 中记录的后续固定提交版本。
- Database startup probe initializes configured tenant schemas and runs SELECT 1 before opening the HTTP listener. It is startup readiness, not continuous database-health monitoring. / 数据库启动探针在监听 HTTP 前初始化配置的租户 schema 并执行 SELECT 1。它检查启动就绪，不是持续数据库健康监控。

## Open from phone / 手机访问

1. Open / 打开: https://job-platform-staging.up.railway.app/
2. Open Railway project `job-stack-requirements`, environment `staging`, service `job-platform`, tab `Variables`. / 打开 Railway 项目 `job-stack-requirements` → `staging` 环境 → `job-platform` 服务 → `Variables`。
3. Reveal and copy `DZ_ACCESS_TOKEN`; paste into the dashboard access-token field and select Load. / 显示并复制 `DZ_ACCESS_TOKEN`，粘贴到看板的“访问令牌”，点击“载入”。
4. This is an empty staging database. No historical phone database or private resume was uploaded. Register sources/import authorized records through the CLI before expecting search results. / 这是空的测试环境数据库，未上传手机历史数据库或私人简历。应先通过 CLI 注册来源并导入授权数据，再查询结果。

Project / 项目: https://railway.com/project/8c4f9dae-09c3-4314-ab59-d808f9f5bf15

## Limits / 限制

Staging is not a certified production service. No load/SLA test, backup restore drill, real ATS submission or funded model call has been performed. Running Railway resources can consume the account's existing allowance; no plan upgrade was purchased. / 测试环境不是经过认证的生产服务。尚未执行负载/SLA 测试、备份恢复演练、真实 ATS 投递或有余额的模型调用。Railway 运行资源可能消耗账号现有额度；未购买套餐升级。

Model credentials, approved target-platform access and representative coverage data remain external dependencies; see the bilingual gap register. / 模型凭据、已批准的目标平台访问权限及代表性覆盖率数据仍是外部依赖，详见双语缺口登记表。

## Final deployment / 最终部署

Pinned application commit / 固定应用提交: `4b15ca7fe11e2a367a5b34ecab88c25488903a5a`.
Railway deployment / Railway 部署: `a4eacf57-c8a1-4313-97e4-aa7865197f1a`, **SUCCESS**.
Runtime log / 运行日志: `Tenant database initialization passed.` — actual Railway PostgreSQL 18 schema initialization and SELECT 1 succeeded before HTTP startup. / 真实 Railway PostgreSQL 18 的 schema 初始化和 SELECT 1 在 HTTP 启动前执行成功。

The service is pinned: future GitHub pushes do not automatically change the running revision; reconnect its source to a verified commit for release. / 服务已固定提交版本：后续 GitHub push 不会自动更换运行版本，发布时应将来源重新连接到已核验的提交。
