"""技能本体：规范 id + 别名 + 前置依赖。别名越长越优先，短英文词加边界。"""
from __future__ import annotations

import re

SKILLS: dict[str, dict] = {
    "lang.python": {"name": "Python", "domain": "语言", "prereq": [],
                    "aliases": {"python", "python3", "py3"}},
    "lang.js": {"name": "JavaScript", "domain": "语言", "prereq": [],
                "aliases": {"javascript", "es6", "es2015", "typescript", "js"}},
    "lang.java": {"name": "Java", "domain": "语言", "prereq": [],
                  "aliases": {"java", "jdk", "spring boot", "springboot"}},
    "lang.go": {"name": "Go", "domain": "语言", "prereq": [],
                "aliases": {"golang", "go 语言"}},
    "py.pandas": {"name": "Python 数据分析（Pandas 库）", "domain": "数据", "prereq": ["lang.python"],
                  "aliases": {"pandas", "numpy", "数据清洗", "数据框"}},
    "db.sql": {"name": "SQL 数据库查询", "domain": "数据", "prereq": [],
               "aliases": {"sql", "mysql", "hive", "窗口函数", "group by", "postgresql"}},
    "db.nosql": {"name": "NoSQL 数据库/消息队列（Redis 等）", "domain": "数据", "prereq": ["db.sql"],
                 "aliases": {"redis", "mongodb", "nosql", "kafka", "消息队列"}},
    "stat.basic": {"name": "统计基础", "domain": "数学", "prereq": [],
                   "aliases": {"统计学", "概率论", "描述性统计", "假设检验", "统计基础"}},
    "stat.ab": {"name": "A/B 实验", "domain": "数学", "prereq": ["stat.basic"],
                "aliases": {"ab test", "ab testing", "abtest", "a/b", "ab 实验", "置信区间", "显著性"}},
    "bi.excel": {"name": "Excel", "domain": "工具", "prereq": [],
                 "aliases": {"excel", "vlookup", "数据透视", "power query"}},
    "bi.tableau": {"name": "BI 可视化看板（Tableau/Power BI）", "domain": "工具", "prereq": ["bi.excel"],
                   "aliases": {"tableau", "power bi", "看板", "bi 报表"}},
    "tool.git": {"name": "Git", "domain": "工具", "prereq": [],
                 "aliases": {"git", "github", "gitlab", "版本管理"}},
    "tool.linux": {"name": "Linux/Shell", "domain": "工具", "prereq": [],
                   "aliases": {"linux", "shell", "bash", "命令行"}},
    "tool.docker": {"name": "Docker", "domain": "运维", "prereq": ["tool.linux"],
                    "aliases": {"docker", "容器化", "k8s", "kubernetes", "containers", "containerized", "containerization"}},
    "ops.ci": {"name": "CI/CD 自动构建发布（Jenkins）", "domain": "运维", "prereq": ["tool.git"],
               "aliases": {"ci/cd", "jenkins", "github actions", "流水线"}},
    "ops.monitor": {"name": "监控告警", "domain": "运维", "prereq": ["tool.linux"],
                    "aliases": {"prometheus", "grafana", "监控", "告警"}},
    "web.html": {"name": "HTML/CSS", "domain": "前端", "prereq": [],
                 "aliases": {"html", "css", "响应式"}},
    "web.vue": {"name": "Vue", "domain": "前端", "prereq": ["lang.js", "web.html"],
                "aliases": {"vue", "vue3", "vue2"}},
    "web.react": {"name": "React", "domain": "前端", "prereq": ["lang.js", "web.html"],
                  "aliases": {"react", "jsx", "next.js"}},
    "net.http": {"name": "HTTP/接口开发", "domain": "网络", "prereq": [],
                 "aliases": {"http", "rest api", "restful", "restful api", "接口文档"}},
    "crawl.http": {"name": "爬虫/数据采集", "domain": "工程", "prereq": ["net.http", "lang.python"],
                   "aliases": {"爬虫", "python requests", "requests 库", "requests.get", "requests.post", "httpx", "scrapy", "xpath", "beautifulsoup"}},
    "auto.browser": {"name": "浏览器自动化（模拟操作网页）", "domain": "工程", "prereq": ["lang.js", "net.http"],
                     "aliases": {"playwright", "selenium", "ui 自动化", "自动化测试", "浏览器自动化"}},
    "auto.rpa": {"name": "RPA 流程自动化（影刀等）", "domain": "工程", "prereq": [],
                 "aliases": {"rpa", "影刀", "uipath", "流程自动化", "n8n"}},
    "ml.sklearn": {"name": "机器学习（Sklearn 等库）", "domain": "算法", "prereq": ["py.pandas", "stat.basic"],
                   "aliases": {"sklearn", "scikit-learn", "机器学习", "xgboost", "逻辑回归"}},
    "ml.deep": {"name": "深度学习（PyTorch 等）", "domain": "算法", "prereq": ["ml.sklearn"],
                "aliases": {"pytorch", "tensorflow", "深度学习", "神经网络", "transformer", "transformers", "finetuning", "fine-tuning", "reinforcement learning"}},
    "nlp.llm": {"name": "大模型/LLM 应用（Agent 等）", "domain": "算法", "prereq": ["ml.deep"],
                "aliases": {"llm", "llms", "大模型", "prompt", "prompts", "rag", "agent", "agents", "langchain",
                            "langgraph", "mcp", "model context protocol", "embeddings", "向量库", "vector database",
                            "function calling", "tool calling", "dify", "coze"}},
    "cloud.basic": {"name": "云服务", "domain": "运维", "prereq": ["tool.linux"],
                    "aliases": {"aws", "阿里云", "腾讯云", "云服务器", "ecs"}},
    "biz.product": {"name": "产品思维", "domain": "业务", "prereq": [],
                    "aliases": {"产品思维", "需求分析", "用户研究", "竞品"}},
    "biz.comm": {"name": "沟通协作", "domain": "业务", "prereq": [],
                 "aliases": {"沟通", "跨部门", "汇报", "协作能力", "communication and", "communication skills", "verbal communication", "written communication", "communication style", "communication abilities"}},
}


def _hit(text: str, alias: str) -> bool:
    # 所有纯 ASCII 别名一律词边界匹配：excel 不再命中 excellent，http 不再命中 https://
    if alias.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text) is not None
    return alias in text


def canon(text: str) -> str:
    t = (text or "").lower()
    best, size = "", 0
    for cid, spec in SKILLS.items():
        for a in spec["aliases"]:
            if len(a) > size and _hit(t, a):
                best, size = cid, len(a)
    return best


def normalize(skills) -> list:
    for s in skills:
        if not s.cid:
            s.cid = canon(s.raw)
    return skills


def name(cid: str) -> str:
    return SKILLS.get(cid, {}).get("name", cid or "?")


def missing_prereq(cid: str, mine: dict) -> list[str]:
    return [p for p in SKILLS.get(cid, {}).get("prereq", []) if mine.get(p, 0) < 1]


def topo(plan: list[str], mine: dict) -> list[str]:
    out, seen = [], set()

    def walk(cid):
        if cid in seen:
            return
        seen.add(cid)
        for p in SKILLS.get(cid, {}).get("prereq", []):
            if mine.get(p, 0) < 1:
                walk(p)
        out.append(cid)

    for c in plan:
        walk(c)
    return out
