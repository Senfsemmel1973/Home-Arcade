"""Inspect an installed RC and test import in an isolated, disposable data tree."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import pwd
import shutil
import socket
import subprocess
import sys
import uuid

def worker(base):
    assert os.geteuid()!=0
    assert base.parent==Path('/var/lib') and base.name.startswith('home-arcade-rc1-test-')
    sys.path.insert(0,'/opt/home-arcade/app')
    from factory import create
    from service import Paths,Importer,Catalog
    from webapp import App
    original=create('/etc/home-arcade/settings.json')
    paths=Paths(base/'catalog/games.json',base/'private',base/'roms/vcs2600',base/'roms/c64',base/'covers')
    test=App(Importer(paths,original.importer.schema,original.importer.profiles,Catalog(None)),original.secret,original.origin,[str(n) for n in original.networks])
    owner='rc-install-test';peer=str(next(iter(original.networks)).network_address+1)
    def call(path,method='GET',value=None,raw=None):
        data=raw if raw is not None else json.dumps(value).encode() if value is not None else b''
        env={'REQUEST_METHOD':method,'SCRIPT_NAME':'/emulator/import-api','PATH_INFO':path,'HTTP_HOST':test.host,
             'REMOTE_ADDR':peer,'REMOTE_USER':owner,'HTTP_ORIGIN':test.origin,'HTTP_X_CSRF_TOKEN':test.csrf(owner),
             'HTTP_X_FILENAME':'RC-Synthetic.prg','CONTENT_TYPE':'application/octet-stream' if raw is not None else 'application/json',
             'CONTENT_LENGTH':str(len(data)),'wsgi.input':io.BytesIO(data)}
        status=[]
        result=b''.join(test(env,lambda s,h:status.append(int(s[:3]))))
        assert status==[200],(path,status,result[:160])
        return json.loads(result)
    # Original BASIC program: 10 END. Generated here, never a shipped ROM file.
    media=bytes([1,8,7,8,10,0,128,0,0,0])
    draft=call('/preview','POST',raw=media)
    assert draft['state']=='ready',draft
    item={'token':draft['token'],'title':'RC Install Test','workId':None,'coverSha256':None}
    result=call('/commit','POST',[item]);game=result['games'][0]
    assert (base/game['rom']).read_bytes()==media
    repeated=call('/commit','POST',[item]);assert repeated['repeated']
    managed=call('/managed');assert len(managed['games'])==1
    call('/delete','POST',{'id':game['id'],'base':managed['base']})
    assert test.importer.manifest()[1]['games']==[]
    assert not any((base/'roms').rglob('*.prg'))
    print(json.dumps({'result':'PASS','preview':True,'commit':True,'duplicateCommitIdempotent':True,'managedDelete':True,'scope':'installed WSGI/backend under service user, isolated data; simulated upstream identity; no browser password read'}))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-host');parser.add_argument('--output',type=Path);parser.add_argument('--worker',type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.worker)
    assert os.geteuid()==0 and socket.gethostname().split('.')[0]==args.expect_host
    assert args.output and not args.output.exists()
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import install
    install.verify_package()
    identity=json.loads(Path('/etc/home-arcade/installation.json').read_bytes())
    assert identity['version']=='2.0.0'
    code=install.program_tree(Path('/opt/home-arcade'))
    assert code==json.loads(Path('/etc/home-arcade/program-files.json').read_bytes())
    def tree(root):return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    live=Path('/var/lib/home-arcade');before=tree(live);config_before=tree(Path('/etc/home-arcade'))
    assert json.loads((live/'catalog/games.json').read_bytes())=={'version':1,'games':[]}
    assert not any(p.is_file() for name in ('roms','covers') for p in (live/name).rglob('*'))
    account=pwd.getpwnam(identity['user'])
    base=Path('/var/lib')/('home-arcade-rc1-test-'+uuid.uuid4().hex)
    base.mkdir(mode=0o700);os.chown(base,account.pw_uid,account.pw_gid)
    try:
        for name in ('catalog','private','roms','roms/c64','roms/vcs2600','covers'):
            path=base/name;path.mkdir(mode=0o700);os.chown(path,account.pw_uid,account.pw_gid)
        catalog=base/'catalog/games.json';catalog.write_text('{"version":1,"games":[]}\n');os.chown(catalog,account.pw_uid,account.pw_gid);os.chmod(catalog,0o600)
        result=subprocess.run(['runuser','-u',identity['user'],'--','/usr/bin/python3','-I','-B',str(Path(__file__).resolve()),'--worker',str(base)],capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        import_result=json.loads(result.stdout)
    finally:
        assert base.parent==Path('/var/lib') and base.name.startswith('home-arcade-rc1-test-') and not base.is_symlink()
        shutil.rmtree(base)
    assert tree(live)==before and tree(Path('/etc/home-arcade'))==config_before
    assert install.program_tree(Path('/opt/home-arcade'))==code
    report={'result':'PASS','host':args.expect_host,'version':identity['version'],'games':0,'activeRomAndCoverFiles':0,'programFiles':len(code),
            'isolatedImport':import_result,'liveDataAndConfigurationUnchanged':True,'testFixtureRemoved':True}
    fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    if os.environ.get('SUDO_UID'):os.chown(args.output,int(os.environ['SUDO_UID']),int(os.environ['SUDO_GID']))
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
