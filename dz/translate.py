"""英文岗位名 → 中文（静态映射字典，零依赖）。

覆盖不到的保留原文，调用方标 [EN]，让中文界面一眼认出英文源。
映射保守：宁可译不出，也不乱猜。
"""
from __future__ import annotations

import re

# (正则, 中文)，按顺序替换，长的在前。
RULES = (
    (r"\bmachine learning\b", "机器学习"),
    (r"\bsite reliability\b", "SRE 运维"),
    (r"\bfull[- ]?stack\b", "全栈"),
    (r"\bdata scientist\b", "数据科学家"),
    (r"\bdata engineer\b", "数据工程师"),
    (r"\bresearch engineer\b", "研究工程师"),
    (r"\bresearch scientist\b", "研究科学家"),
    (r"\baccount executive\b", "客户经理"),
    (r"\btrust and safety\b", "信任与安全"),
    (r"\bproduct manager\b", "产品经理"),
    (r"\bengineering manager\b", "工程经理"),
    (r"\bbackend\b", "后端"),
    (r"\bfront[- ]?end\b", "前端"),
    (r"\bsoftware engineer\b", "软件工程师"),
    (r"\bdevops\b", "DevOps"),
    (r"\bsecurity\b", "安全"),
    (r"\binfrastructure\b", "基础设施"),
    (r"\bplatform\b", "平台"),
    (r"\banalytics\b", "分析"),
    (r"\boperations\b", "运营"),
    (r"\brecruit\w*\b", "招聘"),
    (r"\bfinance|financial\b", "金融/财务"),
    (r"\blegal\b", "法务"),
    (r"\bsales\b", "销售"),
    (r"\bmarketing\b", "市场"),
    (r"\bdesign\w*\b", "设计"),
    (r"\bengineer\b", "工程师"),
    (r"\bdeveloper\b", "开发工程师"),
    (r"\bscientist\b", "科学家"),
    (r"\bmanager\b", "经理"),
    (r"\banalyst\b", "分析师"),
)


def zh(title: str) -> str:
    """英文岗位名 → 中文岗位名。改不动就返回原文。"""
    if not title:
        return ""
    out = title
    for pat, cn in RULES:
        out = re.sub(pat, cn, out, flags=re.I)
    # 清掉残留的 ", 公司名/城市" 后缀（Lever 已去，这里兜底）
    out = re.sub(r",\s*[A-Z][A-Za-z0-9 .&()-]{2,40}$", "", out)
    return out.strip()


def display(title: str) -> str:
    """界面/报告用：能译就译；译不动且是英文，标 [EN]。

    中文标题（哪怕夹带 java 之类英文词）不算英文源，不标。"""
    z = zh(title)
    if z == title and re.search(r"[\u4e00-\u9fff]", title):
        return title
    if z == title and re.search(r"[A-Za-z]{3,}", title):
        return "%s [EN]" % title
    return z
