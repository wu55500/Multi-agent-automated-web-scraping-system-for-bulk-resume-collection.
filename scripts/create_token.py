"""Create a local token registry; token is printed only on this interactive command."""
import argparse,hashlib,json,secrets
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('--tenant',default='personal'); p.add_argument('--role',choices=['reader','operator'],default='operator'); p.add_argument('--out',default='var/tokens.json'); a=p.parse_args()
token=secrets.token_urlsafe(32); path=Path(a.out); path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
records=json.loads(path.read_text()) if path.exists() else []
records.append({'sha256':hashlib.sha256(token.encode()).hexdigest(),'tenant':a.tenant,'role':a.role})
with path.open('w') as f: json.dump(records,f)
path.chmod(0o600); print(token)
