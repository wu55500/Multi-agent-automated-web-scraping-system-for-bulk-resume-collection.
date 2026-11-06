"""Bounded HTTPS transport. Redirects/proxies disabled; use network egress rules in production."""
import ipaddress
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from email.utils import parsedate_to_datetime

UA = 'JobRequirementsBot/5.0'


def validate_url(url):
    p = urllib.parse.urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443):
        raise ValueError('public HTTPS URL without credentials required')
    addresses = socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('non-public destination refused')
    return p


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(url, data=None, headers=None, timeout=20):
    validate_url(url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    req = urllib.request.Request(url,data=data,headers={'User-Agent':UA,**(headers or {})})
    with opener.open(req,timeout=timeout) as r:
        body = r.read(5_000_001)
        if len(body)>5_000_000:
            raise ValueError('response exceeds 5MB')
        return r.status,dict(r.headers),body


class Client:
    def __init__(self, store, source, transport=request):
        self.store,self.source,self.transport = store,source,transport
        self.robots = {}

    def _call(self,url):
        s = self.store.gate(self.source)
        allowed = urllib.parse.urlsplit(s['endpoint']).netloc
        if urllib.parse.urlsplit(url).netloc != allowed:
            raise PermissionError('URL outside registered source origin')
        # Request slots are shared by workers and persisted between invocations.
        with self.store.tx():
            s = self.store.gate(self.source)
            now = time.time()
            if s['blocked_until']>now:
                raise PermissionError('source circuit open; retry after cooldown')
            slot = max(now,s['next_request'])
            if slot-now>30:
                raise PermissionError('source busy; retry later')
            self.store.db.execute('UPDATE dim_source SET next_request=? WHERE id=?',(slot+s['interval'],self.source))
        if slot>now: time.sleep(slot-now)
        t = time.monotonic()
        try:
            status,headers,body = self.transport(url)
            self.last_headers = headers
            kind = 'ok'
            low = body[:100000].lower()
            if b'<html' in low and any(x in low for x in (b'captcha',b'verify you are human',b'cf-chl-')):
                kind = 'captcha'
                self.store.db.execute('UPDATE dim_source SET blocked_until=? WHERE id=?',(time.time()+3600,self.source))
            self.store.event(self.source,status,kind,(time.monotonic()-t)*1000)
            if kind == 'captcha': raise PermissionError('human verification required')
            if not 200<=status<300: raise ValueError('non-success response')
            return body
        except urllib.error.HTTPError as e:
            cooldown = 300 if e.code == 429 else 60
            retry = e.headers.get('Retry-After','')
            try: cooldown = max(cooldown,float(retry))
            except ValueError:
                try: cooldown = max(cooldown,parsedate_to_datetime(retry).timestamp()-time.time())
                except (ValueError,TypeError): pass
            self.store.db.execute('UPDATE dim_source SET blocked_until=? WHERE id=?',(time.time()+min(86400,cooldown),self.source))
            self.store.event(self.source,e.code,'http_error',(time.monotonic()-t)*1000)
            raise
        except (OSError,ValueError) as e:
            self.store.event(self.source,0,'transport_error',(time.monotonic()-t)*1000,type(e).__name__)
            raise

    def get(self,url):
        p = urllib.parse.urlsplit(url)
        origin = p.scheme+'://'+p.netloc
        if origin not in self.robots:
            rp = urllib.robotparser.RobotFileParser()
            try:
                body = self._call(origin+'/robots.txt')
                rp.parse(body.decode('utf-8','replace').splitlines())
            except urllib.error.HTTPError as e:
                if e.code not in (404,410): raise
                rp.parse([])
                self.store.db.execute('UPDATE dim_source SET blocked_until=0 WHERE id=?',(self.source,))
            self.robots[origin] = rp
        rp = self.robots[origin]
        if not rp.can_fetch(UA,url):
            self.store.event(self.source,403,'robots_denied')
            raise PermissionError('robots disallows URL')
        delay = rp.crawl_delay(UA) or rp.crawl_delay('*') or 0
        if delay:
            self.store.db.execute('UPDATE dim_source SET interval=max(interval,?) WHERE id=?',(delay,self.source))
        return self._call(url)

    def json(self,url):
        return json.loads(self.get(url))
