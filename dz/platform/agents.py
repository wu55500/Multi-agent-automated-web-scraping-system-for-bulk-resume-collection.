"""Deterministic specialist pipeline; output labels never imply an uncalled LLM."""
import json
from ..extract import extract_rule
from ..score import evaluate
from ..forge import plan_projects


def analyze(store,pid,profile):
    p=store.db.execute('SELECT * FROM postings WHERE id=?',(pid,)).fetchone()
    if not p: raise ValueError('unknown posting')
    version=store.db.execute('SELECT payload FROM versions WHERE posting_id=? AND content_hash=?',(pid,p['current_hash'])).fetchone()
    raw=json.loads(version[0])['raw']; skills=extract_rule(raw).skills
    score=evaluate(skills,profile.get('mine',{}))
    # Planning is a suggestion, never a claim that the candidate completed a project.
    plans=plan_projects(score.get('gaps',[]),budget_hours=profile.get('budget_hours',8))
    evidence=[{'cid':s.cid,'text':s.evidence,'valid':s.evidence in raw} for s in skills]
    result={'posting':pid,'engine':'deterministic-rule','match':score,'learning_plan':plans,
            'audit':{'pass':all(x['valid'] for x in evidence),'evidence':evidence},
            'note':'Suggested learning projects are not completed resume experience.'}
    with store.tx(): store.audit('agent.analysis',{'posting':pid,'pass':result['audit']['pass']})
    return result


def reply(message,facts):
    if not isinstance(facts,dict): raise ValueError('facts must be an object')
    if any(x in message.lower() for x in ['薪','salary','身份证','银行卡','合同']):
        return {'intent':'sensitive','state':'needs_human','draft':None}
    if any(x in message.lower() for x in ['面试','interview','时间','schedule']):
        return {'intent':'scheduling','state':'draft','draft':'感谢邀请，请告知面试形式、预计时长和可选时间，我核对日程后确认。'}
    # Only verbatim, user-provided evidence-backed facts are inserted.
    safe=[f['text'] for f in facts.get('facts',[]) if isinstance(f,dict) and f.get('text') and f.get('evidence')]
    return {'intent':'general','state':'draft','draft':'感谢联系。'+'；'.join(safe[:3]),'engine':'template','requires_confirmation':True}
