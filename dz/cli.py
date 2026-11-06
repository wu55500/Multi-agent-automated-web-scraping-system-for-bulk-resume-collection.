"""命令行入口：python3 -m dz.cli run --offline"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter

from . import agg, classify
from .adapters import fill as fill_adapter
from .extract import LLM, extract
from .forge import plan_projects, resume_bullets
from .ontology import SKILLS, name
from .queue import Queue
from .score import by_domain, evaluate, tier
from .store import Store

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_jsonl(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(ln) for ln in f if ln.strip()]


def _ensure_mine(store: Store) -> dict:
    mine = store.mine()
    if mine:
        return mine
    p = os.path.join(ROOT, "data", "me.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        store.set_mine(d.get("mine", {}), d.get("notes", {}))
        return store.mine()
    return {}


def _bridge_notify(title: str, text: str) -> bool:
    """给 DSH 桥发系统通知（127.0.0.1:3081）。失败静默，不影响管线。"""
    try:
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:3081/notify",
            data=json.dumps({"title": title, "text": text}).encode(),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read().decode() or "{}")
            # 桥返回 200 但 body.ok=false（如通知权限未授予）也算未送达
            return resp.status == 200 and body.get("ok", True)
    except Exception:
        return False


def cmd_pipeline(args) -> int:
    """定时全自动主链路：collect → sync → eval → run --offline → 系统通知。

    每段独立 try：一段失败不拖垮全链，最后统一通知结果。
    红线不变：只碰公开接口/本地文件，不投递。
    """
    t0 = time.time()
    db = args.db
    results: dict = {}
    ok = True

    def ns(**kw):
        return argparse.Namespace(db=db, **kw)

    def stage(name, fn):
        nonlocal ok
        try:
            results[name] = fn()
        except Exception as e:  # 网络断了/文件没了都记下来，不中断
            ok = False
            results[name] = {"ok": False, "error": str(e)[:200]}

    # 1) 采集公开 ATS（限速/robots/来源留存，可能断网）
    stage("collect", lambda: _collect_once(db))
    # 2) GitHub 数据集同步（只读本地 CSV，零网络）
    stage("sync", lambda: _sync_once(db))
    # 3) 黄金集评测（离线确定性）
    stage("eval", lambda: _eval_once(db))
    # 4) 差距报告 + 投递队列 + 看板（离线规则，不调模型）
    stage("report", lambda: _report_once(db))
    # 5) B 主干自愈：API 服务器掉了就拉起（走 logs/api.log）
    stage("api", lambda: _api_once(db))
    # 6) 开源证据链：GitHub 公开 API，匿名限速+预算，每天补几个技能（21 天缓存）
    stage("opensrc", lambda: _opensrc_once(db))

    store = Store(db)
    cost = int((time.time() - t0) * 1000)

    lines = []
    c = results.get("collect", {})
    if isinstance(c, dict) and c.get("jobs"):
        lines.append("采集 %d 条（入库 %d）" % (c.get("jobs", 0), c.get("stored", 0)))
    s = results.get("sync", {})
    if isinstance(s, dict) and s.get("rows"):
        lines.append("同步 %d 行（新入库 %d）" % (s.get("rows", 0), s.get("stored", 0)))
    e = results.get("eval", {})
    if isinstance(e, dict) and e.get("micro"):
        lines.append("评测 F1=%.3f（%d 条黄金集）" % (e["micro"]["f1"], e.get("golden", 0)))
    if "report" in results and "FAIL" not in str(results.get("report")):
        lines.append("差距报告已生成 reports/latest.md")
    fails = [k for k, v in results.items() if isinstance(v, dict) and v.get("ok") is False]
    fails += [k for k, v in results.items() if isinstance(v, str) and v.startswith("FAIL")]
    title = "dz 管线 ✅ 完成" if ok else "dz 管线 ⚠️ 部分失败（%s）" % ("、".join(fails) or "?")
    text = "\n".join(lines) or "无变化"
    if not ok:
        text += "\n失败段: " + ("、".join(fails) or "?")
    sent = _bridge_notify(title, text)
    results["notify"] = sent
    brief = {
        "collect": {"jobs": results.get("collect", {}).get("jobs"),
                    "stored": results.get("collect", {}).get("stored")},
        "sync": {"rows": results.get("sync", {}).get("rows"),
                 "stored": results.get("sync", {}).get("stored")},
        "eval": {"f1": (results.get("eval") or {}).get("micro", {}).get("f1"),
                 "golden": (results.get("eval") or {}).get("golden")},
        "report": "ok" if "report" in results and not str(results.get("report")).startswith("FAIL") else None,
        "api": results.get("api"),
        "notify": sent,
        "fails": fails,
    }
    store.log_run("pipeline", ok, json.dumps(brief, ensure_ascii=False), cost)
    print(json.dumps({"ok": ok, "notify": sent, "results": results, "cost_ms": cost}, ensure_ascii=False, indent=1))
    return 0 if ok else 1


def _opensrc_once(db: str) -> dict:
    """每日小额抓 GitHub 证据：预算 8 次核心 API，抓不完下轮接着抓。"""
    from . import opensrc
    store = Store(db)
    try:
        res = opensrc.build(store, budget=8)
        store.log_run("opensrc", bool(res.get("ok")), json.dumps(res, ensure_ascii=False))
        return res
    except Exception as e:
        store.log_run("opensrc", False, str(e)[:200])
        return {"ok": False, "error": str(e)[:200]}


def _collect_once(db: str) -> dict:
    """公开板采集：多公司多板，每板独立容错（一板挂了不拖全链）。"""
    from . import collect
    store = Store(db)
    gh_boards = ("anthropic", "gitlab", "databricks", "cloudflare")
    lv_boards = ("spotify", "palantir")
    gh_res, lv_res = {}, {}
    for name in gh_boards:
        try:
            gh_res[name] = collect.collect_board(store, name, 0, None, True)
        except Exception as e:
            gh_res[name] = {"ok": False, "err": str(e)[:120]}
    for name in lv_boards:
        try:
            lv_res[name] = collect.collect_lever(store, name, 0, None, True)
        except Exception as e:
            lv_res[name] = {"ok": False, "err": str(e)[:120]}
    allr = list(gh_res.values()) + list(lv_res.values())
    return {"ok": bool(allr and all(r.get("ok") for r in allr)),
            "greenhouse": gh_res, "lever": lv_res,
            "jobs": sum(r.get("jobs", 0) for r in allr),
            "stored": sum(r.get("stored", 0) for r in allr)}


def _sync_once(db: str) -> dict:
    from . import sync
    p = os.path.join(os.path.dirname(ROOT), ".dl", "longgang.csv")
    return sync.sync_csv(Store(db), p)


def _eval_once(db: str) -> dict:
    from . import eval as evm
    return evm.run(Store(db), os.path.join(ROOT, "data", "golden.jsonl"))


def _api_once(db: str, port: int = 8770) -> str:
    """B 主干自愈：API 服务器活着就 ok，死了就拉起一个脱离管线进程的实例。"""
    import subprocess
    import sys
    import urllib.request
    url = "http://127.0.0.1:%d/api/stats" % port
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            r.read()
        return "ok"
    except Exception:
        os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
        log = open(os.path.join(ROOT, "logs", "api.log"), "ab")
        subprocess.Popen([sys.executable, "-m", "dz.cli", "api", "--port", str(port)],
                         cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
        time.sleep(3)
        try:
            with urllib.request.urlopen(url, timeout=3) as r:
                r.read()
            return "restarted"
        except Exception:
            return "FAIL"


def _report_once(db: str) -> int:
    args = argparse.Namespace(db=db, cap=15, offline=True,
                              file=[os.path.join(ROOT, "data", "jds.jsonl")])
    return cmd_run(args)


def cmd_profile(args) -> int:
    """岗位画像：岗位名 → 技术栈统计 + 样例岗位。纯离线 SQL。"""
    from . import profile
    import re as _re
    store = Store(args.db)
    mine = _ensure_mine(store)
    spec = profile.parse_role(args.role)
    res = profile.query(store, spec, easy=not args.all)
    md = profile.render(spec, res, mine, not args.all, store)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    slug = _re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "-", args.role).strip("-") or "profile"
    out = os.path.join(ROOT, "reports", "profile-%s.md" % slug)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print("\n画像落档:", out)
    return 0


def cmd_opensrc(args) -> int:
    """GitHub 开源项目证据链：抓取/展示。--build 抓新证据，否则只展示缓存。"""
    from . import opensrc
    from .ontology import name as skill_name
    store = Store(args.db)
    if args.build:
        cids = [c.strip() for c in args.cids.split(",")] if args.cids else None
        res = opensrc.build(store, cids=cids, budget=args.budget, force=args.force)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return 0
    cids = ([c.strip() for c in args.cids.split(",")] if args.cids
            else sorted(opensrc.SKILLS))
    for cid in cids:
        rows = store.projects(cid)
        if not rows:
            continue
        print("\n### %s\n" % skill_name(cid))
        for r in rows:
            print("- **%s** ★%s  [%s](%s)" % (r["repo"], r["stars"], r["lang"], r["url"]))
            if r["title"]:
                print("  - 简介(原文): %s [EN]" % (r["intro"][:200] or r["desc"] or ""))
            if r["intro_zh"]:
                print("  - 术语标注: %s" % r["intro_zh"][:260])
            for u in (json.loads(r["uses"]) if r["uses"] else []):
                print("  - 用到%s: %s [EN]" % (skill_name(cid), u))
            mods = json.loads(r["modules"]) if r["modules"] else []
            if mods:
                print("  - 关键模块/文件: " + ", ".join(mods[:10]))
    return 0


def cmd_run(args) -> int:
    store = Store(args.db)
    mine = _ensure_mine(store)
    q = Queue(store, daily_cap=args.cap)
    llm = None if args.offline else LLM()
    files = args.file if isinstance(args.file, (list, tuple)) else [args.file]
    rows = []
    for f in files:
        rows += _load_jsonl(f)

    out = []
    for r in rows:
        jd = extract(store, r["raw"], llm)
        jd.source = r.get("source", "paste")
        jd.title = jd.title or r.get("title", "")
        jd.company = r.get("company", "") or jd.company
        jd.city = r.get("city", "") or jd.city
        store.put_job(jd)
        store.put_tag(classify.tag({"id": jd.id, "raw": jd.raw, "city": jd.city,
                                    "company": jd.company, "size": r.get("size", ""),
                                    "title": jd.title or r.get("title", "")}))
        rep = evaluate(jd.skills, mine)
        queued = q.enqueue(jd.id, rep["coverage"]) if rep["coverage"] >= 0.3 else False
        out.append({"jd": jd, "rep": rep, "queued": queued})

    out.sort(key=lambda x: -x["rep"]["coverage"])
    md = render_report(out, mine, q, store)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    path = os.path.join(ROOT, "reports", time.strftime("%Y%m%d-report.md"))
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(ROOT, "reports", "latest.md"), "w", encoding="utf-8") as f:
        f.write(md)

    avg = sum(x["rep"]["coverage"] for x in out) / len(out) if out else 0
    print("解析 %d 条 JD，平均覆盖 %.0f%%" % (len(out), avg * 100))
    for x in out[:5]:
        print("  %-22s %-6s 覆盖 %3.0f%%  %s" % (
            x["jd"].title[:22], x["jd"].company[:6], x["rep"]["coverage"] * 100,
            tier(x["rep"]["coverage"])))
    print("队列:", q.snapshot())
    print("单条报告:", path)
    print_summary(store, mine)
    market = _market_closure(store, mine)
    if market:
        for p in (path, os.path.join(ROOT, "reports", "latest.md")):
            with open(p, "a", encoding="utf-8") as f:
                f.write(market)
        print("市场闭环:", len(market), "字符已并入报告")
    return 0


def _market_closure(store, mine) -> str:
    """全库市场差距 → 学习计划 + 简历草稿（相对全库样本而非静态池）。

    每日自动：把 12k 岗位市场里"我缺什么"直接换算成项目计划与可写简历点，
    写进同一份靶心报告——GPT-B 学习闭环的自动化落点。纯离线。"""
    from .web import _as_skills, records
    rec = records(store, mine)
    need, wsum = Counter(), Counter()
    hardest = None
    for x in rec:
        sk = _as_skills(x["skills"])
        if not sk:
            continue
        rep = evaluate(sk, mine)
        if len(sk) >= 3 and (hardest is None
                             or rep["coverage"] < hardest["rep"]["coverage"]):
            hardest = {"jd": x["job"], "skills": sk, "rep": rep}
        for g in rep["gaps"]:
            need[g["cid"]] += 1
            wsum[g["cid"]] += g["w"]
    if not wsum:
        return ""
    gaps = [{"cid": c, "w": w, "prereq": []} for c, w in wsum.most_common(8)
            if need[c] >= 3]
    L = ["", "## 学习闭环 · 全库市场（每日自动，样本 %d 条）" % len(rec), ""]
    if not gaps:
        L.append("市场无集中缺口。")
    else:
        L.append("| 缺口技能 | 需求岗位数 | 缺口总权重 |")
        L.append("|---|---|---|")
        for g in gaps:
            L.append("| %s | %d | %.1f |" % (name(g["cid"]), need[g["cid"]], g["w"]))
        plan = plan_projects(gaps, budget_hours=40)
        L.append("")
        L.append("### 两周项目计划（%.0f 小时预算，覆盖 %d 个缺口）"
                 % (plan["hours"], len(plan["covered"])))
        for p in plan["projects"]:
            L.append("- **%s** · %dh · 缺口权重 %.1f" % (p["title"], p["hours"], p["gain"]))
            for a in p["artifacts"]:
                L.append("  - 交付：%s" % a)
            L.append("  - 面试官会问：%s" % p["追问点"])
        if plan["left"]:
            L.append("")
            L.append("### 没有项目能覆盖，只能啃的：")
            L.append("  " + "、".join(name(g["cid"]) for g in plan["left"]))
    if hardest:
        bl = resume_bullets(hardest["skills"], mine, store.notes())
        L.append("")
        L.append("### 全库最难的一条：%s · %s（覆盖 %.0f%%）"
                 % (hardest["jd"]["title"][:24] or "（无标题）",
                    hardest["jd"]["company"][:10],
                    hardest["rep"]["coverage"] * 100))
        miss_top = [name(g["cid"]) for g in hardest["rep"]["gaps"][:6]]
        if miss_top:
            L.append("- 这条缺的：%s" % "、".join(miss_top))
        if bl["ready"]:
            L.append("- 可以写进简历的（都有你的真实材料兜底）：")
            for b in bl["ready"][:4]:
                L.append("  - %s" % b["bullet"])
                L.append("    > 证据：「%s」 ← 对应 JD 原话「%s」" % (b["bound_to"], b["job_words"]))
        if bl["refused"]:
            L.append("")
            L.append("### 拒绝生成（没有真实材料，编造会在背调翻车）")
            for b in bl["refused"][:3]:
                L.append("- %s：%s" % (name(b["cid"]), b["reason"]))
    L.append("")
    return "\n".join(L)


def print_summary(store, mine) -> dict:
    from .web import _html, records
    rec = records(store, mine)
    s = agg.summary(rec)
    md = agg.to_markdown(s)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    with open(os.path.join(ROOT, "reports", "summary.md"), "w", encoding="utf-8") as f:
        f.write(md)
    with open(os.path.join(ROOT, "reports", "dashboard.html"), "wb") as f:
        f.write(_html(store, mine))
    print("总表:", os.path.join(ROOT, "reports", "summary.md"))
    print("看板:", os.path.join(ROOT, "reports", "dashboard.html"),
          "（或 python3 -m dz.cli serve 用浏览器看）")
    for title, rows in (("按地域", s["by_city"]), ("按规模", s["by_size"]),
                        ("按 agent", s["by_agent"])):
        print("--", title)
        for r in rows:
            print("   %-12s %2d 条  覆盖 %3.0f%%  agent %3.0f%%  %s" % (
                r["key"], r["n"], r["coverage"] * 100, r["agent_ratio"] * 100,
                "、".join(t[0] for t in r["top"][:4])))
    if s.get("by_family"):
        print("-- 按岗位族")
        for f in s["by_family"]:
            print("   %-18s %2d 条  覆盖 %3.0f%%  agent %3.0f%%  %s" % (
                f["key"], f["n"], f["coverage"] * 100, f["agent_ratio"] * 100,
                "、".join(t[0] for t in f["top"][:4])))
    return s


def render_report(out, mine, q, store) -> str:
    L = []
    L.append("# 靶心报告 · " + time.strftime("%Y-%m-%d %H:%M"))
    L.append("")
    if out:
        avg = sum(x["rep"]["coverage"] for x in out) / len(out)
        L.append("池子 %d 条 JD，平均覆盖 %.0f%%，已入队 %d 条。"
                 % (len(out), avg * 100, sum(1 for x in out if x["queued"])))
        L.append("")
        L.append("| 岗位 | 公司 | 覆盖 | 硬缺口 | 结论 |")
        L.append("|---|---|---|---|---|")
        for x in out:
            r = x["rep"]
            L.append("| %s | %s | %.0f%% | %d | %s |" % (
                x["jd"].title[:24] or "（无标题）", x["jd"].company[:10],
                r["coverage"] * 100, r["must_missed"], tier(r["coverage"])))
        L.append("")

    for x in out[:1]:
        jd, rep = x["jd"], x["rep"]
        L.append("## 最值得打的一条：%s" % (jd.title or jd.id))
        L.append("")
        L.append("- 覆盖率 **%.0f%%**（硬缺口 %d 条）" % (rep["coverage"] * 100, rep["must_missed"]))
        if rep["gaps"]:
            L.append("- 缺口（按权重排，含加分项）：")
            for g in rep["gaps"][:5]:
                pre = ("，前置缺 " + "/".join(name(p) for p in g["prereq"])) if g["prereq"] else ""
                L.append("  - %s（权重 %.2f%s）" % (name(g["cid"]), g["w"], pre))
        if rep["hits"]:
            L.append("- 已经够格写的：" + "、".join(name(h["cid"]) for h in rep["hits"][:6]))
        plan = plan_projects(rep["gaps"], budget_hours=24)
        if plan["projects"]:
            L.append("")
            L.append("### 周末做什么（%.0f 小时，覆盖 %d 个缺口）"
                     % (plan["hours"], len(plan["covered"])))
            for p in plan["projects"]:
                L.append("- **%s** · %dh · 缺口权重 %.1f" % (p["title"], p["hours"], p["gain"]))
                for a in p["artifacts"]:
                    L.append("  - 交付：%s" % a)
                L.append("  - 面试官会问：%s" % p["追问点"])
        if plan["left"]:
            L.append("")
            L.append("### 没有项目能覆盖，只能啃的：")
            L.append("  " + "、".join(name(g["cid"]) for g in plan["left"]))
        bl = resume_bullets(jd.skills, mine, store.notes())
        if bl["ready"]:
            L.append("")
            L.append("### 可以写进简历的（都有你的真实材料兜底）")
            for b in bl["ready"]:
                L.append("- %s  " % b["bullet"])
                L.append("  > 证据：「%s」 ← 对应 JD 原话「%s」" % (b["bound_to"], b["job_words"]))
        if bl["refused"]:
            L.append("")
            L.append("### 拒绝生成（没有真实材料，编造会在背调翻车）")
            for b in bl["refused"][:5]:
                L.append("- %s：%s" % (name(b["cid"]), b["reason"]))
        L.append("")

    snap = q.snapshot()
    L.append("## 队列")
    L.append("")
    L.append("已投/已填 %d 条，今日上限 %d。" % (snap["submitted_today"], snap["cap"]))
    L.append("")
    return "\n".join(L)


def cmd_claim(args) -> int:
    store = Store(args.db)
    q = Queue(store, daily_cap=args.cap)
    row = q.claim()
    if not row:
        print(json.dumps(q.snapshot(), ensure_ascii=False))
        print("没有可领的任务（或今天到上限了）。")
        return 1
    jd = store.job(row["job_id"])
    print(json.dumps({"job": jd["title"], "company": jd["company"],
                      "score": round(row["score"] * 100, 1),
                      "attempts": row["attempts"]}, ensure_ascii=False))  # noqa
    print("下一次：python3 -m dz.cli submit %s --note '已投'" % row["job_id"])
    return 0


def cmd_submit(args) -> int:
    store = Store(args.db)
    q = Queue(store)
    q.mark(args.job, "submitted", args.note or "")
    print("已标记 submitted:", args.job[:8])
    return 0


def cmd_stats(args) -> int:
    store = Store(args.db)
    print(json.dumps({"store": store.stats(),
                      "queue": Queue(store, args.cap).snapshot()},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_fill(args) -> int:
    fill_adapter.run(args.url, profile_dir=args.profile)
    return 0


def cmd_pack(args) -> int:
    """填表包：一条岗位的信息+证据命中+可写简历点打成一页，复制粘贴即可，不提交。"""
    from .schema import JD
    store = Store(args.db)
    job = store.job(args.job)
    if not job:
        print("找不到 job:", args.job)
        return 1
    jd = JD.from_dict(job)
    mine = _ensure_mine(store)
    rep = evaluate(jd.skills, mine)
    bl = resume_bullets(jd.skills, mine, store.notes())
    L = ["# 投递卡 · %s" % (jd.title or jd.id[:8]), "",
         "- 公司：%s" % (jd.company or "未知"),
         "- 城市：%s" % (jd.city or "未知"),
         "- 薪资：%s" % (jd.salary or "未知"),
         "- 覆盖：%.0f%%（硬缺口 %d 条）" % (rep["coverage"] * 100, rep["must_missed"]),
         "", "## 要求技能", ""]
    for s in jd.skills:
        L.append("- %s%s" % (name(s.cid) or s.raw, "（必须）" if s.must else "（加分）"))
    L += ["", "## 我的命中（有真实材料兜底，可写进话术）"]
    if bl["ready"]:
        for b in bl["ready"]:
            L.append("- %s ← 对应 JD「%s」" % (b["bullet"], b["job_words"]))
    else:
        L.append("- （暂无命中：先补缺口，或如实写「学习中」）")
    L += ["", "## 硬缺口（优先补）"]
    if rep["gaps"]:
        for g in rep["gaps"][:6]:
            L.append("- %s（权重 %.2f）" % (name(g["cid"]), g["w"]))
    else:
        L.append("- 无")
    L += ["", "## 填写清单（手动）",
          "- 姓名/电话/邮箱/简历附件：填真实信息",
          "- 沟通话术：「我的命中」改写 2-3 句 + 一句对岗位的理解",
          "- 最后一步「提交」由你自己点，本工具只整理、不代投", ""]
    md = chr(10).join(L)
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    path = os.path.join(ROOT, "reports", "pack_%s.md" % jd.id[:8])
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    print(md)
    print("已写入:", path)
    return 0


def cmd_import(args) -> int:
    """导入真实 JD：粘贴一段原文，或给一个 CSV（首行是列名）。"""
    out = args.out or os.path.join(ROOT, "data", "imported.jsonl")
    rows = []
    if args.text:
        rows.append({"source": "user", "title": args.title or "",
                     "company": args.company or "", "city": args.city or "",
                     "salary": args.salary or "", "raw": args.text})
    if args.csv:
        import csv as _csv
        with open(args.csv, newline="", encoding="utf-8-sig") as f:
            for r in _csv.DictReader(f):
                rows.append({"source": "user-csv",
                             "title": r.get("title") or r.get("岗位") or r.get("标题") or "",
                             "company": r.get("company") or r.get("公司") or "",
                             "city": r.get("city") or r.get("城市") or "",
                             "salary": r.get("salary") or r.get("薪资") or "",
                             "size": r.get("size") or r.get("规模") or "",
                             "raw": chr(10).join("%s：%s" % (k, v)
                                                for k, v in r.items() if v)})
    if not rows:
        print("没有输入：--text 'JD原文...' 或 --csv 文件.csv")
        return 1
    with open(out, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + chr(10))
    print("已追加 %d 条到 %s" % (len(rows), out))
    print("下一步：python3 -m dz.cli run --file %s --offline" % out)
    return 0


def cmd_serve(args) -> int:
    from .web import serve
    store = Store(args.db)
    serve(store, _ensure_mine(store), port=args.port)
    return 0


def cmd_reextract(args) -> int:
    """词表变更后的维护命令：清 jd: 缓存 → 全库按新别名重新抽取（不发网络请求）。"""
    t0 = time.time()
    store = Store(args.db)
    store.db.execute("delete from cache where k like 'jd:%'")
    store.db.commit()
    rows = store.db.execute("select id, raw, source, title, company, city, salary, source_url from jobs").fetchall()
    n = 0
    for jid, raw, source, title, company, city, salary, source_url in rows:
        jd = extract(store, raw, votes=1)
        jd.id = jid
        jd.source = source
        jd.title = title or jd.title
        jd.company = company
        jd.city = city
        jd.salary = salary
        jd.source_url = source_url
        jd.engine = "rule"
        store.put_job(jd)
        n += 1
        if n % 2000 == 0:
            print("... %d/%d (%.0fs)" % (n, len(rows), time.time() - t0))
    cost = int((time.time() - t0) * 1000)
    store.log_run("reextract", True, "rows=%d" % n, cost)
    print(json.dumps({"ok": True, "rows": n, "cost_ms": cost}, ensure_ascii=False))
    return 0


def cmd_sync(args) -> int:
    from . import sync
    store = Store(args.db)
    r = sync.sync_csv(store, args.file, limit=args.limit, dry_run=args.dry_run)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 1


def cmd_eval(args) -> int:
    from . import eval as evm
    store = Store(args.db)
    rep = evm.run(store, args.golden)
    m = rep["micro"]
    print("黄金集 %d 条 | micro: P=%.3f R=%.3f F1=%.3f | TP=%d FP=%d FN=%d" % (
        rep["golden"], m["p"], m["r"], m["f1"], m["tp"], m["fp"], m["fn"]))
    print("macro: P=%.3f R=%.3f F1=%.3f" % (rep["macro"]["p"], rep["macro"]["r"], rep["macro"]["f1"]))
    print("报告: %s" % os.path.join(ROOT, "reports", "eval.md"))
    return 0


def cmd_api(args) -> int:
    from .api import serve as api_serve
    store = Store(args.db)
    mine = sorted(_ensure_mine(store).keys())
    print("B 主干 API: http://127.0.0.1:%d  (前端: /  | 数据接口带 X-Token)" % args.port)
    api_serve(store, mine, port=args.port, token=args.token or None,
              static_dir=os.path.join(ROOT, "web"))
    return 0


def cmd_collect(args) -> int:
    from . import collect
    store = Store(args.db)
    llm = None if args.offline else LLM()
    if args.vendor == "auto":
        # Lever 一次 GET 全量，先试；失败/空板回落 Greenhouse
        r = collect.collect_lever(store, args.board, args.limit, llm, args.tech_only)
        if not r.get("ok") or not r.get("jobs"):
            r2 = collect.collect_board(store, args.board, args.limit, llm, args.tech_only)
            r2["vendor"] = "greenhouse"
            r = r2
        else:
            r["vendor"] = "lever"
    elif args.vendor == "lever":
        r = collect.collect_lever(store, args.board, args.limit, llm, args.tech_only)
        r["vendor"] = "lever"
    else:
        r = collect.collect_board(store, args.board, args.limit, llm, args.tech_only)
        r["vendor"] = "greenhouse"
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("ok") else 1


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "platform":
        from .platform.cli import main as platform_main
        return platform_main(argv[1:])
    p = argparse.ArgumentParser(prog="dz")
    p.add_argument("--db", default=os.path.join(ROOT, "dz.db"))
    p.add_argument("--cap", type=int, default=15, help="每日投递上限")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="跑一遍：解析→归一化→打分→入队→出报告")
    r.add_argument("--file", nargs="+",
                   default=[os.path.join(ROOT, "data", "jds.jsonl")])
    r.add_argument("--offline", action="store_true", help="不调模型，走词典规则")
    r.set_defaults(func=cmd_run)

    c = sub.add_parser("claim", help="领一条今天的投递任务")
    c.set_defaults(func=cmd_claim)

    s = sub.add_parser("submit", help="人工确认已提交后推进状态")
    s.add_argument("job")
    s.add_argument("--note", default="")
    s.set_defaults(func=cmd_submit)

    st = sub.add_parser("stats", help="看队列和库")
    st.set_defaults(func=cmd_stats)

    rex = sub.add_parser("reextract", help="词表变更后全库重抽取（清 jd: 缓存，不发网络请求）")
    rex.set_defaults(func=cmd_reextract)

    sy = sub.add_parser("sync", help="GitHub BOSS 数据集同步（只读本地 CSV，不发网络请求）")
    sy.add_argument("--file", default=os.path.join(os.path.dirname(ROOT), ".dl", "longgang.csv"))
    sy.add_argument("--limit", type=int, default=0, help="最多入库条数（0=全部）")
    sy.add_argument("--dry-run", action="store_true", help="只统计不写库")
    sy.set_defaults(func=cmd_sync)

    ev = sub.add_parser("eval", help="黄金集评测：P/R/F1（离线规则引擎 vs 人工标注）")
    ev.add_argument("--golden", default=os.path.join(ROOT, "data", "golden.jsonl"))
    ev.set_defaults(func=cmd_eval)

    ap = sub.add_parser("api", help="起 B 主干 API（只读接口 + 静态前端）")
    ap.add_argument("--port", type=int, default=8770)
    ap.add_argument("--token", default="", help="访问数据接口要带的 X-Token（空=不鉴权）")
    ap.set_defaults(func=cmd_api)

    pl = sub.add_parser("pipeline", help="定时全自动：collect → sync → eval → run → 系统通知（每段独立容错）")
    pl.set_defaults(func=cmd_pipeline)

    pf = sub.add_parser("profile", help="岗位画像：岗位名 → 技术栈频次统计（可 --easy 只看低门槛）")
    pf.add_argument("--role", required=True,
                    help="岗位名/族别名，如 Java、AI+爬虫、Python+Java+agent、AI+大数据")
    pf.add_argument("--all", action="store_true",
                    help="包含高门槛岗位（默认只看低门槛：不要求 985/211/硕博/竞赛）")
    pf.set_defaults(func=cmd_profile)

    osr = sub.add_parser("opensrc", help="开源项目证据链：技能 → GitHub 项目 → README 用途 → 关键模块")
    osr.add_argument("--cids", default="", help="逗号分隔技能 id（空=全部），如 crawl.http,nlp.llm")
    osr.add_argument("--build", action="store_true", help="抓取并缓存（默认只展示已有缓存）")
    osr.add_argument("--budget", type=int, default=8, help="本次核心 API 预算（匿名限 60 次/小时）")
    osr.add_argument("--force", action="store_true", help="忽略 21 天缓存强制重抓")
    osr.set_defaults(func=cmd_opensrc)

    cl = sub.add_parser("collect", help="自动采集公开 ATS（Greenhouse/Lever），限速+robots+来源留存")
    cl.add_argument("--board", default="anthropic", help="board 名，如 anthropic / openai / spotify")
    cl.add_argument("--vendor", default="auto", choices=["auto", "greenhouse", "lever"],
                    help="auto=先试 Lever 再回落 Greenhouse")
    cl.add_argument("--limit", type=int, default=0, help="最多入库条数（0=全部）")
    cl.add_argument("--tech-only", action="store_true", help="只保留岗位族能归类的技术岗")
    cl.add_argument("--offline", action="store_true", help="不调模型，走词典规则")
    cl.set_defaults(func=cmd_collect)

    v = sub.add_parser("serve", help="本地看板（stdlib，无依赖）")
    v.add_argument("--port", type=int, default=8787)
    v.set_defaults(func=cmd_serve)

    f = sub.add_parser("fill", help="半自动填表（需要 playwright，只填不提交）")
    f.add_argument("--url", required=True)
    f.add_argument("--profile", default="")
    f.set_defaults(func=cmd_fill)

    pk = sub.add_parser("pack", help="一条岗位的投递卡（手动填表包，不提交）")
    pk.add_argument("job", help="job id（dz.cli claim 拿到）")
    pk.set_defaults(func=cmd_pack)

    im = sub.add_parser("import", help="导入真实 JD：粘贴文本或 CSV")
    im.add_argument("--text")
    im.add_argument("--title", default="")
    im.add_argument("--company", default="")
    im.add_argument("--city", default="")
    im.add_argument("--salary", default="")
    im.add_argument("--csv")
    im.add_argument("--out", default="")
    im.set_defaults(func=cmd_import)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
