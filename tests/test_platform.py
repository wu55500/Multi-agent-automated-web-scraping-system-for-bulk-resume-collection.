import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from dz.platform.store import Store,digest,dumps
from dz.platform.api import handler
from dz.platform.network import Client,validate_url
from dz.platform.adapters import collect,jsonld
from dz.adapters.rss import parse
from dz.platform.submit import send
from dz.platform.agents import analyze,reply
from dz.platform.migration import migrate


def row(id='1',**kw):
    return dict({'id':id,'title':'Python engineer','raw':'要求熟悉 Python 与 SQL。','company':'Acme','city':'上海','source_url':'https://example.com/job'},**kw)


class PlatformTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.s=Store(self.tmp.name)
        self.s.register('a','json',quota=100,consent='test authorization',compliance='approved',interval=0)
        self.s.register('b','json',quota=100,consent='test authorization',compliance='approved',interval=0)
    def tearDown(self): self.s.close(); self.tmp.cleanup()
    def test_requires_source(self):
        with self.assertRaises(ValueError): self.s.ingest('missing',[row()])
    def test_requires_consent(self):
        with self.assertRaises(ValueError): self.s.register('bad','json')
    def test_partner_requires_contract(self):
        with self.assertRaises(ValueError): self.s.register('bad','partner',consent='yes',compliance='approved')
    def test_source_disabled(self):
        self.s.enable('a',False)
        with self.assertRaises(PermissionError): self.s.ingest('a',[row()])
    def test_quota_atomic(self):
        self.s.db.execute('UPDATE dim_source SET quota=1 WHERE id="a"')
        with self.assertRaises(PermissionError): self.s.ingest('a',[row(),row('2')])
        self.assertFalse(self.s.jobs())
        self.s.ingest('a',[row()])
        with self.assertRaises(PermissionError): self.s.ingest('a',[row('2')])
    def test_invalid_batch_no_partial_write(self):
        with self.assertRaises(ValueError): self.s.ingest('a',[row(),{'id':'2'}])
        self.assertFalse(self.s.jobs())
    def test_duplicate_idempotence(self):
        self.s.ingest('a',[row()]); self.s.ingest('a',[row()])
        self.assertEqual(len(self.s.rows('SELECT * FROM versions')),1)
    def test_history(self):
        self.s.ingest('a',[row()]); self.s.ingest('a',[row(raw='要求 Python 和 Docker')])
        self.assertEqual(len(self.s.rows('SELECT * FROM versions')),2)
    def test_history_immutable(self):
        self.s.ingest('a',[row()])
        with self.assertRaises(sqlite3.IntegrityError): self.s.db.execute('DELETE FROM versions')
    def test_exact_merge_and_evidence(self):
        self.s.ingest('a',[row()]); self.s.ingest('b',[row('other')])
        self.assertEqual(len({r['canonical_id'] for r in self.s.jobs()}),1)
        for e in self.s.rows('SELECT * FROM evidence'):
            self.assertEqual(row()['raw'][e['start']:e['end']],e['text'])
    def test_fuzzy_not_silent(self):
        self.s.ingest('a',[row()]); self.s.ingest('b',[row(raw='熟悉 Python')])
        self.assertEqual(len(self.s.candidates()),1)
        self.assertEqual(len({r['canonical_id'] for r in self.s.jobs()}),2)
    def test_merge_audited(self):
        self.s.ingest('a',[row()]); self.s.ingest('b',[row(raw='熟悉 Python')])
        jobs=self.s.jobs(); self.s.merge(jobs[0]['id'],jobs[1]['id'],'same employer requisition verified')
        self.assertEqual(len({r['canonical_id'] for r in self.s.jobs()}),1)
        self.assertTrue(self.s.verify_audit()['ok'])
    def test_zero_overlap_no_estimate(self):
        self.s.ingest('a',[row()]); self.s.ingest('b',[row(company='Other')])
        r=self.s.coverage('a','b',assumptions=True)
        self.assertEqual(r['observed_unique'],2); self.assertIsNone(r['estimate'])
    def test_conditional_coverage(self):
        self.s.ingest('a',[row(),row('2',company='B')]); self.s.ingest('b',[row(),row('3',company='C')])
        self.assertIsNone(self.s.coverage('a','b')['estimate'])
        r=self.s.coverage('a','b',assumptions=True)
        self.assertEqual(r['estimate'],3.5); self.assertEqual(r['overlap'],1)
    def test_audit_immutable(self):
        with self.assertRaises(sqlite3.IntegrityError): self.s.db.execute('UPDATE audit SET payload="x"')
        with self.assertRaises(sqlite3.IntegrityError): self.s.db.execute('DELETE FROM audit')
        self.assertTrue(self.s.verify_audit()['ok'])
    def test_tenant_isolation(self):
        self.s.ingest('a',[row()]); other=Store(self.tmp.name,'other')
        self.assertFalse(other.jobs()); other.close()
    def test_tenant_path_traversal(self):
        with self.assertRaises(ValueError): Store(self.tmp.name,'../escape')
    def test_daily_health(self):
        for code in (200,429,403): self.s.event('a',code,'http')
        self.s.event('a',200,'captcha')
        r=self.s.rows('SELECT * FROM ods_crawl_health')[0]
        self.assertEqual((r['rate_limited'],r['blocked'],r['captcha_cnt']),(1,1,1))
    def app(self):
        self.s.ingest('a',[row()]); return self.s.prepare_application(self.s.jobs()[0]['id'],{'facts':[{'text':'Built a Python API','evidence':'portfolio/project-1'}]})['id']
    def approve(self,aid):
        rh=self.s.db.execute('SELECT resume_hash FROM applications WHERE id=?',(aid,)).fetchone()[0]
        self.s.approve(aid,rh)
    def test_requires_evidence(self):
        self.s.ingest('a',[row()])
        with self.assertRaises(ValueError): self.s.prepare_application(self.s.jobs()[0]['id'],{'facts':[{'text':'invented'}]})
    def test_no_unapproved_claim(self):
        aid=self.app()
        with self.assertRaises(PermissionError): self.s.claim_application(aid)
    def test_stale_approval(self):
        aid=self.app(); self.approve(aid); self.s.ingest('a',[row(raw='changed requirements')])
        with self.assertRaises(PermissionError): self.s.claim_application(aid)
    def test_expired_approval(self):
        aid=self.app(); self.approve(aid); self.s.db.execute('UPDATE applications SET approved_until=0')
        with self.assertRaises(PermissionError): self.s.claim_application(aid)
    def test_claim_once(self):
        aid=self.app(); self.approve(aid); self.s.claim_application(aid)
        with self.assertRaises(PermissionError): self.s.claim_application(aid)
    @patch.dict(os.environ,{'DZ_SUBMISSION_KEY':'test'})
    def test_delivery_receipt(self):
        aid=self.app(); self.approve(aid)
        def transport(url,**kw):
            self.assertEqual(kw['headers']['Idempotency-Key'],aid)
            return 200,{},b'{"receipt":"confirmed-1"}'
        self.assertEqual(send(self.s,aid,'https://example.com',transport)['state'],'submitted')
    @patch.dict(os.environ,{'DZ_SUBMISSION_KEY':'test'})
    def test_timeout_not_retried(self):
        aid=self.app(); self.approve(aid)
        def transport(*a,**kw): raise TimeoutError()
        self.assertEqual(send(self.s,aid,'https://example.com',transport)['state'],'uncertain')
        with self.assertRaises(PermissionError): send(self.s,aid,'https://example.com',transport)
        self.s.reconcile(aid,'submitted','gateway receipt')
    def test_analysis_and_sensitive_reply(self):
        self.s.ingest('a',[row()]); report=analyze(self.s,self.s.jobs()[0]['id'],{'mine':{}})
        self.assertTrue(report['audit']['pass'])
        self.assertEqual(reply('期望薪资多少',{})['state'],'needs_human')
    def test_rss_atom(self):
        for xml in (b'<rss><channel><item><guid>x</guid><title>Python</title><description>SQL</description></item></channel></rss>',b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>x</id><title>Python</title><content>SQL</content><link href="/a"/></entry></feed>'):
            r=parse(xml,'https://example.com'); self.assertEqual(r[0]['id'],'x'); self.assertEqual(r[0]['raw'],'SQL')
    def test_xml_entity_rejected(self):
        with self.assertRaises(ValueError): parse(b'<!DOCTYPE rss><rss/>')
    def test_jsonld_graph(self):
        html='<script type="application/ld+json">'+json.dumps({'@graph':[{'@type':'JobPosting','title':'Python','description':'SQL'}]})+'</script>'
        self.assertEqual(jsonld(html,'https://example.com')[0]['raw'],'SQL')
    def test_smartrecruiters_pagination(self):
        class Fake:
            def json(_,url):
                if '?' in url: return {'content':[{'id':'1'}],'totalFound':1}
                return {'id':'1','name':'Python','jobAd':{'sections':{'jobDescription':{'text':'SQL'}}}}
        self.assertEqual(collect(Fake(),'smartrecruiters','https://example.com/jobs')[0]['raw'],'SQL')
    def test_robots_per_path(self):
        self.s.db.execute('UPDATE dim_source SET endpoint="https://example.com/jobs" WHERE id="a"')
        def fake(url): return (200,{},b'User-agent: *\nDisallow: /private' if url.endswith('robots.txt') else b'[]')
        c=Client(self.s,'a',fake); self.assertEqual(c.get('https://example.com/jobs'),b'[]')
        with self.assertRaises(PermissionError): c.get('https://example.com/private')
    def test_429_persists_circuit(self):
        self.s.db.execute('UPDATE dim_source SET endpoint="https://example.com/jobs" WHERE id="a"')
        def fake(url): raise urllib.error.HTTPError(url,429,'limited',{'Retry-After':'3600'},None)
        with self.assertRaises(urllib.error.HTTPError): Client(self.s,'a',fake).get('https://example.com/jobs')
        self.assertGreater(self.s.source('a')['blocked_until'],0)
    def test_private_network_rejected(self):
        with self.assertRaises(ValueError): validate_url('http://example.com')
        with patch('socket.getaddrinfo',return_value=[(2,1,6,'',('127.0.0.1',443))]):
            with self.assertRaises(ValueError): validate_url('https://example.com')
    def test_migration_repeat_and_increment(self):
        from dz.store import Store as Legacy
        from dz.schema import JD
        path=Path(self.tmp.name)/'old.db'; old=Legacy(str(path))
        old.put_job(JD.from_dict(row())); migrate(self.s,path,'owned export')
        migrate(self.s,path,'owned export'); self.assertEqual(len(self.s.jobs()),1)
        old.put_job(JD.from_dict(row('2',raw='Docker required'))); migrate(self.s,path,'owned export')
        self.assertEqual(len(self.s.jobs()),2); old.db.close()


class APITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        s=Store(self.tmp.name,'alice'); s.register('a','json',consent='test',compliance='approved'); s.ingest('a',[row()]); s.close()
        tokens=[{'sha256':hashlib.sha256(t.encode()).hexdigest(),'tenant':tenant,'role':role} for t,tenant,role in [('a','alice','reader'),('b','bob','operator')]]
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.tmp.name,tokens))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self): self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup()
    def get(self,token,path='/api/jobs',data=None):
        req=urllib.request.Request(self.base+path,headers={'Authorization':'Bearer '+token},data=data)
        return json.load(urllib.request.urlopen(req))
    def test_auth_required(self):
        with self.assertRaises(urllib.error.HTTPError) as e: self.get('')
        self.assertEqual(e.exception.code,401)
    def test_tenant_query_cannot_override(self):
        self.assertEqual(len(self.get('a')['data']),1)
        self.assertEqual(self.get('b','/api/jobs?tenant=alice')['data'],[])
    def test_reader_cannot_write(self):
        with self.assertRaises(urllib.error.HTTPError) as e: self.get('a','/api/import',b'{}')
        self.assertEqual(e.exception.code,403)
    def test_bad_payload(self):
        with self.assertRaises(urllib.error.HTTPError) as e: self.get('b','/api/import',b'[]')
        self.assertEqual(e.exception.code,400)
    def test_dashboard(self):
        with urllib.request.urlopen(self.base) as r: self.assertIn('text/html',r.headers['Content-Type'])

if __name__=='__main__': unittest.main()

class AdditionalTests(unittest.TestCase):
    def test_calendar_timezone_and_escaping(self):
        from dz.platform.calendar import invitation
        s=invitation('面试,测试\n第二行','2026-11-10T10:00:00+08:00','2026-11-10T11:00:00+08:00')
        self.assertIn('DTSTART:20261110T020000Z',s)
        self.assertIn('面试\\,测试\\n第二行',s)
        with self.assertRaises(ValueError): invitation('x','2026-11-10T10:00:00','2026-11-10T11:00:00')
    def test_calendar_line_lengths(self):
        from dz.platform.calendar import invitation
        s=invitation('面试'*100,'2026-11-10T10:00:00+08:00','2026-11-10T11:00:00+08:00')
        self.assertTrue(all(len(x.encode())<=75 for x in s.split('\r\n')))
    def test_concurrent_quota(self):
        with tempfile.TemporaryDirectory() as root:
            s=Store(root); s.register('a','json',quota=1,consent='test',compliance='approved'); s.close()
            barrier=threading.Barrier(2); results=[]
            def run(i):
                db=Store(root); barrier.wait()
                try: db.ingest('a',[row(str(i))]); results.append('ok')
                except PermissionError: results.append('denied')
                finally: db.close()
            threads=[threading.Thread(target=run,args=(i,)) for i in range(2)]
            for t in threads:t.start()
            for t in threads:t.join()
            self.assertCountEqual(results,['ok','denied'])
    def test_drift_missing_baseline_not_zero(self):
        from dz.platform.analytics import drift
        with tempfile.TemporaryDirectory() as root:
            s=Store(root); s.register('a','json',consent='test',compliance='approved'); s.ingest('a',[row()])
            r=drift(s); self.assertTrue(r['items']); self.assertIsNone(r['items'][0]['delta']); s.close()
    def test_greenhouse_and_lever_body(self):
        class Fake:
            def json(self,url):
                if url=='gh': return {'jobs':[{'id':1,'title':'Python','content':'<p>SQL</p>'}]}
                return [{'id':'1','text':'Python','lists':[{'text':'Requirements','content':'<p>SQL</p>'}]}]
        self.assertIn('SQL',collect(Fake(),'greenhouse','gh')[0]['raw'])
        self.assertIn('SQL',collect(Fake(),'lever','lv')[0]['raw'])
    def test_pagination_incomplete_fails(self):
        class Fake:
            def json(self,url):
                if '?' in url:return {'content':[{'id':'1'}],'totalFound':500}
                return {'name':'Python','jobAd':{'sections':{}}}
        with self.assertRaises(ValueError):collect(Fake(),'smartrecruiters','https://example.com',max_pages=1)
    def test_cli_roundtrip(self):
        import subprocess,sys
        with tempfile.TemporaryDirectory() as root:
            base=[sys.executable,'-m','dz.cli','platform','--root',root]
            subprocess.run(base+['source','add','--id','a','--kind','json','--consent','test','--compliance','approved'],check=True,capture_output=True)
            result=subprocess.run(base+['import','--source','a','--file','examples/jobs.json'],check=True,capture_output=True,text=True)
            self.assertEqual(json.loads(result.stdout)['inserted'],1)
            s=Store(root); self.assertEqual(len(s.rows('SELECT * FROM p3_invocation_log')),2); s.close()
