"""三维分类：地域 / 公司规模 / 有没有 agent（LLM）要求。

这三列就是"同一张表里能横向比"的关键：同一个 SQL 要求，
在大厂是"熟悉"，在 20 人小厂是"你一个人全干"。
"""
from __future__ import annotations

import re

from . import roles

CITIES = ("北京", "上海", "深圳", "杭州", "广州", "成都", "远程")
SIZE_ORDER = ("大厂", "中厂", "小厂", "未知")
AGENT_ORDER = (2, 1, 0)

BIG = ("字节", "抖音", "阿里", "腾讯", "美团", "京东", "拼多多", "百度", "网易",
       "快手", "滴滴", "华为", "小米", "蚂蚁", "携程", "哔哩", "B站", "小红书",
       "得物", "SHEIN", "中金", "招商银行", "大疆", "OPPO", "vivo", "商汤",
       "旷视", "理想汽车", "蔚来", "比亚迪", "中兴")
MID = ("科技", "网络", "信息", "数据", "软件", "集团")

AGENT_KW = ("agent", "智能体", "llm", "大模型", "rag", "prompt", "提示词",
            "langchain", "function calling", "mcp", "自动化编排", "多智能体",
            "workflow 编排", "copilot")
WEAK = ("ai", "aigc", "chatgpt")

REQ_MARK = ("任职要求", "岗位要求", "要求：", "任职资格")


def city(raw: str, given: str = "") -> str:
    if given and given.strip():
        return given.strip()
    for c in CITIES:
        if c in raw:
            return c
    return "其他"


def size(company: str, raw: str, given: str = "") -> str:
    g = (given or "").strip()
    if g and g in SIZE_ORDER:
        return g
    if g and "人" in g:  # 招聘软件导出的公司规模列：20-99人 / 500-999人 / 1000-9999人 / 10000人以上
        if "0-20" in g or "20-99" in g:
            return "小厂"
        if "100-499" in g or "500-999" in g:
            return "中厂"
        if "1000" in g or "10000" in g:
            return "大厂"
    if any(b in company for b in BIG):
        return "大厂"
    if "初创" in raw or "0-20人" in raw or "20-99人" in raw:
        return "小厂"
    if "1000人以上" in raw or "上市公司" in raw:
        return "中厂"
    if any(m in company for m in MID):
        return "中厂"
    return "未知"


def _req_section(raw: str) -> str:
    """截出"任职要求"之后的部分：要求区里的 agent 才是真要求。"""
    idx = -1
    for m in REQ_MARK:
        i = raw.find(m)
        if i > idx:
            idx = i
    return raw[idx:] if idx >= 0 else raw


def agent_level(raw: str) -> int:
    low = raw.lower()
    req = _req_section(low)
    if any(k in req for k in AGENT_KW):
        return 2
    if any(k in low for k in AGENT_KW):
        return 1
    if any(k in low for k in WEAK):
        return 1
    return 0


AGENT_LABEL = {2: "明确要求 agent/LLM", 1: "提到相关词", 0: "无"}


def family(raw: str, title: str = "") -> str:
    """岗位族 id + 是否带 AI 标记，合并成一个 key（如 crawl+ai）。"""
    fam = roles.detect(title, raw)
    plus = fam in roles.PLUS and (ai_plus(raw) or roles.ai_plus(title))
    return roles.key(fam, plus)


def family_label(key: str) -> str:
    return roles.label_of(key)


def ai_plus(raw: str) -> bool:
    """只有在「任职要求」里出现 AI 词才算 AI+，避免开头公司介绍里的 AI 误伤。"""
    return roles.ai_plus(_req_section((raw or "").lower()))


def tag(job: dict) -> dict:
    raw = job.get("raw", "")
    title = job.get("title", "")
    return {
        "job_id": job["id"],
        "city": city(raw, job.get("city", "")),
        "size": size(job.get("company", ""), raw, job.get("size", "")),
        "agent_level": agent_level(raw),
        "family": family(raw, title),
    }
