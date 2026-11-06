import json
from html.parser import HTMLParser
from urllib.parse import quote
from ..collect import strip_html, lever_row
from ..adapters.rss import parse as parse_rss


class LinkedData(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.parts=[]; self.documents=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('type')=='application/ld+json':
            self.active=True; self.parts=[]
    def handle_data(self,data):
        if self.active: self.parts.append(data)
    def handle_endtag(self,tag):
        if tag=='script' and self.active:
            self.documents.append(json.loads(''.join(self.parts))); self.active=False


def jsonld(html,url):
    parser=LinkedData(); parser.feed(html)
    rows=[]
    def walk(obj):
        if isinstance(obj,list):
            for x in obj: walk(x)
        elif isinstance(obj,dict):
            typ=obj.get('@type',[])
            if typ=='JobPosting' or isinstance(typ,list) and 'JobPosting' in typ:
                loc=obj.get('jobLocation',{})
                if isinstance(loc,list): loc=loc[0] if loc else {}
                address=loc.get('address',{}) if isinstance(loc,dict) else {}
                org=obj.get('hiringOrganization',{})
                ident=obj.get('identifier',{})
                rows.append({'id':str(ident.get('value') if isinstance(ident,dict) and ident.get('value') else obj.get('url') or url),
                    'title':obj.get('title',''),'raw':strip_html(obj.get('description','')),
                    'company':org.get('name','') if isinstance(org,dict) else str(org),
                    'city':address.get('addressLocality','') if isinstance(address,dict) else '',
                    'source_url':obj.get('url') or url})
            for k,v in obj.items():
                if k != '@context' and isinstance(v,(dict,list)): walk(v)
    for doc in parser.documents: walk(doc)
    return rows


def collect(client,kind,endpoint,company='',max_pages=20):
    if not 1<=max_pages<=100: raise ValueError('max_pages must be 1..100')
    if kind=='rss': return parse_rss(client.get(endpoint),endpoint)
    if kind in ('jsonld','workday'):
        # Workday customer sites exposing JobPosting are handled without relying on private APIs.
        rows=jsonld(client.get(endpoint).decode('utf-8'),endpoint)
        if not rows: raise ValueError('no public JobPosting; use authorized export or configured renderer')
        return rows
    if kind in ('json','partner'):
        data=client.json(endpoint)
        if not isinstance(data,list): raise ValueError('normalized JSON feed must be an array')
        return data
    if kind=='greenhouse':
        return [{'id':str(j['id']),'title':j['title'],'raw':strip_html(j.get('content','')),
                 'company':j.get('company_name') or company,'city':(j.get('location') or {}).get('name',''),
                 'source_url':j.get('absolute_url','')} for j in client.json(endpoint)['jobs']]
    if kind=='lever':
        rows=[]
        for j in client.json(endpoint):
            r=lever_row(j); r.update(id=str(j['id']),company=company,source_url=j.get('hostedUrl',''))
            rows.append(r)
        return rows
    if kind=='smartrecruiters':
        rows=[]; seen=set(); offset=0
        for page in range(max_pages):
            data=client.json(endpoint+('?'+ 'limit=100&offset='+str(offset)))
            items=data.get('content',[])
            for item in items:
                jid=str(item['id'])
                if jid in seen: raise ValueError('pagination repeated an id')
                seen.add(jid)
                j=client.json(endpoint.rstrip('/')+'/'+quote(jid,safe=''))
                sections=j.get('jobAd',{}).get('sections',{})
                raw='\n'.join(strip_html(v.get('text','')) for v in sections.values() if isinstance(v,dict))
                rows.append({'id':jid,'title':j.get('name',''),'raw':raw,'company':company,
                             'city':j.get('location',{}).get('city',''),'source_url':j.get('applyUrl','')})
            offset+=len(items)
            if not items or offset>=data.get('totalFound',offset): return rows
        raise ValueError('pagination limit reached; refusing silently incomplete batch')
    raise ValueError('unsupported adapter: '+kind)
