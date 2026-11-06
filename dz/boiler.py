"""样板文本剔除：JD 里的页脚/福利/公司简介/平等机会声明不是技能要求。

千问 PDF2 实测教训：safety / multimodal 命中率 100% 是页脚样板文本造成的假高频。
任何频次统计都必须先剔除 boilerplate，否则结论全错。

用法：
    from .boiler import clean
    text2, report = clean(raw)   # report: {"lines_in": n, "lines_out": n, "rules": [...]}
"""
from __future__ import annotations

import re

# (规则名, 正则) —— 命中即剔除该行；中文福利词、英文样板、公司简介段
RULES = (
    ("cn_benefits", re.compile(
        r"五险一金|六险一金|带薪年假|年假|下午茶|零食|节日福利|团建|体检|期权|股票期权|"
        r"弹性工作|餐补|房补|交通补贴|加班费|年终奖|生日会|健身房|补充医疗")),
    ("cn_hr", re.compile(
        r"投递方式|简历请投|简历投递|联系方式|联系人|邮箱地址|联系电话|工作地点：|"
        r"工作时间|薪酬范围|薪资范围|工资待遇|我们的福利|公司福利|你将获得")),
    ("cn_about", re.compile(
        r"公司简介|关于我们|集团简介|企业简介|是一家|成立于|总部位于|已获得|融资")),
    ("en_eeo", re.compile(
        r"equal opportunity|reasonable accommodation|diversity|inclusion|"
        r"we are an equal|non-?discrimination|protected by law", re.I)),
    ("en_benefits", re.compile(
        r"benefits include|perks|stock options|health insurance|401k|401\(k\)|"
        r"paid time off|paternity leave|maternity leave|remote-friendly", re.I)),
    ("en_hr", re.compile(
        r"how to apply|apply now|recruiter|talent acquisition|compensation range|"
        r"salary range|the pay|we offer a competitive", re.I)),
    ("en_about", re.compile(
        r"about the company|about us|who we are|our mission|we are a|founded in|"
        r"backed by|series [a-f]", re.I)),
    ("en_privacy", re.compile(
        r"privacy policy|privacy notice|ccpa|gdpr|data protection", re.I)),
    ("en_scam", re.compile(
        r"your safety matters|recruiters only contact|be cautious of emails|"
        r"confirmed position openings", re.I)),
    ("en_blurb", re.compile(
        r"how we're different|we believe that the highest-impact|as such, we great|"
        r"come work with us|anthropic is a public benefit|"
        r"we view ai research as an empirical|host frequent research discussions", re.I)),
)


def clean(raw: str) -> tuple[str, dict]:
    """返回 (清洗后文本, 统计)。只删整行，绝不删词 —— 保守，宁可漏删不可误删技能句。"""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    kept, hits = [], []
    for ln in lines:
        drop = False
        for name, rx in RULES:
            if rx.search(ln):
                drop = True
                hits.append(name)
                break
        if not drop:
            kept.append(ln)
    report = {
        "lines_in": len(lines),
        "lines_out": len(kept),
        "dropped": len(lines) - len(kept),
        "rules": sorted(set(hits)),
        "hit_detail": {n: hits.count(n) for n in sorted(set(hits))},
    }
    return "\n".join(kept), report


def pollution(raw: str) -> dict:
    """量化一条 JD 的样板污染率（不修改文本）。"""
    _, rep = clean(raw)
    total = len([ln for ln in raw.splitlines() if ln.strip()])
    return {"lines": total, "boiler_lines": rep["dropped"],
            "ratio": round(rep["dropped"] / total, 4) if total else 0.0,
            "rules": rep["hit_detail"]}
