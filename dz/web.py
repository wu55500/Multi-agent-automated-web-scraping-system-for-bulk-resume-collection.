"""本地看板：stdlib http.server，零依赖，手机浏览器打开 127.0.0.1:8787 就能看。"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

from .agg import summary, to_markdown
from .classify import AGENT_LABEL
from .score import evaluate

PAGE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>招聘技术要求总表</title>
<style>
:root{--bg:#faf7f1;--card:#fff;--ink:#2b2620;--ink2:#6d6458;--line:#e8e0d2;--acc:#3a7d5c}
@media(prefers-color-scheme:dark){:root{--bg:#171512;--card:#211d19;--ink:#ece5da;--ink2:#a49a8b;--line:#332d26;--acc:#7fbb98}}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,"PingFang SC",system-ui,sans-serif}
h1{font-size:19px;margin:0 0 4px}h2{font-size:15px;margin:24px 0 8px;color:var(--acc)}
h3{font-size:13px;margin:18px 0 4px;color:var(--ink)}
.sub{color:var(--ink2);font-size:12px;margin-bottom:8px}
table{width:100%;border-collapse:collapse;background:var(--card);font-size:12px;
margin-bottom:8px;border:1px solid var(--line);border-radius:8px;overflow:hidden}
th,td{padding:7px 8px;text-align:left;border-bottom:1px solid var(--line)}
th{background:color-mix(in srgb,var(--acc) 12%,transparent);font-weight:600}
td.h{font-variant-numeric:tabular-nums;text-align:right;color:var(--ink2)}
tr:last-child td{border-bottom:0}
.wrap{overflow-x:auto}
code{font-size:11px;color:var(--ink2)}
</style></head><body>
<h1>招聘技术要求总表</h1>
<div class="sub">地域 / 规模 / agent 三维交叉 · 数据来自本地库（示例 + 真实导入）</div>
<div id="app"></div>
<script>
const D = __DATA__;
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function groupBox(title, rows){
  let h = '<h2>'+title+'</h2><div class="wrap"><table><tr><th>分组</th><th>岗位</th>'+
          '<th>平均覆盖</th><th>要求 agent</th><th>出现最多的技术栈</th></tr>';
  for(const r of rows){
    h += '<tr><td>'+esc(r.key)+'</td><td class="h">'+r.n+'</td><td class="h">'+
         Math.round(r.coverage*100)+'%</td><td class="h">'+Math.round(r.agent_ratio*100)+
         '%</td><td>'+r.top.map(t=>esc(t[0])+'<code> '+t[2]+'</code>').join('、')+'</td></tr>';
  }
  return h + '</table></div>';
}
function familyBox(f){
  let h = '<h3>'+esc(f.key)+' <code>'+f.n+' 条</code></h3>'+
          '<div class="sub">平均覆盖 <b>'+Math.round(f.coverage*100)+'%</b> · 明确要求 agent <b>'+
          Math.round(f.agent_ratio*100)+'%</b> · 最常见：'+
          f.top.map(t=>esc(t[0])+'<code> '+t[2]+'</code>').join('、')+'</div>';
  h += '<div class="wrap"><table><tr><th>维度</th><th>分组</th><th>岗位</th>'+
       '<th>覆盖</th><th>agent</th><th>技术栈</th></tr>';
  for(const d of f.detail){
    h += '<tr><td>'+esc(d.dim)+'</td><td>'+esc(d.k)+'</td><td class="h">'+d.n+
         '</td><td class="h">'+Math.round(d.coverage*100)+'%</td><td class="h">'+
         Math.round(d.agent_ratio*100)+'%</td><td>'+
         d.top.map(t=>esc(t[0])+'<code> '+t[2]+'</code>').join('、')+'</td></tr>';
  }
  return h + '</table></div>';
}
function matrixBox(m){
  let h = '<h2>技术栈 × 分组 交叉表</h2><div class="wrap"><table><tr><th>技能</th>';
  for(const k in m.cols) for(const c of m.cols[k]) h += '<th>'+esc(c)+'</th>';
  h += '</tr>';
  for(const row of m.rows){
    h += '<tr><td>'+esc(row.skill)+'</td>';
    for(const k in m.cols) for(const c of row.cells[k])
      h += '<td class="h">'+(c.n? c.pct+'%' : '-')+'</td>';
    h += '</tr>';
  }
  return h + '</table></div>';
}
const srcs = D.sources ? Object.entries(D.sources).map(e=>esc(e[0])+' '+e[1]).join('、') : '';
let h = '<div class="sub">样本 <b>'+D.total+'</b> 条 · 平均覆盖 <b>'+
        Math.round(D.avg_coverage*100)+'%</b> · 明确要求 agent/LLM <b>'+
        D.agent_required+'</b> 条'+(srcs? ' · 来源 '+srcs : '')+'</div>';
h += groupBox('按地域', D.by_city) + groupBox('按公司规模', D.by_size) +
     groupBox('按 agent 要求', D.by_agent);
if(D.by_family && D.by_family.length){
  h += '<h2>按岗位族（8 个方向）</h2>';
  for(const f of D.by_family) h += familyBox(f);
}
h += matrixBox(D.matrix);
document.getElementById('app').innerHTML = h;
</script></body></html>"""


def records(store, mine: dict) -> list[dict]:
    tags = store.tags()
    out = []
    for job in store.jobs(limit=2000):
        sk = store.job_skills(job["id"])
        t = tags.get(job["id"]) or {"city": "其他", "size": "未知", "agent_level": 0}
        out.append({"job": job, "skills": sk, "tag": t,
                    "coverage": evaluate(_as_skills(sk), mine)["coverage"]})
    return out


def _as_skills(rows):
    from .schema import Skill
    return [Skill(raw=r["raw"], cid=r["cid"], must=bool(r["must"]),
                  years=r["years"], evidence=r["evidence"], confidence=r["conf"])
            for r in rows]


def _html(store, mine) -> bytes:
    s = summary(records(store, mine))
    return PAGE.replace("__DATA__", json.dumps(s, ensure_ascii=False)).encode()


def serve(store, mine, port: int = 8787):
    class H(BaseHTTPRequestHandler):
        def _send(self, code, body: bytes, ctype: str):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            try:
                if self.path in ("/", "/index.html"):
                    self._send(200, _html(store, mine), "text/html; charset=utf-8")
                elif self.path == "/api/summary":
                    body = json.dumps(summary(records(store, mine)),
                                      ensure_ascii=False, indent=2).encode()
                    self._send(200, body, "application/json; charset=utf-8")
                elif self.path in ("/report", "/report.md"):
                    body = to_markdown(summary(records(store, mine))).encode()
                    self._send(200, body, "text/markdown; charset=utf-8")
                else:
                    self._send(404, b"not found", "text/plain")
            except Exception as e:  # 别让看板因为一条脏数据挂掉
                self._send(500, str(e).encode(), "text/plain; charset=utf-8")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", port), H)  # 单线程：sqlite 连接不能跨线程
    print("看板: http://127.0.0.1:%d/   JSON: /api/summary   报告: /report" % port)
    srv.serve_forever()
