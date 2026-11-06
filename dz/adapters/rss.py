"""RSS 2 / Atom 1 parser; no network, DTDs rejected."""
import xml.etree.ElementTree as ET
from urllib.parse import urljoin
from ..collect import strip_html
from ..platform.store import digest


def parse(data, base=''):
    if len(data)>5_000_000 or b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('unsafe or oversized XML')
    root = ET.fromstring(data)
    rows = []
    for node in root.iter():
        if node.tag.split('}')[-1] not in ('item','entry'): continue
        fields = {}
        for child in node:
            key=child.tag.split('}')[-1]
            value=''.join(child.itertext())
            if key=='link':
                if child.get('rel','alternate')=='alternate': fields['link']=child.get('href') or value
            else: fields[key]=value
        raw=strip_html(fields.get('encoded') or fields.get('content') or fields.get('description') or fields.get('summary') or fields.get('title',''))
        url=urljoin(base,fields.get('link',''))
        rows.append({'id':fields.get('guid') or fields.get('id') or url or digest(raw),
                     'title':fields.get('title',''), 'raw':raw,'source_url':url,
                     'published_at':fields.get('published') or fields.get('pubDate') or fields.get('updated','')})
    return rows
