"""高门槛识别：岗位是否要求 985/211/硕博学历，或高难算法/数学。

用户画像需求：「不要求学历 92、算法和数学高难度要求的岗位」优先看。
保守策略：出现任一信号即标记 hard（宁可多滤，不让用户去投学历/竞赛门槛的岗）。
纯离线规则，可单测。ASCII 一律词边界，避免 noise→noi、acme→acm 这类误伤。
"""
from __future__ import annotations

import re

# (模式, 展示标签)。ASCII 模式走词边界正则，中文走子串。
DEGREE = (
    (r"\bph\.?\s?d\b", "PhD"), (r"\bdoctorate\b", "博士"),
    (r"\bmaster'?s\b", "硕士"), (r"\bm\.s\.\b", "硕士"),
    (r"\bms\b", "硕士"), (r"\bpost-?graduate\b", "研究生"),
    ("研究生及以上", "研究生及以上"), ("研究生学历", "研究生学历"),
    ("硕士", "硕士"), ("博士", "博士"),
)
ALGO = (
    (r"\bacm\b", "ACM 竞赛"), (r"\bicpc\b", "ICPC 竞赛"),
    (r"\bnoi\b", "NOI 竞赛"), (r"\bcompetitive programming\b", "竞赛编程"),
    (r"\btop[- ]tier conference\b", "顶会"), (r"\bfirst[- ]author\b", "第一作者"),
    (r"\bpeer[- ]reviewed publication\b", "论文发表"),
    ("算法竞赛", "算法竞赛"), ("数学竞赛", "数学竞赛"),
    ("信息学竞赛", "信息学竞赛"), ("竞赛金牌", "竞赛金牌"), ("强基", "强基"),
    ("数论", "数论"),
)
MATH = ("数学系", "应用数学", "数值优化", "随机过程", "泛函分析", "实变函数")

_NUM = re.compile(r"(?<!\d)(?:985|211)(?!\d)")


def _hit(pat: str, low: str, raw: str) -> bool:
    if pat.isascii():
        return re.search(pat, low) is not None
    return pat in raw


def detect(raw: str) -> tuple[bool, str]:
    """返回 (是否高门槛, 理由)。理由用来解释给用户看，不是黑盒。"""
    if not raw:
        return False, ""
    low = raw.lower()
    m = _NUM.search(raw)
    if m:
        return True, "要求学历：" + m.group(0)
    for pat, label in DEGREE:
        if _hit(pat, low, raw):
            return True, "要求学历：" + label
    for pat, label in ALGO:
        if _hit(pat, low, raw):
            return True, "算法/竞赛：" + label
    for k in MATH:
        if k in raw:
            return True, "高难数学：" + k
    return False, ""
