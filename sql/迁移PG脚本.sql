-- ============================================================
-- PostgreSQL 迁移脚本（P0 交付物 · 阶段1 启用）
-- 状态：未验证（本机无 PostgreSQL，无法实跑；上线前必须在真 PG 14+ 上执行并过回归）
-- 用途：V2 五库 + 数仓四层的 PG 方言建表，与 建表脚本V2.sql 一一对应
-- 说明：SQLite→PG 切换时，业务代码只改 store.py 的连接配置，业务代码零改动（适配器原则）
-- RLS（行级安全）骨架已给注释，阶段1 按租户启用
-- ============================================================
BEGIN;

CREATE TABLE IF NOT EXISTS gov_schema_version (schema_name TEXT PRIMARY KEY, version INTEGER, applied_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS gov_agent_tasks (task_id BIGSERIAL PRIMARY KEY, tenant_id TEXT DEFAULT 'personal', stage TEXT, ok INTEGER, error TEXT, cost_ms INTEGER, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS gov_audit_events (event_id BIGSERIAL PRIMARY KEY, ts TIMESTAMPTZ, actor TEXT, action TEXT, entity_type TEXT, entity_id TEXT, detail TEXT, evt_hash TEXT);
CREATE TABLE IF NOT EXISTS gov_approvals (approval_id BIGSERIAL PRIMARY KEY, tenant_id TEXT DEFAULT 'personal', kind TEXT, target_id TEXT, agent TEXT, status TEXT, reason TEXT, decided_at TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS mi_source_registry (source_id BIGSERIAL PRIMARY KEY, category TEXT, name TEXT, base_url TEXT, enabled INTEGER DEFAULT 1, probe_ok INTEGER, probe_at TIMESTAMPTZ, notes TEXT);
CREATE TABLE IF NOT EXISTS mi_source_postings (source_posting_id TEXT PRIMARY KEY, canonical_job_id TEXT, platform TEXT, source_url TEXT, raw_hash TEXT, fetched_at TIMESTAMPTZ, tenant_id TEXT DEFAULT 'personal');
CREATE TABLE IF NOT EXISTS mi_canonical_jobs (canonical_job_id TEXT PRIMARY KEY, tenant_id TEXT DEFAULT 'personal', title TEXT, company_name TEXT, city TEXT, salary_min_raw TEXT, salary_max_raw TEXT, salary_period TEXT, salary_months_per_year NUMERIC(6,2), salary_min_monthly NUMERIC(12,2), salary_max_monthly NUMERIC(12,2), salary_min_annual NUMERIC(14,2), salary_max_annual NUMERIC(14,2), salary_currency TEXT, salary_tax_basis TEXT, salary_includes_bonus INTEGER, salary_parse_confidence NUMERIC(5,4), salary_parse_status TEXT, experience_text TEXT, experience_min_years NUMERIC(4,1), experience_max_years NUMERIC(4,1), education TEXT, major_required TEXT, responsibilities_text TEXT, requirements_text TEXT, publish_time TIMESTAMPTZ, is_active INTEGER DEFAULT 1, tags JSONB, source_scope TEXT);
CREATE TABLE IF NOT EXISTS mi_job_versions (job_version_id TEXT PRIMARY KEY, canonical_job_id TEXT, version_no INTEGER, jd_hash TEXT, content TEXT, created_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS mi_job_identity_links (link_id BIGSERIAL PRIMARY KEY, canonical_job_id TEXT, source_posting_id TEXT, confidence NUMERIC(5,4), evidence TEXT);
CREATE TABLE IF NOT EXISTS mi_companies (company_id BIGSERIAL PRIMARY KEY, company_name TEXT, site TEXT, industry TEXT, size_text TEXT, city TEXT, tenant_id TEXT DEFAULT 'personal');
CREATE TABLE IF NOT EXISTS mi_company_aliases (alias_id BIGSERIAL PRIMARY KEY, company_id BIGINT, alias_name TEXT, source TEXT);
CREATE TABLE IF NOT EXISTS mi_skills (skill_id BIGSERIAL PRIMARY KEY, cid TEXT UNIQUE, name TEXT, name_plain TEXT, category TEXT);
CREATE TABLE IF NOT EXISTS mi_skill_aliases (alias_id BIGSERIAL PRIMARY KEY, skill_id BIGINT, alias_term TEXT);
CREATE TABLE IF NOT EXISTS mi_job_skill_evidence (evidence_id BIGSERIAL PRIMARY KEY, job_version_id TEXT, skill_id BIGINT, skill_name_raw TEXT, requirement_level TEXT, evidence_text TEXT, evidence_location TEXT, extraction_method TEXT, confidence NUMERIC(5,4), extractor_version TEXT);
CREATE TABLE IF NOT EXISTS mi_parser_runs (run_id BIGSERIAL PRIMARY KEY, raw_document_id TEXT, parser_version TEXT, ok INTEGER, cost_ms INTEGER, ts TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS a1_user_profiles (profile_id BIGSERIAL PRIMARY KEY, tenant_id TEXT DEFAULT 'personal', mine JSONB, notes TEXT, updated_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a1_job_match_results (match_id BIGSERIAL PRIMARY KEY, canonical_job_id TEXT, match_score NUMERIC(5,4), resume_version_id BIGINT, ts TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a1_skill_gap_reports (gap_id BIGSERIAL PRIMARY KEY, match_id BIGINT, missing_skills JSONB, ts TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a1_project_plans (project_id BIGSERIAL PRIMARY KEY, canonical_job_id TEXT, title TEXT, plan_text TEXT, status TEXT, created_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a1_resume_versions (resume_version_id BIGSERIAL PRIMARY KEY, tenant_id TEXT DEFAULT 'personal', name TEXT, content_text TEXT, created_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a1_application_records (application_id TEXT PRIMARY KEY, tenant_id TEXT DEFAULT 'personal', canonical_job_id TEXT, resume_version_id BIGINT, status TEXT, apply_time TIMESTAMPTZ, confirm_time TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS a2_hr_conversations (conversation_id BIGSERIAL PRIMARY KEY, tenant_id TEXT DEFAULT 'personal', platform TEXT, contact TEXT, started_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a2_hr_messages (message_id BIGSERIAL PRIMARY KEY, conversation_id BIGINT, direction TEXT, content TEXT, ts TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a2_reply_drafts (draft_id BIGSERIAL PRIMARY KEY, message_id BIGINT, content TEXT, intent TEXT, status TEXT, created_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS a2_interview_sessions (session_id BIGSERIAL PRIMARY KEY, canonical_job_id TEXT, questions JSONB, feedback TEXT, ts TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS a3_audit_runs (audit_id BIGSERIAL PRIMARY KEY, scope TEXT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, ok INTEGER, summary TEXT);
CREATE TABLE IF NOT EXISTS a3_audit_findings (finding_id BIGSERIAL PRIMARY KEY, audit_id BIGINT, severity TEXT, category TEXT, entity_type TEXT, entity_id TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS a3_gate_decisions (gate_id BIGSERIAL PRIMARY KEY, kind TEXT, target_id TEXT, agent TEXT, decision TEXT, reason TEXT, decided_at TIMESTAMPTZ);

CREATE TABLE IF NOT EXISTS dw_ods_raw_documents (document_id TEXT PRIMARY KEY, source_id BIGINT, document_type TEXT, source_url TEXT, canonical_url TEXT, raw_payload_uri TEXT, raw_payload_hash TEXT, content_type TEXT, http_status INTEGER, published_at_raw TEXT, fetched_at TIMESTAMPTZ, crawl_batch_id TEXT, parser_version TEXT);
CREATE TABLE IF NOT EXISTS dw_ods_raw_job_postings (id TEXT PRIMARY KEY, platform TEXT, source_url TEXT, source_type TEXT, raw_payload TEXT, raw_hash TEXT, crawl_batch_id TEXT, http_status INTEGER, crawl_time TIMESTAMPTZ, publish_time_raw TEXT);
CREATE TABLE IF NOT EXISTS dw_ods_crawl_events (batch_id TEXT PRIMARY KEY, source_id BIGINT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ, ok INTEGER, error TEXT, items_fetched INTEGER, valid_items INTEGER, success_rate NUMERIC(5,4), dup_rate NUMERIC(5,4), cost_ms INTEGER, fetch_latency_ms INTEGER);

CREATE TABLE IF NOT EXISTS dw_dwd_source_postings (source_posting_id TEXT PRIMARY KEY, canonical_job_id TEXT, platform TEXT, source_url TEXT, raw_hash TEXT, fetched_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS dw_dwd_canonical_jobs (canonical_job_id TEXT PRIMARY KEY, title TEXT, company_name TEXT, city TEXT, salary_min_monthly NUMERIC(12,2), salary_max_monthly NUMERIC(12,2), experience_min_years NUMERIC(4,1), experience_max_years NUMERIC(4,1), education TEXT, tags JSONB, source_scope TEXT);
CREATE TABLE IF NOT EXISTS dw_dwd_job_versions (job_version_id TEXT PRIMARY KEY, canonical_job_id TEXT, version_no INTEGER, jd_hash TEXT, created_at TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS dw_dwd_job_identity_links (link_id BIGINT PRIMARY KEY, canonical_job_id TEXT, source_posting_id TEXT, confidence NUMERIC(5,4), evidence TEXT);
CREATE TABLE IF NOT EXISTS dw_dwd_job_skill_evidence (evidence_id BIGINT PRIMARY KEY, job_version_id TEXT, skill_id BIGINT, skill_name_raw TEXT, requirement_level TEXT, evidence_text TEXT, evidence_location TEXT, extraction_method TEXT, confidence NUMERIC(5,4), extractor_version TEXT);

CREATE TABLE IF NOT EXISTS dw_dws_skill_frequency_daily (stat_date DATE, platform TEXT, job_category TEXT, city TEXT, skill_id BIGINT, job_count INTEGER, mention_count INTEGER, numerator INTEGER, denominator INTEGER, metric_definition_version TEXT, source_scope TEXT, deduplication_policy TEXT, time_window TEXT);
CREATE TABLE IF NOT EXISTS dw_dws_skill_requirement_daily (stat_date DATE, skill_id BIGINT, requirement_level TEXT, job_count INTEGER, numerator INTEGER, denominator INTEGER, source_scope TEXT);
CREATE TABLE IF NOT EXISTS dw_dws_market_distribution_daily (stat_date DATE, platform TEXT, job_category TEXT, city TEXT, job_count INTEGER, avg_salary_min NUMERIC(12,2), avg_salary_max NUMERIC(12,2), education_dist JSONB, major_dist JSONB, top_tech JSONB, sample_size INTEGER, source_composition TEXT);
CREATE TABLE IF NOT EXISTS dw_dws_skill_salary_relationship (stat_date DATE, skill_id BIGINT, job_count INTEGER, avg_salary_min NUMERIC(12,2), avg_salary_max NUMERIC(12,2), correlation_note TEXT);
CREATE TABLE IF NOT EXISTS dw_dws_drift_monitor (stat_date DATE, skill_id BIGINT, drift_type TEXT, current_ratio NUMERIC(6,4), baseline_ratio NUMERIC(6,4), delta_ratio NUMERIC(8,4), drift_score NUMERIC(6,4), sample_size INTEGER, baseline_window TEXT, current_window TEXT, source_composition TEXT, ci_low NUMERIC(6,4), ci_high NUMERIC(6,4), alert_level TEXT);

CREATE TABLE IF NOT EXISTS dw_ads_job_recommend (job_id TEXT, match_score NUMERIC(5,4), project_suggestion TEXT, resume_version TEXT, ts TIMESTAMPTZ);
CREATE TABLE IF NOT EXISTS dw_ads_tech_radar (stat_date DATE, skill_id BIGINT, current_ratio NUMERIC(6,4), baseline_ratio NUMERIC(6,4), delta NUMERIC(8,4), sample_size INTEGER, action TEXT);
CREATE TABLE IF NOT EXISTS dw_ads_city_radar (stat_date DATE, city TEXT, job_count INTEGER, avg_salary_min NUMERIC(12,2), avg_salary_max NUMERIC(12,2), source_composition TEXT);
CREATE TABLE IF NOT EXISTS dw_ads_gap_dashboard (profile_id BIGINT, missing_skills JSONB, project_plan_id BIGINT, ts TIMESTAMPTZ);

-- 行级安全（阶段1 企业化时启用；默认关闭 = 单租户个人使用）
-- ALTER TABLE mi_canonical_jobs ENABLE ROW LEVEL SECURITY;
-- CREATE POLICY tenant_isolation ON mi_canonical_jobs USING (tenant_id = current_setting('app.tenant_id'));

COMMIT;
