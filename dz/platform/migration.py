"""Repeatable legacy import, preserving every row and recording the actual source.
No source database writes. Partial runs can be restarted; ingest versions are unique.
"""
import sqlite3
from pathlib import Path


def migrate(store,path,consent):
    path=Path(path).resolve()
    if not path.is_file(): raise ValueError('legacy database missing')
    old=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True); old.row_factory=sqlite3.Row
    results=[]
    try:
        sources=[r[0] for r in old.execute('SELECT DISTINCT source FROM jobs')]
        for source in sources:
            sid='legacy:'+str(source)
            # Do not overwrite a revoked/disabled existing registration.
            if not store.db.execute('SELECT 1 FROM dim_source WHERE id=?',(sid,)).fetchone():
                store.register(sid,'json',quota=1_000_000,consent=consent,compliance='approved')
            cursor=old.execute('SELECT * FROM jobs WHERE source IS ?',(source,))
            count=0
            while True:
                rows=cursor.fetchmany(500)
                if not rows: break
                store.ingest(sid,[{k:(r[k] or '') for k in ('id','title','raw','company','city','source_url')} for r in rows])
                count+=len(rows)
            actual=store.db.execute('SELECT count(*) FROM postings WHERE source=?',(sid,)).fetchone()[0]
            if actual<count: raise RuntimeError('migration count mismatch')
            results.append({'source':source,'read':count,'stored':actual})
    finally: old.close()
    return {'sources':results,'note':'Legacy barriers are job eligibility, not compliance audits. Not migrated as violations.'}
