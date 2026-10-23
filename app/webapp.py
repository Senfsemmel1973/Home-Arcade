"""Framework-free WSGI adapter. Apache supplies authenticated REMOTE_USER.

No daemon start, no HTTP server and no automatic provisioning on import.
"""
import hashlib
import hmac
import ipaddress
import json
import re
import time
import urllib.parse

from storage import Refused, demand, digest
from formats import MAX_IMAGE


class App:
    def __init__(self, importer, secret, origin='http://localhost', networks=('127.0.0.0/8', '::1/128')):
        demand(isinstance(secret, bytes) and len(secret) >= 32, 'Servergeheimnis fehlt.')
        self.importer, self.secret, self.origin = importer, secret, origin
        self.host = urllib.parse.urlsplit(origin).netloc
        self.networks = [ipaddress.ip_network(n) for n in networks]

    def csrf(self, owner, expires=None):
        expires = expires or int(time.time())+1800
        message = f'{owner}\n{expires}'.encode()
        return str(expires)+'.'+hmac.new(self.secret, message, hashlib.sha256).hexdigest()

    def authorize(self, env, write=False):
        owner = env.get('REMOTE_USER', '')
        demand(re.fullmatch(r'[A-Za-z0-9_-]{1,64}', owner), 'Import-Anmeldung erforderlich.', 401)
        if write:
            demand(env.get('HTTP_ORIGIN') == self.origin, 'Fremder oder fehlender Origin.', 403)
            token = env.get('HTTP_X_CSRF_TOKEN', '')
            try:
                expires = int(token.split('.')[0])
            except ValueError:
                expires = 0
            demand(time.time() <= expires <= time.time()+1801 and
                   hmac.compare_digest(token, self.csrf(owner, expires)), 'Bestätigungstoken fehlt/abgelaufen.', 403)
        return owner

    def body(self, env, limit, mime):
        demand(env.get('CONTENT_TYPE', '').split(';')[0] == mime, 'Falscher Inhaltstyp.', 415)
        length = env.get('CONTENT_LENGTH', '')
        demand(length.isdigit() and 0 < int(length) <= limit, 'Upload-/Requestgröße ungültig.', 413)
        data = env['wsgi.input'].read(int(length))
        demand(len(data) == int(length), 'Upload unvollständig oder Länge falsch.')
        return data

    def __call__(self, env, start_response):
        status, mime, result = 200, 'application/json', None
        try:
            demand(env.get('HTTP_HOST') == self.host, 'Hostname nicht erlaubt.', 403)
            peer = ipaddress.ip_address(env.get('REMOTE_ADDR', ''))
            demand(any(peer in n for n in self.networks), 'Nur freigegebenes LAN.', 403)
            method = env.get('REQUEST_METHOD')
            # Mount the same app on /emulator/import-api, /emulator/roms,
            # and /emulator/covers; SCRIPT_NAME is set by Apache, not the client.
            mount = env.get('SCRIPT_NAME', '')
            path = env.get('PATH_INFO', '')
            if mount == '/emulator/games.json':
                demand(method in ('GET', 'HEAD') and path in ('', '/'), 'Methode/Pfad nicht erlaubt.', 405)
                result, _ = self.importer.manifest()
                mime = 'application/json'
            elif mount in ('/emulator/roms', '/emulator/covers'):
                demand(method in ('GET', 'HEAD'), 'Methode nicht erlaubt.', 405)
                prefix = 'roms' if mount.endswith('roms') else 'covers'
                demand(re.fullmatch(r'/(?:vcs2600/[a-z0-9-]+\.bin|c64/[a-z0-9-]+\.(?:d64|prg|t64))' if prefix == 'roms'
                                    else r'/[a-z0-9-]+\.jpg', path), 'Ungültiger Ressourcenpfad.', 404)
                result, mime = self.importer.resource(prefix+path)
            elif (mount == '/emulator/import-api' and path == '/library-actions'
                  and method in ('GET', 'HEAD') and env.get('QUERY_STRING') == 'view=links'):
                # Public presentation only; uses the same validated source as cover lookup.
                result = {'levelComplete': self.importer.catalog.base}
            elif mount == '/emulator/import-api' and path == '/library-actions' and method == 'GET':
                listing=self.importer.removable()
                result={'base':listing['base'],'ids':[g['id'] for g in listing['games']]}
            elif mount == '/emulator/import-api' and re.fullmatch('/asset-cover/[a-z0-9-]+',path) and method in ('GET','HEAD'):
                result,mime=self.importer.resource('covers/'+path.rsplit('/',1)[1]+'.jpg')
            else:
                demand(mount == '/emulator/import-api', 'Route nicht erlaubt.', 404)
                owner = self.authorize(env, write=method == 'POST')
                if path == '/session' and method == 'GET':
                    result = {'csrf': self.csrf(owner), 'maxFiles': 32}
                elif path == '/preview' and method == 'POST':
                    filename = urllib.parse.unquote(env.get('HTTP_X_FILENAME', ''), errors='strict')
                    result = self.importer.preview(owner, filename, self.body(env, MAX_IMAGE, 'application/octet-stream'))
                elif path == '/matches' and method == 'GET':
                    q = urllib.parse.parse_qs(env.get('QUERY_STRING', ''), max_num_fields=2)
                    title = q.get('title', [''])[0]
                    demand(0 < len(title) <= 300, 'Titel ungültig.')
                    hits, warning = self.importer.catalog.matches(title)
                    result = {'matches': [{'id': g['id'], 'title': g['title'], 'hasCover': bool(g['cover'])} for g in hits], 'warning': warning}
                elif path == '/cover' and method == 'GET':
                    q = urllib.parse.parse_qs(env.get('QUERY_STRING', ''), max_num_fields=1)
                    wid = q.get('workId', [''])[0]
                    demand(wid.isdigit(), 'Work-ID ungültig.')
                    result, mime = self.importer.catalog.cover(int(wid)), 'image/jpeg'
                elif path == '/commit' and method == 'POST':
                    result = self.importer.commit(owner, json.loads(self.body(env, 32768, 'application/json')))
                elif path == '/managed' and method == 'GET':
                    result = self.importer.removable()
                elif path == '/administration' and method == 'GET':
                    result = self.importer.administration()
                elif path == '/upload-cover' and method == 'POST':
                    result=self.importer.upload_cover(owner,self.body(env,2097152,'application/octet-stream'))
                elif re.fullmatch('/uploaded-cover/[a-f0-9]{32}',path) and method == 'GET':
                    result,mime=self.importer.uploaded_cover(owner,path.rsplit('/',1)[1]),'image/jpeg'
                elif path == '/set-cover' and method == 'POST':
                    value=json.loads(self.body(env,1024,'application/json'))
                    demand(set(value)=={'id','base','token'},'Ungültige Coverbestätigung.')
                    result=self.importer.set_cover(owner,value['id'],value['base'],value['token'])
                elif path == '/delete' and method == 'POST':
                    value = json.loads(self.body(env, 1024, 'application/json'))
                    demand(set(value) == {'id', 'base'}, 'Ungültige Löschbestätigung.')
                    result = self.importer.delete(owner, value['id'], value['base'])
                elif path == '/discard' and method == 'POST':
                    value = json.loads(self.body(env, 1024, 'application/json'))
                    result = self.importer.discard(owner, value['token'])
                elif re.fullmatch('/status/[a-f0-9]{32}', path) and method == 'GET':
                    result = self.importer.status(owner, path.rsplit('/', 1)[1])
                else:
                    raise Refused('Route/Methode nicht erlaubt.', 405)
        except Refused as e:
            status, result = e.status, {'error': str(e)}
        except (ValueError, KeyError, UnicodeError):
            status, result = 400, {'error': 'Ungültige Anfrage.'}
        except Exception:
            status, result = 503, {'error': 'Import nicht abgeschlossen. Status prüfen; bei Recovery-Konflikt Betreiber informieren.'}
        if not isinstance(result, bytes):
            mime = 'application/json'
            result = json.dumps(result, ensure_ascii=True).encode()
        headers = [('Content-Type', mime), ('Content-Length', str(len(result))),
                   ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                   ('Cross-Origin-Resource-Policy', 'same-origin'),
                   ('Content-Security-Policy', "default-src 'none'; frame-ancestors 'none'")]
        if mime == 'image/jpeg':
            headers.append(('X-Cover-SHA256', digest(result)))
        names = {200: 'OK', 400: 'Bad Request', 401: 'Unauthorized', 403: 'Forbidden',
                 404: 'Not Found', 405: 'Method Not Allowed', 409: 'Conflict', 410: 'Gone',
                 413: 'Content Too Large', 415: 'Unsupported Media Type', 422: 'Unprocessable Content',
                 503: 'Service Unavailable'}
        start_response(f'{status} {names.get(status, "Error")}', headers)
        return [b'' if env.get('REQUEST_METHOD') == 'HEAD' else result]
