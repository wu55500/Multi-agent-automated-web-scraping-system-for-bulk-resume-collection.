"""GitHub BOSS 数据集同步：本地 CSV → 结构化 JD → 规则抽取 → 入库。

数据来源：qybaihe/longgang-jobs-data/data/longgang_all.csv —— BOSS直聘公开搜索接口采集、
发布在 GitHub 的一次性静态数据集（2026-08-25，龙岗区 11,576 条）。
本模块只读本地文件，不发任何网络请求，不碰任何登录态。
raw 拼接格式与早期 800 条样本一致，保证抽取结果可复现。
"""
from __future__ import annotations

import csv
import time

from . import classify
from .boiler import pollution
from .extract import extract_rule


def flatten(row: dict) -> dict:
    title = (row.get("title") or "").strip()
    boss = (row.get("boss_name") or "").strip()
    scale = (row.get("company_scale") or "").strip()
    industry = (row.get("company_industry") or "").strip()
    loc = (row.get("location") or "").strip()
    salary = (row.get("salary") or "").strip()
    tags = (row.get("tags") or "").strip().replace(" | ", " ； ")
    skills = (row.get("skills") or "").strip().replace(", ", " 、 ")
    comp = boss + ("（%s·%s）" % (scale, industry) if scale or industry else "")
    lines = ["岗位：" + title, "公司：" + comp, "地点：" + loc, "薪资：" + salary]
    if tags or skills:
        req = tags + ("；" + skills if skills else "")
        lines.append("任职要求：" + req)
    return {
        "title": title,
        "company": boss,
        "city": loc.split("·")[0] if loc else "",
        "salary": salary,
        "link": (row.get("job_link") or "").strip(),
        "raw": chr(10).join(lines),
    }


def sync_csv(store, path: str, source: str = "boss-longgang-2026-08",
             limit: int = 0, dry_run: bool = False) -> dict:
    t0 = time.time()
    n = stored = dup = bad = poll_lines = 0
    with open(path, encoding="utf-8-sig") as f:
        rd = csv.DictReader(f)
        for row in rd:
            if limit and stored >= limit:
                break
            n += 1
            job_id = (row.get("job_id") or "").strip()
            if not job_id:
                bad += 1
                continue
            jid = "boss-" + job_id
            if store.job(jid):
                dup += 1
                continue
            fl = flatten(row)
            if len(fl["raw"]) < 30:
                bad += 1
                continue
            poll_lines += pollution(fl["raw"])["boiler_lines"]
            jd = extract_rule(fl["raw"])
            jd.id = jid
            jd.source = source
            jd.title = fl["title"] or jd.title
            jd.company = fl["company"]
            jd.city = fl["city"]
            jd.salary = fl["salary"]
            jd.source_url = fl["link"]
            if not dry_run:
                store.put_job(jd)
                store.put_tag(classify.tag({
                    "id": jd.id, "raw": fl["raw"], "city": fl["city"],
                    "company": fl["company"], "size": "", "title": fl["title"]}))
            stored += 1
            if stored % 1000 == 0:
                print("... %d 行（用时 %.0fs）" % (stored, time.time() - t0))
    cost = int((time.time() - t0) * 1000)
    detail = "rows=%d stored=%d dup=%d bad=%d poll_lines=%d" % (
        n, stored, dup, bad, poll_lines)
    if not dry_run:
        # ok 语义 = 同步过程本身成功；stored=0（全部去重）也是健康空跑，不算失败
        store.log_run("sync_github", True, detail, cost)
    return {"ok": True, "dry_run": dry_run, "rows": n, "stored": stored,
            "dup": dup, "bad": bad, "poll_lines": poll_lines, "cost_ms": cost}
