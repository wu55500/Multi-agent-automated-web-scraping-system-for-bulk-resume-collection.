import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from .postgres import open_store as Store
from .network import Client
from .adapters import collect


def main(argv=None):
    p=argparse.ArgumentParser(description='V5 job intelligence and approved application workflow')
    p.add_argument('--root',default='var/tenants'); p.add_argument('--tenant',default='personal')
    sub=p.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('source'); s.add_argument('action',choices=['list','add','off','on'])
    s.add_argument('--id'); s.add_argument('--kind',default='json',choices=['json','partner','rss','jsonld','workday','greenhouse','lever','smartrecruiters'])
    s.add_argument('--endpoint',default=''); s.add_argument('--quota',type=int,default=1000)
    s.add_argument('--consent',default=''); s.add_argument('--compliance',default='')
    s.add_argument('--contract',default=''); s.add_argument('--interval',type=float,default=2)
    i=sub.add_parser('import'); i.add_argument('--source',required=True); i.add_argument('--file',required=True)
    c=sub.add_parser('collect'); c.add_argument('--source',required=True); c.add_argument('--company',default=''); c.add_argument('--render',action='store_true')
    c.add_argument('--max-pages',type=int,default=20)
    for cmd in ('jobs','health','audit','candidates','applications'): sub.add_parser(cmd)
    co=sub.add_parser('cov-estimate'); co.add_argument('a'); co.add_argument('b'); co.add_argument('--days',type=int,default=30)
    co.add_argument('--city',default=''); co.add_argument('--accept-assumptions',action='store_true')
    m=sub.add_parser('merge'); m.add_argument('left'); m.add_argument('right'); m.add_argument('--reason',required=True)
    a=sub.add_parser('prepare'); a.add_argument('posting'); a.add_argument('--resume',required=True)
    a=sub.add_parser('approve'); a.add_argument('id'); a.add_argument('--resume-hash',required=True)
    a=sub.add_parser('send'); a.add_argument('ids',nargs='+')
    a=sub.add_parser('reconcile'); a.add_argument('id'); a.add_argument('--state',choices=['submitted','failed'],required=True); a.add_argument('--receipt',required=True)
    a=sub.add_parser('serve'); a.add_argument('--port',type=int,default=8771); a.add_argument('--host',default='127.0.0.1')
    a=sub.add_parser('migrate-legacy'); a.add_argument('--db',required=True); a.add_argument('--consent',required=True)
    a=sub.add_parser('analyze'); a.add_argument('posting'); a.add_argument('--profile',required=True)
    a=sub.add_parser('reply'); a.add_argument('--message',required=True); a.add_argument('--facts',required=True)
    a=sub.add_parser('drift'); a.add_argument('--days',type=int,default=7); a.add_argument('--source',default=''); a.add_argument('--city',default='')
    a=sub.add_parser('calendar'); a.add_argument('--title',required=True); a.add_argument('--start',required=True); a.add_argument('--end',required=True); a.add_argument('--out',required=True)
    a=p.parse_args(argv)
    if a.cmd=='serve':
        from .api import serve
        serve(a.root,a.host,a.port); return 0
    store=Store(a.root,a.tenant); start=time.monotonic(); ok=False
    try:
        if a.cmd=='source':
            if a.action=='list': result=store.rows('SELECT * FROM dim_source')
            elif a.action=='add':
                if not a.id: raise ValueError('--id required')
                store.register(a.id,a.kind,a.endpoint,a.quota,a.consent,a.compliance,a.contract,a.interval); result=store.source(a.id)
            else: store.enable(a.id,a.action=='on'); result=store.source(a.id)
        elif a.cmd=='import':
            path=Path(a.file)
            if path.stat().st_size>20_000_000: raise ValueError('file too large')
            with path.open(encoding='utf-8-sig',newline='') as f:
                if path.suffix=='.csv': rows=list(csv.DictReader(f))
                elif path.suffix=='.jsonl': rows=[json.loads(x) for x in f if x.strip()]
                else: rows=json.load(f)
            result=store.ingest(a.source,rows)
        elif a.cmd=='collect':
            s=store.gate(a.source); client=Client(store,a.source)
            if a.render:
                from .render import collect_rendered
                rows=collect_rendered(client,s['endpoint'])
            else: rows=collect(client,s['kind'],s['endpoint'],a.company,a.max_pages)
            result=store.ingest(a.source,rows)
        elif a.cmd=='jobs': result=store.jobs()
        elif a.cmd=='health': result=store.rows('SELECT * FROM ods_crawl_health ORDER BY day DESC,source')
        elif a.cmd=='audit': result=store.verify_audit()
        elif a.cmd=='candidates': result=store.candidates()
        elif a.cmd=='applications': result=store.rows('SELECT id,posting_id,state,resume_hash,updated FROM applications')
        elif a.cmd=='cov-estimate': result=store.coverage(a.a,a.b,a.days,a.city,a.accept_assumptions)
        elif a.cmd=='merge': result=store.merge(a.left,a.right,a.reason)
        elif a.cmd=='prepare': result=store.prepare_application(a.posting,json.loads(Path(a.resume).read_text()))
        elif a.cmd=='approve': store.approve(a.id,a.resume_hash); result={'approved':a.id}
        elif a.cmd=='send':
            from .submit import send
            endpoint=os.environ.get('DZ_SUBMISSION_URL','')
            result=[]
            for aid in a.ids:
                try: result.append(send(store,aid,endpoint))
                except (ValueError,PermissionError) as e: result.append({'id':aid,'error':str(e)})
        elif a.cmd=='reconcile': store.reconcile(a.id,a.state,a.receipt); result={'id':a.id,'state':a.state}
        elif a.cmd=='migrate-legacy':
            from .migration import migrate
            result=migrate(store,a.db,a.consent)
        elif a.cmd=='analyze':
            from .agents import analyze
            result=analyze(store,a.posting,json.loads(Path(a.profile).read_text()))
        elif a.cmd=='reply':
            from .agents import reply
            result=reply(a.message,json.loads(Path(a.facts).read_text()))
        elif a.cmd=='drift':
            from .analytics import drift
            result=drift(store,a.days,a.source,a.city)
        elif a.cmd=='calendar':
            from .calendar import invitation
            Path(a.out).write_text(invitation(a.title,a.start,a.end),encoding='utf-8')
            result={'file':a.out,'sent':False}
        print(json.dumps(result,ensure_ascii=False,indent=2)); ok=True; return 0
    except (ValueError,PermissionError,OSError) as e:
        print(json.dumps({'ok':False,'error':str(e)},ensure_ascii=False),file=sys.stderr); return 1
    finally:
        store.db.execute('INSERT INTO p3_invocation_log(command,ts,duration_ms,ok) VALUES(?,?,?,?)',
                         (a.cmd,time.time(),(time.monotonic()-start)*1000,int(ok)))
        store.close()

if __name__=='__main__': sys.exit(main())
