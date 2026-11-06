"""GitHub 开源项目证据链：技能 → 真实开源项目 → README 用途 → 关键模块/文件路径。

合规红线：只用公开 API（搜索/仓库/文件树 + raw README），匿名不登录；
限速（搜索 10 次/分钟 → 间隔 7 秒；核心 API 每次运行设预算，默认 8 次）；
全部结果缓存入库（21 天不重抓），一次抓不完整下次接着抓。

用途提取不吹不编：README 原文引用 + 术语自动标注中文，模块路径原样列出。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request

from .ontology import SKILLS, name as skill_name

API = "https://api.github.com"
RAW = "https://raw.githubusercontent.com"
# 直连被网络抖断时的公开只读降级通道（同一 REST API 的公共镜像，不登录、只读）
API_BASES = (API, "https://gh-proxy.com/https://api.github.com")
UA = {"User-Agent": "dz/1.0 (personal job-hunt analysis; low-rate public reader)",
      "Accept": "application/vnd.github+json"}

REFRESH_DAYS = 21.0
SEARCH_SLEEP = 7.0        # 匿名搜索限 10 次/分钟
RAW_SLEEP = 2.0           # raw 走 CDN，仍礼貌限速

QUERY = {
    "lang.python": "python language:Python stars:>5000",
    "lang.java": "java language:Java stars:>5000",
    "lang.go": "go language:Go stars:>3000",
    "lang.js": "javascript language:JavaScript stars:>5000",
    "web.react": "react language:JavaScript stars:>5000",
    "web.vue": "vue language:JavaScript stars:>2000",
    "web.html": "html css frontend",
    "db.sql": "sql database",
    "db.nosql": "redis",
    "crawl.http": "scrapy crawler",
    "auto.browser": "playwright",
    "auto.rpa": "rpa automation",
    "net.http": "http client library",
    "nlp.llm": "llm agent framework",
    "ml.deep": "pytorch deep learning",
    "ml.sklearn": "scikit-learn machine learning",
    "py.pandas": "pandas data analysis",
    "tool.docker": "docker language:Go stars:>5000",
    "tool.git": "git",
    "tool.linux": "linux shell tools",
    "cloud.basic": "cloud sdk",
    "ops.monitor": "prometheus monitoring",
    "ops.ci": "ci cd pipeline",
    "bi.excel": "excel spreadsheet library",
    "bi.tableau": "dashboard analytics",
    "stat.basic": "statistics library",
    "stat.ab": "ab testing",
    "biz.comm": "communication framework",
    "biz.product": "product management",
}

# 拿文件树时优先看的目录（核心 API 预算有限，按代码优先排序）
TREE_DIRS = ("src", "lib", "libs", "app", "packages", "pkg", "core", "modules",
             "codes", "internal", "scrapy", "server", "backend", "client",
             "docker", "docs")
_NOISE_RE = re.compile(r"https?://\S+")
_SRC_EXT = re.compile(r"\.(py|java|go|js|ts|jsx|tsx|vue|rs|rb|php|c|h|cc|cpp|scala|kt)$")


def _aliases(cid: str):
    al = list(SKILLS[cid]["aliases"]) if cid in SKILLS else [cid]
    al.sort(key=len, reverse=True)
    ascii_a, zh_a = [], []
    for a in al:
        if re.search(r"[\u4e00-\u9fff]", a):
            zh_a.append(a)
        elif re.search(r"[a-z]", a.lower()):
            ascii_a.append(a.lower())
    return ascii_a[:8], zh_a[:4]


def _pat(cid: str):
    ascii_a, zh_a = _aliases(cid)
    pats = [r"\b%s\b" % re.escape(a.replace(" ", r"\s+")) for a in ascii_a if len(a) >= 2]
    pats += [re.escape(z) for z in zh_a]
    if not pats:
        pats = [r"\b%s\b" % cid]
    return re.compile("|".join(pats), re.IGNORECASE)


def _get(url: str, throttle: float = 2.0, timeout: int = 20):
    time.sleep(throttle)
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def _json(url: str, throttle: float = 2.0):
    code, body = _get(url, throttle)
    if code != 200 or not body:
        return None
    try:
        return json.loads(body)
    except Exception:
        return None


_DIRECT_DOWN = {"ts": 0.0}


def _api(path: str, throttle: float = 2.0):
    """API 请求：直连优先，网络抖断时走公开镜像；404/422 说明请求本身错，不重试。
    熔断：直连 5 分钟内挂过就先走镜像，避免每次白等 12 秒超时。"""
    bases = list(API_BASES)
    if time.time() - _DIRECT_DOWN["ts"] < 300:
        bases = (API_BASES[1], API_BASES[0])
    for i, base in enumerate(bases):
        code, body = _get(base + path, throttle if i == 0 else 1.0, timeout=12)
        if code == 200 and body:
            if base == API and _DIRECT_DOWN["ts"]:
                _DIRECT_DOWN["ts"] = 0
            try:
                return json.loads(body)
            except Exception:
                return None
        if code in (404, 422):
            break
        if base == API:
            _DIRECT_DOWN["ts"] = time.time()
    return None


def search_raw(q: str):
    data = _api("/search/repositories?q=%s&sort=stars&order=desc&per_page=3"
                % urllib.parse.quote(q), SEARCH_SLEEP)
    if not data:
        return []
    return _repos(data)


def _repos(data):
    out = []
    for it in data.get("items", [])[:3]:
        out.append({"repo": it.get("full_name", ""),
                    "stars": it.get("stargazers_count", 0),
                    "url": it.get("html_url", ""),
                    "lang": it.get("language") or "",
                    "branch": it.get("default_branch", "HEAD"),
                    "desc": (it.get("description") or "").strip(),
                    "updated": it.get("updated_at", "")})
    return out


def search_repos(cid: str):
    return search_raw(QUERY.get(cid, cid))


def fetch_readme(repo: dict) -> str:
    base = "%s/%s/%s/" % (RAW, repo["repo"], repo["branch"])
    for name in ("README.md", "readme.md", "README.rst", "README"):
        code, body = _get(base + name, RAW_SLEEP)
        if code == 200 and body:
            return body.decode("utf-8", "replace")
    return ""


def _usage_lines(readme: str, pat, limit: int = 3):
    """README 里体现该技术栈用途的行：先去 URL 再匹配，图片/链接/指令行不算。"""
    hits = []
    for ln in readme.splitlines():
        s = ln.strip()
        if not s or len(s) < 15:
            continue
        if s.startswith(("#", ">", "|", "!", "<", "..", ":", "[", "(", "- [", "* [")):
            continue
        s = _NOISE_RE.sub("", s)
        s = re.sub(r"<[^>]+>", " ", s).strip()
        if len(s) < 15:
            continue
        if pat.search(s):
            s = re.sub("[*_\u0060~]", "", s)[:220]
            if s not in hits:
                hits.append(s)
        if len(hits) >= limit:
            break
    return hits


def _intro(readme: str):
    """(标题, 简介段)：找标题后第一个「真段落」——跳过徽章/图片/列表块。"""
    title, blocks = "", []
    cur = []
    for ln in readme.splitlines():
        s = ln.strip()
        if not title and s.startswith("# "):
            title = s[2:].strip()
            continue
        if not title:
            continue
        if s.startswith("#"):
            if cur:
                blocks.append(cur)
            break
        if not s:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        cur.append(s)
    if cur:
        blocks.append(cur)
    intro = ""
    for blk in blocks:
        text = " ".join(blk)
        if not text or len(text) < 30:
            continue
        if any(b.startswith(("- ", "* ", "|", "[", "<", "..")) for b in blk):
            continue
        if "http" in text[:120]:
            continue
        intro = text
        break
    intro = re.sub(r"\s+", " ", intro).strip()[:400]
    return title, intro


def _gloss(text: str, cid: str) -> str:
    out = text
    nm = skill_name(cid) if cid in SKILLS else cid
    ascii_a, _ = _aliases(cid)
    for a in sorted(set(ascii_a), key=len, reverse=True)[:8]:
        if len(a) < 2:
            continue
        out = re.sub(r"(?i)\b%s\b" % re.escape(a),
                     "%s(即「%s」)" % (a, nm), out)
    return out


def fetch_tree(repo: dict, budget: list):
    """关键模块/文件路径。根树 + 最多 2 个代码目录下钻。

    truncated 的树也照样用——API 会返回前 1000 条，够当证据。"""
    pat = _pat(repo.get("_cid", ""))
    path = "/repos/%s/git/trees/%s" % (repo["repo"], repo["branch"])
    data = _api(path, 2.0)
    if budget[0] <= 0 or not data:
        return []
    budget[0] -= 1
    entries = data.get("tree") or []
    paths = [e["path"] for e in entries if e.get("type") == "blob"]
    subs = [(e["path"], e.get("sha", "")) for e in entries
            if e.get("type") == "tree" and e["path"].lower() in TREE_DIRS]
    subs.sort(key=lambda p: (TREE_DIRS.index(p[0].lower())
                             if p[0].lower() in TREE_DIRS else 99))
    for d, sha in subs[:2]:
        if budget[0] <= 0 or not sha:
            break
        sub = _api("/repos/%s/git/trees/%s?recursive=1"
                   % (repo["repo"], sha), 2.0)
        budget[0] -= 1
        if not sub:
            continue
        for e in sub.get("tree") or []:
            if e.get("type") == "blob":
                paths.append("%s/%s" % (d, e["path"]))
    return _pick(paths, pat)


def _pick(paths, pat, limit: int = 12):
    src = [p for p in paths if _SRC_EXT.search(p) and "/." not in p]
    hit = [p for p in src if pat.search(p)]
    chosen = hit[:limit]
    for p in src:
        if p not in chosen and len(chosen) < limit:
            chosen.append(p)
    if not chosen:
        rest = [p for p in paths if p not in src][:4]
        chosen = rest
    return chosen


# Agent 时代趋势证据（伪 cid，只进 projects 表，不参与技能本体统计）
TRENDS = {
    "trend.orch": "langgraph in:name",
    "trend.workflow": "n8n",
    "trend.mcp": "mcp servers",
    "trend.observe": "langfuse llm observability",
}


def build(store, cids=None, budget: int = 8, force: bool = False) -> dict:
    now = time.time()
    todo = []
    for cid in (cids or sorted(SKILLS)):
        if cid not in SKILLS:
            continue
        ts = store.project_ts(cid)
        rows = store.projects(cid)
        fresh = ts and (now - ts) < REFRESH_DAYS * 86400
        thin = len(rows) < 2 or any(not r["modules"] for r in rows)
        if fresh and not force and not thin:
            continue
        todo.append(cid)
    if not todo:
        td = _build_trends(store, [budget], now, force)
        return {"ok": True, "cids": [], "trends": td,
                "note": "全部技能证据已在 21 天缓存期内"}
    box = [budget]
    done, failed = [], []
    for cid in todo:
        repos = search_repos(cid)
        if not repos:
            failed.append(cid)
            continue
        store.clear_projects(cid)
        for repo in repos[:2]:
            repo["_cid"] = cid
            readme = fetch_readme(repo)
            if readme:
                pat = _pat(cid)
                title, intro = _intro(readme)
                uses = json.dumps(_usage_lines(readme, pat), ensure_ascii=False)
                modules = json.dumps(fetch_tree(repo, box), ensure_ascii=False)
            else:
                title = intro = uses = ""
                modules = json.dumps(fetch_tree(repo, box), ensure_ascii=False)
            store.put_project(cid, repo["repo"], repo["stars"], repo["url"],
                              repo["lang"], repo["updated"], title, intro,
                              _gloss(intro, cid), uses, modules,
                              repo["desc"], now)
        done.append(cid)
    td = _build_trends(store, box, now, force)
    return {"ok": True, "cids": done, "failed": failed, "trends": td,
            "budget_left": box[0]}


def _build_trends(store, box: list, now: float, force: bool) -> list:
    """技能本体抓完后，用剩余核心 API 预算补 Agent 时代趋势项目（各取 1 个）。"""
    got = []
    for cid, q in TRENDS.items():
        if box[0] < 2:
            break
        ts = store.project_ts(cid)
        if ts and not force and (now - ts) < REFRESH_DAYS * 86400:
            continue
        repos = search_raw(q)
        if not repos:
            continue
        repo = repos[0]
        repo["_cid"] = q
        readme = fetch_readme(repo)
        if readme:
            pat = _pat(q)
            title, intro = _intro(readme)
            uses = json.dumps(_usage_lines(readme, pat), ensure_ascii=False)
            modules = json.dumps(fetch_tree(repo, box), ensure_ascii=False)
        else:
            title = intro = uses = ""
            modules = json.dumps(fetch_tree(repo, box), ensure_ascii=False)
        store.put_project(cid, repo["repo"], repo["stars"], repo["url"],
                          repo["lang"], repo["updated"], title, intro,
                          intro, uses, modules,
                          repo["desc"], now)
        got.append(cid)
    return got
