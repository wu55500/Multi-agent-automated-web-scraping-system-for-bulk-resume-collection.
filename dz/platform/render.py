"""Optional Playwright renderer for a registered public JobPosting page.
All network requests must stay at the registered origin and pass robots checks.
"""
from urllib.parse import urlsplit
from .adapters import jsonld


def collect_rendered(client,url):
    from playwright.sync_api import sync_playwright
    origin=urlsplit(url).netloc
    # Client fetch checks source state/robots and obtains HTML before browser startup.
    client.get(url)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True)
        context=browser.new_context(service_workers='block',user_agent='JobRequirementsBot/5.0')
        def route(reqroute):
            req=reqroute.request
            if req.method!='GET' or urlsplit(req.url).netloc!=origin:
                reqroute.abort(); return
            try:
                body=client.get(req.url)
                reqroute.fulfill(status=200,body=body,content_type=client.last_headers.get('Content-Type','text/html'))
            except Exception:
                reqroute.abort()
        context.route('**/*',route)
        page=context.new_page()
        page.goto(url,wait_until='networkidle',timeout=30000)
        text=page.content()
        browser.close()
    if any(x in text.lower() for x in ('captcha','verify you are human','cf-chl-')):
        client.store.event(client.source,403,'captcha')
        raise PermissionError('manual verification required')
    rows=jsonld(text,url)
    if not rows: raise ValueError('no JobPosting after rendering')
    return rows
