"""B 主干 API：纯标准库 http.server，统一信封 + 中文错误 + token 401 钩子。

设计约束（千问 PDF2 §5 同款）：
1. 零第三方依赖，http.server.ThreadingHTTPServer；
2. 统一信封：{"ok": bool, "data": ..., "err": str|null, "ts": epoch}；
3. 错误一律中文可读；未知路径 404 也走信封；
4. 可配 token：请求头 X-Token 不符直接 401，不泄露任何数据；
5. 只读接口 —— 本模块没有任何写库路径（写走 cli）。
"""
from __future__ import annotations

import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .ontology import SKILLS

HEAD = {"Content-Type": "application/json; charset=utf-8",
        "Cache-Control": "no-store"}

# 国外渠道（greenhouse/lever）：默认所有视图与画像都不展示，显式传 source 才看得到
FOREIGN = ("greenhouse", "lever")


def _nm(cid: str) -> str:
    s = SKILLS.get(cid)
    return s["name"] if s else cid


def _env(ok: bool, data=None, err=None) -> dict:
    return {"ok": ok, "data": data, "err": err, "ts": int(time.time())}


class Api:
    def __init__(self, store, mine: list[str], token: str | None = None):
        self.store, self.mine, self.token = store, mine, token

    # ---- 数据面（全部走 store 的读方法，不碰 sqlite 细节） ----

    def stats(self, q=None) -> dict:
        return self.store.stats(exclude=FOREIGN)

    def jobs(self, q) -> dict:
        from .translate import display as zh_title
        source = q.get("source", [""])[0]
        family = q.get("family", [""])[0]
        title = q.get("q", [""])[0]
        limit = min(int(q.get("limit", ["50"])[0] or 50), 200)
        # 国外渠道默认不展示（用户明确不看）；显式传 source 才看得到
        exclude = None if source else FOREIGN
        items = self.store.jobs(source=source or None, family=family or None,
                                limit=limit, exclude=exclude,
                                title=title or None)
        sm = self.store.job_skills_map([it["id"] for it in items])
        names = sorted({it["company"] for it in items if it["company"]})
        sites = self.store.company_sites(names)
        for it in items:
            it["zh"] = zh_title(it.get("title", "") or "")
            it["skills"] = [_nm(c) for c in sm.get(it["id"], [])]
            it["site"] = sites.get(it["company"], "")
        return {"items": items}

    def graph(self, q) -> dict:
        source = q.get("source", [""])[0] or None
        top = min(int(q.get("top", ["15"])[0] or 15), 50)
        exclude = None if source else FOREIGN
        rows = self.store.skill_freq(source=source, limit=top, exclude=exclude)
        cooc = self.store.cooc(source=source, limit=12, exclude=exclude)
        for c in cooc:
            c["an"] = _nm(c["a"])
            c["bn"] = _nm(c["b"])
        return {"nodes": [{"cid": r["cid"], "name": _nm(r["cid"]), "n": r["n"]}
                          for r in rows],
                "cooc": cooc}

    def evidence(self, q) -> dict:
        cid = q.get("skill", [""])[0]
        if not cid:
            return {"items": [], "hint": "需要 ?skill=cid"}
        limit = min(int(q.get("limit", ["10"])[0] or 10), 50)
        return {"items": self.store.evidence(cid, limit=limit, exclude=FOREIGN)}

    def gap(self, q) -> dict:
        source = q.get("source", [""])[0] or None
        exclude = None if source else FOREIGN
        rows = self.store.skill_freq(source=source, limit=30, exclude=exclude)
        mine = set(self.mine)
        hot_lack = [{"cid": r["cid"], "name": _nm(r["cid"]), "n": r["n"]}
                    for r in rows if r["cid"] not in mine]
        have_hot = [{"cid": r["cid"], "name": _nm(r["cid"]), "n": r["n"], "rank": i + 1}
                    for i, r in enumerate(rows) if r["cid"] in mine]
        return {"hot_lack": hot_lack, "have_hot": have_hot,
                "coverage_top10": round(len(have_hot[:10]) / 10, 3) if len(rows) >= 10
                else round(len(have_hot) / max(len(rows), 1), 3)}

    def runs(self, q) -> dict:
        return {"items": self.store.runs(limit=min(int(q.get("limit", ["20"])[0] or 20), 100))}

    def profile(self, q) -> dict:
        from . import profile
        role = q.get("role", [""])[0]
        if not role:
            return {"markdown": "", "hint": "需要 ?role=岗位名，如 Java、AI+爬虫、Python+Java+agent"}
        easy = q.get("easy", ["0"])[0] in ("1", "true", "yes")
        spec = profile.parse_role(role)
        res = profile.query(self.store, spec, easy=easy, exclude=FOREIGN)
        mine_lv = self.store.mine() or {}
        md = profile.render(spec, res, mine_lv, easy, self.store)
        return {"role": role, "label": spec.get("label", role), "markdown": md}

    def projects(self, q) -> dict:
        cid = q.get("skill", [""])[0] or q.get("cid", [""])[0]
        if not cid:
            return {"items": [], "hint": "需要 ?skill=cid，如 crawl.http、lang.java"}
        return {"items": self.store.projects(cid)}

    def dispatch(self, path: str, q) -> dict:
        m = {"/api/stats": self.stats, "/api/jobs": self.jobs,
             "/api/graph": self.graph, "/api/evidence": self.evidence,
             "/api/gap": self.gap, "/api/runs": self.runs,
             "/api/profile": self.profile, "/api/projects": self.projects}
        f = m.get(path)
        if not f:
            return _env(False, err="未知接口：" + path)
        try:
            return _env(True, data=f(q))
        except Exception as e:  # 兜底：异常也走信封，绝不裸 500
            return _env(False, err="接口内部错误：" + str(e)[:200])


STATIC = {"/": "index.html", "/index.html": "index.html"}


def make_handler(api: Api, static_dir: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, body: dict, code: int = 200):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            for k, v in HEAD.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _send_static(self, name: str):
            if not static_dir:
                self._send(_env(False, err="静态目录未配置"), 404)
                return
            p = os.path.join(static_dir, name)
            if not os.path.isfile(p):
                self._send(_env(False, err="静态文件不存在：" + name), 404)
                return
            data = open(p, "rb").read()
            self.send_response(200)
            self.send_header("Content-Type",
                             "text/html; charset=utf-8" if name.endswith(".html")
                             else "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path in STATIC:  # 前端壳公开；数据接口才走 token
                self._send_static(STATIC[u.path])
                return
            if api.token and self.headers.get("X-Token") != api.token:
                self._send(_env(False, err="未授权：X-Token 缺失或不正确"), 401)
                return
            q = parse_qs(u.query)
            if u.path == "/healthz":
                self._send(_env(True, data={"status": "up"}))
                return
            self._send(api.dispatch(u.path, q))

        def log_message(self, *a):  # 静默访问日志，省存储
            pass

    return Handler


def serve(store, mine, port: int = 8770, token: str | None = None,
          static_dir: str | None = None):
    api = Api(store, mine, token)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(api, static_dir))
    srv.serve_forever()
