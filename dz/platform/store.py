from __future__ import annotations
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from difflib import SequenceMatcher
from ..extract import extract_rule


def dumps(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(x):
    return hashlib.sha256(x.encode()).hexdigest()


def norm(x):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', x).casefold()).strip()


DDL = '''
CREATE TABLE IF NOT EXISTS dim_source (
 id TEXT PRIMARY KEY, kind TEXT NOT NULL, endpoint TEXT NOT NULL DEFAULT '',
 enabled INTEGER NOT NULL DEFAULT 1, quota INTEGER NOT NULL CHECK(quota>=0),
 consent TEXT NOT NULL, compliance TEXT NOT NULL, contract TEXT NOT NULL DEFAULT '',
 interval REAL NOT NULL DEFAULT 2 CHECK(interval>=0), next_request REAL NOT NULL DEFAULT 0,
 blocked_until REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS usage_daily (day TEXT, source TEXT, used INTEGER NOT NULL,
 PRIMARY KEY(day,source));
CREATE TABLE IF NOT EXISTS postings (id TEXT PRIMARY KEY, source TEXT NOT NULL REFERENCES dim_source(id),
 external_id TEXT NOT NULL, canonical_id TEXT NOT NULL, title TEXT NOT NULL,
 company TEXT NOT NULL, city TEXT NOT NULL, source_url TEXT NOT NULL, current_hash TEXT NOT NULL,
 first_seen REAL NOT NULL, last_seen REAL NOT NULL, UNIQUE(source,external_id));
CREATE TABLE IF NOT EXISTS versions (id TEXT PRIMARY KEY, posting_id TEXT NOT NULL REFERENCES postings(id),
 content_hash TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL,
 UNIQUE(posting_id,content_hash));
CREATE TABLE IF NOT EXISTS evidence (version_id TEXT NOT NULL REFERENCES versions(id),
 cid TEXT NOT NULL, text TEXT NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
 extractor TEXT NOT NULL, PRIMARY KEY(version_id,cid));
CREATE TABLE IF NOT EXISTS crawl_events (id INTEGER PRIMARY KEY, source TEXT, ts REAL NOT NULL,
 status INTEGER NOT NULL, kind TEXT NOT NULL, latency_ms REAL NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dws_coverage_estimate (id INTEGER PRIMARY KEY, ts REAL, report TEXT);
CREATE TABLE IF NOT EXISTS p3_invocation_log (id INTEGER PRIMARY KEY, command TEXT, ts REAL,
 duration_ms REAL, ok INTEGER);
CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY, ts REAL NOT NULL,
 action TEXT NOT NULL, payload TEXT NOT NULL, prev TEXT NOT NULL, hash TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit
 BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit
 BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
CREATE TRIGGER IF NOT EXISTS version_no_update BEFORE UPDATE ON versions
 BEGIN SELECT RAISE(ABORT,'immutable version'); END;
CREATE TRIGGER IF NOT EXISTS version_no_delete BEFORE DELETE ON versions
 BEGIN SELECT RAISE(ABORT,'immutable version'); END;
CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, posting_id TEXT NOT NULL REFERENCES postings(id),
 version_hash TEXT NOT NULL, resume TEXT NOT NULL, resume_hash TEXT NOT NULL, state TEXT NOT NULL,
 approved_until REAL, attempts INTEGER NOT NULL DEFAULT 0, receipt TEXT, updated REAL NOT NULL,
 UNIQUE(posting_id,version_hash,resume_hash));
CREATE INDEX IF NOT EXISTS posting_canonical ON postings(canonical_id);
CREATE INDEX IF NOT EXISTS crawl_source_time ON crawl_events(source,ts);
CREATE VIEW IF NOT EXISTS ods_crawl_health AS
 SELECT date(ts,'unixepoch') day,source,count(*) requests,
 sum(status BETWEEN 200 AND 299 AND kind='ok') success,sum(status=429) rate_limited,
 sum(kind='captcha') captcha_cnt,sum(status IN (401,403)) blocked,
 avg(latency_ms) avg_latency_ms FROM crawl_events GROUP BY day,source;
'''


class Store:
    """Each tenant has a distinct SQLite file. Tenant is resolved from auth, never query data.

    Local OS owner remains trusted: hash chains and SQL triggers do not protect
    against an administrator replacing the database or dropping triggers.
    """
    def __init__(self, root, tenant='personal'):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', tenant):
            raise ValueError('invalid tenant')
        root = Path(root)
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = root / (tenant + '.sqlite3')
        self.db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        self.path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript(DDL)

    def close(self):
        self.db.close()

    @contextmanager
    def tx(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise

    def rows(self, sql, params=()):
        return [dict(r) for r in self.db.execute(sql, params)]

    def audit(self, action, payload):
        prev = self.db.execute('SELECT hash FROM audit ORDER BY seq DESC LIMIT 1').fetchone()
        prev = prev[0] if prev else ''
        ts = time.time()
        payload = dumps(payload)
        h = digest(dumps([ts, action, payload, prev]))
        self.db.execute('INSERT INTO audit(ts,action,payload,prev,hash) VALUES(?,?,?,?,?)',
                        (ts, action, payload, prev, h))

    def verify_audit(self):
        prev = ''
        for r in self.rows('SELECT * FROM audit ORDER BY seq'):
            if r['prev'] != prev or r['hash'] != digest(dumps([r['ts'], r['action'], r['payload'], prev])):
                return {'ok': False, 'seq': r['seq']}
            prev = r['hash']
        return {'ok': True, 'head': prev}

    def source(self, source):
        row = self.db.execute('SELECT * FROM dim_source WHERE id=?', (source,)).fetchone()
        if not row:
            raise ValueError('source not registered')
        return dict(row)

    def register(self, source, kind, endpoint='', quota=1000, consent='', compliance='', contract='', interval=2):
        if not source.strip() or not consent.strip() or compliance != 'approved':
            raise ValueError('source requires consent reference and approved review')
        if kind == 'partner' and not contract.strip():
            raise ValueError('partner requires contract reference')
        if quota < 0 or interval < 0:
            raise ValueError('negative quota or interval')
        with self.tx():
            self.db.execute('''INSERT INTO dim_source(id,kind,endpoint,quota,consent,compliance,contract,interval)
              VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind,
              endpoint=excluded.endpoint,quota=excluded.quota,consent=excluded.consent,
              compliance=excluded.compliance,contract=excluded.contract,interval=excluded.interval''',
              (source, kind, endpoint, quota, consent, compliance, contract, interval))
            self.audit('source.register', {'id': source, 'kind': kind, 'consent': consent})

    def enable(self, source, enabled):
        self.source(source)
        with self.tx():
            self.db.execute('UPDATE dim_source SET enabled=? WHERE id=?', (int(enabled), source))
            self.audit('source.enabled', {'source': source, 'enabled': enabled})

    def gate(self, source):
        s = self.source(source)
        if not s['enabled'] or s['compliance'] != 'approved' or not s['consent']:
            raise PermissionError('source disabled or unapproved')
        return s

    def ingest(self, source, records):
        records = list(records)
        if len(records) > 10000:
            raise ValueError('maximum 10000 rows per batch')
        prepared = []
        for r in records:
            if not isinstance(r, dict) or any(not isinstance(r.get(k), str) or not r[k].strip()
                                              for k in ('id', 'title', 'raw')):
                raise ValueError('each record requires string id/title/raw')
            if len(dumps(r)) > 1_000_000:
                raise ValueError('record too large')
            prepared.append(dict(r))
        now = time.time()
        day = time.strftime('%Y-%m-%d', time.gmtime(now))
        inserted = changed = 0
        with self.tx():
            s = self.gate(source)
            used = self.db.execute('SELECT used FROM usage_daily WHERE day=? AND source=?', (day, source)).fetchone()
            if (used[0] if used else 0) + len(prepared) > s['quota']:
                raise PermissionError('daily imported-record quota exceeded')
            self.db.execute('INSERT INTO usage_daily VALUES(?,?,?) ON CONFLICT(day,source) DO UPDATE SET used=used+excluded.used',
                            (day, source, len(prepared)))
            for r in prepared:
                pid = digest(dumps([source, r['id']]))
                h = digest(dumps(r))
                old = self.db.execute('SELECT current_hash,canonical_id FROM postings WHERE id=?', (pid,)).fetchone()
                # Conservative exact identity; fuzzy matches are review candidates, never silent merges.
                identity = [norm(r.get(k, '')) for k in ('company', 'title', 'city', 'raw')]
                canonical = digest(dumps(identity)) if all(identity[:3]) else pid
                if old:
                    canonical = old['canonical_id']
                self.db.execute('''INSERT INTO postings VALUES(?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET title=excluded.title,company=excluded.company,
                    city=excluded.city,source_url=excluded.source_url,current_hash=excluded.current_hash,last_seen=excluded.last_seen''',
                    (pid, source, r['id'], canonical, r['title'], r.get('company',''), r.get('city',''),
                     r.get('source_url',''), h, now, now))
                vid = digest(dumps([pid, h]))
                new_version = self.db.execute('INSERT OR IGNORE INTO versions VALUES(?,?,?,?,?)',
                                              (vid, pid, h, dumps(r), now)).rowcount
                if new_version:
                    for skill in extract_rule(r['raw']).skills:
                        start = r['raw'].find(skill.evidence)
                        if start >= 0:
                            self.db.execute('INSERT OR IGNORE INTO evidence VALUES(?,?,?,?,?,?)',
                                (vid, skill.cid, skill.evidence, start, start+len(skill.evidence), 'rule-v5'))
                inserted += not bool(old)
                changed += bool(old and old['current_hash'] != h)
            self.audit('ingest', {'source': source, 'rows': len(prepared), 'inserted': inserted, 'changed': changed})
        return {'rows': len(prepared), 'inserted': inserted, 'changed': changed}

    def jobs(self, query='', limit=100):
        return self.rows('SELECT * FROM postings WHERE title LIKE ? ORDER BY last_seen DESC LIMIT ?',
                         ('%'+query+'%', max(1, min(int(limit), 500))))

    def candidates(self, threshold=.85):
        groups = {}
        for r in self.rows('SELECT * FROM postings'):
            if r['company'] and r['city']:
                groups.setdefault((norm(r['company']),norm(r['city'])), []).append(r)
        result = []
        for rows in groups.values():
            # Explicit bounded review window, not an unbounded quadratic production job.
            rows = rows[:500]
            for i,a in enumerate(rows):
                for b in rows[i+1:]:
                    if a['source'] == b['source'] or a['canonical_id'] == b['canonical_id']:
                        continue
                    score = SequenceMatcher(None,norm(a['title']),norm(b['title'])).ratio()
                    if score >= threshold:
                        result.append({'left': a['id'], 'right': b['id'], 'title_similarity': score,
                                       'reason': 'same normalized company/city; human review required'})
        return result

    def merge(self, left, right, reason):
        if not reason.strip():
            raise ValueError('merge evidence required')
        with self.tx():
            rows = self.rows('SELECT id,canonical_id FROM postings WHERE id IN (?,?)', (left,right))
            if len(rows) != 2:
                raise ValueError('two distinct existing postings required')
            target = min(r['canonical_id'] for r in rows)
            ids = [r['canonical_id'] for r in rows]
            self.db.execute('UPDATE postings SET canonical_id=? WHERE canonical_id IN (?,?)',(target,*ids))
            self.audit('identity.merge', {'left':left,'right':right,'reason':reason,'previous':rows,'target':target})
        return {'canonical_id':target}

    def coverage(self, a, b, days=30, city='', assumptions=False):
        if a == b or not 1 <= days <= 3650:
            raise ValueError('distinct sources and valid days required')
        self.source(a); self.source(b)
        sets = []
        for s in (a,b):
            sets.append({r['canonical_id'] for r in self.rows('''SELECT canonical_id FROM postings
              WHERE source=? AND last_seen>=? AND (?='' OR city=?)''', (s,time.time()-days*86400,city,city))})
        n1,n2,m = len(sets[0]),len(sets[1]),len(sets[0]&sets[1])
        union = len(sets[0]|sets[1])
        report = {'sources':[a,b], 'days':days,'city':city,'n1':n1,'n2':n2,'overlap':m,
                  'observed_unique':union,'estimate':None,'coverage':None,'method':'observed-only-v1',
                  'warning':'Observed postings are not verified active jobs or total-market coverage.'}
        if m and assumptions:
            estimate = (n1+1)*(n2+1)/(m+1)-1
            variance = (n1+1)*(n2+1)*(n1-m)*(n2-m)/((m+1)**2*(m+2))
            lo,hi = max(union,estimate-1.96*variance**.5), max(union,estimate+1.96*variance**.5)
            report.update(estimate=estimate,coverage=union/estimate,method='chapman-conditional-v1',
                          approximate_interval=[lo,hi],warning='Conditional on closed population, accurate linkage, independent sources and equal capture probability; interval excludes model/linkage uncertainty.')
        with self.tx():
            self.db.execute('INSERT INTO dws_coverage_estimate(ts,report) VALUES(?,?)',(time.time(),dumps(report)))
            self.audit('coverage', report)
        return report

    def event(self, source, status, kind, latency=0, detail=''):
        self.db.execute('INSERT INTO crawl_events(source,ts,status,kind,latency_ms,detail) VALUES(?,?,?,?,?,?)',
                        (source,time.time(),status,kind,latency,detail[:500]))

    def prepare_application(self, posting_id, resume):
        if not isinstance(resume,dict) or not resume.get('facts') or not isinstance(resume['facts'],list):
            raise ValueError('resume requires facts [{text,evidence}]')
        for f in resume['facts']:
            if not isinstance(f,dict) or not isinstance(f.get('text'),str) or not f['text'].strip() or not isinstance(f.get('evidence'),str) or not f['evidence'].strip():
                raise ValueError('each resume fact requires text and evidence reference')
        with self.tx():
            p = self.db.execute('SELECT * FROM postings WHERE id=?',(posting_id,)).fetchone()
            if not p:
                raise ValueError('unknown posting')
            rh = digest(dumps(resume)); aid = digest(dumps([posting_id,p['current_hash'],rh]))
            self.db.execute('INSERT OR IGNORE INTO applications(id,posting_id,version_hash,resume,resume_hash,state,updated) VALUES(?,?,?,?,?,?,?)',
                            (aid,posting_id,p['current_hash'],dumps(resume),rh,'draft',time.time()))
            self.audit('application.prepare', {'id':aid})
        return {'id':aid,'state':self.db.execute('SELECT state FROM applications WHERE id=?',(aid,)).fetchone()[0]}

    def approve(self, aid, resume_hash, ttl=3600):
        if not 1 <= ttl <= 86400:
            raise ValueError('approval TTL out of range')
        with self.tx():
            r = self.db.execute('SELECT a.*,p.current_hash FROM applications a JOIN postings p ON p.id=a.posting_id WHERE a.id=?',(aid,)).fetchone()
            if not r or r['state'] not in ('draft','approved') or r['resume_hash'] != resume_hash or r['version_hash'] != r['current_hash']:
                raise ValueError('stale or invalid application')
            self.db.execute("UPDATE applications SET state='approved',approved_until=?,updated=? WHERE id=?",(time.time()+ttl,time.time(),aid))
            self.audit('application.approve',{'id':aid,'resume_hash':resume_hash,'ttl':ttl})

    def claim_application(self, aid):
        with self.tx():
            r = self.db.execute('SELECT a.*,p.current_hash,p.source FROM applications a JOIN postings p ON p.id=a.posting_id WHERE a.id=?',(aid,)).fetchone()
            if not r or r['state'] != 'approved' or r['approved_until'] < time.time() or r['version_hash'] != r['current_hash']:
                raise PermissionError('current unexpired approval required')
            self.gate(r['source'])
            self.db.execute("UPDATE applications SET state='sending',attempts=attempts+1,updated=? WHERE id=?",(time.time(),aid))
            self.audit('application.claim',{'id':aid})
            return dict(r)

    def complete_application(self, aid, state, receipt):
        if state not in ('submitted','uncertain','failed'):
            raise ValueError('invalid final state')
        with self.tx():
            n = self.db.execute("UPDATE applications SET state=?,receipt=?,updated=? WHERE id=? AND state='sending'",(state,dumps(receipt),time.time(),aid)).rowcount
            if n != 1:
                raise ValueError('application not sending')
            self.audit('application.result',{'id':aid,'state':state})

    def reconcile(self, aid, state, receipt):
        if state not in ('submitted','failed') or not receipt.strip():
            raise ValueError('manual receipt and submitted/failed required')
        with self.tx():
            n = self.db.execute("UPDATE applications SET state=?,receipt=?,updated=? WHERE id=? AND state IN ('sending','uncertain')",(state,dumps({'manual_evidence':receipt}),time.time(),aid)).rowcount
            if n != 1: raise ValueError('nothing to reconcile')
            self.audit('application.reconcile',{'id':aid,'state':state,'receipt':receipt})
