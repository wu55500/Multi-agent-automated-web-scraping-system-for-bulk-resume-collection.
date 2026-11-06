"""Real Chromium UI + rendered JobPosting fixture; never contacts employers."""
import hashlib,json,tempfile,threading,unittest
from http.server import ThreadingHTTPServer
from playwright.sync_api import sync_playwright
from dz.platform.api import handler
from dz.platform.store import Store
from dz.platform.network import Client
from dz.platform.render import collect_rendered


class BrowserTests(unittest.TestCase):
    def test_mobile_dashboard(self):
        with tempfile.TemporaryDirectory() as root:
            s=Store(root);s.register('test','json',consent='fixture',compliance='approved')
            s.ingest('test',[{'id':'1','title':'Python demo','raw':'熟悉 Python'}]);s.close()
            token='test-only-not-a-production-secret'
            server=ThreadingHTTPServer(('127.0.0.1',0),handler(root,[{'tenant':'personal','role':'operator','sha256':hashlib.sha256(token.encode()).hexdigest()}]))
            t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
            try:
                with sync_playwright() as p:
                    browser=p.chromium.launch();page=browser.new_page(viewport={'width':390,'height':844})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto('http://127.0.0.1:'+str(server.server_port))
                    page.fill('#token',token);page.click('#load');page.wait_for_function("document.querySelector('#output').textContent.includes('Python demo')")
                    page.click('[data-tab="audit"]');page.wait_for_function("document.querySelector('#output').textContent.includes('true')")
                    self.assertEqual(errors,[])
                    self.assertLessEqual(page.evaluate('document.documentElement.scrollWidth'),390)
                    page.screenshot(path='browser-mobile.png',full_page=True);browser.close()
            finally:server.shutdown();server.server_close();t.join()
    def test_dynamic_jobposting_render(self):
        with tempfile.TemporaryDirectory() as root:
            s=Store(root);s.register('test','jsonld',endpoint='https://fixture.example/job',interval=0,consent='fixture',compliance='approved')
            html=b'''<html><body><script>let s=document.createElement('script');s.type='application/ld+json';s.textContent=JSON.stringify({'@type':'JobPosting',title:'Rendered Python',description:'SQL'});document.body.append(s);</script></body></html>'''
            def transport(url):return 200,{'Content-Type':'text/html'},b'User-agent: *\nAllow: /' if url.endswith('robots.txt') else html
            rows=collect_rendered(Client(s,'test',transport),'https://fixture.example/job')
            self.assertEqual(rows[0]['title'],'Rendered Python');s.close()

if __name__=='__main__':unittest.main()
