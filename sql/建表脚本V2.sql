-- ============================================================
-- V2 建表脚本（P0 交付物）
-- 作用：在 dz.db 里建 V2 五库 + 数仓四层（共 41 张表），老表不动
-- 说明：SQLite 方言执行；所有字段按 PostgreSQL 标准设计（阶段1 用 迁移PG脚本.sql 切换）
-- 时间字段统一 TEXT(ISO 时间戳)；tenant_id 从第一天就有
-- 安全：全部 CREATE TABLE IF NOT EXISTS，可重复执行
-- ============================================================

-- ---------- gov_ 平台治理 ----------
CREATE TABLE IF NOT EXISTS gov_schema_version (
  schema_name TEXT PRIMARY KEY, version INTEGER, applied_at TEXT);

CREATE TABLE IF NOT EXISTS gov_agent_tasks (
  task_id INTEGER PRIMARY KEY, tenant_id TEXT DEFAULT 'personal',
  stage TEXT, ok INTEGER, error TEXT, cost_ms INTEGER,
  started_at TEXT, finished_at TEXT);

CREATE TABLE IF NOT EXISTS gov_audit_events (          -- 不可变审计事件，业务 Agent 无写权限
  event_id INTEGER PRIMARY KEY, ts TEXT, actor TEXT, action TEXT,
  entity_type TEXT, entity_id TEXT, detail TEXT, evt_hash TEXT);

CREATE TABLE IF NOT EXISTS gov_approvals (
  approval_id INTEGER PRIMARY KEY, tenant_id TEXT DEFAULT 'personal',
  kind TEXT, target_id TEXT, agent TEXT, status TEXT, reason TEXT, decided_at TEXT);

-- ---------- mi_ 市场情报 ----------
CREATE TABLE IF NOT EXISTS mi_source_registry (
  source_id INTEGER PRIMARY KEY, category TEXT, name TEXT, base_url TEXT,
  enabled INTEGER DEFAULT 1, probe_ok INTEGER, probe_at TEXT, notes TEXT);

CREATE TABLE IF NOT EXISTS mi_source_postings (        -- 平台上的一条招聘记录
  source_posting_id TEXT PRIMARY KEY, canonical_job_id TEXT,
  platform TEXT, source_url TEXT, raw_hash TEXT, fetched_at TEXT,
  tenant_id TEXT DEFAULT 'personal');

CREATE TABLE IF NOT EXISTS mi_canonical_jobs (         -- 跨来源统一岗位实体
  canonical_job_id TEXT PRIMARY KEY, tenant_id TEXT DEFAULT 'personal',
  title TEXT, company_name TEXT, city TEXT,
  salary_min_raw TEXT, salary_max_raw TEXT, salary_period TEXT,
  salary_months_per_year REAL, salary_min_monthly REAL, salary_max_monthly REAL,
  salary_min_annual REAL, salary_max_annual REAL, salary_currency TEXT,
  salary_tax_basis TEXT, salary_includes_bonus INTEGER,
  salary_parse_confidence REAL, salary_parse_status TEXT,
  experience_text TEXT, experience_min_years REAL, experience_max_years REAL,
  education TEXT, major_required TEXT,
  responsibilities_text TEXT, requirements_text TEXT,
  publish_time TEXT, is_active INTEGER DEFAULT 1,
  tags TEXT, source_scope TEXT);

CREATE TABLE IF NOT EXISTS mi_job_versions (           -- 岗位历史版本，永不覆盖
  job_version_id TEXT PRIMARY KEY, canonical_job_id TEXT,
  version_no INTEGER, jd_hash TEXT, content TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS mi_job_identity_links (     -- 跨来源归并关系（证据+置信度）
  link_id INTEGER PRIMARY KEY, canonical_job_id TEXT,
  source_posting_id TEXT, confidence REAL, evidence TEXT);

CREATE TABLE IF NOT EXISTS mi_companies (
  company_id INTEGER PRIMARY KEY, company_name TEXT, site TEXT,
  industry TEXT, size_text TEXT, city TEXT, tenant_id TEXT DEFAULT 'personal');

CREATE TABLE IF NOT EXISTS mi_company_aliases (
  alias_id INTEGER PRIMARY KEY, company_id INTEGER, alias_name TEXT, source TEXT);

CREATE TABLE IF NOT EXISTS mi_skills (
  skill_id INTEGER PRIMARY KEY, cid TEXT UNIQUE, name TEXT,
  name_plain TEXT, category TEXT);

CREATE TABLE IF NOT EXISTS mi_skill_aliases (
  alias_id INTEGER PRIMARY KEY, skill_id INTEGER, alias_term TEXT);

CREATE TABLE IF NOT EXISTS mi_job_skill_evidence (     -- 技能证据链（原文定位+必须/加分）
  evidence_id INTEGER PRIMARY KEY, job_version_id TEXT, skill_id INTEGER,
  skill_name_raw TEXT, requirement_level TEXT, evidence_text TEXT,
  evidence_location TEXT, extraction_method TEXT, confidence REAL,
  extractor_version TEXT);

CREATE TABLE IF NOT EXISTS mi_parser_runs (
  run_id INTEGER PRIMARY KEY, raw_document_id TEXT, parser_version TEXT,
  ok INTEGER, cost_ms INTEGER, ts TEXT);

-- ---------- a1_ Agent1 求职执行 ----------
CREATE TABLE IF NOT EXISTS a1_user_profiles (
  profile_id INTEGER PRIMARY KEY, tenant_id TEXT DEFAULT 'personal',
  mine TEXT, notes TEXT, updated_at TEXT);

CREATE TABLE IF NOT EXISTS a1_job_match_results (
  match_id INTEGER PRIMARY KEY, canonical_job_id TEXT,
  match_score REAL, resume_version_id INTEGER, ts TEXT);

CREATE TABLE IF NOT EXISTS a1_skill_gap_reports (
  gap_id INTEGER PRIMARY KEY, match_id INTEGER, missing_skills TEXT, ts TEXT);

CREATE TABLE IF NOT EXISTS a1_project_plans (
  project_id INTEGER PRIMARY KEY, canonical_job_id TEXT, title TEXT,
  plan_text TEXT, status TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS a1_resume_versions (
  resume_version_id INTEGER PRIMARY KEY, tenant_id TEXT DEFAULT 'personal',
  name TEXT, content_text TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS a1_application_records (    -- 投递记录=业务交易，不进数仓
  application_id TEXT PRIMARY KEY, tenant_id TEXT DEFAULT 'personal',
  canonical_job_id TEXT, resume_version_id INTEGER, status TEXT,
  apply_time TEXT, confirm_time TEXT);

-- ---------- a2_ Agent2 沟通与面试 ----------
CREATE TABLE IF NOT EXISTS a2_hr_conversations (
  conversation_id INTEGER PRIMARY KEY, tenant_id TEXT DEFAULT 'personal',
  platform TEXT, contact TEXT, started_at TEXT);

CREATE TABLE IF NOT EXISTS a2_hr_messages (
  message_id INTEGER PRIMARY KEY, conversation_id INTEGER,
  direction TEXT, content TEXT, ts TEXT);

CREATE TABLE IF NOT EXISTS a2_reply_drafts (
  draft_id INTEGER PRIMARY KEY, message_id INTEGER, content TEXT,
  intent TEXT, status TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS a2_interview_sessions (
  session_id INTEGER PRIMARY KEY, canonical_job_id TEXT,
  questions TEXT, feedback TEXT, ts TEXT);

-- ---------- a3_ Agent3 审计监管 ----------
CREATE TABLE IF NOT EXISTS a3_audit_runs (
  audit_id INTEGER PRIMARY KEY, scope TEXT, started_at TEXT,
  finished_at TEXT, ok INTEGER, summary TEXT);

CREATE TABLE IF NOT EXISTS a3_audit_findings (
  finding_id INTEGER PRIMARY KEY, audit_id INTEGER, severity TEXT,
  category TEXT, entity_type TEXT, entity_id TEXT, detail TEXT);

CREATE TABLE IF NOT EXISTS a3_gate_decisions (         -- 闸门放行/驳回记录
  gate_id INTEGER PRIMARY KEY, kind TEXT, target_id TEXT,
  agent TEXT, decision TEXT, reason TEXT, decided_at TEXT);

-- ---------- 数仓 ODS 原始层 ----------
CREATE TABLE IF NOT EXISTS dw_ods_raw_documents (      -- 六类情报通用原始文档
  document_id TEXT PRIMARY KEY, source_id INTEGER, document_type TEXT,
  source_url TEXT, canonical_url TEXT, raw_payload_uri TEXT,
  raw_payload_hash TEXT, content_type TEXT, http_status INTEGER,
  published_at_raw TEXT, fetched_at TEXT, crawl_batch_id TEXT,
  parser_version TEXT);

CREATE TABLE IF NOT EXISTS dw_ods_raw_job_postings (   -- 招聘 JD 原始
  id TEXT PRIMARY KEY, platform TEXT, source_url TEXT, source_type TEXT,
  raw_payload TEXT, raw_hash TEXT, crawl_batch_id TEXT,
  http_status INTEGER, crawl_time TEXT, publish_time_raw TEXT);

CREATE TABLE IF NOT EXISTS dw_ods_crawl_events (       -- 采集任务执行记录（健康指标）
  batch_id TEXT PRIMARY KEY, source_id INTEGER, started_at TEXT, finished_at TEXT,
  ok INTEGER, error TEXT, items_fetched INTEGER, valid_items INTEGER,
  success_rate REAL, dup_rate REAL, cost_ms INTEGER, fetch_latency_ms INTEGER);

-- ---------- 数仓 DWD 明细层（P2 填充：从 mi_ 清洗而来，口径与 mi_ 对齐） ----------
CREATE TABLE IF NOT EXISTS dw_dwd_source_postings (
  source_posting_id TEXT PRIMARY KEY, canonical_job_id TEXT,
  platform TEXT, source_url TEXT, raw_hash TEXT, fetched_at TEXT);

CREATE TABLE IF NOT EXISTS dw_dwd_canonical_jobs (
  canonical_job_id TEXT PRIMARY KEY, title TEXT, company_name TEXT, city TEXT,
  salary_min_monthly REAL, salary_max_monthly REAL, experience_min_years REAL,
  experience_max_years REAL, education TEXT, tags TEXT, source_scope TEXT);

CREATE TABLE IF NOT EXISTS dw_dwd_job_versions (
  job_version_id TEXT PRIMARY KEY, canonical_job_id TEXT,
  version_no INTEGER, jd_hash TEXT, created_at TEXT);

CREATE TABLE IF NOT EXISTS dw_dwd_job_identity_links (
  link_id INTEGER PRIMARY KEY, canonical_job_id TEXT,
  source_posting_id TEXT, confidence REAL, evidence TEXT);

CREATE TABLE IF NOT EXISTS dw_dwd_job_skill_evidence (
  evidence_id INTEGER PRIMARY KEY, job_version_id TEXT, skill_id INTEGER,
  skill_name_raw TEXT, requirement_level TEXT, evidence_text TEXT,
  evidence_location TEXT, extraction_method TEXT, confidence REAL,
  extractor_version TEXT);

-- ---------- 数仓 DWS 汇总层（P3 填充：口径严谨，每条带分子/分母/口径版本） ----------
CREATE TABLE IF NOT EXISTS dw_dws_skill_frequency_daily (
  stat_date TEXT, platform TEXT, job_category TEXT, city TEXT, skill_id INTEGER,
  job_count INTEGER, mention_count INTEGER, numerator INTEGER, denominator INTEGER,
  metric_definition_version TEXT, source_scope TEXT, deduplication_policy TEXT,
  time_window TEXT);

CREATE TABLE IF NOT EXISTS dw_dws_skill_requirement_daily (
  stat_date TEXT, skill_id INTEGER, requirement_level TEXT, job_count INTEGER,
  numerator INTEGER, denominator INTEGER, source_scope TEXT);

CREATE TABLE IF NOT EXISTS dw_dws_market_distribution_daily (
  stat_date TEXT, platform TEXT, job_category TEXT, city TEXT, job_count INTEGER,
  avg_salary_min REAL, avg_salary_max REAL, education_dist TEXT, major_dist TEXT,
  top_tech TEXT, sample_size INTEGER, source_composition TEXT);

CREATE TABLE IF NOT EXISTS dw_dws_skill_salary_relationship (
  stat_date TEXT, skill_id INTEGER, job_count INTEGER,
  avg_salary_min REAL, avg_salary_max REAL, correlation_note TEXT);

CREATE TABLE IF NOT EXISTS dw_dws_drift_monitor (      -- 三分法：词汇/需求结构/概念漂移
  stat_date TEXT, skill_id INTEGER, drift_type TEXT, current_ratio REAL,
  baseline_ratio REAL, delta_ratio REAL, drift_score REAL, sample_size INTEGER,
  baseline_window TEXT, current_window TEXT, source_composition TEXT,
  ci_low REAL, ci_high REAL, alert_level TEXT);

-- ---------- 数仓 ADS 应用层（只放分析视图，不放交易数据） ----------
CREATE TABLE IF NOT EXISTS dw_ads_job_recommend (
  job_id TEXT, match_score REAL, project_suggestion TEXT,
  resume_version TEXT, ts TEXT);

CREATE TABLE IF NOT EXISTS dw_ads_tech_radar (
  stat_date TEXT, skill_id INTEGER, current_ratio REAL, baseline_ratio REAL,
  delta REAL, sample_size INTEGER, action TEXT);

CREATE TABLE IF NOT EXISTS dw_ads_city_radar (
  stat_date TEXT, city TEXT, job_count INTEGER, avg_salary_min REAL,
  avg_salary_max REAL, source_composition TEXT);

CREATE TABLE IF NOT EXISTS dw_ads_gap_dashboard (
  profile_id INTEGER, missing_skills TEXT, project_plan_id INTEGER, ts TEXT);
