"""Explicit approved batch delivery to a user-configured authorized integration.

Gateway contract: HTTPS POST with Idempotency-Key, JSON {application_id,resume,posting_id}.
A 2xx with {receipt: nonempty string} confirms delivery to the gateway. A downstream
employer receipt is only as trustworthy as that authorized integration. No guessed forms.
"""
import json
import os
from .network import request


def send(store,aid,endpoint,transport=request):
    # Configuration is server-side; never accept arbitrary destinations from API clients.
    if not endpoint.startswith('https://'):
        raise ValueError('authorized gateway HTTPS endpoint required')
    key=os.environ.get('DZ_SUBMISSION_KEY','')
    if not key: raise ValueError('DZ_SUBMISSION_KEY missing')
    app=store.claim_application(aid)
    body=json.dumps({'application_id':aid,'posting_id':app['posting_id'],'resume':json.loads(app['resume'])}).encode()
    try:
        status,_,data=transport(endpoint,data=body,headers={'Content-Type':'application/json',
                        'Authorization':'Bearer '+key,'Idempotency-Key':aid})
        receipt=json.loads(data)
        if not 200<=status<300 or not isinstance(receipt.get('receipt'),str) or not receipt['receipt'].strip():
            raise ValueError('missing gateway receipt')
    except Exception as e:
        store.complete_application(aid,'uncertain',{'error_type':type(e).__name__})
        return {'id':aid,'state':'uncertain','action':'reconcile with gateway before any retry'}
    store.complete_application(aid,'submitted',receipt)
    return {'id':aid,'state':'submitted','receipt':receipt['receipt']}
