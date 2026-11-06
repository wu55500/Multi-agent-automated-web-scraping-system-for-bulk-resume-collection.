"""PostgreSQL backend with a schema per tenant and serialized write transactions.

Schema isolation is enforced by server-side tenant routing. The service database
role is trusted across schemas; this is not a per-tenant SQL credential boundary.
"""
import hashlib
import os
import re
from contextlib import contextmanager
from .store import Store, DDL


class Row(dict):
    def __getitem__(self,key):
        if isinstance(key,int): return list(self.values())[key]
        return super().__getitem__(key)


def row_factory(cursor):
    names=[c.name for c in (cursor.description or [])]
    return lambda values: Row(zip(names,[v.isoformat() if hasattr(v,"isoformat") else v for v in values]))


class Connection:
    def __init__(self,conn): self.conn=conn
    def execute(self,query,params=()):
        ignore=query.startswith('INSERT OR IGNORE INTO ')
        if ignore: query=query.replace('INSERT OR IGNORE INTO ','INSERT INTO ',1)+' ON CONFLICT DO NOTHING'
        query=query.replace('interval=max(interval,?)','interval=GREATEST(interval,?)')
        # Queries are internal constants; parameters are never interpolated as SQL.
        query=query.replace('?', '%s')
        return self.conn.execute(query,params)
    def close(self): self.conn.close()


def ddl():
    body=DDL[:DDL.index('CREATE VIEW IF NOT EXISTS ods_crawl_health')]
    body=re.sub(r'CREATE TRIGGER IF NOT EXISTS .*?END;', '',body,flags=re.S)
    body=body.replace('end INTEGER', '"end" INTEGER')
    body=body.replace('INTEGER PRIMARY KEY','BIGSERIAL PRIMARY KEY').replace(' REAL',' DOUBLE PRECISION')
    body+='''
CREATE OR REPLACE VIEW ods_crawl_health AS
 SELECT (to_timestamp(ts) AT TIME ZONE 'UTC')::date day,source,count(*) requests,
 count(*) FILTER (WHERE status BETWEEN 200 AND 299 AND kind='ok') success,
 count(*) FILTER (WHERE status=429) rate_limited,
 count(*) FILTER (WHERE kind='captcha') captcha_cnt,
 count(*) FILTER (WHERE status IN (401,403)) blocked,avg(latency_ms) avg_latency_ms
 FROM crawl_events GROUP BY day,source;
CREATE OR REPLACE FUNCTION reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
 BEGIN RAISE EXCEPTION 'immutable record'; END $$;
DROP TRIGGER IF EXISTS audit_immutable ON audit;
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit
 FOR EACH ROW EXECUTE FUNCTION reject_mutation();
DROP TRIGGER IF EXISTS version_immutable ON versions;
CREATE TRIGGER version_immutable BEFORE UPDATE OR DELETE ON versions
 FOR EACH ROW EXECUTE FUNCTION reject_mutation();
'''
    return body


class PGStore(Store):
    def __init__(self,dsn,tenant='personal'):
        import psycopg
        from psycopg import sql
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',tenant): raise ValueError('invalid tenant')
        # Case-sensitive tenant identities map to distinct safe schema identifiers.
        self.schema='tenant_'+hashlib.sha256(tenant.encode()).hexdigest()[:32]
        self.lock=int(hashlib.sha256(self.schema.encode()).hexdigest()[:15],16)
        conn=psycopg.connect(dsn,autocommit=True,row_factory=row_factory)
        self.db=Connection(conn)
        try:
            with conn.transaction():
                conn.execute('SELECT pg_advisory_xact_lock(%s)',(self.lock,))
                conn.execute(sql.SQL('CREATE SCHEMA IF NOT EXISTS {}').format(sql.Identifier(self.schema)))
                conn.execute(sql.SQL('SET search_path TO {}, pg_catalog').format(sql.Identifier(self.schema)))
                conn.execute(ddl())
        except BaseException:
            conn.close(); raise

    @contextmanager
    def tx(self):
        with self.db.conn.transaction():
            # Mirrors SQLite BEGIN IMMEDIATE semantics for quota/claim/audit atomicity.
            self.db.conn.execute('SELECT pg_advisory_xact_lock(%s)',(self.lock,))
            yield


def open_store(root,tenant='personal'):
    dsn=os.environ.get('DZ_DATABASE_URL')
    return PGStore(dsn,tenant) if dsn else Store(root,tenant)
