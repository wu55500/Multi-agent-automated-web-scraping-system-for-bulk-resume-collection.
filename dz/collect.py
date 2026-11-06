"""公开 ATS 采集器：Greenhouse / Lever 公开 board API，全自动 + 合规内建。

合规约束（千问 PDF2 §8 同款，写死在代码里，无法通过参数关掉）：
1. 令牌桶限速：两次请求间隔 2~5s 随机 jitter；
2. 指数退避：失败最多重试 2 次，间隔 60s / 300s，不轰炸；
3. robots.txt 检查：Disallow 的路径不抓（结果缓存）；
4. 每条请求写 events(kind=collect.*)，保留 source_url 与抓取时间；
5. 只读公开接口：无登录态、无绕过、无签名逆向、无代理池。
"""
from __future__ import annotations

import html
import json
import random
import re
import time
import urllib.parse
import urllib.request

from . import classify
from .extract import extract
from .schema import JD

GH = "https://boards-api.greenhouse.io/v1/boards"
UA = {"User-Agent": "dz/1.0 (personal job-hunt analysis; low-rate reader)"}
BACKOFF = (60.0, 300.0)

# 英文 JD 的岗位族检测偏中文词，这里补一道标题级技术岗过滤（只增不减）
TECH_TITLE = re.compile(
    r"engineer|developer|scientist|software|hardware|machine learning|\bml\b|\bai\b|"
    r"agent|data|security|platform|infrastructure|devops|\bsre\b|research|"
    r"applied|robotics|safety|compute|cloud|\bit\b", re.I)


class Throttle:
    """令牌桶：最小间隔 2s，外加 0~3s jitter。"""

    def __init__(self, lo: float = 2.0, hi: float = 5.0):
        self.lo, self.hi = lo, hi
        self.last = 0.0

    def wait(self) -> None:
        now = time.time()
        gap = self.last + random.uniform(self.lo, self.hi) - now
        if gap > 0:
            time.sleep(gap)
        self.last = time.time()


def _get_json(url: str, throttle: Throttle, store):
    for i in range(2):
        throttle.wait()
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read().decode("utf-8", "replace")
                store.log("collect.fetch", url,
                          {"http": r.status, "bytes": len(body),
                           "cost_ms": int((time.time() - t0) * 1000)})
                if body.lstrip().startswith(("{", "[")):
                    return json.loads(body)
                return None
        except Exception as e:
            store.log("collect.fail", url, {"err": str(e)[:200], "attempt": i + 1})
            if i + 1 < 2:
                time.sleep(BACKOFF[i])
    return None


def robots_ok(store, url: str) -> bool:
    """robots.txt 允许才抓；robots 拿不到时保守放行，但记录日志。"""
    parts = urllib.parse.urlparse(url)
    key = "robots:" + parts.netloc
    hit = store.cache_get(key)
    if hit is not None:
        return bool(hit)
    robots_url = parts.scheme + "://" + parts.netloc + "/robots.txt"
    try:
        req = urllib.request.Request(robots_url, headers=UA)
        with urllib.request.urlopen(req, timeout=15) as r:
            txt = r.read().decode("utf-8", "replace")
        dis: set = set()
        cur = "*"
        for ln in txt.splitlines():
            ln = ln.strip()
            low = ln.lower()
            if low.startswith("user-agent:"):
                cur = ln.split(":", 1)[1].strip().lower()
            elif low.startswith("disallow:") and cur in ("*", "dz", "dz/1.0"):
                p = ln.split(":", 1)[1].strip()
                if p:
                    dis.add(p)
        ok = not any(parts.path.startswith(p) for p in dis)
        store.cache_put(key, ok)
        store.log("collect.robots", robots_url, {"allowed": ok, "rules": len(dis)})
        return ok
    except Exception as e:
        store.log("collect.robots", robots_url, {"err": str(e)[:120]})
        return True


def strip_html(s: str) -> str:
    # greenhouse board API 的 content 字段是 HTML 实体转义过的（&lt;div class=&quot;…&gt;），
    # 必须先去转义，否则 &lt;/&gt; 被当成实体抹掉，标签名和属性全漏进正文（2026-10 实测回归）。
    s = html.unescape(s)
    # 无标签快路径：避免 <[^>]+> 在没有任何 '>' 的文本上 O(n^2) 回溯（30 分钟重采集的真凶）
    if "<" not in s:
        s = s.replace("\u00a0", " ").replace("\xa0", " ")
        return s.strip()
    # 块级结束标签转成换行，保住段落结构 —— 样板文本按行剔除依赖它
    s = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", s, flags=re.S | re.I)
    s = re.sub(r"</(p|div|li|ul|ol|h[1-6]|br|tr|section)>", chr(10), s, flags=re.I)
    s = re.sub(r"<br[^>]*>", chr(10), s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"&[a-z]+;", " ", s)
    s = re.sub(r"[ \t\r\f\v]+", " ", s)
    s = re.sub(r" *\n *", chr(10), s)
    s = re.sub(r"\n{3,}", chr(10) + chr(10), s)
    return s.strip()


def collect_board(store, company: str, limit: int = 0, llm=None,
                  tech_only: bool = False) -> dict:
    t0 = time.time()
    url = "%s/%s/jobs?content=true" % (GH, urllib.parse.quote(company))
    if not robots_ok(store, url):
        store.log_run("collect_greenhouse", False, "robots disallow: " + url)
        return {"ok": False, "err": "robots disallow", "stored": 0}
    data = _get_json(url, Throttle(), store)
    if not data:
        store.log_run("collect_greenhouse", False, "fetch failed: " + url)
        return {"ok": False, "err": "fetch failed", "stored": 0}
    jobs = data.get("jobs", [])
    stored = skipped_short = skipped_nontech = 0
    for j in jobs:
        if limit and stored + skipped_short + skipped_nontech >= limit:
            break
        raw = strip_html(j.get("content", "") or "")
        if len(raw) < 200:
            skipped_short += 1
            continue
        loc = j.get("location") or {}
        jd = extract(store, raw, llm)
        jd.id = "gh-%s" % j.get("id", "")
        jd.source = "greenhouse"
        jd.title = j.get("title", "") or jd.title
        jd.company = j.get("company_name", "") or jd.company
        jd.city = loc.get("name", "") if isinstance(loc, dict) else str(loc or "")
        jd.source_url = j.get("absolute_url", "")
        tag = classify.tag({"id": jd.id, "raw": raw, "city": jd.city,
                            "company": jd.company, "size": "", "title": jd.title})
        if tech_only and not tag["family"] and not TECH_TITLE.search(jd.title):
            skipped_nontech += 1
            continue
        store.put_job(jd)
        store.put_tag(tag)
        stored += 1
    store.log_run("collect_greenhouse", True,
                  "board=%s jobs=%d stored=%d skip_short=%d skip_nontech=%d" % (
                      company, len(jobs), stored, skipped_short, skipped_nontech),
                  int((time.time() - t0) * 1000))
    return {"ok": True, "board": company, "jobs": len(jobs),
            "stored": stored, "skipped_short": skipped_short,
            "skipped_nontech": skipped_nontech,
            "cost_ms": int((time.time() - t0) * 1000)}
LEVER = "https://api.lever.co/v0/postings"


def lever_row(p: dict) -> dict:
    """Lever posting → 结构化行。纯函数，便于单测。

    Lever 的 *Plain 字段已是纯文本，无 HTML，不需要 strip_html。
    """
    cats = p.get("categories") or {}
    parts = [p.get("descriptionPlain"), p.get("descriptionBodyPlain")]
    # 正文在 lists 里（What You'll Do / Who You Are，HTML），*Plain 只有简介——
    # 2026-10 实测：漏掉 lists 会让整条 JD 只剩公司样板（技能抽取全空）
    for l in p.get("lists") or []:
        parts.append(l.get("text", ""))
        parts.append(strip_html(l.get("content") or ""))
    parts.append(p.get("additionalPlain"))
    parts.append(strip_html(p.get("additional") or ""))
    parts.append(p.get("openingPlain"))
    raw = "\n".join(x for x in parts if isinstance(x, str) and x.strip())
    title = (p.get("text") or "")
    # "Account Executive - Commercial, Spotify Technology" → 去掉公司后缀
    if ", " in title:
        head = title.split(", ")[0]
        if len(head) > 5:
            title = head
    sr = p.get("salaryRange") or {}
    salary = ""
    if sr and sr.get("min") is not None:
        salary = "%s-%s %s/%s" % (sr.get("min"), sr.get("max"),
                                  sr.get("currency", ""), sr.get("interval", ""))
    return {"raw": raw, "title": title, "city": cats.get("location", ""),
            "team": cats.get("team", ""), "salary": salary,
            "url": p.get("hostedUrl") or p.get("applyUrl", "")}


def collect_lever(store, company: str, limit: int = 0, llm=None,
                  tech_only: bool = False) -> dict:
    """Lever 公开 board：一次 GET 拿全部 JD（含全文），限速/robots/来源留存同 Greenhouse。"""
    t0 = time.time()
    url = "%s/%s?mode=json" % (LEVER, urllib.parse.quote(company))
    if not robots_ok(store, url):
        store.log_run("collect_lever", False, "robots disallow: " + url)
        return {"ok": False, "err": "robots disallow", "stored": 0}
    data = _get_json(url, Throttle(), store)
    if not isinstance(data, list):
        store.log_run("collect_lever", False, "fetch failed: " + url)
        return {"ok": False, "err": "fetch failed", "stored": 0}
    stored = skipped_short = skipped_nontech = 0
    for p in data:
        if limit and stored + skipped_short + skipped_nontech >= limit:
            break
        row = lever_row(p)
        if len(row["raw"]) < 200:
            skipped_short += 1
            continue
        jd = extract(store, row["raw"], llm)
        jd.id = "lv-%s" % p.get("id", "")
        jd.source = "lever"
        jd.title = row["title"] or jd.title
        jd.company = company
        jd.city = row["city"] or jd.city
        jd.salary = row["salary"] or jd.salary
        jd.source_url = row["url"]
        tag = classify.tag({"id": jd.id, "raw": row["raw"], "city": jd.city,
                            "company": company, "size": "", "title": jd.title})
        if tech_only and not tag["family"] and not TECH_TITLE.search(jd.title):
            skipped_nontech += 1
            continue
        store.put_job(jd)
        store.put_tag(tag)
        stored += 1
    store.log_run("collect_lever", True,
                  "board=%s jobs=%d stored=%d skip_short=%d skip_nontech=%d" % (
                      company, len(data), stored, skipped_short, skipped_nontech),
                  int((time.time() - t0) * 1000))
    return {"ok": True, "board": company, "jobs": len(data),
            "stored": stored, "skipped_short": skipped_short,
            "skipped_nontech": skipped_nontech,
            "cost_ms": int((time.time() - t0) * 1000)}

