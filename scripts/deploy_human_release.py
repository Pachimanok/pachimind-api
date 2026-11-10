"""Constrained code-only release; never performs decisions against the real vault."""
import fcntl,hashlib,hmac,json,os,pwd,shutil,socket,subprocess,sys,tarfile,tempfile,time
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
BASE=Path('/srv/pachimind')
FILES={'api/app/main.py','api/app/core/vault_parser.py','api/app/models/note.py','api/app/core/meeting_capture.py',
       'api/app/core/human_review.py','api/app/core/human_note_review.py','api/app/routers/human.py',
       'web/dist/index.html','web/dist/server.cjs','web/dist/relationship-review.js','web/dist/human.js','web/dist/human.css'}
def require(ok,label):
    if not ok:raise RuntimeError(label)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def target(relative):
    component,name=relative.split('/',1);require(component in {'api','web','mcp'},'Invalid component')
    root=BASE/('node' if component=='web' else component);p=root/name
    require(not p.is_symlink() and p.resolve().is_relative_to(root.resolve()),'Unsafe destination');return p
def run(args):subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def pid(unit):return subprocess.check_output(['systemctl','show',unit,'-p','MainPID','--value'],text=True).strip()
def bindings(unit,names):
    entries=Path('/proc/'+pid(unit)+'/environ').read_bytes().split(b'\0')
    result={name:next((e.split(b'=',1)[1].decode() for e in entries if e.startswith(name.encode()+b'=')),None) for name in names}
    require(all(result.values()),'Required configured service binding unavailable');return result

def get(url,headers=None):
    try:
        with urlopen(Request(url,headers=headers or {}),timeout=30) as r:return r.status,r.read(),r.headers
    except HTTPError as e:return e.code,b'',e.headers

def healthy():
    for _ in range(40):
        try:
            status,body,_=get('http://127.0.0.1:8000/health')
            if status==200 and json.loads(body).get('vault_connected') is True:return
        except (OSError,ValueError):pass
        time.sleep(.5)
    raise RuntimeError('API health check failed')
def node_healthy():
    for _ in range(40):
        try:
            if get('http://127.0.0.1:3000/')[0]==200:return
        except OSError:pass
        time.sleep(.5)
    raise RuntimeError('Node health check failed')
def atomic(source,dest,uid,gid,mode):
    fd,tmp=tempfile.mkstemp(prefix='.human-release-',dir=dest.parent)
    try:
        with os.fdopen(fd,'wb') as out:out.write(source.read_bytes());out.flush();os.fsync(out.fileno())
        os.chown(tmp,uid,gid);os.chmod(tmp,mode);os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
def verify(backup):
    state=json.loads((backup/'state.json').read_text());manifest=state['manifest']
    for rel,row in manifest['files'].items():require(sha(target(rel))==row['after'],'Installed code mismatch')
    for rel,expected in manifest['preserved'].items():require(sha(target(rel))==expected,'Preserved code changed')
    require(pid('pachimind-mcp')==state['mcp_pid'],'MCP restarted unexpectedly')
    healthy();node_healthy()
    web=bindings('pachimind-node',['AUTH_SECRET','FRONTEND_PASSWORD']);api=bindings('pachimind-api',['PM_API_KEY','API_KEYS'])
    token=hmac.new(web['AUTH_SECRET'].encode(),web['FRONTEND_PASSWORD'].encode(),hashlib.sha256).hexdigest()
    headers={'Authorization':'Bearer '+token};base='https://pachimind.rail.ar'
    status,body,h=get(base+'/api/human/summary',headers)
    require(status==200 and 'no-store' in h.get('Cache-Control',''),'Owner inbox unavailable or cacheable')
    data=json.loads(body);require(isinstance(data.get('total_pending'),int) and set(data['counts'])=={'links','person','meeting','note'},'Unexpected inbox schema')
    require(get(base+'/api/human/summary')[0]==401,'Anonymous inbox access')
    require(get(base+'/api/human/summary',{'X-API-Key':api['PM_API_KEY']})[0]==401,'API key impersonated owner session')
    keys=json.loads(api['API_KEYS']);reader=next((k for k,v in keys.items() if v=='ai_context'),None);require(bool(reader),'IA reader unavailable')
    require(get('http://127.0.0.1:8000/human/summary',{'X-API-Key':reader})[0]==403,'IA key accessed human inbox')
    require(get('http://127.0.0.1:8000/human/summary',{'X-API-Key':api['PM_API_KEY'],'X-PachiMind-Actor':'assistant'})[0]==403,'Assistant actor accessed human inbox')
    require(get(base+'/vault/associations?view=all&per_page=1',{'X-API-Key':reader,'X-PachiMind-Actor':'assistant'})[0]==200,'Read-only associations regressed')
    # Only three already-authorized proposal checks; no inventory/body export or decisions.
    for item in manifest.get('known_pending_checks', []):
        status,body,_=get(base+'/api/human/items/links/'+item,headers)
        require(status==200,'Known pending proposal unavailable')
        detail=json.loads(body);require(detail.get('state')=='pending' and detail.get('validation',{}).get('ok') is True,'Known pending proposal no longer valid')
    for name in ['index.html','human.js','human.css','relationship-review.js']:
        rel='web/dist/'+name;status,body,h=get(base+'/'+('' if name=='index.html' else name)+'?v='+manifest['files'][rel]['after'][:12])
        require(status==200 and hashlib.sha256(body).hexdigest()==manifest['files'][rel]['after'],'HTTPS asset mismatch')
        if name=='index.html':require('no-store' in h.get('Cache-Control',''),'Index cache policy missing')
    print('CHECKS: owner inbox HTTPS, anonymous/key rejection, IA/assistant isolation, 3 known proposals pending and valid, asset hashes, read-only associations and unchanged MCP OK. No decisions performed.',flush=True)
def restore(backup):
    state=json.loads((backup/'state.json').read_text());manifest=state['manifest'];require(set(manifest['files'])==FILES,'Invalid rollback manifest')
    for rel,row in manifest['files'].items():
        p=target(rel);require(not p.exists() or sha(p) in {row['before'],row['after']},'Code changed after release; stop')
        if row['before'] is not None:require(sha(backup/'code'/rel)==row['before'],'Backup hash mismatch')
    for unit in ['pachimind-node','pachimind-api']:run(['systemctl','stop',unit])
    for rel,row in manifest['files'].items():
        p=target(rel)
        if row['before'] is None:
            if p.exists():p.unlink()
        else:atomic(backup/'code'/rel,p,row['uid'],row['gid'],row['mode'])
    for unit in ['pachimind-api','pachimind-node']:run(['systemctl','start',unit])
    healthy();node_healthy()
    print('ROLLBACK: code/assets restored; original vault, sidecar history, credentials and OAuth preserved.',flush=True)
def stage(archive,expected):
    require(sha(archive)==expected,'Archive checksum mismatch')
    s=Path(tempfile.mkdtemp(prefix='human-stage-',dir=BASE))
    with tarfile.open(archive) as t:t.extractall(s,filter='data')
    manifest=json.loads((s/'release-manifest.json').read_text());require(set(manifest['files'])==FILES,'Invalid manifest')
    for rel,row in manifest['files'].items():require(sha(s/rel)==row['after'],'Staged source mismatch')
    env=os.environ.copy();env.update(VAULT_PATH=str(s/'synthetic-unused'),API_KEYS='{}',PM_API_KEY='',NODE_URL='http://127.0.0.1:9',PYTHONDONTWRITEBYTECODE='1')
    with (s/'tests.log').open('w') as log:
        result=subprocess.run([str(BASE/'api/.venv/bin/python'),'-m','unittest','discover','-s','tests','-v'],cwd=s/'api',env=env,stdout=log,stderr=subprocess.STDOUT)
    require(result.returncode==0,'Staged synthetic tests failed')
    for line in (s/'tests.log').read_text().splitlines()[-4:]:print(line)
    run(['node','--check',str(s/'web/dist/server.cjs')])
    (s/'READY').write_text(sha(s/'release-manifest.json'));print('STAGE:',s,flush=True)
def deploy(s):
    require(s.parent==BASE and s.name.startswith('human-stage-'),'Invalid stage')
    require((s/'READY').read_text()==sha(s/'release-manifest.json'),'Stage not verified')
    manifest=json.loads((s/'release-manifest.json').read_text());require(set(manifest['files'])==FILES,'Invalid manifest')
    for rel,row in manifest['files'].items():
        p=target(rel);require(sha(s/rel)==row['after'],'Staged file changed')
        require((not p.exists()) if row['before'] is None else sha(p)==row['before'],'Production baseline changed')
    for rel,expected in manifest['preserved'].items():require(sha(target(rel))==expected,'Preserved code changed')
    for unit in ['pachimind-api','pachimind-node','pachimind-mcp']:require(pid(unit)!='0','Expected active service')
    bindings('pachimind-node',['AUTH_SECRET','FRONTEND_PASSWORD']);bindings('pachimind-api',['PM_API_KEY','API_KEYS'])
    backup=Path(tempfile.mkdtemp(prefix='human-backup-',dir=BASE))
    for rel,row in manifest['files'].items():
        if row['before'] is not None:
            p=target(rel);st=p.stat();row.update(uid=st.st_uid,gid=st.st_gid,mode=st.st_mode&0o777)
            b=backup/'code'/rel;b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,b);require(sha(b)==row['before'],'Backup mismatch')
    (backup/'state.json').write_text(json.dumps({'manifest':manifest,'mcp_pid':pid('pachimind-mcp')},indent=2));shutil.copy2(__file__,backup/'release.py')
    print('BACKUP:',backup,flush=True);owner=pwd.getpwnam('pachimind')
    try:
        for unit in ['pachimind-node','pachimind-api']:run(['systemctl','stop',unit])
        for rel in sorted(FILES):atomic(s/rel,target(rel),owner.pw_uid,owner.pw_gid,0o640)
        for unit in ['pachimind-api','pachimind-node']:run(['systemctl','start',unit])
        verify(backup)
    except BaseException:
        restore(backup);raise
    (backup/'DEPLOYED').write_text(manifest['api_commit']+'\n'+manifest['web_commit']+'\n')
    print('DEPLOYED: Humano and pending-link review. No business item approved/declined, no permission changes.',flush=True)
def main():
    os.umask(0o077);require(os.geteuid()==0 and socket.gethostname()=='srv920347','Designated VPS only')
    lock=(BASE/'.human-release.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    mode=sys.argv[1]
    if mode=='stage':stage(Path(sys.argv[2]),sys.argv[3])
    elif mode=='deploy':deploy(Path(sys.argv[2]).resolve())
    elif mode in {'verify','rollback'}:
        backup=Path(sys.argv[2]).resolve();require(backup.parent==BASE and backup.name.startswith('human-backup-'),'Invalid backup')
        (verify if mode=='verify' else restore)(backup)
    else:raise RuntimeError('Unknown operation')
if __name__=='__main__':
    try:main()
    except BaseException as exc:
        print('Release stopped:',type(exc).__name__,str(exc) if isinstance(exc,RuntimeError) else '(details suppressed)',flush=True);sys.exit(1)
