"""SQLite 存储：作业、技能、我的水平、投递队列、事件日志、模型缓存。"""
from __future__ import annotations

import json
import sqlite3
import time

SCHEMA = """
create table if not exists jobs(
  id text primary key, source text, title text, company text, city text,
  salary text, seniority text, raw text, engine text, source_url text, ts real);
create table if not exists job_skills(
  job_id text, raw text, cid text, must int, years real, evidence text, conf real);
create table if not exists mine(cid text primary key, depth int, note text, ts real);
create table if not exists apps(
  job_id text primary key, state text, score real, attempts int default 0,
  next_at real default 0, lease_until real default 0, ts real, note text);
create table if not exists events(
  seq integer primary key autoincrement, kind text, ref text, payload text, ts real);
create table if not exists cache(k text primary key, v text, ts real);
create table if not exists tags(
  job_id text primary key, city text, size text, agent_level int, ts real,
  family text);
create table if not exists run_log(
  id integer primary key autoincrement, stage text, ok int, detail text,
  cost_ms int, ts real);
create table if not exists barriers(
  job_id text primary key, hard int, why text, ts real);
create table if not exists projects(
  cid text, repo text, stars int, url text, lang text, updated text,
  title text, intro text, intro_zh text, uses text, modules text,
  desc text, ts real, primary key (cid, repo));
create table if not exists companies(
  name text primary key, site text, ts real);
"""

# 版本化迁移：只允许追加新版本，不改历史 —— SQLite→PG 时按同一契约平移
MIGRATIONS = {
    1: "create table if not exists schema_version(v int primary key);",
}

# 老库补列：create table if not exists 不会给已存在的表加字段
MIGRATE = (
    ("tags", "family", "text"),
    ("jobs", "source_url", "text"),
)


class Store:
    def __init__(self, path="dz.db"):
        # check_same_thread=False：API 用 ThreadingHTTPServer 多线程读；写只走 cli 单进程
        self.db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)
        self._migrate()
        self.db.commit()
        self.path = path

    def _migrate(self) -> None:
        # 旧式补列（幂等）
        for table, col, decl in MIGRATE:
            have = {r["name"] for r in self.db.execute("pragma table_info(%s)" % table)}
            if col not in have:
                self.db.execute("alter table %s add column %s %s" % (table, col, decl))
        # 版本化迁移
        try:
            cur = self.db.execute("select max(v) from schema_version").fetchone()[0] or 0
        except sqlite3.OperationalError:
            cur = 0
        for v in sorted(MIGRATIONS):
            if v > cur:
                self.db.executescript(MIGRATIONS[v])
                self.db.execute("insert or replace into schema_version(v) values(?)", (v,))
                self.db.commit()

    # ---------- 作业 ----------
    def put_job(self, jd) -> None:
        c = self.db
        c.execute("insert or replace into jobs values(?,?,?,?,?,?,?,?,?,?,?)",
                  (jd.id, jd.source, jd.title, jd.company, jd.city, jd.salary,
                   jd.seniority, jd.raw, jd.engine, jd.source_url, time.time()))
        c.execute("delete from job_skills where job_id=?", (jd.id,))
        c.executemany(
            "insert into job_skills values(?,?,?,?,?,?,?)",
            [(jd.id, s.raw, s.cid, int(s.must), s.years, s.evidence, s.confidence)
             for s in jd.skills])
        c.commit()
        self.log("job", jd.id, {"title": jd.title, "engine": jd.engine,
                                "skills": len(jd.skills)})

    def job(self, job_id: str):
        r = self.db.execute("select * from jobs where id=?", (job_id,)).fetchone()
        if not r:
            return None
        return dict(r)

    def jobs(self, limit=100, source=None, family=None, exclude=None,
             title=None):
        sql = ("select j.id, j.source, j.title, j.company, j.city, j.salary, "
               "j.seniority, j.engine, j.source_url, j.ts, "
               "t.size, t.agent_level, t.family "
               "from jobs j left join tags t on t.job_id = j.id")
        cond, args = [], []
        if title:
            cond.append("lower(j.title) like ?")
            args.append("%" + title.lower() + "%")
        if source:
            cond.append("j.source = ?")
            args.append(source)
        if exclude:
            cond.append("j.source not in (%s)" % ",".join("?" * len(exclude)))
            args += list(exclude)
        if family:
            cond.append("t.family = ?")
            args.append(family)
        if cond:
            sql += " where " + " and ".join(cond)
        sql += " order by j.ts desc limit ?"
        args.append(limit)
        out = []
        for r in self.db.execute(sql, args):
            d = dict(r)
            d["skills"] = [x["cid"] for x in self.db.execute(
                "select cid from job_skills where job_id = ?", (d["id"],))]
            out.append(d)
        return out

    def skill_freq(self, source=None, limit=30, exclude=None):
        sql = ("select s.cid, count(*) n from job_skills s "
               "join jobs j on j.id = s.job_id")
        args, cond = [], []
        if source:
            cond.append("j.source = ?")
            args.append(source)
        if exclude:
            cond.append("j.source not in (%s)" % ",".join("?" * len(exclude)))
            args += list(exclude)
        if cond:
            sql += " where " + " and ".join(cond)
        sql += " group by s.cid order by n desc limit ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql, args)]

    def cooc(self, source=None, limit=12, exclude=None):
        sql = ("select a.cid a, b.cid b, count(*) n from job_skills a "
               "join job_skills b on b.job_id = a.job_id and a.cid < b.cid "
               "join jobs j on j.id = a.job_id")
        args, cond = [], []
        if source:
            cond.append("j.source = ?")
            args.append(source)
        if exclude:
            cond.append("j.source not in (%s)" % ",".join("?" * len(exclude)))
            args += list(exclude)
        if cond:
            sql += " where " + " and ".join(cond)
        sql += " group by a.cid, b.cid order by n desc limit ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql, args)]

    def evidence(self, cid, limit=10, exclude=None):
        sql = ("select j.id, j.title, j.company, j.source, s.evidence "
               "from job_skills s join jobs j on j.id = s.job_id "
               "where s.cid = ? and s.evidence != ''")
        args = [cid]
        if exclude:
            sql += " and j.source not in (%s)" % ",".join("?" * len(exclude))
            args += list(exclude)
        sql += " order by random() limit ?"
        args.append(limit)
        return [dict(r) for r in self.db.execute(sql, args)]

    def job_skills(self, job_id: str):
        return [dict(r) for r in self.db.execute(
            "select * from job_skills where job_id=? order by must desc, conf desc",
            (job_id,))]

    def put_tag(self, t: dict) -> None:
        self.db.execute(
            "insert or replace into tags(job_id,city,size,agent_level,family,ts)"
            " values(?,?,?,?,?,?)",
            (t["job_id"], t["city"], t["size"], int(t["agent_level"]),
             t.get("family", ""), time.time()))
        self.db.commit()

    def tags(self) -> dict:
        return {r["job_id"]: dict(r) for r in self.db.execute("select * from tags")}

    # ---------- 我的水平 ----------
    def set_mine(self, mapping: dict, notes: dict | None = None) -> None:
        now = time.time()
        self.db.executemany(
            "insert or replace into mine values(?,?,?,?)",
            [(cid, int(d), (notes or {}).get(cid, ""), now) for cid, d in mapping.items()])
        self.db.commit()

    def mine(self) -> dict:
        return {r["cid"]: r["depth"] for r in self.db.execute("select * from mine")}

    def notes(self) -> dict:
        return {r["cid"]: r["note"] for r in self.db.execute(
            "select * from mine where note<>''")}

    # ---------- 公司官网缓存 ----------
    def put_company(self, name: str, site: str) -> None:
        self.db.execute("insert or replace into companies values(?,?,?)",
                        (name, site, time.time()))
        self.db.commit()

    def company_sites(self, names) -> dict:
        out = {}
        for i in range(0, len(names), 500):
            chunk = names[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for name, site in self.db.execute(
                    "select name, site from companies where name in (%s)" % ph,
                    chunk):
                out[name] = site
        return out

    def job_skills_map(self, ids) -> dict:
        out = {i: [] for i in ids}
        if not ids:
            return out
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            ph = ",".join("?" * len(chunk))
            for jid, cid in self.db.execute(
                    "select job_id, cid from job_skills where job_id in (%s)"
                    " order by job_id" % ph, chunk):
                out[jid].append(cid)
        return out

    # ---------- 缓存 ----------
    def cache_get(self, k: str):
        r = self.db.execute("select v from cache where k=?", (k,)).fetchone()
        return json.loads(r["v"]) if r else None

    def cache_put(self, k: str, v) -> None:
        self.db.execute("insert or replace into cache values(?,?,?)",
                        (k, json.dumps(v, ensure_ascii=False), time.time()))
        self.db.commit()

    # ---------- 事件 ----------
    def log(self, kind: str, ref: str, payload=None) -> None:
        self.db.execute("insert into events(kind,ref,payload,ts) values(?,?,?,?)",
                        (kind, ref, json.dumps(payload or {}, ensure_ascii=False),
                         time.time()))
        self.db.commit()

    def stats(self, exclude: tuple | None = None) -> dict:
        def q(sql, args=()):
            return self.db.execute(sql, args).fetchone()[0]
        where, args = "", ()
        if exclude:
            where = " where source not in (%s)" % ",".join("?" * len(exclude))
            args = tuple(exclude)
        return {
            "jobs": q("select count(*) from jobs" + where, args),
            "skills": q("select count(*) from job_skills s"
                        " join jobs j on j.id = s.job_id" + where, args),
            "apps": q("select count(*) from apps"),
            "events": q("select count(*) from events"),
            "runs": q("select count(*) from run_log"),
        }

    # ---------- 运行日志（质量可观测层） ----------
    def log_run(self, stage: str, ok: bool, detail: str = "", cost_ms: int = 0) -> None:
        self.db.execute(
            "insert into run_log(stage,ok,detail,cost_ms,ts) values(?,?,?,?,?)",
            (stage, int(ok), detail, int(cost_ms), time.time()))
        self.db.commit()

    def runs(self, limit: int = 50):
        return [dict(r) for r in self.db.execute(
            "select * from run_log order by id desc limit ?", (limit,))]

    def schema_version(self) -> int:
        try:
            return self.db.execute("select max(v) from schema_version").fetchone()[0] or 0
        except sqlite3.OperationalError:
            return 0

    # ---------- 高门槛标记 ----------
    def put_barrier(self, job_id: str, hard: bool, why: str = "") -> None:
        self.db.execute(
            "insert or replace into barriers(job_id,hard,why,ts) values(?,?,?,?)",
            (job_id, int(bool(hard)), why, time.time()))
        self.db.commit()

    def barriers(self) -> dict:
        return {r["job_id"]: dict(r)
                for r in self.db.execute("select * from barriers")}

    # ---------- 开源项目证据链 ----------
    def put_project(self, cid: str, repo: str, stars: int, url: str, lang: str,
                    updated: str, title: str, intro: str, intro_zh: str,
                    uses: str, modules: str, desc: str, ts: float) -> None:
        self.db.execute(
            "insert or replace into projects(cid,repo,stars,url,lang,updated,"
            "title,intro,intro_zh,uses,modules,desc,ts) "
            "values(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (cid, repo, stars, url, lang, updated, title, intro, intro_zh,
             uses, modules, desc, ts))
        self.db.commit()

    def projects(self, cid: str) -> list:
        return [dict(r) for r in self.db.execute(
            "select * from projects where cid=? order by stars desc", (cid,))]

    def project_ts(self, cid: str) -> float:
        r = self.db.execute(
            "select max(ts) from projects where cid=?", (cid,)).fetchone()
        return float(r[0]) if r and r[0] is not None else 0.0

    def clear_projects(self, cid: str) -> None:
        self.db.execute("delete from projects where cid=?", (cid,))
        self.db.commit()

    def pending_projects(self) -> list:
        return [r["cid"] for r in self.db.execute(
            "select cid from projects group by cid")]
