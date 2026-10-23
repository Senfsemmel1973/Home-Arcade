"""Home Arcade 2.0.0. Fresh Ubuntu 24.04 installation only.

No action without --apply. Exact repeated installs verify without mutations.
Existing different installations stop; this is not an upgrade authorization.
"""
import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import contextlib
import socket
import tarfile
import time
from urllib.request import build_opener, ProxyHandler, Request
from urllib.error import HTTPError
if os.name == 'posix':
    import grp
    import pwd

VERSION='2.0.0'
HERE=Path(__file__).resolve().parent
BACKUP=Path('/var/backups/home-arcade-install-before-'+VERSION)
CONFIG=Path('/etc/home-arcade')
APACHE=Path('/etc/apache2')
INSTALL_STARTED=False
PACKAGES=['apache2','apache2-utils','libapache2-mod-wsgi-py3','python3','python3-pil']

def lan_network(value):
    net=ipaddress.ip_network(value,strict=True)
    allowed=('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16','127.0.0.0/8') if net.version==4 else ('fc00::/7','::1/128')
    demand(any(net.subnet_of(ipaddress.ip_network(n)) for n in allowed),'Only private LAN/loopback networks permitted')
    return str(net)

def listener_settings(args,nets):
    values=getattr(args,'listen_address',None)
    demand(values,'Explicit private --listen-address required')
    addresses=[ipaddress.ip_address(x) for x in values]
    demand(len(set(addresses))==len(addresses),'Duplicate listener')
    demand(all(any(a.version==n.version and a in n for n in map(ipaddress.ip_network,nets)) for a in addresses),'Listener outside allowed LAN networks')
    return [str(a) for a in addresses]

def render_ports(addresses):
    return ''.join('Listen '+('['+a+']' if ':' in a else a)+':80\n' for a in addresses).encode()

@contextlib.contextmanager
def private_package_start(addresses):
    """Suppress apt service activation until private listeners are installed."""
    policy=Path('/usr/sbin/policy-rc.d');guard=b'#!/bin/sh\n# Home Arcade installer: defer package service startup\nexit 101\n'
    global INSTALL_STARTED
    backup=BACKUP
    demand(not backup.exists(),'Installation backup already exists; investigate before retry')
    backup.mkdir(mode=0o700)
    INSTALL_STARTED=True
    baseline={'version':VERSION,'host':socket.gethostname().split('.')[0],
              'createdUtc':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
              'newInstallation':True,'previousGames':0,'apacheExisted':Path('/etc/apache2').exists(),
              'packages':{},'dataRestorePerformed':False}
    for package in PACKAGES:
        result=subprocess.run(['dpkg-query','-W','-f=${Status} ${Version}',package],capture_output=True,text=True)
        baseline['packages'][package]={'installed':result.returncode==0,'status':result.stdout.strip()}
    put(backup/'before.json',(json.dumps(baseline,indent=2)+'\n').encode(),0o600)
    if baseline['apacheExisted']:
        archive=backup/'apache-before.tar.gz'
        with tarfile.open(archive,'x:gz') as out:out.add('/etc/apache2',arcname='apache')
        os.chmod(archive,0o600)
        restored=backup/'restore-verification';restored.mkdir(mode=0o700)
        with tarfile.open(archive) as src:src.extractall(restored,filter='data')
        def contents(root):
            return {p.relative_to(root).as_posix():('link',os.readlink(p)) if p.is_symlink() else ('file',hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob('*') if p.is_symlink() or p.is_file()}
        demand(contents(Path('/etc/apache2'))==contents(restored/'apache'),'Apache backup extraction mismatch')
    put(backup/'backup-proof.json',(json.dumps({'verified':True,'apacheConfigExtracted':baseline['apacheExisted'],
         'noPreviousApplicationOrGameData':True})+'\n').encode(),0o600)
    previous=None
    if policy.exists() or policy.is_symlink():
        s=policy.lstat();demand(stat.S_ISREG(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,'Unsafe policy-rc.d')
        previous=(policy.read_bytes(),s.st_mode&0o777,s.st_uid,s.st_gid)
        put(backup/'policy-rc.d',previous[0],0o600)
    temp=policy.with_name('policy-rc.d.home-arcade-tmp')
    put(temp,guard,0o755);os.replace(temp,policy)
    try:
        yield
        ports=Path('/etc/apache2/ports.conf')
        s=ports.lstat();demand(stat.S_ISREG(s.st_mode) and s.st_uid==0 and not s.st_mode&0o022,'Unsafe Apache ports file')
        put(backup/'ports.conf',ports.read_bytes(),0o600)
        temporary=ports.with_name('ports.conf.home-arcade-tmp')
        put(temporary,render_ports(addresses));os.replace(temporary,ports)
    finally:
        demand(policy.read_bytes()==guard,'policy-rc.d changed concurrently; manual inspection required')
        if previous:
            raw,mode,uid,gid=previous;put(temp,raw,mode,uid,gid);os.replace(temp,policy)
        else:policy.unlink()

def demand(ok,message):
    if not ok: raise RuntimeError(message)

def run(args,**kwargs):
    return subprocess.run(args,check=True,**kwargs)

def safe_path(value):
    demand(isinstance(value,str) and re.fullmatch(r'/[A-Za-z0-9_/-]+',value), 'Unsafe absolute installation path')
    p=Path(value)
    demand('..' not in p.parts and p.as_posix()==value and len(p.parts)>=3, 'Unsafe installation path')
    for q in (p,*p.parents):
        if q.exists() or q.is_symlink():
            s=q.lstat()
            demand(not stat.S_ISLNK(s.st_mode) and s.st_uid==0 and not s.st_mode & 0o022,
                   'Installation ancestors must be root-owned and not group/world writable: '+str(q))
    return p

def verify_package(ownership=True):
    manifest=json.loads((HERE/'package-manifest.json').read_bytes())
    demand(manifest.get('version')==VERSION and manifest.get('product')=='Home Arcade','Wrong package identity')
    expected=manifest['files']
    actual={p.relative_to(HERE).as_posix() for p in HERE.rglob('*') if p.is_file()}
    demand(actual==set(expected)|{'package-manifest.json','SHA256SUMS'},'Package positive-list mismatch')
    for rel,info in expected.items():
        p=HERE/rel
        demand(not p.is_symlink() and p.stat().st_nlink==1 and p.stat().st_size==info['bytes'] and
               hashlib.sha256(p.read_bytes()).hexdigest()==info['sha256'],'Package mismatch: '+rel)
    for p in (HERE,*HERE.rglob('*')):
        demand(not p.is_symlink(),'Symlinks are not allowed in the package')
        if os.name=='posix' and ownership:
            s=p.stat()
            demand(s.st_uid==0 and not s.st_mode & 0o022,'Package must be root-owned and not group/world writable')
    if os.name=='posix' and ownership:
        for parent in HERE.parents:
            s=parent.lstat()
            demand(stat.S_ISDIR(s.st_mode) and s.st_uid==0 and not s.st_mode & 0o022,
                   'Package ancestors must be root-owned and not group/world writable')
    demand((HERE/'schema/manifest.js').read_bytes()==(HERE/'web/manifest.js').read_bytes(),'Schema copies differ')
    demand(json.loads((HERE/'empty-catalog.json').read_bytes())=={'version':1,'games':[]},'Catalog not empty')
    sums={}
    for line in (HERE/'SHA256SUMS').read_text(encoding='ascii').splitlines():
        checksum,name=line.split('  ',1)
        demand(name not in sums and re.fullmatch('[0-9a-f]{64}',checksum),'Invalid checksum list')
        sums[name]=checksum
    wanted={rel:info['sha256'] for rel,info in expected.items()}
    wanted['package-manifest.json']=hashlib.sha256((HERE/'package-manifest.json').read_bytes()).hexdigest()
    demand(sums==wanted,'Checksum list mismatch')
    return manifest


def program_tree(root):
    result={}
    for p in root.rglob('*'):
        demand(not p.is_symlink(),'Unexpected installed symlink')
        if p.is_file():result[p.relative_to(root).as_posix()]=hashlib.sha256(p.read_bytes()).hexdigest()
    return result


def health(host,address,expected_games):
    target='['+address+']' if ':' in address else address
    client=build_opener(ProxyHandler({}))
    def fetch(path):
        with client.open(Request('http://'+target+'/emulator/'+path,headers={'Host':host}),timeout=20) as response:
            return response.read()
    demand(VERSION.encode() in fetch(''),'Visible RC version missing')
    catalog=json.loads(fetch('games.json'))
    demand(len(catalog['games'])==expected_games,'Unexpected HTTP library size')
    try:fetch('import/')
    except HTTPError as error:demand(error.code==401,'Administration authentication unavailable')
    else:raise RuntimeError('Administration unexpectedly public')


def protected_tree(base):
    for path in (base,*base.rglob('*')):
        s=path.lstat()
        demand(not path.is_symlink() and s.st_uid==0 and not s.st_mode&0o022,'Unsafe installed code/configuration')


def repeat_install(args,manifest,host,nets,root,data):
    config=CONFIG
    for base in (root,config):
        protected_tree(base)
    identity=json.loads((config/'installation.json').read_bytes())
    demand(identity==dict(version=VERSION,program=str(root),data=str(data),user=args.app_user),
           'Existing different installation: clean installer refuses upgrade/reset')
    expected={k:v['sha256'] for k,v in manifest['files'].items() if k.startswith(('app/','schema/','web/','runtime/','provenance/'))}
    actual=program_tree(root)
    demand(set(actual)==set(expected)|{'entry.wsgi','release.json'},'Installed program inventory differs')
    demand(all(actual[k]==v for k,v in expected.items()),'Installed code differs from this RC package')
    demand(actual==json.loads((config/'program-files.json').read_bytes()),'Installed program proof mismatch')
    cfg=json.loads((config/'settings.json').read_bytes())
    wanted=dict(origin='http://'+host,networks=nets,manifest=str(data/'catalog/games.json'),state=str(data/'private'),
        vcs=str(data/'roms/vcs2600'),c64=str(data/'roms/c64'),covers=str(data/'covers'),node=str(root/'runtime/bin/node'),
        profiles=str(root/'app/atari-profiles.json'),secret=str(config/'secret'),
        coverOrigin=None if args.disable_covers else None)
    demand(cfg==wanted,'Installed settings differ; no automatic modification')
    demand([line.split(':')[0] for line in (config/'users').read_text().splitlines() if line.strip()]==[args.login],'Browser login differs')
    demand((config/'secret').stat().st_size>=32,'Missing installation secret')
    demand((APACHE/'sites-available/home-arcade.conf').read_text()==apache_config(root,data,host,nets,args.app_user),
           'Installed Apache site differs')
    demand((APACHE/'ports.conf').read_bytes()==render_ports(listener_settings(args,nets)),'Listener differs')
    demand(sorted(p.name for p in (APACHE/'sites-enabled').iterdir())==['home-arcade.conf'],'Unexpected enabled sites')
    run(['apache2ctl','-t'],capture_output=True)
    run(['systemctl','is-active','--quiet','apache2'])
    raw=(data/'catalog/games.json').read_bytes()
    validation=run([str(root/'runtime/bin/node'),str(root/'app/validate.cjs')],input=raw,capture_output=True)
    demand(validation.stdout==b'OK','Current catalog invalid; no reset performed')
    catalog=json.loads(raw)
    for game in catalog['games']:
        rom=data/game['rom']
        demand(rom.resolve().is_relative_to(data.resolve()) and rom.is_file() and rom.stat().st_size==game['bytes'] and hashlib.sha256(rom.read_bytes()).hexdigest()==game['sha256'],'Existing ROM mismatch')
    health(host,listener_settings(args,nets)[0],len(catalog['games']))
    print(json.dumps({'result':'ALREADY_CURRENT','version':VERSION,'games':len(catalog['games']),'changes':False},indent=2))
    args.already_current=True
    return host,nets,root,data

def settings(args):
    host=args.hostname
    demand(re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',host) and '..' not in host and len(host)<=253,
           'Invalid hostname; use one canonical DNS name')
    demand(re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}',args.app_user),'Invalid application account')
    demand(re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.login),'Invalid browser login')
    nets=[lan_network(n) for n in args.network]
    demand(nets and all(ipaddress.ip_network(n).prefixlen>0 for n in nets),'Explicit limited LAN networks required')
    root=safe_path(args.program_root); data=safe_path(args.data_root)
    demand(root!=data and not root.is_relative_to(data) and not data.is_relative_to(root),'Program/data paths overlap')
    demand(root.parent.is_dir() and data.parent.is_dir(),'Program/data parent directories must exist')
    return host,nets,root,data

def preflight(args):
    manifest=verify_package()
    demand(os.geteuid()==0,'Run as root on the separately approved Ubuntu target')
    demand(platform.machine() in ('x86_64','amd64'),'x86_64 required')
    release=dict(line.split('=',1) for line in Path('/etc/os-release').read_text().splitlines() if '=' in line)
    demand(release.get('ID','').strip('"')=='ubuntu' and release.get('VERSION_ID','').strip('"')=='24.04','Ubuntu 24.04 required')
    demand(sys.version_info[:2]==(3,12),'Python 3.12 required')
    demand(socket.gethostname().split('.')[0]==args.expect_host,'Wrong target host')
    host,nets,root,data=settings(args)
    demand(host==args.expect_host,'Canonical hostname must match approved target')
    if Path('/etc/home-arcade/installation.json').is_file():
        return repeat_install(args,manifest,host,nets,root,data)
    for p in (root,data,Path('/etc/home-arcade'),Path('/etc/apache2/sites-available/home-arcade.conf')):
        demand(not p.exists() and not p.is_symlink(),'Existing installation/path; no changes made: '+str(p))
    try: pwd.getpwnam(args.app_user)
    except KeyError: pass
    else: raise RuntimeError('Application account already exists; refusing reuse')
    try: grp.getgrnam(args.app_user)
    except KeyError: pass
    else: raise RuntimeError('Application group already exists; refusing reuse')
    sites=Path('/etc/apache2/sites-enabled')
    demand(not sites.exists() or all(p.name=='000-default.conf' for p in sites.iterdir()),'Existing non-default Apache sites; refusing changes')
    demand(shutil.disk_usage(root.parent if root.parent.exists() else '/').free>1024**3,'At least 1 GiB free required')
    addresses=listener_settings(args,nets)
    demand(not BACKUP.exists(),'Prior RC install backup exists: inspect partial install before retry')
    interfaces=json.loads(run(['ip','-j','address','show'],capture_output=True,text=True).stdout)
    local={a['local'] for i in interfaces for a in i.get('addr_info',[])}
    demand(set(addresses)<=local,'A listener address is not configured on this VM')
    print(json.dumps({'version':VERSION,'hostname':host,'networks':nets,'program':str(root),'data':str(data),
                      'listenAddresses':addresses,'packages':PACKAGES,'catalogGames':0,'publicRedistribution':'LOCAL BUILD: external components have separate rights'},indent=2))
    return host,nets,root,data

def put(path,data,mode=0o644,uid=0,gid=0):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,mode)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    os.chown(path,uid,gid);os.chmod(path,mode)

def apache_config(root,data,host,nets,user):
    lines=['<VirtualHost *:80>',f' ServerName {host}',f' DocumentRoot {root}/web',
           ' ServerSignature Off',' AllowEncodedSlashes Off',
           ' Header always set X-Content-Type-Options "nosniff"',
           f' WSGIDaemonProcess home-arcade user={user} group={user} threads=4 processes=1 home={data} python-path={root}/app',
           ' WSGIProcessGroup home-arcade',' WSGIApplicationGroup %{GLOBAL}',
           f' <Directory "{root}">','  Options -Indexes -FollowSymLinks -ExecCGI -Includes -MultiViews',
           '  AllowOverride None','  Require all granted',' </Directory>',
           f' <Directory "{data}">','  Require all denied',' </Directory>',
           ' <Location "/">','  <RequireAll>',f'   Require host-not-used-placeholder',
           '  </RequireAll>',' </Location>']
    # Strict host and explicit peer networks apply to static resources as well as WSGI.
    lines=lines[:lines.index(' <Location "/">')]+[
        ' <Location "/">','  <RequireAll>',f'   Require expr "%{{HTTP_HOST}} == \'{host}\'"',
        '   Require ip '+' '.join(nets),'  </RequireAll>',' </Location>',
        ' RedirectMatch "^/$" "/emulator/"',
        ' <LocationMatch "^/(?!emulator(?:/|$)|$)">','  Require all denied',' </LocationMatch>']
    for mount in ('games.json','roms','covers','import-api'):
        lines.append(f' WSGIScriptAlias /emulator/{mount} {root}/entry.wsgi')
    lines.extend([f' AliasMatch "^/emulator/?$" "{root}/web/index.html"',
                  f' Alias "/emulator/import/" "{root}/web/import/"',
                  f' <Directory "{root}/web/import">','  DirectoryIndex index.html',' </Directory>'])
    for p in sorted((HERE/'web').rglob('*')):
        if not p.is_file():continue
        rel=p.relative_to(HERE/'web').as_posix()
        if rel=='index.html' or rel.startswith('import/'):continue
        lines.append(f' Alias "/emulator/{rel}" "{root}/web/{rel}"')
    lines.extend([' <LocationMatch "^/emulator/(?:import(?:/|$)|import-api(?:/(?!asset-cover/[a-z0-9-]+$|library-actions$)|$))">',
                  '  AuthType Basic','  AuthName "Home Arcade Verwaltung"','  AuthBasicProvider file',
                  '  AuthUserFile /etc/home-arcade/users','  <RequireAll>','   Require valid-user',
                  f'   Require expr "%{{HTTP_HOST}} == \'{host}\'"','   Require ip '+' '.join(nets),
                  '  </RequireAll>','  LimitRequestBody 524288',' </LocationMatch>',
                  ' <LocationMatch "^/emulator/import-api/upload-cover$">','  LimitRequestBody 2097152',' </LocationMatch>',
                  ' ErrorLog ${APACHE_LOG_DIR}/home-arcade-error.log',' CustomLog ${APACHE_LOG_DIR}/home-arcade-access.log combined',
                  '</VirtualHost>',''])
    return '\n'.join(lines)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--expect-host',required=True)
    p.add_argument('--hostname',required=True);p.add_argument('--network',action='append',required=True)
    p.add_argument('--listen-address',action='append',required=True)
    p.add_argument('--app-user',default='home-arcade');p.add_argument('--login',default='admin')
    p.add_argument('--program-root',default='/opt/home-arcade');p.add_argument('--data-root',default='/var/lib/home-arcade')
    p.add_argument('--disable-covers',action='store_true');p.add_argument('--apply',action='store_true')
    p.add_argument('--install-dependencies',action='store_true')
    args=p.parse_args();host,nets,root,data=preflight(args)
    if getattr(args,'already_current',False):return
    if not args.apply:
        print('PREFLIGHT ONLY: no changes made');return
    password=getpass.getpass('New Home Arcade browser password (min 12 characters): ')
    demand(len(password)>=12 and '\n' not in password and '\r' not in password,'Invalid password')
    demand(password==getpass.getpass('Repeat password: '),'Passwords differ')
    os.umask(0o022)
    with private_package_start(listener_settings(args,nets)):
        if args.install_dependencies:
            run(['apt-get','update']);run(['apt-get','install','--no-install-recommends','-y',*PACKAGES])
        else:
            for package in PACKAGES:
                r=run(['dpkg-query','-W','-f=${Status}',package],capture_output=True,text=True)
                demand(r.stdout=='install ok installed','Missing dependency: '+package)
    run(['/usr/bin/python3','-I','-c','from PIL import Image; import sys; assert sys.version_info[:2] == (3,12)'])
    run(['useradd','--system','--user-group','--home-dir',str(data),'--no-create-home','--shell','/usr/sbin/nologin',args.app_user])
    account=pwd.getpwnam(args.app_user);wg=grp.getgrnam('www-data').gr_gid
    # No broad copy: package positive-list controls every installed program file.
    root.mkdir(mode=0o755)
    for rel in json.loads((HERE/'package-manifest.json').read_bytes())['files']:
        if not rel.startswith(('app/','schema/','web/','runtime/','provenance/')):continue
        target=root/rel;target.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        put(target,(HERE/rel).read_bytes(),0o755 if rel=='runtime/bin/node' else 0o644)
    data.mkdir(mode=0o755);os.chown(data,0,0)
    for rel in ('catalog','private','roms','roms/vcs2600','roms/c64','covers'):
        d=data/rel;d.mkdir(mode=0o700);os.chown(d,account.pw_uid,account.pw_gid);os.chmod(d,0o700)
    put(data/'catalog/games.json',(HERE/'empty-catalog.json').read_bytes(),0o600,account.pw_uid,account.pw_gid)
    config=Path('/etc/home-arcade');config.mkdir(mode=0o755)
    secret=config/'secret';put(secret,os.urandom(48),0o640,0,account.pw_gid)
    cfg=dict(origin='http://'+host,networks=nets,manifest=str(data/'catalog/games.json'),state=str(data/'private'),
             vcs=str(data/'roms/vcs2600'),c64=str(data/'roms/c64'),covers=str(data/'covers'),
             node=str(root/'runtime/bin/node'),profiles=str(root/'app/atari-profiles.json'),secret=str(secret),
             coverOrigin=None if args.disable_covers else None)
    put(config/'settings.json',(json.dumps(cfg,indent=2)+'\n').encode(),0o644)
    result=run(['htpasswd','-niB',args.login],input=(password+'\n').encode(),capture_output=True)
    put(config/'users',result.stdout,0o640,0,wg);password=None
    entry="import sys\nsys.path.insert(0, "+repr(str(root/'app'))+")\nfrom factory import create\napplication=create('/etc/home-arcade/settings.json')\n"
    put(root/'entry.wsgi',entry.encode())
    put(root/'release.json',(json.dumps({'product':'Home Arcade','version':VERSION,'status':'source-build','catalogSchema':1})+'\n').encode())
    put(config/'installation.json',(json.dumps(dict(version=VERSION,program=str(root),data=str(data),user=args.app_user))+'\n').encode())
    program_files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
    put(config/'program-files.json',(json.dumps(program_files,indent=2)+'\n').encode())
    put(Path('/etc/apache2/sites-available/home-arcade.conf'),apache_config(root,data,host,nets,args.app_user).encode())
    run(['a2enmod','wsgi','headers','auth_basic','authn_file','authz_host','alias','mime','dir'])
    # Validate before switching the enabled virtual host. No app writes during preflight.
    run(['apache2ctl','-t','-c','Include /etc/apache2/sites-available/home-arcade.conf'])
    run(['a2dissite','000-default']);run(['a2ensite','home-arcade']);run(['apache2ctl','-t'])
    run(['systemctl','enable','apache2']);run(['systemctl','restart','apache2'])
    health(host,listener_settings(args,nets)[0],0)
    put(BACKUP/'result.json',(json.dumps({'result':'PASS','version':VERSION,'gamesAtInstall':0,
        'program':str(root),'data':str(data),'backup':str(BACKUP),'manualAcceptance':'PENDING'})+'\n').encode(),0o600)
    print('Installed '+VERSION+' with zero games. Perform the packaged acceptance plan; installation alone is not acceptance.')

if __name__=='__main__':
    try:main()
    except Exception as e:
        if INSTALL_STARTED and BACKUP.is_dir():
            failure=BACKUP/'failure.json'
            if not failure.exists():
                put(failure,(json.dumps({'result':'STOP','error':str(e),'dataRestored':False,
                    'automaticUninstall':False,'operatorInspectionRequired':True})+'\n').encode(),0o600)
        print('STOP: '+str(e)+'. Do not rerun after a partial installation; preserve logs and inspect the recorded state. No automatic reset or data restore.',file=sys.stderr)
        sys.exit(1)
