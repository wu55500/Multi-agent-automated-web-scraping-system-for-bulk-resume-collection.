"""数据模型：只用 dataclass，零第三方依赖，手机 Termux 也能跑。"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Optional

SENIORITY = ("实习", "校招", "初级", "中级", "高级", "专家")
STATES = ("draft", "queued", "filling", "filled", "submitted",
          "replied", "interview", "rejected", "dead")


def h16(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def squash(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


@dataclass
class Skill:
    raw: str
    cid: str = ""
    must: bool = True
    years: Optional[float] = None
    evidence: str = ""
    confidence: float = 1.0

    @property
    def weight(self) -> float:
        return (1.0 if self.must else 0.5) * max(0.0, min(1.0, self.confidence))


@dataclass
class JD:
    source: str
    title: str
    raw: str
    company: str = ""
    city: str = ""
    salary: str = ""
    seniority: str = ""
    skills: list[Skill] = field(default_factory=list)
    engine: str = "rule"
    id: str = ""
    source_url: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = h16(self.raw)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["skills"] = [asdict(s) for s in self.skills]
        return d

    @staticmethod
    def from_dict(d: dict) -> "JD":
        skills = [Skill(**s) for s in d.get("skills", [])]
        return JD(
            source=d.get("source", "paste"), title=d.get("title", ""),
            raw=d.get("raw", ""), company=d.get("company", "") or "",
            city=d.get("city", "") or "", salary=d.get("salary", "") or "",
            seniority=d.get("seniority", "") or "", skills=skills,
            engine=d.get("engine", "rule"), id=d.get("id", ""),
            source_url=d.get("source_url", ""),
        )
