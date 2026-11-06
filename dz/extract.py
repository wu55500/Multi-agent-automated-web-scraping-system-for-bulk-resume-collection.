"""JD 抽取：LLM 三票自洽 + 证据必须原文可查 + 规则兜底 + 内容哈希缓存。

三条硬约束（这是整个系统可信度的来源）：
1. 每条技能必须带 evidence，且 evidence 必须是 JD 原文的子串，否则丢弃；
2. 三次采样投票，少于 2 票的字段丢弃（压模型幻觉）；
3. 没 key / 超时 / 解析失败，一律降级到词典规则，产品不瘫。
"""
from __future__ import annotations

import json
import os
import re
import urllib.request

from .ontology import SKILLS, _hit, canon
from .schema import JD, Skill, h16, squash
from .boiler import clean as _clean_boiler, pollution as _pollution


def _lex() -> dict[str, list[str]]:
    """词典规则直接从技能本体别名生成（长别名优先）：改 ontology 就自动生效。"""
    return {cid: sorted(spec["aliases"], key=len, reverse=True)
            for cid, spec in SKILLS.items()}


LEX = _lex()

PROMPT = """你是招聘 JD 解析器。只输出 JSON，不要解释、不要加markdown围栏。
从 JD 里抽取技能要求。每条必须带 evidence：从 JD 原文原样复制 6-30 字，不要改写、不要翻译。
JD 里没写的技能不要补。不确定就降低 confidence。
输出格式：
{"title":str,"company":str,"city":str,"salary":str,
 "skills":[{"raw":str,"must":bool,"years":number|null,"evidence":str,"confidence":number}]}

JD 原文：
"""


class LLM:
    """OpenAI 兼容协议，默认 DeepSeek。没有 key 就抛错，让上层降级。"""

    def __init__(self, key: str | None = None, model="deepseek-chat",
                 base="https://api.deepseek.com", timeout=60):
        self.key = key or os.environ.get("DEEPSEEK_API_KEY", "")
        self.model, self.base, self.timeout = model, base.rstrip("/"), timeout

    def json(self, prompt: str, temperature=0.7) -> dict:
        if not self.key:
            raise RuntimeError("no api key")
        body = json.dumps({
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }).encode()
        req = urllib.request.Request(
            self.base + "/chat/completions", data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.key})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode())
        return json.loads(data["choices"][0]["message"]["content"])


def _verified(raw: str, skills: list[dict]) -> list[Skill]:
    """证据核验：evidence 不在原文里的整条丢掉。"""
    hay = squash(raw)
    out = []
    for s in skills:
        text = (s.get("raw") or "").strip()
        ev = (s.get("evidence") or "").strip()
        if not text or len(ev) < 2 or squash(ev) not in hay:
            continue
        out.append(Skill(
            raw=text, cid=canon(text) or canon(ev), must=bool(s.get("must", True)),
            years=s.get("years"), evidence=ev,
            confidence=float(s.get("confidence", 1.0))))
    return out


def _vote(samples: list[list[Skill]], keep=2) -> list[Skill]:
    """按 raw 归一化后投票，>=keep 票的留下；取票数最高那条的证据。"""
    bag: dict[str, dict] = {}
    for sk in samples:
        seen = set()
        for s in sk:
            k = re.sub(r"\s+", "", s.raw).lower()
            if k in seen:
                continue
            seen.add(k)
            slot = bag.setdefault(k, {"n": 0, "skill": s})
            slot["n"] += 1
            if len(s.evidence) > len(slot["skill"].evidence):
                slot["skill"] = s
    return [v["skill"] for v in bag.values() if v["n"] >= min(keep, len(samples))]


def extract_llm(llm: LLM, raw: str, votes=3) -> JD:
    samples = []
    for _ in range(votes):
        out = llm.json(PROMPT + raw[:8000], temperature=0.8)
        samples.append(_verified(raw, out.get("skills", [])))
    head = llm.json(PROMPT + raw[:8000], temperature=0.2)
    skills = _vote(samples, keep=2)
    jd = JD(source="llm", title=head.get("title", "") or "", raw=raw,
            company=head.get("company", "") or "", city=head.get("city", "") or "",
            salary=head.get("salary", "") or "", skills=skills, engine="deepseek")
    return jd


def extract_rule(raw: str) -> JD:
    low = raw.lower()
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    title = lines[0][:60] if lines else ""
    skills: list[Skill] = []
    for cid, words in LEX.items():
        for w in words:
            if not _hit(low, w):
                continue
            line = next((ln for ln in lines if _hit(ln.lower(), w)), "")
            skills.append(Skill(raw=w, cid=cid, must=("熟悉" in line or "要求" in line),
                                evidence=line[:60] or w, confidence=0.6))
            break
    return JD(source="paste", title=title, raw=raw, skills=skills, engine="rule")


def extract(store, raw: str, llm: LLM | None = None, votes=3) -> JD:
    key = "jd:" + h16(raw)
    hit = store.cache_get(key)
    if hit:
        jd = JD.from_dict(hit)
        store.log("extract.cache", jd.id, {"engine": jd.engine})
        return jd
    # 样板文本剔除：解析用清洗后的文本，但证据必须是原文子串 —— 只删整行，不改写任何词
    clean_raw, rep = _clean_boiler(raw)
    work = clean_raw if len(clean_raw) >= 200 else raw
    if rep["dropped"] > 0:
        store.log("boiler", h16(raw), _pollution(raw))
    jd = None
    if llm and llm.key:
        try:
            jd = extract_llm(llm, work, votes=votes)
        except Exception as e:  # 网络/额度/解析失败都降级
            store.log("extract.fallback", h16(raw), {"err": str(e)[:200]})
    if jd is None or not jd.skills:
        jd = extract_rule(work)
        if llm and llm.key:
            jd.engine = "rule-fallback"
    jd.raw = raw  # 入库原文不删样板：证据审计以原文为准
    store.cache_put(key, jd.to_dict())
    store.log("extract", jd.id, {"engine": jd.engine, "skills": len(jd.skills)})
    return jd
