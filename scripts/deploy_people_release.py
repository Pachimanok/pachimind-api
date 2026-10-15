"""Fixed Personas release. Private backup, code-only install and automatic rollback."""
import fcntl, hashlib, json, os, pwd, shutil, signal, socket, stat, subprocess, sys, tempfile, time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
FILES = [('api/app/__init__.py', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), ('api/app/config.py', 'd4a100c06a07b4ca84ec53e524e33c4bd7915df8b58dbe95c2a159e1bb450926'), ('api/app/core/__init__.py', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), ('api/app/core/id_utils.py', 'c13cb6eb4853f0268e5105a20cef11b72e15c8101e2455c73ac6379e14bba210'), ('api/app/core/inbox_writer.py', '9c6dcd4866b7f7ad9b273840d89c3d1c698f865a998b33f1e30ce6e747aab5d3'), ('api/app/core/meeting_capture.py', '827dfa35016c0b74ba67b2ed6096b31680bae2cbe141ae4e659380cec660ba51'), ('api/app/core/note_writer.py', '147be11b980a60bed8903b5094b2a3be1a447ed6d4bfb88f6da78b4b428a73c4'), ('api/app/core/notebooklm_importer.py', 'f90750d9e1166abadeed4ac05ddefa550cc897550a3b2f1b2af5824352bf11ac'), ('api/app/core/people.py', '14b9fab0d6f377d35c925ed07ad8cc1739c68a181ae993447431c1dfc52dead8'), ('api/app/core/project_memory.py', '532f591ee2d810a47602af64a236ee38dae76f57f5a54ef48c556b575a40bb4b'), ('api/app/core/todo.py', 'be7fd84c321f4bcf2c866391ab3ba93e513ac92a7a7fc6cf84518577067ba656'), ('api/app/core/vault_index.py', 'dbf18822337c41b6d3876766164996893b1bf19827764e326fcd019a560214ca'), ('api/app/core/vault_linker.py', '3a8a703d18890d6575dafae6bdc6ffc17413e7efb928d0b0cc350509823fa5db'), ('api/app/core/vault_parser.py', '9eb083b5001ec23150d802aee18a000c655ed5c9434a3b7b90724e1672375112'), ('api/app/core/vault_watcher.py', '18a9a45e7bca226c920367f3703645373557338c5bf447b9185c92b6eb1e7124'), ('api/app/main.py', 'dc8e47c90706a3dc8eb99e1a3d9790ec8e8e14afb1bbbc085edd448a684dcff0'), ('api/app/middleware/__init__.py', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), ('api/app/middleware/auth.py', '6dafeae92da1a5577a3ca2e92c35d4daaed8eabc10ba0b82ed073ad9b06b9289'), ('api/app/middleware/permissions.py', '11b26e5fac016a7627a674529cebd2066023ac030f1db0f28151009e09a1a0cb'), ('api/app/models/__init__.py', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), ('api/app/models/filters.py', '9c22c5a8b0cbd717b9b5a3a820da8a8faf1b496b2dfab21af2ca1d2d3f138df5'), ('api/app/models/meetings.py', '5b753b2882685e7939afdcc19ca9ee956c412e26666de751a7a98e6a9ad52f83'), ('api/app/models/note.py', '76eba4821849c4bb73490f88fbfe57ec4235ad48b98f2288ba6e913a1bf8f956'), ('api/app/models/people.py', '16a4ed62ad6deb6a9eedf50e3468b6a05c175b0c738855f1c4169e725ee199c9'), ('api/app/models/responses.py', '22cd7ca45f4838ec0c863d2c0083741b76d3f0eb6f28051df6e3c7e80c334d70'), ('api/app/routers/__init__.py', 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'), ('api/app/routers/actions.py', '02185a4e869b8029fcf25297c37e5ec33987c86552122979da6177b9d6e00d90'), ('api/app/routers/ai.py', '34f4a1fcd00e8f32714395599002493d2109041155387121d66053d93a111e57'), ('api/app/routers/attachments.py', '471b6aa5d92b7615eaaada798b86383cc3105d6c0e36d151700c7649a5894c05'), ('api/app/routers/clients.py', 'd3743207d26e1b1c9af42a36dd1a8127804e51ecb4bc156b15418e1c9ded9249'), ('api/app/routers/decisions.py', '8377f080e31d374179d083bb39f657fb12b3aa579565efa97a27c6aeb9c93de4'), ('api/app/routers/health.py', '70e72e88b66d2d068b0cbbc2c62509dab9a7b089737d402841179bb255727308'), ('api/app/routers/inbox.py', 'acd13f02df9a239406aa0d67ee5275d3b7cb0161a2be818f26488ff58c051122'), ('api/app/routers/links.py', 'b01432c77aca1fb7ae027fc06ae87b23f279ab155402565a094de56670ffee84'), ('api/app/routers/meetings.py', 'af2e22a02ef508bbcec0f57acee32b08ee3d332fadddf47c5ec5c01d19a16a0e'), ('api/app/routers/notebooklm.py', 'a6849cdffd3fc129bd15503cb1d707681f7d0bf4570153d9d91200fa46a2c5c0'), ('api/app/routers/notes.py', 'f6045f761888bb081ed9cb79a79155b97ee441c3364f9862db4ae871484340bd'), ('api/app/routers/people.py', '70600ce0bf2baa3268e223c6b791286ccd527f739971fc518658df6d3156954a'), ('api/app/routers/people_workspace.py', 'ce0c43c35440ed45d7aec31e5e4f8d5ab373e5689485c90cb194d51986c4a063'), ('api/app/routers/projects.py', '6152567b94ed0774e8fde0cc0d6f4e1032d8742c7f2207a32b9d4ffa4b81a09d'), ('api/app/routers/search.py', '36eff189fa9477b9c5a28e26332c674cc07c38aa86309304f8253525856c7b86'), ('api/app/routers/vault.py', '093923d19251bbad86c82ebdd67b0eca9335e31f13cc083dde160ec0cb685e2e'), ('api/requirements.txt', '46e06610a94d52097c893ee04ebd97bb1782c1c979cd5ef12f55548a5a0ae07c'), ('web/dist/icon.svg', 'd8ba66707c44f1e0c8bf3a7039514879762c88012e5a0b2f4cdb7d87566496b5'), ('web/dist/index.html', 'a3339fcf56c0402acdb1ce54c06eecf2377309801f6cab81dfc67505f3c6a22b'), ('web/dist/manifest.json', 'bfaa99e2f73ee0697fecdc40585fa1c8b0d1510521fe01232f1b260622f55ebd'), ('web/dist/people.css', 'f0dbaa13c2b703a499df60a01d503cc64392343cbdfbfb4b712268f4df41f00a'), ('web/dist/people.js', '4dcf41060b53897a34ef5bea56646f883cd907d1d502fdba53342f62c79e61bd'), ('web/dist/server.cjs', '95dd14a7f388dd7402caae85ae5088c4103784a95ea3e019735479ba88b258b7'), ('web/package-lock.json', 'b4eef8970b1c560e8c9cfc49da20b07f07fcf05e4e43c5455060bc9a7c455863'), ('web/package.json', '23afb6a2205ea907b5be6f369275efe12d06922ad331bed68c8f975fce6c4902'), ('mcp/auth.py', '9602cf3e51a4f705da9733320e1d92b2b7f4927cd05046c60516daef3ccab148'), ('mcp/people_types.py', '333f066d06b7328df3e8d585ae61cc6e20d4479e864f976adc45656efe039bea'), ('mcp/requirements.txt', '559dc198bf9693c8de00f287f800379b22abd587056d6420ef655f1863e9290a'), ('mcp/server.py', '585750bf9882326f1fdabb71c66d7f5250c55a6a4e328143025f335225897fab')]
BASE=Path('/srv/pachimind')
ROOTS={'api':BASE/'api','web':BASE/'node','mcp':BASE/'mcp'}
UNITS=['pachimind-api','pachimind-node','pachimind-mcp']
EXTRAS=['vault-sync.timer','vault-sync.service','weekly-digest.timer','weekly-digest.service']

def run(args):
    return subprocess.run(args,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def active(unit):
    return subprocess.run(['systemctl','is-active','--quiet',unit]).returncode==0

def env_for(unit):
    pid=subprocess.check_output(['systemctl','show',unit,'-p','MainPID','--value'],text=True).strip()
    return dict(e.split(b'=',1) for e in Path('/proc/'+pid+'/environ').read_bytes().split(b'\0') if b'=' in e)

def request(url,key=None):
    headers={'X-API-Key':key.decode()} if key else {}
    try:
        with urlopen(Request(url,headers=headers),timeout=15) as r:
            return r.status,r.read()
    except HTTPError as e:
        return e.code,b''

def target(relative):
    component,name=relative.split('/',1)
    root=ROOTS[component]
    dest=root/name
    if not dest.resolve().is_relative_to(root.resolve()) or dest.is_symlink():
        raise RuntimeError('Unsafe target: '+relative)
    return dest

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def install(source,dest,uid,gid,mode):
    missing=[];parent=dest.parent
    while not parent.exists():
        missing.append(parent);parent=parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o750);os.chown(directory,uid,gid)
    fd,tmp=tempfile.mkstemp(prefix='.people-release-',dir=dest.parent)
    try:
        with os.fdopen(fd,'wb') as f:
            with source.open('rb') as original: shutil.copyfileobj(original,f)
            f.flush();os.fsync(f.fileno())
        os.chown(tmp,uid,gid);os.chmod(tmp,mode);os.replace(tmp,dest)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def restore(backup):
    manifest=json.loads((backup/'before.json').read_text())
    allowed={relative for relative,_ in FILES}
    if {r['relative'] for r in manifest} != allowed:raise RuntimeError('Invalid rollback manifest')
    # Validate every backup BEFORE touching production.
    for row in manifest:
        if row['exists'] and sha(backup/'code'/row['relative'])!=row['sha256']:
            raise RuntimeError('Invalid backup hash: '+row['relative'])
    for unit in reversed(UNITS):run(['systemctl','stop',unit])
    for row in manifest:
        dest=target(row['relative'])
        if row['exists']:
            install(backup/'code'/row['relative'],dest,row['uid'],row['gid'],row['mode'])
        elif dest.exists():dest.unlink()
    for unit in UNITS:run(['systemctl','start',unit])
    if not all(active(u) for u in UNITS):raise RuntimeError('Rollback services not active')
    print('ROLLBACK: previous code restored; vault, env and OAuth were not restored or deleted.',flush=True)

def checks(api_key):
    for url in ['http://127.0.0.1:8000/health','http://127.0.0.1:3000/health','http://127.0.0.1:8001/mcp-health']:
        ok=False
        for attempt in range(20):
            try:
                code,data=request(url)
                if code==200 and json.loads(data).get('status')=='ok':ok=True;break
            except (OSError,ValueError):pass
            time.sleep(1)
        if not ok:raise RuntimeError('Local health check failed')
    for url in ['http://127.0.0.1:8000/people/directory','http://127.0.0.1:3000/people/directory','https://pachimind.rail.ar/people/directory']:
        code,_=request(url)
        if code!=401:raise RuntimeError('Unauthenticated route must return 401: '+url+' status '+str(code))
    code,_=request('https://pachimind.rail.ar/api/v1/people/directory')
    if code not in (401,404):raise RuntimeError('Unexpected public API/v1 access status '+str(code))
    if code==404:print('API/v1 not published; checking existing authenticated gateway.',flush=True)
    code,data=request('http://127.0.0.1:8000/health')
    if code!=200 or json.loads(data).get('vault_connected') is not True:raise RuntimeError('Vault not connected')
    code,_=request('http://127.0.0.1:8001/mcp')
    if code!=401:raise RuntimeError('MCP must require OAuth')
    code,data=request('http://127.0.0.1:8000/people/directory?per_page=1',api_key)
    if code!=200 or 'results' not in json.loads(data):raise RuntimeError('Authorized directory read failed')
    code,data=request('https://pachimind.rail.ar/people.js')
    if code!=200 or b'renderPersonalEditor' not in data:raise RuntimeError('Published Personas asset missing')
    code,data=request('http://127.0.0.1:8001/.well-known/oauth-protected-resource/mcp')
    if code!=200 or set(json.loads(data).get('scopes_supported',[]))!={'pachimind:read','pachimind:write'}:
        raise RuntimeError('OAuth scope discovery failed')
    code,_=request('https://pachimind.rail.ar/mcp-health')
    if code!=200:raise RuntimeError('Published MCP health failed')
    if not all(active(u) for u in UNITS):raise RuntimeError('A service is not active')
    print('CHECKS: local services, authenticated read, public access rejection, HTTPS asset and OAuth discovery OK.',flush=True)

def main():
    os.umask(0o077)
    if os.geteuid()!=0 or socket.gethostname()!='srv920347':raise RuntimeError('Run as root on srv920347 only')
    lock=(BASE/'.people-deploy.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    if len(sys.argv)==3 and sys.argv[1]=='--rollback':
        backup=Path(sys.argv[2]).resolve()
        if backup.parent!=BASE or not backup.name.startswith('personas-backup-'):raise RuntimeError('Invalid backup path')
        restore(backup);return
    if len(sys.argv)!=2:raise RuntimeError('Usage: python3 script.py STAGE')
    stage=Path(sys.argv[1]).resolve()
    if stage.parent!=BASE or not stage.name.startswith('pachimind-personas-stage-') or not (stage/'READY').is_file():
        raise RuntimeError('Verified staging directory required')
    for relative,expected in FILES:
        if sha(stage/relative)!=expected:raise RuntimeError('Staging hash mismatch: '+relative)
        target(relative)
    if not all(active(u) for u in UNITS):raise RuntimeError('Expected all three services active')
    envs={u:env_for(u) for u in UNITS}
    api_env=envs['pachimind-api'];keys=json.loads(api_env.get(b'API_KEYS',b'{}'))
    key=api_env.get(b'PM_API_KEY',b'')
    if not key or keys.get(key.decode())!='personal':raise RuntimeError('API internal personal credential is not configured')
    for unit in ['pachimind-node','pachimind-mcp']:
        if envs[unit].get(b'PM_API_KEY')!=key:raise RuntimeError('Internal credentials differ; values omitted')
    if not any(v=='ai_context' for v in keys.values()):raise RuntimeError('Missing read-only AI credential')
    vault=Path(api_env.get(b'VAULT_PATH',b'').decode()).resolve()
    if vault!=BASE/'vault' or not vault.is_dir():raise RuntimeError('Unexpected vault path')
    # No environment/config files are copied or edited by this deployment.
    run(['apache2ctl','configtest'])
    size=int(subprocess.check_output(['du','-sb',str(vault)],text=True).split()[0])
    if shutil.disk_usage(BASE).free < size+1024**3:raise RuntimeError('Not enough free disk for private vault backup plus 1 GiB')
    backup=Path(tempfile.mkdtemp(prefix='personas-backup-',dir=BASE))
    print('BACKUP:',backup,flush=True)
    shutil.copy2(__file__,backup/'deploy.py')
    paused=[u for u in EXTRAS if active(u)]
    (backup/'paused-units.json').write_text(json.dumps(paused))
    changed=False;stopped=False
    try:
        for unit in paused:run(['systemctl','stop',unit])
        stopped=True
        for unit in reversed(UNITS):run(['systemctl','stop',unit])
        rows=[]
        for relative,expected in FILES:
            dest=target(relative);row={'relative':relative,'exists':dest.exists()}
            if dest.exists():
                info=dest.stat();saved=backup/'code'/relative;saved.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(dest,saved)
                row.update(uid=info.st_uid,gid=info.st_gid,mode=stat.S_IMODE(info.st_mode),sha256=sha(saved))
            rows.append(row)
        (backup/'before.json').write_text(json.dumps(rows,indent=2)+'\n')
        # Preserve all vault files including .pachimind; exclude only git internals.
        run(['tar','--exclude=./.git','-C',str(vault),'-cpf',str(backup/'vault.tar'),'.'])
        run(['tar','-tf',str(backup/'vault.tar')])
        print('BACKUP verified; installing code only.',flush=True)
        account=pwd.getpwnam('pachimind')
        changed=True
        for relative,expected in FILES:
            install(stage/relative,target(relative),account.pw_uid,account.pw_gid,0o640)
        for unit in UNITS:run(['systemctl','start',unit])
        checks(key)
        (backup/'DEPLOYED').write_text('Personas fb46b27 / 6b3f679 / fbc9383; checked read-only.\n')
        print('DEPLOYED. Backup and rollback helper:',backup,flush=True)
        print('No person, relationship, meeting or proposal was created by checks.',flush=True)
    except BaseException:
        print('STOP: deployment incomplete.',flush=True)
        if changed:
            try:restore(backup)
            except BaseException:print('ROLLBACK FAILED. Keep backup and inspect services; do not delete data.',flush=True)
        elif stopped:
            for unit in UNITS:
                subprocess.run(['systemctl','start',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        raise
    finally:
        for unit in paused:
            subprocess.run(['systemctl','start',unit],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

if __name__=='__main__':
    def interrupted(signum,frame):raise RuntimeError('Interrupted; rolling back if needed')
    signal.signal(signal.SIGTERM,interrupted)
    try:main()
    except BaseException as exc:
        # No request headers, environment, application bodies or tracebacks in output.
        print('STOP:',type(exc).__name__,str(exc) if isinstance(exc,RuntimeError) else 'Operation failed; details withheld to protect credentials',file=sys.stderr)
        sys.exit(1)
