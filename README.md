# An automated multi-agent web crawler system for collecting job-specific technology stack requirements and conducting high-volume resume submissions

岗位技术栈情报与经确认的批量投递。新增 V5 工程基线来自已核实的 54 测试旧包；没有获得此前声称的 107 测试 V4 源码，不能视为其完整继承版。

## 运行

Python 3.10+，核心零第三方依赖。

```bash
python3 -m unittest discover -s tests
python3 -m dz.cli platform --help
python3 -m dz.cli platform source add --id authorized-export --kind json --quota 10000 --consent owned-export --compliance approved
python3 -m dz.cli platform import --source authorized-export --file examples/jobs.json
python3 -m dz.cli platform jobs
python3 -m dz.cli platform health
python3 -m dz.cli platform audit
```

新功能统一通过 `python3 -m dz.cli platform` 或 `python3 -m dz.platform.cli` 使用。旧 CLI 保留兼容，但旧 `dz.db` API **不具备新租户边界，不用于多用户部署**。新入口默认存储 `var/tenants/personal.sqlite3`。

## 看板与租户

```bash
python3 scripts/create_token.py --tenant personal --role operator
export DZ_TOKEN_FILE=var/tokens.json
python3 -m dz.cli platform serve --port 8771
```

访问 http://127.0.0.1:8771 ，输入上一步在本机生成的令牌。支持岗位、来源、覆盖率、健康、投递状态、技能变化、审计校验。令牌绑定租户与角色；每个租户独立 SQLite 文件；`reader` 不能写入。撤销令牌：从本地注册文件移除对应条目并重启服务。生产必须加 HTTPS 反向代理、网络出口控制、备份、访问速率限制；当前 stdlib 服务是可运行参考实现，未做生产容量认证。

## 采集来源

登记真实授权依据后运行 `collect --source ID --company COMPANY`。`--endpoint` 必须填写实际完整入口：

- Greenhouse：`https://boards-api.greenhouse.io/v1/boards/BOARD/jobs?content=true`
- Lever：`https://api.lever.co/v0/postings/BOARD?mode=json`
- SmartRecruiters：`https://api.smartrecruiters.com/v1/companies/COMPANY/postings`，列表分页后读取详情。
- `rss`：RSS 2 / Atom 1 URL；`json`：标准化记录数组；`partner`：还要求 `--contract`。
- `jsonld` / `workday`：公开页面的 JobPosting 结构化数据。**不是 Workday 全租户通用 CXS 适配器**，无结构化数据会报错。
- `collect --render`：可选 Playwright 渲染；先安装可选依赖和 Chromium。当前环境未跑浏览器实测。

每条标准记录含 `id,title,raw`，可选 `company,city,source_url`。CSV/JSON/JSONL 均可导入。注册配额按每天 UTC 输入记录数扣减（重复输入也计数），源停用立即阻止导入。网络只访问登记来源域，限速、robots、持久化冷却、429 和 CAPTCHA 记录；不自动破解验证。当前 DNS 检查不能独自防御 DNS 重绑定，服务部署须配置网络出口限制。

## 归并与覆盖率

`candidates` 输出同公司/城市下的标题相似候选；每组最多检查 500 条，待扩展分页。严格相同公司、标题、城市、正文自动归并，缺少公司/城市时不自动归并。`merge LEFT RIGHT --reason EVIDENCE` 保存人工依据；同名不同职位仍可能误合并，必须抽检。

`cov-estimate SOURCE_A SOURCE_B --days 30 --city 上海` 默认只报观测并集。只有存在重叠且显式提供 `--accept-assumptions` 才输出条件性 Chapman 估计。该值不证明市场覆盖率达到 90%，也不证明岗位仍在招聘。

## 分析与投递

`analyze POSTING_ID --profile FILE` 调用规则抽取、差距评分、学习项目规划、原文证据校验。`reply --message TEXT --facts FILE` 生成待确认模板；敏感问题转人工。这些是确定性模块，不冒充真实调用多个大模型。旧 `dz.extract.LLM` 保留真实兼容 API 接口，但本次没有提供密钥进行实测。

```bash
python3 -m dz.cli platform prepare POSTING_ID --resume examples/resume.json
python3 -m dz.cli platform applications
python3 -m dz.cli platform approve APPLICATION_ID --resume-hash EXACT_HASH
# 仅配置你有权使用且实现以下契约的投递网关后运行：
export DZ_SUBMISSION_URL=https://your-authorized-gateway.example/applications
export DZ_SUBMISSION_KEY=YOUR_SECRET
python3 -m dz.cli platform send APPLICATION_ID_1 APPLICATION_ID_2
```

网关契约：POST JSON `{application_id,posting_id,resume}`，Bearer 密钥与 `Idempotency-Key`；成功返回 JSON `{receipt:"..."}`。系统确认的是**网关回执**，不能自行证明招聘平台最终收到。不会默认向任何企业发送。简历的事实引用只校验字段存在，事实真实性仍须由用户核实。审批绑定岗位版本和简历哈希；超时变成 `uncertain`，不自动重投。`reconcile ID --state submitted --receipt EVIDENCE` 人工对账。旧填表适配器仍仅填表。

`calendar --title 面试 --start 2026-11-10T10:00:00+08:00 --end 2026-11-10T11:00:00+08:00 --out interview.ics` 导出日历，不发送邀请。

## 迁移与部署

```bash
python3 -m dz.cli platform migrate-legacy --db dz.db --consent owned-export
```

只读旧库，批次事务、唯一版本、可重跑补齐后续记录；不把学历门槛迁为合规违法记录。旧版 `迁移数据.py` 改为新 CLI 入口。PG 历史 DDL 的岗位主键类型已修正，但**没有 PG 实例验证，也没有将新运行时替换为 PostgreSQL**。容器配置见 `deploy/`；本环境没有 Docker，未做容器运行验收。

验收与缺口：[docs/DELIVERY_V5.md](docs/DELIVERY_V5.md)。旧设计和验收文档只作历史参考，不能覆盖本文件的实际状态。
