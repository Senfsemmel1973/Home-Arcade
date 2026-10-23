"""Small browser importer, invoked through WSGI; no server lifecycle here."""
from dataclasses import dataclass
import io
import json
import re
import subprocess
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid
import warnings
from pathlib import Path

from formats import inspect, MAX_IMAGE
from storage import Refused, atomic, demand, digest, encode, locked, read, safe_parents


def normal(title):
    title = unicodedata.normalize('NFKC', title).casefold()
    return ' '.join(title.translate(str.maketrans({'’': "'", '‘': "'", '–': '-', '—': '-'})).split())


class Schema:
    def __init__(self, node, bridge):
        self.node, self.bridge = str(node), str(bridge)

    def validate(self, manifest):
        data = encode(manifest)
        demand(len(data) <= 2097152, 'Kataloggrößenlimit erreicht.')
        r = subprocess.run([self.node, self.bridge], input=data, capture_output=True,
                           timeout=10, cwd=Path(self.bridge).parent, check=False)
        demand(r.returncode == 0 and r.stdout == b'OK',
               'Manifestvalidierung verweigert: ' + r.stderr.decode(errors='replace')[:300])


class Catalog:
    """Read-only fixed-origin LC client. Tests inject a synthetic transport."""
    def __init__(self, base='http://cover-catalog.invalid/', fetch=None):
        demand(base in ('http://cover-catalog.invalid/', None), 'Nicht freigegebene Coverquelle.')
        self.base, self.fetch = base, fetch or self._get
        self.cached, self.until = [], 0

    def _get(self, relative, limit):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise Refused('LC-Redirect nicht erlaubt.')
        request = urllib.request.Request(self.base + relative, headers={'Accept': '*/*'})
        with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(request, timeout=5) as r:
            data = r.read(limit + 1)
            demand(len(data) <= limit, 'LC-Antwort zu groß.')
            return data

    def works(self):
        if self.base is None:
            return []
        if time.time() < self.until:
            return self.cached
        data = self.fetch('api/games', 8*1024*1024)
        demand(len(data) <= 8*1024*1024, 'LC-Katalog zu groß.')
        source = json.loads(data)
        games = source.get('games') if isinstance(source, dict) else None
        demand(isinstance(games, list) and len(games) <= 30000, 'LC-Katalogstruktur ungültig.')
        result = []
        seen = set()
        for g in games:
            if not isinstance(g, dict):
                continue
            wid, title, cover = g.get('id'), g.get('title'), g.get('cover')
            if type(wid) != int or wid <= 0 or wid in seen or not isinstance(title, str) or not 0 < len(title) <= 300:
                continue
            seen.add(wid)
            if not isinstance(cover, str) or not re.fullmatch(r'assets/covers/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png)', cover):
                cover = None
            result.append({'id': wid, 'title': title, 'cover': cover})
        self.cached, self.until = result, time.time() + 120
        return result

    def matches(self, title):
        try:
            hits = [g for g in self.works() if normal(g['title']) == normal(title)]
            return hits[:50], None
        except Exception:
            return [], 'Level Complete nicht verfügbar; Import ohne Cover möglich.'

    def cover(self, wid):
        g = next((g for g in self.works() if g['id'] == wid), None)
        demand(g is not None and g['cover'], 'Kein gültiges LC-Cover.')
        raw = self.fetch(g['cover'], 2097152)
        demand(len(raw) <= 2097152, 'Cover zu groß.')
        return normalize_cover(raw)


def normalize_cover(raw):
        demand(0 < len(raw) <= 2097152, 'Cover muss 1 bis 2097152 Bytes haben.', 413)
        from PIL import Image, UnidentifiedImageError
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            try:
                image = Image.open(io.BytesIO(raw))
            except (UnidentifiedImageError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
                raise Refused('Nur gültige JPEG-/PNG-Bilder sind erlaubt.', 415) from e
            with image:
                demand(image.format in ('JPEG', 'PNG') and image.width*image.height <= 12000000,
                       'Bildformat oder Pixelgröße nicht erlaubt.')
                try:
                    image.load()
                except OSError as e:
                    raise Refused('Bilddatei ist beschädigt.',415) from e
                image.thumbnail((1200, 1600))
                out = io.BytesIO()
                image.convert('RGB').save(out, 'JPEG', quality=88)
        result = out.getvalue()
        demand(len(result) <= 2097152, 'Normalisiertes Cover zu groß.')
        return result


@dataclass(frozen=True)
class Paths:
    manifest: Path
    state: Path
    vcs: Path
    c64: Path
    covers: Path


class Importer:
    def __init__(self, paths, schema, profiles, catalog=None, checkpoint=None):
        self.p, self.schema, self.profiles = paths, schema, profiles
        self.catalog = catalog or Catalog()
        self.checkpoint = checkpoint or (lambda _: None)
        # Provisioning is deliberately separate. Constructor creates nothing.
        for d in (paths.manifest.parent, paths.state, paths.vcs, paths.c64, paths.covers):
            demand(safe_parents(d).is_dir(), 'Datenverzeichnis muss vorab provisioniert sein.')

    def manifest(self):
        raw = read(self.p.manifest)
        data = json.loads(raw)
        self.schema.validate(data)
        return raw, data

    def _token(self, token):
        demand(isinstance(token, str) and re.fullmatch(r'[a-f0-9]{32}', token), 'Ungültige Entwurfs-ID.')
        return token

    def _draft(self, token, owner):
        token = self._token(token)
        meta = json.loads(read(self.p.state / (token + '.json')))
        demand(meta['owner'] == owner, 'Entwurf gehört einem anderen Benutzer.', 403)
        demand(meta['expires'] >= time.time(), 'Entwurf abgelaufen; erneut auswählen.', 410)
        data = read(self.p.state / (token + '.rom'), MAX_IMAGE)
        demand(digest(data) == meta['profile']['sha256'], 'Entwurf beschädigt.')
        return meta, data

    def preview(self, owner, filename, data):
        demand(len(data) <= MAX_IMAGE, 'ROM zu groß.', 413)
        raw, current = self.manifest()
        sha = digest(data)
        found = next((g for g in current['games'] if g['sha256'] == sha), None)
        if found:
            return {'state': 'existing', 'title': found['title'], 'id': found['id']}
        profile = inspect(filename, data, self.profiles)
        title = filename.rsplit('.', 1)[0].strip()
        demand(title and len(title) <= 240, 'Kein brauchbarer Titelvorschlag.')
        matches, warning = self.catalog.matches(title)
        with locked(self.p.state / 'import.lock'):
            self._recover()
            self._expire()
            demand(sum(x.stat().st_size for x in self.p.state.iterdir()
                       if re.fullmatch(r'[a-f0-9]{32}\.(?:json|rom)', x.name)) + len(data) <= 32*1024*1024,
                   'Temporäres Importbudget erreicht.', 413)
            token = uuid.uuid4().hex
            meta = {'owner': owner, 'expires': time.time()+1800, 'base': digest(raw),
                    'title': title, 'profile': profile}
            atomic(self.p.state / (token+'.rom'), data, replace=False)
            try:
                atomic(self.p.state / (token+'.json'), encode(meta), replace=False)
            except Exception:
                (self.p.state / (token+'.rom')).unlink()
                raise
        return {'state': 'ready', 'token': token, 'title': title, 'profile': profile,
                'matches': [{'id': g['id'], 'title': g['title'], 'hasCover': bool(g['cover'])} for g in matches],
                'warning': warning}

    def _expire(self):
        # Called under lock. Only generated names, no recursive deletion.
        for p in self.p.state.glob('upload-*.json'):
            if re.fullmatch('upload-[a-f0-9]{32}.json',p.name) and json.loads(read(p))['expires']<time.time():
                other=p.with_suffix('.jpg')
                if other.exists(): read(other);other.unlink()
                p.unlink()
        for p in self.p.state.glob('*.json'):
            if re.fullmatch('[a-f0-9]{32}.json', p.name):
                meta = json.loads(read(p))
                if meta['expires'] < time.time():
                    p.unlink()
                    other = p.with_suffix('.rom')
                    if other.exists():
                        read(other, MAX_IMAGE)
                        other.unlink()

    def discard(self, owner, token):
        with locked(self.p.state / 'import.lock'):
            self._draft(token, owner)
            (self.p.state / (token+'.json')).unlink()
            (self.p.state / (token+'.rom')).unlink()
        return {'state': 'discarded'}

    def _entry(self, profile, title, current):
        demand(isinstance(title, str) and 0 < len(title.strip()) <= 300 and
               not re.search(r'[\x00-\x1f\x7f]', title), 'Ungültiger Titel.')
        title = title.strip()
        stem = unicodedata.normalize('NFKD', title).encode('ascii', 'ignore').decode().lower()
        stem = re.sub('[^a-z0-9]+', '-', stem).strip('-')[:40].strip('-') or 'spiel'
        base = f"{stem}-{profile['system']}-{profile['sha256'][:8]}"
        gid = base
        ids = {g['id'] for g in current['games']}
        suffix = 1
        while gid in ids:
            suffix += 1
            gid = base + '-' + str(suffix)
        ext, system = profile['format'], profile['system']
        g = {'id': gid, 'title': title, 'system': system,
             'player': 'c64/player.html' if system == 'c64' else 'atari/player.html',
             'rom': f'roms/{system}/{gid}.{ext}', 'format': ext, 'bytes': profile['bytes'],
             'sha256': profile['sha256'], 'serverFile': gid+'.'+ext,
             'controls': 'Linker Stick oder Steuerkreuz; Feuer mit A. Tastatur im Player.',
             'instructions': 'Im Player manuell starten. Hinweise und allgemeine Tasten im Player verwenden.'}
        if system == 'c64':
            n = max([640000]+[x['loadProfile']['gameId'] for x in current['games'] if x['system'] == 'c64'])+1
            g.update(joyPort=1, loadProfile={'core': 'vice_x64sc', 'autostart': 'warp',
                                           'model': 'C64 PAL', 'program': '*', 'gameId': n})
        else:
            g.update(mapper=profile['mapper'], region=profile['region'])
        return g

    def _target(self, g, cover=False):
        demand(re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', g['id']), 'Unsichere Ziel-ID.')
        if cover:
            return self.p.covers / (g['id']+'.jpg')
        return (self.p.c64 if g['system'] == 'c64' else self.p.vcs) / g['serverFile']

    def _recover(self):
        self._recover_cover()
        self._recover_delete()
        receipt_path = self.p.state / 'active.json'
        if not receipt_path.exists():
            return
        receipt = json.loads(read(receipt_path))
        raw, current = self.manifest()
        committed = all(any(g['id'] == e['id'] and g['sha256'] == e['sha256'] for g in current['games'])
                        for e in receipt['entries'])
        if not committed:
            demand(digest(raw) == receipt['base'], 'Recovery-Konflikt; Import stoppen.', 409)
            for e in receipt['entries']:
                for cover, sha in ((False, e['sha256']), (True, receipt['covers'].get(e['id']))):
                    if sha is None:
                        continue
                    target = self._target(e, cover)
                    if target.exists() or target.is_symlink():
                        demand(digest(read(target)) == sha, 'Recovery-Konflikt an neuer Datei.', 409)
                        target.unlink()
        receipt['state'] = 'committed' if committed else 'rolled-back'
        atomic(self.p.state / ('result-'+receipt['token']+'.json'), encode(receipt))
        receipt_path.unlink()

    def _managed(self):
        entries = {}
        for p in self.p.state.glob('result-*.json'):
            r = json.loads(read(p))
            if r.get('state') == 'committed':
                for g in r['entries']:
                    entries.setdefault(g['id'], []).append(g)
        return entries

    def _is_managed(self, game, records=None):
        originals = (self._managed() if records is None else records).get(game['id'], [])
        return any({k:v for k,v in original.items() if k!='cover'} ==
                   {k:v for k,v in game.items() if k!='cover'} for original in originals)

    def removable(self):
        raw, manifest = self.manifest()
        managed = self._managed()
        return {'base': digest(raw), 'games': [g for g in manifest['games']
                if self._is_managed(g, managed)]}

    def administration(self):
        raw, manifest = self.manifest()
        managed = self._managed()
        return {'base': digest(raw), 'games': [dict(g, removable=self._is_managed(g, managed)) for g in manifest['games']]}

    def upload_cover(self, owner, data):
        cover = normalize_cover(data)
        with locked(self.p.state/'import.lock'):
            self._recover(); self._expire()
            demand(sum(x.stat().st_size for x in self.p.state.glob('upload-*.jpg'))+len(cover)<=32*1024*1024,
                   'Temporäres Coverbudget erreicht.', 413)
            token=uuid.uuid4().hex
            atomic(self.p.state/('upload-'+token+'.jpg'),cover,replace=False)
            try:
                atomic(self.p.state/('upload-'+token+'.json'),encode({'owner':owner,'expires':time.time()+1800,'sha256':digest(cover)}),replace=False)
            except Exception:
                (self.p.state/('upload-'+token+'.jpg')).unlink();raise
        return {'token':token,'sha256':digest(cover)}

    def uploaded_cover(self, owner, token):
        self._token(token)
        meta=json.loads(read(self.p.state/('upload-'+token+'.json')))
        demand(meta['owner']==owner and meta['expires']>=time.time(),'Cover gehört anderem Benutzer oder ist abgelaufen.',403)
        data=read(self.p.state/('upload-'+token+'.jpg'))
        demand(digest(data)==meta['sha256'],'Cover beschädigt.',409)
        return data

    def _recover_cover(self):
        active=self.p.state/'cover-active.json'
        if not active.exists(): return
        r=json.loads(read(active));raw,_=self.manifest();target=self._target(r['game'],True)
        actual=digest(read(target)) if target.exists() or target.is_symlink() else None
        demand(digest(raw) in (r['base'],r['after']),'Cover-Recovery-Konflikt.',409)
        if digest(raw)==r['after'] and actual==r['new']:
            active.unlink();return
        demand(digest(raw)==r['base'] and actual in (r['old'],r['new']),'Coverdatei verändert; Recovery gestoppt.',409)
        if actual==r['new']:
            if r['old'] is None: target.unlink()
            else:
                old=read(self.p.state/r['backup'])
                demand(digest(old)==r['old'],'Coverbackup beschädigt.',409)
                atomic(target,old)
        active.unlink()

    def set_cover(self, owner, gid, base, token):
        with locked(self.p.state/'import.lock'):
            self._recover();raw,current=self.manifest()
            demand(digest(raw)==base,'Bibliothek geändert; aktualisieren.',409)
            game=next((g for g in current['games'] if g['id']==gid),None)
            demand(game is not None,'Spiel nicht gefunden.',404)
            data=self.uploaded_cover(owner,token);target=self._target(game,True)
            old=read(target) if target.exists() or target.is_symlink() else None
            key=uuid.uuid4().hex;backup='cover-backup-'+key+'.jpg'
            if old is not None: atomic(self.p.state/backup,old,replace=False)
            atomic(self.p.state/('cover-backup-'+key+'.json'),raw,replace=False)
            game['cover']='covers/'+game['id']+'.jpg';self.schema.validate(current);after=encode(current)
            atomic(self.p.state/'cover-active.json',encode({'game':game,'base':digest(raw),'after':digest(after),
                   'new':digest(data),'old':digest(old) if old is not None else None,'backup':backup}),replace=False)
            try:
                self.checkpoint('cover-prepared');atomic(target,data);self.checkpoint('cover-file')
                atomic(self.p.manifest,after);self.checkpoint('cover-manifest');self._recover_cover()
            except Exception:
                self._recover_cover();raise
            return {'state':'updated','id':gid}

    def _recover_delete(self):
        p = self.p.state / 'delete-active.json'
        if not p.exists():
            return
        r = json.loads(read(p))
        raw, current = self.manifest()
        if digest(raw) == r['base']:
            # Manifest was never switched; no files have been removed.
            p.unlink()
            return
        demand(digest(raw) == r['after'], 'Lösch-Recovery-Konflikt; Betreiber informieren.', 409)
        for f in r['files']:
            target = self._target(r['game'], f['cover'])
            if target.exists() or target.is_symlink():
                demand(digest(read(target)) == f['sha256'], 'Löschdatei verändert; Bereinigung gestoppt.', 409)
                target.unlink()
        p.unlink()

    def delete(self, owner, gid, base):
        demand(isinstance(gid, str) and re.fullmatch('[a-z0-9]+(?:-[a-z0-9]+)*', gid), 'Ungültige Spiel-ID.')
        with locked(self.p.state / 'import.lock'):
            self._recover()
            raw, current = self.manifest()
            demand(digest(raw) == base, 'Bibliothek geändert; Liste aktualisieren.', 409)
            g = next((g for g in current['games'] if g['id'] == gid), None)
            demand(g is not None and self._is_managed(g),
                   'Nur nachweislich über diesen Importer angelegte Spiele dürfen entfernt werden.', 403)
            remaining = [x for x in current['games'] if x['id'] != gid]
            files = []
            for cover, field in ((False, 'rom'), (True, 'cover')):
                if field not in g or any(x.get(field) == g[field] for x in remaining):
                    continue
                data = read(self._target(g, cover))
                demand(cover or digest(data) == g['sha256'], 'ROM verändert; Löschen gestoppt.', 409)
                files.append({'cover': cover, 'sha256': digest(data)})
            current['games'] = remaining
            self.schema.validate(current)
            after = encode(current)
            token = uuid.uuid4().hex
            # Keep bounded-file backups for operator recovery; never purge backups here.
            for f in files:
                atomic(self.p.state / ('delete-backup-'+token+('.jpg' if f['cover'] else '.rom')),
                       read(self._target(g, f['cover'])), replace=False)
            atomic(self.p.state / ('delete-backup-'+token+'.json'), raw, replace=False)
            atomic(self.p.state / 'delete-active.json', encode({'owner': owner, 'game': g,
                   'base': digest(raw), 'after': digest(after), 'files': files}), replace=False)
            self.checkpoint('delete-prepared')
            atomic(self.p.manifest, after)
            self.checkpoint('delete-manifest')
            self._recover_delete()
            return {'state': 'deleted', 'id': gid}

    def commit(self, owner, items):
        demand(isinstance(items, list) and 0 < len(items) <= 32, '1 bis 32 Entwürfe erforderlich.')
        for item in items:
            demand(isinstance(item, dict) and {'token', 'title', 'workId', 'coverSha256'} <= set(item) <= {'token', 'title', 'workId', 'coverSha256', 'uploadToken', 'mapper'}, 'Ungültige Bestätigung.')
            if item.get('uploadToken') is not None:
                self._token(item['uploadToken'])
                demand(item['workId'] is None, 'Nur eine Coverquelle wählen.')
            self._token(item['token'])
            demand(item['workId'] is None or type(item['workId']) == int, 'Ungültige Work-ID.')
            demand((item['workId'] is None and item['coverSha256'] is None) or
                   (type(item['workId']) == int and isinstance(item['coverSha256'], str) and
                    re.fullmatch('[a-f0-9]{64}', item['coverSha256'])), 'Covervorschau fehlt.')
        tokens = [i['token'] for i in items]
        demand(len(tokens) == len(set(tokens)), 'Doppelte Entwurfsbestätigung.')
        key = tokens[0]
        request_hash = digest(encode(items))
        with locked(self.p.state / 'import.lock'):
            self._recover()
            result_path = self.p.state / ('result-'+key+'.json')
            if result_path.exists():
                result = json.loads(read(result_path))
                demand(result['owner'] == owner and result['requestHash'] == request_hash, 'Bestätigungskonflikt.', 409)
                demand(result['state'] == 'committed', 'Vorheriger Versuch zurückgerollt; neu auswählen.', 409)
                return {'state': 'committed', 'games': result['entries'], 'repeated': True, 'warnings': result['warnings']}
            raw, current = self.manifest()
            added, payloads, covers, warnings_out, hashes = [], {}, {}, [], set()
            for item in items:
                meta, data = self._draft(item['token'], owner)
                demand(meta['base'] == digest(raw), 'Katalog geändert; Vorschau neu erstellen.', 409)
                profile = inspect('image.'+meta['profile']['format'], data, self.profiles, item.get('mapper'))
                demand(profile['system'] != 'vcs2600' or profile['mapper'] is not None, 'Mapper ausdrücklich auswählen.', 422)
                demand(profile['sha256'] not in hashes and not any(g['sha256'] == profile['sha256'] for g in current['games']),
                       'ROM inzwischen vorhanden oder doppelt ausgewählt.', 409)
                hashes.add(profile['sha256'])
                g = self._entry(profile, item['title'], current)
                if item.get('uploadToken') is not None:
                    cover=self.uploaded_cover(owner,item['uploadToken'])
                    g['cover']='covers/'+g['id']+'.jpg';covers[g['id']]=cover
                if item['workId'] is not None:
                    try:
                        cover = self.catalog.cover(item['workId'])
                        demand(digest(cover) == item['coverSha256'], 'Cover seit Vorschau verändert.')
                        g['cover'] = 'covers/'+g['id']+'.jpg'
                        covers[g['id']] = cover
                    except Exception:
                        warnings_out.append(g['title']+': Cover nicht verfügbar; Titel-Platzhalter.')
                demand(not self._target(g).exists() and not self._target(g).is_symlink(), 'ROM-Ziel existiert bereits.', 409)
                if g.get('cover'):
                    demand(not self._target(g, True).exists() and not self._target(g, True).is_symlink(), 'Cover-Ziel existiert bereits.', 409)
                payloads[g['id']] = data
                current['games'].append(g)
                added.append(g)
            self.schema.validate(current)
            import shutil
            for folder in (self.p.state, self.p.manifest.parent, self.p.vcs, self.p.c64, self.p.covers):
                demand(shutil.disk_usage(folder).free >= 8*1024*1024 + len(raw)*2 + sum(map(len, payloads.values())) + sum(map(len, covers.values())),
                       'Nicht genügend freier Speicher für sicheren Import.', 503)
            receipt = {'owner': owner, 'token': key, 'requestHash': request_hash, 'base': digest(raw),
                       'entries': added, 'covers': {k: digest(v) for k, v in covers.items()},
                       'warnings': warnings_out, 'state': 'prepared'}
            atomic(self.p.state / ('backup-'+key+'.json'), raw, replace=False)
            atomic(self.p.state / 'active.json', encode(receipt), replace=False)
            try:
                self.checkpoint('prepared')
                for g in added:
                    atomic(self._target(g), payloads[g['id']], replace=False)
                    if g.get('cover'):
                        atomic(self._target(g, True), covers[g['id']], replace=False)
                self.checkpoint('files')
                demand(read(self.p.manifest) == raw, 'Katalog zwischenzeitlich geändert.', 409)
                atomic(self.p.manifest, encode(current))
                self.checkpoint('manifest')
                self._recover()
            except Exception:
                self._recover()
                raise
            return {'state': 'committed', 'games': added, 'repeated': False, 'warnings': warnings_out}

    def status(self, owner, token):
        token = self._token(token)
        # Atomic receipt reads; status never initiates recovery or creates locks.
        p = self.p.state / ('result-'+token+'.json')
        if p.exists():
            result = json.loads(read(p))
            demand(result['owner'] == owner, 'Fremder Importstatus.', 403)
            return {'state': result['state'], 'games': result['entries']}
        active = self.p.state / 'active.json'
        if active.exists():
            result = json.loads(read(active))
            demand(result['owner'] == owner, 'Fremder Importstatus.', 403)
            if result['token'] == token:
                return {'state': 'recovery-required'}
        self._draft(token, owner)
        return {'state': 'ready'}

    def resource(self, relative):
        # Only new, registered resources. Legacy Apache aliases keep precedence.
        _, current = self.manifest()
        for g in current['games']:
            if g['rom'] == relative:
                p, mime, sha = self._target(g), 'application/octet-stream', g['sha256']
            elif g.get('cover') == relative:
                p, mime, sha = self._target(g, True), 'image/jpeg', None
            else:
                continue
            if not p.exists():
                raise Refused('Ressource nicht im Importbereich.', 404)
            data = read(p)
            demand(sha is None or digest(data) == sha, 'ROM-Prüfsumme stimmt nicht.', 409)
            return data, mime
        raise Refused('Ressource nicht registriert.', 404)
