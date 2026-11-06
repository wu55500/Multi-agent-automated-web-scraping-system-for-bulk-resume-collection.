"""Start on the device executing this script. Does not create a public URL."""
import argparse,hashlib,json,os,secrets,sys
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root))
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8771);a=p.parse_args()
state=root/'var';state.mkdir(mode=0o700,exist_ok=True)
token=secrets.token_urlsafe(32)
path=state/'local-session-token.json'
path.write_text(json.dumps([{'tenant':'personal','role':'operator','sha256':hashlib.sha256(token.encode()).hexdigest()}]));path.chmod(0o600)
os.environ['DZ_TOKEN_FILE']=str(path)
print('在运行此脚本的同一设备访问 / Open on THIS device: http://127.0.0.1:'+str(a.port))
print('本次访问令牌 / Session token: '+token,flush=True)
from dz.platform.api import serve
try:serve(str(state/'tenants'),'127.0.0.1',a.port)
except OSError as e:raise SystemExit('启动失败 / Startup failed: '+str(e))
