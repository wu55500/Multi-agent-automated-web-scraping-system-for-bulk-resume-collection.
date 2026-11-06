"""岗位族：把「同一个方向」的 JD 聚成一堆，才能横向比技术栈。

标题命中权重 3，正文命中权重 1，取分最高的族。
「AI +」不是单独的族，而是族上的一个标记：AI + 数据采集 = 采集族 且 ai_plus。
加标记而不是另造一族，是因为「AI＋采集」的底座还是采集，
否则同一份 JD 只因为多写了一个大模型就漂到别的族去。
"""
from __future__ import annotations

import re

# 顺序即优先级：得分相同时靠前的赢
ROLES = (
    {"id": "agent", "label": "Agent 应用开发",
     "strong": ("agent", "智能体", "multi-agent", "多智能体", "自主代理"),
     "weak": ("langchain", "langgraph", "mcp", "function calling", "工具调用", "编排")},
    {"id": "ai_app", "label": "AI 应用开发",
     "strong": ("ai 应用", "ai应用", "大模型应用", "llm 应用", "llm应用", "aigc",
                "生成式 ai"),
     "weak": ("rag", "prompt", "提示词", "向量库", "知识库", "智能问答")},
    {"id": "fde", "label": "AI 全栈 / FDE",
     "strong": ("fde", "forward deployed", "全栈"),
     "weak": ("交付工程师", "解决方案", "驻场", "客户现场", "端到端")},
    {"id": "crawl", "label": "爬虫 / 数据采集",
     "strong": ("爬虫", "反爬", "采集", "抓取", "spider", "scrapy"),
     "weak": ("代理池", "验证码", "playwright", "selenium", "xpath", "requests")},
    {"id": "bigdata", "label": "大数据开发",
     "strong": ("大数据", "数仓", "数据仓库", "hadoop", "spark", "flink", "数据湖"),
     "weak": ("etl", "airflow", "doris", "clickhouse", "hive", "实时计算")},
    {"id": "ops", "label": "运维 / SRE",
     "strong": ("运维", "sre", "devops", "k8s", "kubernetes", "可观测"),
     "weak": ("监控告警", "prometheus", "ci/cd", "ansible", "发布系统")},
    {"id": "test", "label": "测试 / QA",
     "strong": ("测试", "qa", "测开", "质量保障"),
     "weak": ("自动化测试", "pytest", "用例", "selenium", "性能测试")},
)

ROLE_LABEL = {r["id"]: r["label"] for r in ROLES}
ROLE_ORDER = tuple(r["id"] for r in ROLES)

# 「AI +」只加在这四个方向上
PLUS = ("crawl", "bigdata", "ops", "test")
PLUS_LABEL = {"crawl": "AI + 数据采集", "bigdata": "AI + 大数据开发",
              "ops": "AI + 运维", "test": "AI + 测试"}

AI_MARK = ("ai", "aigc", "llm", "大模型", "智能体", "agent", "机器学习",
           "深度学习", "多模态", "rag", "prompt", "提示词", "评测", "向量",
           "算法模型")


def _hits(text: str, words) -> int:
    n = 0
    for w in words:
        if w.isascii() and len(w) <= 3:
            if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", text):
                n += 1
        elif w in text:
            n += 1
    return n


def detect(title: str, raw: str) -> str:
    """返回族 id；一个都不像就返回空串（宁可归不到，也别乱塞）。"""
    t = (title or "").lower()
    b = (raw or "").lower()
    best, top = "", 0
    for r in ROLES:
        ts = _hits(t, r["strong"])
        bs = _hits(b, r["strong"])
        bw = _hits(b, r["weak"])
        if ts:
            score = 3 * ts + bs + bw          # 标题命中，正文只是加权
        elif bs >= 2:
            score = 2.0 + 0.1 * bs            # 正文单独命中要够两次，且永远压不过标题
        else:
            score = 0
        if score > top:
            best, top = r["id"], score
    return best


def ai_plus(text: str) -> bool:
    """要求区里出现 AI 词才算「AI +」；只挂在 PLUS 的四个族上。"""
    return _hits((text or "").lower(), AI_MARK) > 0


def label(fam: str, plus: bool = False) -> str:
    if plus and fam in PLUS:
        return PLUS_LABEL[fam]
    return ROLE_LABEL.get(fam, "")


def key(fam: str, plus: bool = False) -> str:
    return fam + ("+ai" if (plus and fam in PLUS) else "")


def all_keys() -> tuple:
    out = []
    for fam in ROLE_ORDER:
        if fam in PLUS:
            out.append(key(fam, True))
        out.append(key(fam, False))
    return tuple(out) + ("",)


def label_of(key_: str) -> str:
    if not key_:
        return "未归类"
    fam, _, flag = key_.partition("+")
    return label(fam, flag == "ai")
