"""匹配打分：覆盖率 = 加权命中 / 加权总要求，深度到 2（写过）即满分。"""
from __future__ import annotations

from .ontology import SKILLS, missing_prereq


def evaluate(skills, mine: dict) -> dict:
    total = got = 0.0
    hits, gaps, unknown = [], [], []
    for s in skills:
        if not s.cid:
            unknown.append(s.raw)
            continue
        w = s.weight
        total += w
        depth = int(mine.get(s.cid, 0))
        got += w * min(depth / 2.0, 1.0)
        row = {"cid": s.cid, "raw": s.raw, "w": round(w, 3), "depth": depth,
               "evidence": s.evidence, "must": s.must,
               "prereq": missing_prereq(s.cid, mine) if depth < 1 else []}
        (hits if depth >= 2 else gaps).append(row)

    def prio(r):
        base = r["w"] * (1 - min(r["depth"] / 2.0, 1.0))
        return base + 0.15 * len(r["prereq"])

    gaps.sort(key=lambda r: -prio(r))
    return {
        "coverage": round(got / total, 3) if total else 0.0,
        "weight_total": round(total, 3),
        "must_missed": sum(1 for r in gaps if r["must"]),
        "hits": sorted(hits, key=lambda r: -r["w"]),
        "gaps": gaps,
        "unknown": unknown,
    }


def tier(coverage: float) -> str:
    if coverage >= 0.85:
        return "可以直接投"
    if coverage >= 0.6:
        return "补两个缺口再投"
    if coverage >= 0.35:
        return "练手区：投了也大概率没回音"
    return "别投，先攒底子"


def blocked_plan(gaps: list[dict]) -> list[str]:
    """把缺口按前置依赖排成学习顺序，前置没会的先排前面。"""
    from .ontology import topo
    return topo([g["cid"] for g in gaps], {})


DOMAIN_ORDER = ("语言", "数据", "数学", "工程", "前端", "算法", "运维", "工具", "业务", "网络")


def by_domain(gaps: list[dict]) -> dict:
    out: dict[str, list] = {}
    for g in gaps:
        dom = SKILLS.get(g["cid"], {}).get("domain", "其他")
        out.setdefault(dom, []).append(g)
    return dict(sorted(out.items(), key=lambda kv: DOMAIN_ORDER.index(kv[0])
                       if kv[0] in DOMAIN_ORDER else 99))
