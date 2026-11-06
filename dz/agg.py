"""聚合出"同一张表"：地域 / 规模 / agent 三维交叉 + 技术栈频次矩阵。"""
from __future__ import annotations

from collections import Counter, defaultdict

from . import roles
from .classify import AGENT_LABEL, AGENT_ORDER, CITIES, SIZE_ORDER
from .ontology import SKILLS, name

NOISE = {"biz.comm", "biz.product"}


def _pct(n: int, total: int) -> str:
    return ("%d%%" % round(100.0 * n / total)) if total else "0%"


def skill_counts(records) -> Counter:
    c = Counter()
    for r in records:
        for s in r["skills"]:
            if s["cid"] and s["cid"] not in NOISE:
                c[s["cid"]] += 1
    return c


def group_block(records, key: str, order, label_fn=str) -> list[dict]:
    buckets: dict = defaultdict(list)
    for r in records:
        buckets[r["tag"][key]].append(r)
    keys = [k for k in order if k in buckets] + [k for k in buckets if k not in order]
    out = []
    for k in keys:
        rows = buckets[k]
        c = skill_counts(rows)
        top = [(name(cid), n, _pct(n, len(rows))) for cid, n in c.most_common(6)]
        cov = sum(r["coverage"] for r in rows) / len(rows) if rows else 0
        ag = sum(1 for r in rows if r["tag"]["agent_level"] == 2)
        out.append({
            "key": label_fn(k), "n": len(rows), "coverage": round(cov, 3),
            "agent_ratio": round(ag / len(rows), 3) if rows else 0.0,
            "top": top,
        })
    return out


def family_blocks(records) -> list[dict]:
    """每个岗位族一张小表：地域 / 规模 / agent 三维都摊在同一张表里。"""
    buckets: dict = defaultdict(list)
    for r in records:
        buckets[(r["tag"].get("family") or "")].append(r)
    order = roles.all_keys()
    keys = [k for k in order if k in buckets] + [k for k in buckets if k not in order]
    out = []
    for k in keys:
        rows = buckets[k]
        c = skill_counts(rows)
        cov = sum(r["coverage"] for r in rows) / len(rows) if rows else 0
        ag = sum(1 for r in rows if r["tag"]["agent_level"] == 2)
        detail = []
        for dim, blocks in (
            ("地域", group_block(rows, "city", CITIES)),
            ("规模", group_block(rows, "size", SIZE_ORDER)),
            ("agent", group_block(rows, "agent_level", AGENT_ORDER,
                                  lambda x: AGENT_LABEL[x])),
        ):
            for b in blocks:
                detail.append({"dim": dim, "k": b["key"], "n": b["n"],
                               "coverage": b["coverage"],
                               "agent_ratio": b["agent_ratio"], "top": b["top"][:3]})
        out.append({
            "key": roles.label_of(k), "fam": k, "n": len(rows),
            "coverage": round(cov, 3),
            "agent_ratio": round(ag / len(rows), 3) if rows else 0.0,
            "top": [(name(cid), n, _pct(n, len(rows))) for cid, n in c.most_common(5)],
            "detail": detail,
        })
    return out


def matrix(records, top_n: int = 12) -> dict:
    c = skill_counts(records)
    rows = [cid for cid, _ in c.most_common(top_n)]
    cols = {
        "城市": [x for x in CITIES if any(r["tag"]["city"] == x for r in records)],
        "规模": [x for x in SIZE_ORDER if any(r["tag"]["size"] == x for r in records)],
        "agent": [AGENT_LABEL[l] for l in AGENT_ORDER
                  if any(r["tag"]["agent_level"] == l for r in records)],
    }
    body = []
    for cid in rows:
        line = {"skill": name(cid), "cid": cid, "cells": {}}
        for cname, keys in cols.items():
            line["cells"][cname] = []
            for k in keys:
                if cname == "城市":
                    sel = [r for r in records if r["tag"]["city"] == k]
                elif cname == "规模":
                    sel = [r for r in records if r["tag"]["size"] == k]
                else:
                    lvl = {v: kk for kk, v in AGENT_LABEL.items()}[k]
                    sel = [r for r in records if r["tag"]["agent_level"] == lvl]
                n = sum(1 for r in sel if any(s["cid"] == cid for s in r["skills"]))
                line["cells"][cname].append({"k": k, "n": n,
                                             "pct": round(100.0 * n / len(sel), 0) if sel else 0})
        body.append(line)
    return {"cols": cols, "rows": body}


def summary(records) -> dict:
    total = len(records)
    c = skill_counts(records)
    engines = Counter(r["job"].get("engine", "rule") for r in records)
    sources = Counter(str(r["job"].get("source", "?")) for r in records)
    return {
        "total": total,
        "engines": dict(engines),
        "sources": dict(sources),
        "avg_coverage": round(sum(r["coverage"] for r in records) / total, 3) if total else 0,
        "agent_required": sum(1 for r in records if r["tag"]["agent_level"] == 2),
        "by_city": group_block(records, "city", CITIES),
        "by_size": group_block(records, "size", SIZE_ORDER),
        "by_agent": group_block(records, "agent_level", AGENT_ORDER,
                                lambda k: AGENT_LABEL[k]),
        "by_family": family_blocks(records),
        "top_skills": [{"cid": cid, "name": name(cid), "n": n,
                        "pct": _pct(n, total)} for cid, n in c.most_common(12)],
        "matrix": matrix(records),
    }


def to_markdown(s: dict) -> str:
    L = ["# 招聘技术要求总表", ""]
    L.append("样本 %d 条 JD，平均覆盖 %.0f%%，其中 %d 条**明确要求 agent/LLM**。"
             % (s["total"], s["avg_coverage"] * 100, s["agent_required"]))
    L.append("")
    L.append("抽取引擎：" + "、".join("%s %d 条" % (k, v)
                                  for k, v in s.get("engines", {}).items())
             + "（rule 只认技能本体词典，覆盖数偏高；配了模型 key 会自动换成 LLM 抽取）")
    L.append("")
    for title, rows in (("按地域", s["by_city"]), ("按公司规模", s["by_size"]),
                        ("按 agent 要求", s["by_agent"])):
        L.append("## " + title)
        L.append("")
        L.append("| 分组 | 岗位数 | 平均覆盖 | 要求 agent 占比 | 出现最多的技术栈 |")
        L.append("|---|---|---|---|---|")
        for r in rows:
            top = "、".join("%s(%s)" % (n, p) for n, _, p in r["top"][:5])
            L.append("| %s | %d | %.0f%% | %.0f%% | %s |"
                     % (r["key"], r["n"], r["coverage"] * 100,
                        r["agent_ratio"] * 100, top))
        L.append("")

    if s.get("by_family"):
        L.append("## 按岗位族（每个方向一张表，维度摊平）")
        L.append("")
        for f in s["by_family"]:
            L.append("### %s（%d 条 · 平均覆盖 %.0f%% · 明确要求 agent %.0f%%）"
                     % (f["key"], f["n"], f["coverage"] * 100,
                        f["agent_ratio"] * 100))
            L.append("")
            L.append("最常见技术栈：" + "、".join("%s(%s)" % (n, p)
                                          for n, _, p in f["top"]))
            L.append("")
            L.append("| 维度 | 分组 | 岗位 | 覆盖 | 要求 agent | 技术栈 |")
            L.append("|---|---|---|---|---|---|")
            for d in f["detail"]:
                top = "、".join("%s(%s)" % (n, p) for n, _, p in d["top"])
                L.append("| %s | %s | %d | %.0f%% | %.0f%% | %s |"
                         % (d["dim"], d["k"], d["n"], d["coverage"] * 100,
                            d["agent_ratio"] * 100, top))
            L.append("")

    m = s["matrix"]
    L.append("## 技术栈 × 分组 交叉表（格子里是「出现该要求的岗位占比」）")
    L.append("")
    head = ["技能"]
    for cname, keys in m["cols"].items():
        head += keys
    L.append("| " + " | ".join(head) + " |")
    L.append("|" + "---|" * len(head))
    for row in m["rows"]:
        cells = [row["skill"]]
        for cname in m["cols"]:
            cells += ["%d%%" % c["pct"] for c in row["cells"][cname]]
        L.append("| " + " | ".join(cells) + " |")
    L.append("")
    src = "、".join("%s（%d 条）" % (k, v)
                    for k, v in (s.get("sources") or {}).items())
    L.append("> 数据来源：" + (src or "未知") + "。示例数据用于跑通流水线；真实岗位用 dz.cli import 导入。")
    return "\n".join(L)
