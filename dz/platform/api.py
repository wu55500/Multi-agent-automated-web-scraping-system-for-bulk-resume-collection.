import hashlib
import hmac
import json
import os
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from .postgres import open_store as Store


def load_tokens(path):
    data=json.loads(Path(path).read_text())
    if not isinstance(data,list) or not data: raise ValueError('token registry required')
    for r in data:
        if len(r.get('sha256',''))!=64 or r.get('role') not in ('reader','operator'):
            raise ValueError('invalid token registry')
    return data


def handler(root,tokens):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # never log credentials or candidate content
        def respond(self,status,data):
            body=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
        def do_GET(self): self.dispatch(False)
        def do_POST(self): self.dispatch(True)
        def dispatch(self,write):
            path=urlsplit(self.path).path
            if not write and path=='/healthz':
                self.respond(200,{'status':'alive'}); return
            if not write and path=='/':
                body=Path(__file__).with_name('dashboard.html').read_bytes()
                self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body); return
            if self.headers.get('Origin') and urlsplit(self.headers['Origin']).netloc!=self.headers.get('Host'):
                self.respond(403,{'error':'cross-origin request refused'}); return
            auth=self.headers.get('Authorization','')
            token=auth[7:] if auth.startswith('Bearer ') else ''
            hashed=hashlib.sha256(token.encode()).hexdigest()
            account=next((r for r in tokens if hmac.compare_digest(r['sha256'],hashed)),None) if token else None
            if not account: self.respond(401,{'error':'authentication required'}); return
            if write and account['role']!='operator': self.respond(403,{'error':'operator required'}); return
            store=None
            try:
                store=Store(root,account['tenant'])
                if write:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=1_000_000: raise ValueError('invalid request size')
                    data=json.loads(self.rfile.read(size))
                    if not isinstance(data,dict): raise ValueError('JSON object required')
                    if path=='/api/import': result=store.ingest(data['source'],data['records'])
                    elif path=='/api/coverage': result=store.coverage(data['a'],data['b'],int(data.get('days',30)),data.get('city',''),data.get('accept_assumptions') is True)
                    elif path=='/api/prepare': result=store.prepare_application(data['posting'],data['resume'])
                    elif path=='/api/approve': store.approve(data['id'],data['resume_hash']); result={'approved':data['id']}
                    else: self.respond(404,{'error':'unknown endpoint'}); return
                elif path=='/api/jobs':
                    q=parse_qs(urlsplit(self.path).query); result=store.jobs(q.get('q',[''])[0],q.get('limit',[100])[0])
                elif path=='/api/health': result=store.rows('SELECT * FROM ods_crawl_health ORDER BY day DESC')
                elif path=='/api/sources': result=store.rows('SELECT id,kind,enabled,quota FROM dim_source')
                elif path=='/api/coverage': result=[json.loads(r['report']) for r in store.rows('SELECT report FROM dws_coverage_estimate ORDER BY id DESC LIMIT 20')]
                elif path=='/api/applications': result=store.rows('SELECT id,posting_id,state,resume_hash,version_hash,resume FROM applications')
                elif path=='/api/drift':
                    from .analytics import drift
                    result=drift(store)
                elif path=='/api/audit': result=store.verify_audit()
                else: self.respond(404,{'error':'unknown endpoint'}); return
                self.respond(200,{'ok':True,'data':result})
            except PermissionError as e: self.respond(403,{'error':str(e)})
            except (ValueError,KeyError,TypeError) as e: self.respond(400,{'error':'invalid input: '+str(e)})
            except Exception: self.respond(500,{'error':'internal error'})
            finally:
                if store: store.close()
    return Handler


def serve(root,host,port):
    if os.environ.get('DZ_ACCESS_TOKEN'):
        secret=os.environ['DZ_ACCESS_TOKEN']
        if len(secret)<32: raise ValueError('DZ_ACCESS_TOKEN must contain at least 32 characters')
        tokens=[{'sha256':hashlib.sha256(secret.encode()).hexdigest(),'tenant':'personal','role':'operator'}]
    elif os.environ.get('DZ_TOKEN_JSON'):
        tokens=json.loads(os.environ['DZ_TOKEN_JSON'])
        if not isinstance(tokens,list) or not tokens or any(r.get('role') not in ('reader','operator') or len(r.get('sha256',''))!=64 for r in tokens):
            raise ValueError('invalid DZ_TOKEN_JSON')
    else:
        tokens=load_tokens(os.environ['DZ_TOKEN_FILE'])
    # Refuse readiness until configured tenant stores can initialize and respond.
    for tenant in {r['tenant'] for r in tokens}:
        database=Store(root,tenant)
        try: database.rows('SELECT 1')
        finally: database.close()
    print('Tenant database initialization passed.',flush=True)
    server=ThreadingHTTPServer((host,port),handler(root,tokens))
    print('Open http://%s:%s; use TLS reverse proxy for remote access.'%(host,port),flush=True)
    try: server.serve_forever()
    finally: server.server_close()
