"""Run only against an ephemeral test PostgreSQL instance."""
import os,unittest,uuid,threading
from dz.platform.postgres import PGStore
from dz.platform.migration import migrate


class PostgreSQLTests(unittest.TestCase):
    def setUp(self):
        self.dsn=os.environ['DZ_TEST_POSTGRES_URL']; self.tenant='test_'+uuid.uuid4().hex
        self.s=PGStore(self.dsn,self.tenant)
        self.s.register('a','json',consent='test',compliance='approved',quota=10)
    def tearDown(self):
        from psycopg import sql
        self.s.db.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(self.s.schema)))
        self.s.close()
    def row(self,id='1'):return {'id':id,'title':'Python','company':'Demo','city':'上海','raw':'要求熟悉 Python 和 SQL'}
    def test_ingest_and_versions(self):
        self.s.ingest('a',[self.row()]);self.s.ingest('a',[self.row()])
        self.assertEqual(len(self.s.jobs()),1);self.assertEqual(len(self.s.rows('SELECT * FROM versions')),1)
        self.assertTrue(self.s.verify_audit()['ok'])
    def test_claim_and_immutable(self):
        import psycopg
        self.s.ingest('a',[self.row()]);pid=self.s.jobs()[0]['id']
        aid=self.s.prepare_application(pid,{'facts':[{'text':'test','evidence':'test'}]})['id']
        rh=self.s.rows('SELECT resume_hash FROM applications')[0]['resume_hash']
        self.s.approve(aid,rh);self.s.claim_application(aid)
        with self.assertRaises(PermissionError):self.s.claim_application(aid)
        self.s.complete_application(aid,'submitted',{'receipt':'test'})
        with self.assertRaises(psycopg.Error):self.s.db.execute('DELETE FROM audit')
        self.assertTrue(self.s.verify_audit()['ok'])
    def test_health_and_tenant_boundary(self):
        self.s.event('a',429,'http_error');self.assertEqual(self.s.rows('SELECT * FROM ods_crawl_health')[0]['rate_limited'],1)
        other=PGStore(self.dsn,self.tenant+'b')
        try:
            self.s.ingest('a',[self.row()]);self.assertEqual(other.jobs(),[])
        finally:
            from psycopg import sql
            other.db.conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(other.schema)));other.close()
    def test_concurrent_quota(self):
        self.s.db.execute('UPDATE dim_source SET quota=1 WHERE id=%s'.replace('%s','?'),('a',))
        barrier=threading.Barrier(2);results=[]
        def worker(i):
            s=PGStore(self.dsn,self.tenant);barrier.wait()
            try:s.ingest('a',[self.row(str(i))]);results.append('ok')
            except PermissionError:results.append('denied')
            finally:s.close()
        ts=[threading.Thread(target=worker,args=(i,)) for i in range(2)]
        for t in ts:t.start()
        for t in ts:t.join(20)
        self.assertCountEqual(results,['ok','denied'])
    def test_legacy_migration(self):
        import tempfile
        from pathlib import Path
        from dz.store import Store
        from dz.schema import JD
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'old.db';old=Store(str(path));old.put_job(JD.from_dict(self.row()));old.db.close()
            migrate(self.s,path,'owned-test-export');migrate(self.s,path,'owned-test-export')
            self.assertEqual(len(self.s.jobs()),1)

if __name__=='__main__':unittest.main()
