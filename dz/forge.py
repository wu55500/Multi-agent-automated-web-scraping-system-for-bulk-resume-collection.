"""对证下药：把缺口编译成"周末能做出来、能被面试官追问"的最小项目 + 简历措辞。

两个算法：
- plan_projects：带权集合覆盖的贪心，每小时预算买到最多缺口权重；
- resume_bullets：证据绑定，没真实材料直接拒绝写，不给编造留口子。
"""
from __future__ import annotations

PROJECTS: dict[str, dict] = {
    "data.ab": {"title": "优惠券策略 A/B 实验", "hours": 8,
                "covers": ["stat.ab", "db.sql", "py.pandas"],
                "artifacts": ["sql/ 里 5 条窗口函数查询", "ab_test.ipynb（样本量+t 检验+置信区间）",
                              "一页结论：这个策略该不该上，为什么"],
                "追问点": "样本量怎么定的？两组方差不等怎么办？"},
    "crawl.watch": {"title": "公开岗位数据监控", "hours": 10,
                    "covers": ["crawl.http", "db.sql", "tool.git"],
                    "artifacts": ["httpx+重试+缓存，只碰 robots 允许的页面",
                                  "SQLite 落库 + 每日去重（哈希主键）", "一条 cron + Markdown 日报"],
                    "追问点": "重复抓怎么去重？对方改版你怎么知道挂了？"},
    "bi.dash": {"title": "经营看板（6 个指标）", "hours": 6,
                "covers": ["bi.tableau", "bi.excel", "db.sql"],
                "artifacts": ["清洗后的宽表", "看板：GMV/客单/复购/退款率/新客成本/留存"],
                "追问点": "口径怎么和财务对齐？异常值怎么处理？"},
    "web.mini": {"title": "极简笔记站（单文件后端）", "hours": 12,
                 "covers": ["web.vue", "lang.js", "web.html", "net.http"],
                 "artifacts": ["Vue3 + 手写 CSS 变量，无 UI 库", "SQLite + 5 个 REST 端点",
                               "只读分享链接 /s/token"],
                 "追问点": "为什么不用路由库？分享链接怎么防遍历？"},
    "auto.form": {"title": "半自动投递助手（人点提交）", "hours": 8,
                  "covers": ["auto.browser", "net.http", "lang.python", "auto.rpa"],
                  "artifacts": ["Playwright 复用已登录 profile，只 fill 不 submit",
                                "队列 + 每日上限 + 状态机", "操作审计日志"],
                  "追问点": "怎么保证不重复投？限速放哪一层？"},
    "ml.churn": {"title": "流失预测（含校准）", "hours": 10,
                 "covers": ["ml.sklearn", "py.pandas", "stat.basic"],
                 "artifacts": ["特征表 + 基线逻辑回归 + 树模型", "ROC/PR + 概率校准曲线",
                               "阈值-成本曲线：为什么选这个阈值"],
                 "追问点": "类别不平衡怎么处理？为什么不用准确率？"},
    "llm.rag": {"title": "简历-岗位检索助教", "hours": 12,
                "covers": ["nlp.llm", "py.pandas", "crawl.http"],
                "artifacts": ["BM25 + 向量混合召回", "提示词模板 + 结构化输出约束",
                              "评测集 30 条 + 命中率/幻觉率"],
                "追问点": "怎么防幻觉？为什么召回要混合？"},
    "ops.pipe": {"title": "一条带测试的 CI 流水线", "hours": 6,
                 "covers": ["ops.ci", "tool.git", "tool.linux"],
                 "artifacts": ["pytest + lint + 构建三阶段", "失败自动发通知", "构建缓存命中率"],
                 "追问点": "怎么让流水线 3 分钟内跑完？"},
    "docker.serve": {"title": "容器化上线一个小服务", "hours": 6,
                     "covers": ["tool.docker", "tool.linux", "cloud.basic"],
                     "artifacts": ["多阶段 Dockerfile（镜像 < 100MB）", "Caddy 反代 + 自动证书",
                                   "healthcheck + 一条告警"],
                     "追问点": "多阶段构建省在哪？健康检查为什么用这个端点？"},
}


def plan_projects(gaps: list[dict], budget_hours: float = 24) -> dict:
    need = {g["cid"]: g["w"] for g in gaps}
    picked, spent, covered = [], 0.0, set()
    while True:
        best = None
        for cid, spec in PROJECTS.items():
            gain = sum(need[c] for c in spec["covers"] if c in need and c not in covered)
            if gain <= 1e-9:
                continue
            eff = gain / spec["hours"]
            if best is None or eff > best[0]:
                best = (eff, cid, gain)
        if not best:
            break
        cid, gain = best[1], best[2]
        if spent + PROJECTS[cid]["hours"] > budget_hours:
            break
        spec = dict(PROJECTS[cid])
        spec["cid"], spec["gain"] = cid, round(gain, 2)
        picked.append(spec)
        spent += spec["hours"]
        covered |= {c for c in spec["covers"] if c in need}
    left = [g for g in gaps if g["cid"] not in covered]
    return {"projects": picked, "hours": spent, "left": left,
            "covered": sorted(covered)}


def resume_bullets(skills, mine: dict, notes: dict) -> dict:
    ok, blocked = [], []
    for s in skills:
        if not s.cid or int(mine.get(s.cid, 0)) < 2:
            continue
        note = (notes.get(s.cid) or "").strip()
        if not note or not s.evidence:
            blocked.append({"cid": s.cid, "reason": "没有真实材料，禁止编造"})
            continue
        ok.append({"cid": s.cid, "bullet": note,
                   "bound_to": s.evidence[:40], "job_words": s.raw})
    return {"ready": ok, "refused": blocked}
