"""Recomputable source/city/time-scoped skill frequencies. No causal claims."""
import time
from .store import dumps


def frequency(store,start,end,source='',city=''):
    rows=store.rows('''SELECT p.canonical_id,p.id,p.current_hash FROM postings p
        WHERE p.last_seen>=? AND p.last_seen<? AND (?='' OR p.source=?) AND (?='' OR p.city=?)''',
        (start,end,source,source,city,city))
    jobs={r['canonical_id'] for r in rows}; skills={}
    for p in rows:
        for e in store.rows('''SELECT e.cid FROM evidence e JOIN versions v ON v.id=e.version_id
            WHERE v.posting_id=? AND v.content_hash=?''',(p['id'],p['current_hash'])):
            skills.setdefault(e['cid'],set()).add(p['canonical_id'])
    return {'denominator':len(jobs),'skills':{k:len(v) for k,v in skills.items()},'start':start,'end':end,
            'source':source,'city':city,'method':'current-version-last-observed-v1'}


def drift(store,days=7,source='',city=''):
    if not 1<=days<=365: raise ValueError('days must be 1..365')
    now=time.time(); split=now-days*86400
    cur=frequency(store,split,now+1,source,city); old=frequency(store,split-days*86400,split,source,city)
    items=[]
    for cid in sorted(cur['skills'].keys() | old['skills'].keys()):
        c=cur['skills'].get(cid,0)/cur['denominator'] if cur['denominator'] else None
        b=old['skills'].get(cid,0)/old['denominator'] if old['denominator'] else None
        items.append({'cid':cid,'current_ratio':c,'baseline_ratio':b,'delta':c-b if c is not None and b is not None else None})
    return {'current':cur,'baseline':old,'items':items,
            'warning':'Different last-observed cohorts, not historical market snapshots. Composition and recrawls can explain changes.'}
