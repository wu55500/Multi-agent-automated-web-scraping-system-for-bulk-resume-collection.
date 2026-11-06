import json
import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dz import agg, classify, roles
from dz.barrier import detect as hard_detect
from dz.extract import _verified, _vote, extract_rule
from dz.forge import plan_projects, resume_bullets
from dz.ontology import canon, normalize
from dz.profile import parse_role, _trend_block
from dz.queue import Queue
from dz.schema import JD, Skill
from dz.score import evaluate
from dz.store import Store
from dz.translate import display as zh_title


class TestOntology(unittest.TestCase):
    def test_longest_alias_wins(self):
        self.assertEqual(canon("熟悉 ES6 与 Vue3"), "web.vue")
        self.assertEqual(canon("熟练使用 Pandas 做清洗"), "py.pandas")

    def test_short_ascii_needs_boundary(self):
        self.assertNotEqual(canon("处理 json 解析"), "lang.js")

    def test_normalize_fills_cid(self):
        skills = normalize([Skill(raw="熟悉 SQL"), Skill(raw="会点 Python")])
        self.assertEqual([s.cid for s in skills], ["db.sql", "lang.python"])


class TestEvidence(unittest.TestCase):
    def test_hallucinated_skill_dropped(self):
        raw = "要求：熟悉 Python 与 SQL。"
        out = _verified(raw, [
            {"raw": "Python", "evidence": "熟悉 Python", "confidence": 1},
            {"raw": "Kubernetes", "evidence": "熟练 Kubernetes 集群", "confidence": 1},
        ])
        self.assertEqual([s.raw for s in out], ["Python"])

    def test_empty_evidence_dropped(self):
        self.assertEqual(_verified("要求 Python", [{"raw": "Python", "evidence": ""}]), [])

    def test_vote_drops_minority(self):
        a = Skill(raw="SQL", evidence="熟悉 SQL")
        b = Skill(raw="Kotlin", evidence="熟悉 Kotlin")
        self.assertEqual([s.raw for s in _vote([[a], [a], [a, b]], keep=2)], ["SQL"])

    def test_rule_extract_finds_skills(self):
        raw = "任职要求：熟悉 Python、MySQL；了解 Playwright；会用 Git。"
        jd = extract_rule(raw)
        cids = {s.cid for s in jd.skills}
        self.assertTrue({"lang.python", "db.sql", "auto.browser", "tool.git"} <= cids)
        self.assertEqual(jd.engine, "rule")


class TestScore(unittest.TestCase):
    def test_coverage_monotonic(self):
        skills = [Skill(raw="SQL", cid="db.sql"), Skill(raw="A/B", cid="stat.ab", must=False)]
        low = evaluate(skills, {"db.sql": 0})
        high = evaluate(skills, {"db.sql": 3, "stat.ab": 3})
        self.assertEqual(low["coverage"], 0.0)
        self.assertGreater(high["coverage"], 0.99)

    def test_must_outweighs_nice(self):
        skills = [Skill(raw="SQL", cid="db.sql", must=True),
                  Skill(raw="Excel", cid="bi.excel", must=False)]
        r = evaluate(skills, {"bi.excel": 3})
        self.assertLess(r["coverage"], 0.5)

    def test_unresolved_goes_to_unknown(self):
        r = evaluate([Skill(raw="量子计算")], {})
        self.assertEqual(r["unknown"], ["量子计算"])
        self.assertEqual(r["coverage"], 0.0)


class TestForge(unittest.TestCase):
    def test_plan_covers_most_weight_per_hour(self):
        gaps = [{"cid": c, "w": 1.0} for c in ("stat.ab", "db.sql", "py.pandas")]
        plan = plan_projects(gaps, budget_hours=8)
        self.assertTrue(plan["projects"])
        self.assertEqual(plan["projects"][0]["cid"], "data.ab")
        self.assertLessEqual(plan["hours"], 8)

    def test_resume_refuses_without_material(self):
        skills = [Skill(raw="SQL", cid="db.sql", evidence="熟悉 SQL")]
        out = resume_bullets(skills, {"db.sql": 3}, {})
        self.assertEqual(out["ready"], [])
        self.assertEqual(out["refused"][0]["cid"], "db.sql")


class TestQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.store = Store(self.tmp.name)

    def tearDown(self):
        os.unlink(self.tmp.name)

    def test_idempotent_enqueue(self):
        q = Queue(self.store)
        self.assertTrue(q.enqueue("a" * 8, 0.6))
        self.assertFalse(q.enqueue("a" * 8, 0.9))

    def test_daily_cap(self):
        q = Queue(self.store, daily_cap=3)
        for i in range(10):
            q.enqueue("job%d" % i, 0.5)
        got = [q.claim() for _ in range(5)]
        self.assertEqual(sum(1 for g in got if g), 3)

    def test_retry_then_dead(self):
        q = Queue(self.store)
        q.enqueue("b" * 8, 0.5)
        q.claim()
        for _ in range(5):
            q.fail("b" * 8, "boom")
        state = self.store.db.execute(
            "select state from apps where job_id=?", ("b" * 8,)).fetchone()[0]
        self.assertEqual(state, "dead")


class TestClassify(unittest.TestCase):
    def test_city_from_raw(self):
        self.assertEqual(classify.city("工作地点：杭州西湖区"), "杭州")
        self.assertEqual(classify.city("工作地点：杭州", "上海"), "上海")
        self.assertEqual(classify.city("没写城市"), "其他")

    def test_size_heuristics(self):
        self.assertEqual(classify.size("字节跳动", ""), "大厂")
        self.assertEqual(classify.size("某科技有限公司", ""), "中厂")
        self.assertEqual(classify.size("独立工作室", "初创 8 人"), "小厂")
        self.assertEqual(classify.size("张三工作室", "", "小厂"), "小厂")

    def test_agent_level(self):
        strong = "岗位职责：做平台。\n任职要求：\n1. 熟悉 LLM 应用开发；\n2. 有 Agent 经验。"
        weak = "我们团队在做 AI 笔记工具。\n任职要求：\n1. 熟悉 Vue3。"
        none = "任职要求：\n1. 熟悉 SQL。"
        self.assertEqual(classify.agent_level(strong), 2)
        self.assertEqual(classify.agent_level(weak), 1)
        self.assertEqual(classify.agent_level(none), 0)


class TestRoles(unittest.TestCase):
    def test_detect_each_family(self):
        cases = {
            "Agent 应用开发工程师": "agent",
            "AI 应用开发": "ai_app",
            "AI 全栈开发 FDE": "fde",
            "爬虫工程师": "crawl",
            "大数据开发工程师": "bigdata",
            "SRE 工程师": "ops",
            "测试开发工程师": "test",
        }
        for title, want in cases.items():
            self.assertEqual(roles.detect(title, title), want, title)

    def test_title_beats_body(self):
        # 标题说爬虫，正文提了一嘴数仓，仍然归爬虫
        self.assertEqual(roles.detect("爬虫工程师", "爬虫工程师\n熟悉数仓 spark"), "crawl")

    def test_body_needs_two_hits(self):
        # 正文只出现一次「数仓」不足以归类（数据分析师不该漂到大数据）
        self.assertEqual(roles.detect("数据分析师", "任职要求：\n了解数仓"), "")

    def test_ai_plus_split(self):
        self.assertEqual(classify.family("任职要求：\n1. 熟悉 pytest 与大模型评测", "AI 测试工程师"),
                         "test+ai")
        self.assertEqual(classify.family("任职要求：\n1. 熟悉 pytest", "测试开发工程师"), "test")
        self.assertEqual(classify.family("任职要求：\n熟悉 scrapy 反爬", "爬虫工程师"), "crawl")
        self.assertEqual(classify.family("任职要求：\n熟悉 scrapy，了解大模型抽取", "爬虫工程师"),
                         "crawl+ai")

    def test_label_of(self):
        self.assertEqual(roles.label_of("crawl+ai"), "AI + 数据采集")
        self.assertEqual(roles.label_of("crawl"), "爬虫 / 数据采集")
        self.assertEqual(roles.label_of(""), "未归类")


class TestStoreMigration(unittest.TestCase):
    def test_old_tags_table_gets_family_column(self):
        import sqlite3
        d = tempfile.mkdtemp()
        p = os.path.join(d, "old.db")
        db = sqlite3.connect(p)
        db.executescript("create table tags(job_id text primary key, city text,"
                         " size text, agent_level int, ts real);")
        db.commit()
        db.close()
        s = Store(p)
        s.put_tag({"job_id": "j1", "city": "北京", "size": "大厂",
                   "agent_level": 2, "family": "crawl+ai"})
        self.assertEqual(s.tags()["j1"]["family"], "crawl+ai")


class TestAgg(unittest.TestCase):
    def _rec(self, city, size, agent, cids, cov=0.5):
        return {"job": {"id": "x", "engine": "rule"},
                "skills": [{"cid": c} for c in cids],
                "tag": {"city": city, "size": size, "agent_level": agent},
                "coverage": cov}

    def test_summary_counts(self):
        recs = [self._rec("北京", "大厂", 2, ["db.sql"]),
                self._rec("杭州", "中厂", 0, ["db.sql", "lang.python"], 0.8)]
        s = agg.summary(recs)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["agent_required"], 1)
        city = {r["key"]: r for r in s["by_city"]}
        self.assertEqual(city["北京"]["n"], 1)
        self.assertEqual(city["杭州"]["coverage"], 0.8)

    def test_matrix_cell_pct(self):
        recs = [self._rec("北京", "大厂", 2, ["db.sql"]),
                self._rec("北京", "中厂", 0, ["lang.python"])]
        s = agg.summary(recs)
        row = next(r for r in s["matrix"]["rows"] if r["cid"] == "db.sql")
        beijing = next(c for c in row["cells"]["城市"] if c["k"] == "北京")
        self.assertEqual(beijing["pct"], 50.0)

    def test_markdown_has_three_axes(self):
        md = agg.to_markdown(agg.summary([self._rec("北京", "大厂", 2, ["db.sql"])]))
        for kw in ("按地域", "按公司规模", "按 agent 要求", "交叉表"):
            self.assertIn(kw, md)

    def test_family_blocks(self):
        recs = [self._rec("北京", "大厂", 2, ["db.sql"]),
                self._rec("上海", "中厂", 0, ["lang.python"], 0.9)]
        recs[0]["tag"]["family"] = "agent"
        recs[1]["tag"]["family"] = "crawl"
        fams = agg.family_blocks(recs)
        keys = [f["key"] for f in fams]
        self.assertIn("Agent 应用开发", keys)
        self.assertIn("爬虫 / 数据采集", keys)
        agent = next(f for f in fams if f["key"] == "Agent 应用开发")
        self.assertEqual(agent["n"], 1)
        self.assertEqual(agent["agent_ratio"], 1.0)
        dims = {d["dim"] for d in agent["detail"]}
        self.assertEqual(dims, {"地域", "规模", "agent"})

    def test_markdown_has_family_section(self):
        recs = [self._rec("北京", "大厂", 2, ["db.sql"])]
        recs[0]["tag"]["family"] = "test+ai"
        md = agg.to_markdown(agg.summary(recs))
        self.assertIn("按岗位族", md)
        self.assertIn("AI + 测试", md)


class TestRealData(unittest.TestCase):
    def test_auto_lex_covers_ontology(self):
        jd = extract_rule("任职要求：熟悉 Kubernetes、Golang、影刀。")
        self.assertEqual({s.cid for s in jd.skills},
                         {"tool.docker", "lang.go", "auto.rpa"})

    def test_auto_lex_short_boundary(self):
        jd = extract_rule("任职要求：输出 json 文件")
        self.assertNotIn("lang.js", {s.cid for s in jd.skills})

    def test_size_scale_column(self):
        self.assertEqual(classify.size("某公司", "", "20-99人"), "小厂")
        self.assertEqual(classify.size("某公司", "", "500-999人"), "中厂")
        self.assertEqual(classify.size("某公司", "", "1000-9999人"), "大厂")
        self.assertEqual(classify.size("某公司", "", "10000人以上"), "大厂")


class TestCliImportPack(unittest.TestCase):
    def test_import_appends_jsonl(self):
        from dz import cli as cli_mod
        tmp = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        tmp.close()
        try:
            args = types.SimpleNamespace(text="任职要求：熟悉 Python", title="爬虫工程师",
                                         company="A", city="北京", salary="20k",
                                         csv=None, out=tmp.name)
            self.assertEqual(cli_mod.cmd_import(args), 0)
            with open(tmp.name, encoding="utf-8") as f:
                row = json.loads(f.read().strip())
            self.assertEqual(row["source"], "user")
            self.assertEqual(row["title"], "爬虫工程师")
        finally:
            os.unlink(tmp.name)

    def test_pack_writes_card(self):
        from dz import cli as cli_mod
        d = tempfile.mkdtemp()
        dbp = os.path.join(d, "t.db")
        store = Store(dbp)
        jd = JD(source="paste", title="爬虫工程师",
                raw="任职要求：" + chr(10) + "熟悉 Python",
                company="A公司", city="杭州", salary="15-25K",
                skills=[Skill(raw="Python", cid="lang.python", must=True,
                              evidence="熟悉 Python")])
        store.put_job(jd)
        try:
            args = types.SimpleNamespace(job=jd.id, db=dbp)
            self.assertEqual(cli_mod.cmd_pack(args), 0)
            path = os.path.join(cli_mod.ROOT, "reports", "pack_%s.md" % jd.id[:8])
            self.assertTrue(os.path.exists(path))
            with open(path, encoding="utf-8") as f:
                self.assertIn("投递卡", f.read())
            os.unlink(path)
        finally:
            os.unlink(dbp)


class TestLever(unittest.TestCase):
    def _post(self):
        return {
            "id": "abc123", "text": "Senior Backend Engineer, Spotify Technology",
            "hostedUrl": "https://jobs.lever.co/spotify/abc123",
            "applyUrl": "https://jobs.lever.co/spotify/abc123/apply",
            "categories": {"team": "Engineering", "location": "Stockholm, Sweden"},
            "descriptionPlain": "Spotify is hiring a backend engineer.",
            "descriptionBodyPlain": "You will design APIs.",
            "additionalPlain": "",
            "lists": [{"text": "Who You Are",
                      "content": "<li>Strong Python and SQL skills.</li><li>Experience with Kubernetes and AWS required.</li>"}],
            "salaryRange": {"min": 100000, "max": 140000, "currency": "SEK", "interval": "per-year"},
        }

    def test_row_fields(self):
        from dz.collect import lever_row
        row = lever_row(self._post())
        self.assertIn("Kubernetes", row["raw"])
        self.assertIn("Strong Python", row["raw"])
        self.assertEqual(row["title"], "Senior Backend Engineer")
        self.assertEqual(row["city"], "Stockholm, Sweden")
        self.assertEqual(row["salary"], "100000-140000 SEK/per-year")
        self.assertEqual(row["url"], "https://jobs.lever.co/spotify/abc123")

    def test_no_salary(self):
        from dz.collect import lever_row
        p = self._post()
        p.pop("salaryRange")
        self.assertEqual(lever_row(p)["salary"], "")

    def test_short_raw_skipped(self):
        import tempfile
        from dz.store import Store
        from dz import collect
        p = self._post()
        p["descriptionPlain"] = "Too short."
        p["descriptionBodyPlain"] = ""
        with tempfile.TemporaryDirectory() as d:
            dbp = os.path.join(d, "t.db")
            store = Store(dbp)
            collect._get_json = lambda *a, **k: [p]
            collect.robots_ok = lambda *a, **k: True
            r = collect.collect_lever(store, "spotify", tech_only=True)
            self.assertEqual(r["stored"], 0)
            self.assertEqual(r["skipped_short"], 1)


class TestBarrier(unittest.TestCase):
    def test_degree_zh(self):
        h, why = hard_detect("任职要求：硕士及以上学历，3 年经验")
        self.assertTrue(h)
        self.assertIn("硕士", why)

    def test_985_boundary(self):
        self.assertTrue(hard_detect("要求 985/211 本科")[0])
        # 数字内嵌不算：职位编号 1521100 之类
        self.assertFalse(hard_detect("编号 152110 岗位招聘")[0])

    def test_ascii_word_boundary(self):
        # noise 含 noi、acme 含 acm：词边界必须挡住
        self.assertFalse(hard_detect("Reduce noise in pipeline with ACME tools")[0])
        self.assertTrue(hard_detect("PhD or Master's degree required")[0])

    def test_clean_jd_not_hard(self):
        h, why = hard_detect("本科及以上，熟悉 Python 与 SQL，负责后端开发。")
        self.assertFalse(h)
        self.assertEqual(why, "")


class TestTranslate(unittest.TestCase):
    def test_en_to_zh(self):
        self.assertIn("软件工程师", zh_title("Staff Software Engineer, Backend"))
        self.assertIn("数据科学家", zh_title("Senior Data Scientist"))

    def test_zh_kept_no_en_tag(self):
        self.assertNotIn("[EN]", zh_title("java开发工程师，应届生亦可培养"))

    def test_unknown_en_tagged(self):
        self.assertIn("[EN]", zh_title("Anthropic Research Resident"))


class TestProfileParse(unittest.TestCase):
    def test_family_plus_ai(self):
        s = parse_role("AI+爬虫")
        self.assertEqual(s["family"], "crawl")
        self.assertTrue(s["ai"])

    def test_skill_keywords(self):
        s = parse_role("Python+Java+agent")
        self.assertEqual(set(s["skills"]), {"lang.python", "lang.java"})
        self.assertEqual(s["family"], "agent")

    def test_title_fallback(self):
        s = parse_role("嵌入式")
        self.assertEqual(s["kws"], ["嵌入式"])
        self.assertEqual(s["skills"], [])

    def test_agent_era_aliases(self):
        from dz.ontology import canon
        self.assertEqual(canon("langgraph"), "nlp.llm")
        self.assertEqual(canon("mcp"), "nlp.llm")
        self.assertEqual(canon("function calling"), "nlp.llm")
        self.assertEqual(canon("n8n"), "auto.rpa")

    def test_trend_block_only_for_ai(self):
        s = parse_role("AI+爬虫")
        self.assertTrue(s["ai"])
        L = _trend_block(s, None)
        self.assertTrue(any("Agent 时代增量" in x for x in L))
        s2 = parse_role("Java")
        self.assertFalse(_trend_block(s2, None))


class TestOpenSrc(unittest.TestCase):
    def test_usage_lines_skip_urls(self):
        from dz.opensrc import _usage_lines, _pat
        md = "\n".join([
            "# Title",
            ".. |logo| image:: https://raw.githubusercontent.com/scrapy/scrapy/master/logo.svg",
            "Scrapy is a fast high-level web crawling framework used for crawling websites.",
            "[![badge](https://img.shields.io/badge/x)]",
            "pip install scrapy",
        ])
        hits = _usage_lines(md, _pat("crawl.http"))
        self.assertFalse(any("raw.githubusercontent" in h for h in hits))
        self.assertTrue(any("high-level web crawling" in h for h in hits))

    def test_intro_skips_toc_badges(self):
        from dz.opensrc import _intro
        md = ("# X\n\n"
              "[Installation](#installation) | [Run](#run)\n\n"
              "[![badge](https://img.shields.io/badge/x)]\n\n"
              "A distributed crawler platform built with Python.\n\n"
              "## Install\n...")
        title, intro = _intro(md)
        self.assertEqual(title, "X")
        self.assertIn("distributed crawler", intro)

    def test_pick_prefers_src(self):
        from dz.opensrc import _pick, _pat
        paths = [".gitignore", "docs/guide.md", "scrapy/commands/crawl.py",
                 "scrapy/spiders/__init__.py", "README.md"]
        got = _pick(paths, _pat("crawl.http"))
        self.assertTrue(any("crawl.py" in p for p in got))
        self.assertFalse(any(p == ".gitignore" for p in got))


class TestBarriersStore(unittest.TestCase):
    def test_roundtrip(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "t.db"))
            store.put_barrier("j1", True, "要求学历：硕士")
            store.put_barrier("j2", False)
            b = store.barriers()
            self.assertTrue(b["j1"]["hard"])
            self.assertEqual(b["j1"]["why"], "要求学历：硕士")
            self.assertFalse(b["j2"]["hard"])


class TestForeignExclude(unittest.TestCase):
    def _mk(self, jid, title, source):
        from types import SimpleNamespace
        return SimpleNamespace(id=jid, title=title, company="C", city="深圳",
                               salary="", seniority="", engine="", source=source,
                               source_url="", raw="", ts=1, skills=[])

    def test_jobs_exclude_foreign(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            store = Store(os.path.join(d, "t.db"))
            store.put_job(self._mk("j1", "Java 开发工程师", "boss-longgang-2026-08"))
            store.put_job(self._mk("j2", "Software Engineer", "greenhouse"))
            rows = store.jobs(exclude=("greenhouse", "lever"))
            self.assertEqual([r["id"] for r in rows], ["j1"])
            rows2 = store.jobs(source="greenhouse")
            self.assertEqual([r["id"] for r in rows2], ["j2"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
