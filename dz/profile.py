"""岗位画像：输入岗位名 → 该岗位在全库的技术栈频次统计。

输入支持：
- 岗位族别名：爬虫 / AI+爬虫 / 大数据 / AI+大数据 / 运维 / 测试 / 全栈 / agent …
- 标题关键词：Java / python / 前端 / 嵌入式 …（可用 + 或空格连多词）
- 混搭：Python+Java+agent → 标题含 python 和 java，且带 agent/LLM 标记
过滤：--easy 只看低门槛（不要求 985/211/硕博/高难算法数学）。
"""
from __future__ import annotations

import re
from collections import Counter

from . import roles
from .ontology import SKILLS, canon as skill_canon, name as skill_name
from .translate import display as zh_title

FAMILY_ALIAS = {
    "爬虫": "crawl", "采集": "crawl", "数据采集": "crawl",
    "大数据": "bigdata", "数仓": "bigdata", "数据仓库": "bigdata",
    "运维": "ops", "sre": "ops", "devops": "ops",
    "测试": "test", "qa": "test", "测开": "test",
    "全栈": "fde", "fde": "fde", "交付": "fde",
    "agent": "agent", "智能体": "agent", "agent开发": "agent", "智能体开发": "agent",
    "ai应用": "ai_app", "ai 应用": "ai_app", "aigc": "ai_app", "大模型": "ai_app",
}

# Agent 时代增量（2026-10 市场调研要点，来源：DeepSeek 联网调研对话）
# 传统自动化=把确定性步骤写死；Agent 把边界推进到「需要理解、判断、动态决策」的环节。
TREND = {
    "title": "Agent 时代增量（市场趋势，DeepSeek 2026-10 调研）",
    "logic": "LLM 负责理解意图、拆解步骤、动态选工具；Python 代码负责确定性执行与校验。"
             "你的 Python 工程能力是驾驭 Agent 的「执行底座」。",
    "business": [
        "代码执行型 Agent：LLM 做 planner、沙箱 Python 做 executor（数据迁移等）",
        "跨系统流程编排：ERP/CRM/工单/桌面软件串成闭环（PCB CAM 异常处理、数据平台工程支持）",
        "非结构化文档「理解+校验」流水线：OCR 提取 + 大模型语义校验 + Python 写入（实测 85%→98.7%）",
        "从「脚本交付」升级为「可观测自动化系统」：工具调用日志、状态机、评估集、人工确认节点",
    ],
    "skills": [
        "Agent 编排框架：LangGraph（招聘最主流）/ LangChain / OpenAI Agents SDK",
        "Tool Calling / 结构化输出：Function Calling、Pydantic、工具 schema 设计",
        "RAG 与向量库：文档切分、检索、重排，让 Agent 查私有知识",
        "MCP（Model Context Protocol）：2026 增速最快的单一技能",
        "沙箱代码执行：代码执行 Agent 的执行底座",
        "评估与可观测：评估集、工具调用日志、异常回退机制",
    ],
    "when": ("agent", "ai_app"),
}


def parse_role(text: str) -> dict:
    """岗位输入 → 查询规格 {kws, skills, family, ai, label}。

    技术词（python/java/docker…）走技能本体匹配（精确到已抽取的技能），
    认不出技能的词走标题模糊匹配。"""
    text = (text or "").strip()
    parts = [p for p in re.split(r"[+\s、,，/]+", text) if p]
    fam, ai, kws, skills = None, False, [], []
    for p in parts:
        pl = p.lower()
        if pl in ("ai", "aigc", "人工智能", "ai+", "＋ai"):
            ai = True
            continue
        if pl in FAMILY_ALIAS:
            fam = FAMILY_ALIAS[pl]
            continue
        cid = skill_canon(p)
        if cid and cid in SKILLS:
            skills.append(cid)
        else:
            kws.append(p)
    if fam == "agent":
        ai = True
    label = roles.label_of(fam + ("+ai" if ai and fam in roles.PLUS else "")) \
        if fam else (text or "关键词")
    return {"kws": kws, "skills": skills, "family": fam, "ai": ai, "label": label}


def _run(store, spec: dict, use_family: bool, use_ai: bool,
         exclude: tuple | None = None) -> list:
    conds, params = [], []
    if exclude:
        conds.append("j.source not in (%s)" % ",".join("?" * len(exclude)))
        params += list(exclude)
    if use_family and spec["family"]:
        conds.append("t.family like ?")
        params.append(spec["family"] + "%")
    if use_ai and spec["ai"]:
        conds.append("t.agent_level >= 1")
    for kw in spec["kws"]:
        conds.append("lower(j.title) like ?")
        params.append("%" + kw.lower() + "%")
    for cid in spec["skills"]:
        conds.append("j.id in (select job_id from job_skills where cid = ?)")
        params.append(cid)
    where = (" where " + " and ".join(conds)) if conds else ""
    sql = ("select j.id, j.title, j.company, j.source from jobs j"
           " join tags t on t.job_id = j.id" + where)
    return [dict(r) for r in store.db.execute(sql, params)]


def query(store, spec: dict, easy: bool = False,
         exclude: tuple | None = None) -> dict:
    """SQL 聚合：岗位数、低门槛数、技能频次、城市分布、样例岗位。

    查不到就逐级放宽：先摘岗位族，再摘 AI 标记，保底技能词。
    exclude=国外渠道时默认不看（greenhouse/lever）。"""
    jobs = _run(store, spec, True, True, exclude)
    relaxed = ""
    if not jobs and spec["family"]:
        jobs = _run(store, spec, False, True, exclude)
        relaxed = "已放宽：忽略岗位族"
    if not jobs and spec["ai"]:
        jobs = _run(store, spec, False, False, exclude)
        relaxed = "已放宽：忽略岗位族与 AI 标记，只按技能/标题词"
    spec["_relaxed"] = relaxed
    hard = store.barriers()
    easy_ids = [j["id"] for j in jobs if not (hard.get(j["id"]) or {}).get("hard")]
    hard_ids = [j["id"] for j in jobs if (hard.get(j["id"]) or {}).get("hard")]
    pool = easy_ids if easy else [j["id"] for j in jobs]
    skills, cities, samples, hard_why = {}, {}, {}, Counter()
    for jid in hard_ids:
        hard_why[(hard[jid].get("why") or "高门槛")] += 1

    def _agg(ids, sql_tpl, key):
        out = {}
        for i in range(0, len(ids), 900):
            chunk = ids[i:i + 900]
            ph = ",".join("?" * len(chunk))
            for k, n in store.db.execute(sql_tpl % ph, chunk):
                out[k] = out.get(k, 0) + n
        return out

    if pool:
        skills = _agg(pool, "select cid, count(*) from job_skills"
                      " where job_id in (%s) group by cid", None)
        cities = _agg(pool, "select city, count(*) from tags"
                      " where job_id in (%s) group by city", None)
        for cid in sorted(skills, key=lambda c: -skills[c])[:8]:
            ph = ",".join("?" * len(pool[:900]))
            rows = store.db.execute(
                "select j.title, j.source from job_skills js join jobs j"
                " on j.id = js.job_id where js.job_id in (%s) and js.cid = ?"
                " limit 3" % ph, pool[:900] + [cid]).fetchall()
            samples[cid] = [(r[0], r[1]) for r in rows]
    top = sorted(skills.items(), key=lambda x: -x[1])
    srcs = Counter(j["source"] for j in jobs)
    return {"jobs": len(jobs), "easy": len(easy_ids), "hard": len(hard_ids),
            "pool": len(pool), "skills": top, "cities": cities,
            "samples": samples, "hard_why": dict(hard_why.most_common(8)),
            "sources": dict(srcs.most_common(5))}


def render(spec: dict, res: dict, mine: dict, easy: bool, store=None) -> str:
    L = ["# 岗位画像 · %s" % spec["label"],
         "",
         "样本 %d 条：低门槛 %d 条、高门槛已剔除 %d 条（--easy=%s）。"
         % (res["jobs"], res["easy"], res["hard"], str(easy).lower())]
    if spec.get("_relaxed"):
        L.append(spec["_relaxed"] + "。")
    L.append("")
    if res["cities"]:
        L.append("城市分布：" + " · ".join(
            "%s %d" % (c, res["cities"][c])
            for c in sorted(res["cities"], key=lambda x: -res["cities"][x])[:6]))
        if res.get("sources"):
            L.append("数据源构成：" + "、".join(
                "%s %d 条" % (s, n) for s, n in res["sources"].items())
                + "。城市集中在深圳，是因为 boss 数据集本身只覆盖深圳龙岗，"
                  "不代表全国市场分布——想补其他城市请再抓对应城市数据集。")
        L.append("")
    if res["hard_why"]:
        L.append("剔除的高门槛原因：" + "；".join(
            "%s×%d" % (w, n) for w, n in res["hard_why"].items()))
        L.append("")
    L.append("## 技术栈频次")
    L.append("")
    L.append("| 技术栈 | 岗位数 | 占比 | 我的水平 | 样例岗位 |")
    L.append("|---|---|---|---|---|")
    for cid, n in res["skills"][:15]:
        pct = n * 100.0 / res["pool"] if res["pool"] else 0
        mine_lv = int(mine.get(cid, 0))
        lv = "★★★" if mine_lv >= 3 else ("★★" if mine_lv == 2 else
                                        ("★" if mine_lv == 1 else "·"))
        smp = res["samples"].get(cid, [])
        tt = "、".join(zh_title(t) for t, _ in smp[:3]) or "—"
        L.append("| %s | %d | %.0f%% | %s | %s |" % (skill_name(cid), n, pct, lv, tt))
    L.append("")
    L += _trend_block(spec, store)
    if store is not None:
        L += _evidence(res, store)
    return "\n".join(L)


def _trend_block(spec: dict, store) -> list:
    """Agent 时代增量：命中 agent/ai_app 家族或 AI 标记时展示市场趋势 + 趋势项目证据。"""
    if not (spec["ai"] or spec["family"] in TREND["when"]):
        return []
    out = ["## %s" % TREND["title"], "",
           "**演进逻辑**：" + TREND["logic"], "",
           "**新业务形态**："]
    for b in TREND["business"]:
        out.append("- " + b)
    out += ["", "**增量技能**："]
    for s in TREND["skills"]:
        out.append("- " + s)
    out.append("")
    if store is not None:
        import json
        try:
            rows = store.db.execute(
                "select repo, stars, lang, url, intro, modules from projects"
                " where cid like 'trend.%' order by cid").fetchall()
        except Exception:
            rows = []
        if rows:
            out.append("**趋势项目证据（GitHub 公开 API 抓取，缓存在库）**：")
            for r in rows:
                out.append("- **%s** ★%s（%s）：%s" % (r[0], r[1], r[2], r[3]))
                if r[4]:
                    out.append("  - 是干什么的(原文): %s [EN]" % r[4][:180])
                mods = json.loads(r[5]) if r[5] else []
                if mods:
                    out.append("  - 关键模块/文件: %s" % "、".join(mods[:6]))
            out.append("")
    return out


def _evidence(res: dict, store) -> list:
    """给头部技术栈附上已缓存的开源项目证据（没有就提示先跑 opensrc --build）。"""
    import json
    out = ["## 开源项目证据（GitHub 公开 API 抓取，缓存在库）", ""]
    shown = 0
    for cid, n in res["skills"][:8]:
        rows = store.projects(cid)
        if not rows:
            continue
        shown += 1
        out.append("### %s" % skill_name(cid))
        for r in rows[:2]:
            out.append("- **%s** ★%s（%s）：%s" % (r["repo"], r["stars"], r["lang"], r["url"]))
            intro = r["intro"] or r["desc"] or ""
            if intro:
                out.append("  - 是干什么的(原文): %s [EN]" % intro[:200])
            for u in (json.loads(r["uses"]) if r["uses"] else [])[:2]:
                out.append("  - 用它做什么: %s [EN]" % u[:180])
            mods = json.loads(r["modules"]) if r["modules"] else []
            if mods:
                out.append("  - 关键模块/文件: %s" % "、".join(mods[:8]))
        out.append("")
    if not shown:
        out.append("证据链还没抓：先跑 \`python3 -m dz.cli opensrc --build\`（匿名限速，21 天缓存）。")
        out.append("")
    return out
