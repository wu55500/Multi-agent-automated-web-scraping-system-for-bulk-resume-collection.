"""Independent reference-sample coverage with Wilson binomial interval."""
import math


def evaluate_sample(store,sample):
    ids=sample.get('canonical_ids')
    if not sample.get('provenance') or not isinstance(ids,list) or not ids or any(not isinstance(x,str) or not x for x in ids):
        raise ValueError('nonempty canonical_ids and sampling provenance required')
    if len(set(ids))!=len(ids):raise ValueError('duplicate reference sample identities')
    found={r['canonical_id'] for r in store.rows('SELECT DISTINCT canonical_id FROM postings')}
    n=len(ids);k=sum(i in found for i in ids);p=k/n;z=1.959963984540054
    den=1+z*z/n;center=(p+z*z/(2*n))/den
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    lo,hi=max(0,center-radius),min(1,center+radius)
    return {'matched':k,'sample_size':n,'sample_coverage':p,'wilson_95':[lo,hi],
            'sample_lower_bound_at_least_90_percent':lo>=.9,'provenance':sample['provenance'],
            'warning':'Interval assumes a representative independent probability sample and correct linkage. This tool does not certify those assumptions or market-wide 90% coverage.'}
