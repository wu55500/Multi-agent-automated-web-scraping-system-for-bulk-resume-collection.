"""黄金集评测：extract_rule vs 人工标注，P/R/F1。

黄金集 = data/golden.jsonl，每行 {"id","title","raw","skills":[cid...]}。
skills 是人工逐句读 JD 后的标注（本轮由我标定，标准：JD 原文出现且属于 29 技能词表）。
评测用 extract_rule（离线、确定性）跑，不调模型 —— 测的是词表+匹配器的下限。

指标：
- micro P/R/F1：跨全部标注汇总 TP/FP/FN；
- per-skill P/R：每个技能的误报/漏报（词表边界问题一目了然）；
- per-JD 最差 10 条：定位规则引擎的短板。
"""
from __future__ import annotations

import json
import os
import time

from .extract import extract_rule
from .boiler import clean as _clean_boiler

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_golden(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if ln.strip():
                out.append(json.loads(ln))
    return out


def evaluate(store, golden_path: str, ) -> dict:
    rows = load_golden(golden_path)
    per_jd = []
    skill_tp, skill_fp, skill_fn = {}, {}, {}
    for g in rows:
        gold = set(g["skills"])
        raw = g.get("raw")
        if raw is None:
            row = store.job(g["job_id"])
            if row is None:
                per_jd.append({"id": g.get("id"), "err": "job_id 不存在于库中"})
                continue
            raw = row["raw"]
        # 镜像线上 extract() 路径：先洗样板再抽（只删整行），保证评测的就是生产行为
        text, _ = _clean_boiler(raw)
        work = text if len(text) >= 200 else raw
        jd = extract_rule(work)
        pred = {s.cid for s in jd.skills}
        tp = gold & pred
        fp = pred - gold
        fn = gold - pred
        for c in tp:
            skill_tp[c] = skill_tp.get(c, 0) + 1
        for c in fp:
            skill_fp[c] = skill_fp.get(c, 0) + 1
        for c in fn:
            skill_fn[c] = skill_fn.get(c, 0) + 1
        p = len(tp) / len(pred) if pred else 1.0
        r = len(tp) / len(gold) if gold else 1.0
        f1 = 2 * p * r / (p + r) if (p + r) else 0.0
        per_jd.append({"id": g["id"], "title": g.get("title", ""),
                       "p": round(p, 3), "r": round(r, 3), "f1": round(f1, 3),
                       "gold": sorted(gold), "pred": sorted(pred),
                       "fp": sorted(fp), "fn": sorted(fn)})
    n = len(rows)
    micro = {
        "p": round(sum(x["f1"] and (len(set(x["gold"]) & set(x["pred"])) / max(len(set(x["pred"])), 1)) for x in per_jd) / n, 3),
        "_": 0,
    }
    # micro 按计数汇总
    tp = sum(len(set(x["gold"]) & set(x["pred"])) for x in per_jd)
    fp = sum(len(set(x["pred"]) - set(x["gold"])) for x in per_jd)
    fn = sum(len(set(x["gold"]) - set(x["pred"])) for x in per_jd)
    m_p = tp / (tp + fp) if (tp + fp) else 1.0
    m_r = tp / (tp + fn) if (tp + fn) else 1.0
    m_f1 = 2 * m_p * m_r / (m_p + m_r) if (m_p + m_r) else 0.0
    macro = {
        "p": round(sum(x["p"] for x in per_jd) / n, 3),
        "r": round(sum(x["r"] for x in per_jd) / n, 3),
        "f1": round(sum(x["f1"] for x in per_jd) / n, 3),
    }
    per_skill = []
    for c in sorted(set(list(skill_tp) + list(skill_fp) + list(skill_fn))):
        t, f, n_ = skill_tp.get(c, 0), skill_fp.get(c, 0), skill_fn.get(c, 0)
        p = t / (t + f) if (t + f) else 1.0
        r = t / (t + n_) if (t + n_) else 1.0
        per_skill.append({"cid": c, "tp": t, "fp": f, "fn": n_,
                          "p": round(p, 3), "r": round(r, 3)})
    per_jd.sort(key=lambda x: x["f1"])
    return {
        "golden": n,
        "micro": {"tp": tp, "fp": fp, "fn": fn, "p": round(m_p, 3),
                  "r": round(m_r, 3), "f1": round(m_f1, 3)},
        "macro": macro,
        "skills": per_skill,
        "worst": per_jd[:10],
        "detail": per_jd,
        "ts": time.time(),
    }


def to_markdown(rep: dict) -> str:
    L = []
    L.append("# dz eval 评测报告")
    L.append("")
    L.append("- 黄金集条数：%d" % rep["golden"])
    L.append("- 生成时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S",
                                              time.localtime(rep["ts"])))
    m = rep["micro"]
    L.append("")
    L.append("## 总体（micro）")
    L.append("")
    L.append("| 指标 | 值 |")
    L.append("|---|---|")
    L.append("| Precision | %.3f |" % m["p"])
    L.append("| Recall | %.3f |" % m["r"])
    L.append("| F1 | %.3f |" % m["f1"])
    L.append("| TP / FP / FN | %d / %d / %d |" % (m["tp"], m["fp"], m["fn"]))
    L.append("")
    L.append("## 总体（macro，按 JD 平均）")
    L.append("")
    L.append("P=%.3f  R=%.3f  F1=%.3f" % (rep["macro"]["p"], rep["macro"]["r"], rep["macro"]["f1"]))
    L.append("")
    L.append("## 按技能（FP=误报，FN=漏报）")
    L.append("")
    L.append("| 技能 | TP | FP | FN | P | R |")
    L.append("|---|---|---|---|---|---|")
    for s in sorted(rep["skills"], key=lambda x: -x["fn"]):
        flag = " ⚠️" if (s["fp"] or s["fn"]) else ""
        L.append("| %s%s | %d | %d | %d | %.2f | %.2f |" % (
            s["cid"], flag, s["tp"], s["fp"], s["fn"], s["p"], s["r"]))
    L.append("")
    L.append("## 最差 10 条 JD")
    L.append("")
    for x in rep["worst"]:
        L.append("- **%s**（%s） F1=%.2f 漏报=%s 误报=%s" % (
            x["title"], x["id"], x["f1"],
            ",".join(x["fn"]) or "-", ",".join(x["fp"]) or "-"))
    return chr(10).join(L)


def run(store, golden_path: str, out_path: str = "") -> dict:
    t0 = time.time()
    rep = evaluate(store, golden_path)
    md = to_markdown(rep)
    out = out_path or os.path.join(ROOT, "reports", "eval.md")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    m = rep["micro"]
    store.log_run("eval", m["f1"] >= 0.7,
                  "golden=%d microF1=%.3f (P=%.3f R=%.3f)" % (
                      rep["golden"], m["f1"], m["p"], m["r"]),
                  int((time.time() - t0) * 1000))
    return rep
