"""Synthetic data only. No network requests or real ROM reads."""
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]/'app'
sys.path.insert(0, str(HERE))
from storage import Refused, atomic, digest, encode, locked, read
from service import Catalog, Importer, Paths, Schema, normal
from formats import d64, SECTORS, OFFSETS
from webapp import App


def disk():
    b = bytearray(174848)
    bam = OFFSETS[17]
    b[bam:bam+3] = bytes([18, 1, 65])
    allocated = {(18, 0), (18, 1), (1, 0)}
    for t, count in enumerate(SECTORS, 1):
        bits = sum(1 << s for s in range(count) if (t, s) not in allocated)
        row = bytes([bits.bit_count()]) + bits.to_bytes(3, 'little')
        b[bam+4+(t-1)*4:bam+8+(t-1)*4] = row
    directory = bam+256
    b[directory:directory+5] = bytes([0, 255, 0x82, 1, 0])
    b[directory+30] = 1
    b[:4] = bytes([0, 3, 1, 8])
    return bytes(b)


def image():
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', (12, 16), 'green').save(out, 'PNG')
    return out.getvalue()


class Tests(unittest.TestCase):
    def setUp(self):
        lab = Path(__file__).parent/'lab-data'
        lab.mkdir(mode=0o700, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='arcade-d1-', dir=lab)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.p = Paths(root/'catalog/games.json', root/'state', root/'vcs/imported', root/'c64/imported', root/'covers/imported')
        for p in (self.p.manifest.parent, self.p.state, self.p.vcs, self.p.c64, self.p.covers):
            p.mkdir(parents=True, mode=0o700, exist_ok=True)
            # mkdir(parents=True) applies mode only to the leaf. Test parents
            # must also be private under Ubuntu's common group-writable umask.
            for parent in [p, *p.parents]:
                if parent == root.parent:
                    break
                parent.chmod(0o700)
        self.original = (Path(__file__).parent/'baseline.json').read_bytes()
        self.p.manifest.write_bytes(self.original)
        self.p.manifest.chmod(0o600)
        self.bin = b'synthetic-atari!' + bytes(8192-16)
        self.profiles = {digest(self.bin): {'mapper': 'F8', 'region': 'auto', 'evidence': 'synthetic test fixture only'}}
        self.requests = []
        def fetch(url, limit):
            self.requests.append(url)
            if url == 'api/games':
                return encode({'games': [{'id': 2562, 'title': 'Example', 'cover': 'assets/covers/example.png',
                                         'private': 'must not be returned'}]})
            return image()
        self.catalog = Catalog(fetch=fetch)
        self.schema = Schema(shutil.which('node'), HERE/'validate.cjs')
        self.imp = Importer(self.p, self.schema, self.profiles, self.catalog)
        self.app = App(self.imp, b's'*32, origin='http://localhost', networks=('127.0.0.0/8',))

    def draft(self, name='Example.d64', data=None):
        return self.imp.preview('test-user', name, disk() if data is None else data)

    def item(self, p, title='Example', work=None):
        return {'token': p['token'], 'title': title, 'workId': work,
                'coverSha256': digest(self.catalog.cover(work)) if work is not None else None}

    def call(self, path, method='GET', value=None, headers=None, raw=None, mount='/emulator/import-api'):
        body = raw if raw is not None else (encode(value) if value is not None else b'')
        env = {'REQUEST_METHOD': method, 'SCRIPT_NAME': mount, 'PATH_INFO': path,
               'HTTP_HOST': 'localhost', 'REMOTE_ADDR': '127.0.0.1', 'REMOTE_USER': 'test-user',
               'HTTP_ORIGIN': 'http://localhost', 'HTTP_X_CSRF_TOKEN': self.app.csrf('test-user'),
               'CONTENT_LENGTH': str(len(body)), 'CONTENT_TYPE': 'application/json', 'wsgi.input': io.BytesIO(body)}
        env.update(headers or {})
        result = {}
        def start(status, hs):
            result.update(status=int(status[:3]), headers=dict(hs))
        response = b''.join(self.app(env, start))
        result['body'] = json.loads(response) if result['headers']['Content-Type'] == 'application/json' and response else response
        return result

    def test_five_originals_unchanged_after_mixed_batch(self):
        a, b = self.draft(), self.draft('Lab.bin', self.bin)
        result = self.imp.commit('test-user', [self.item(a, work=2562), self.item(b, 'Lab')])
        catalog = json.loads(read(self.p.manifest))
        self.assertEqual(catalog['games'][:5], json.loads(self.original)['games'])
        self.assertEqual(len(catalog['games']), 7)
        self.assertEqual(result['games'][0]['joyPort'], 1)
        self.assertEqual(result['games'][1]['region'], 'auto')
        self.assertEqual(result['games'][0]['loadProfile']['gameId'], 640005)
        for g in result['games']:
            data, _ = self.imp.resource(g['rom'])
            self.assertEqual(digest(data), g['sha256'])
        self.assertTrue(self.imp.resource(result['games'][0]['cover'])[0].startswith(b'\xff\xd8'))

    def test_repeated_commit_and_renamed_duplicate(self):
        p = self.draft()
        items = [self.item(p)]
        first = self.imp.commit('test-user', items)
        self.assertTrue(self.imp.commit('test-user', items)['repeated'])
        self.assertEqual(self.draft('renamed.d64')['state'], 'existing')
        self.assertEqual(len(json.loads(read(self.p.manifest))['games']), 6)
        self.assertEqual(self.imp.status('test-user', p['token'])['state'], 'committed')
        self.assertEqual(first['games'][0]['id'], self.imp.status('test-user', p['token'])['games'][0]['id'])

    def test_duplicate_in_batch_rejected_without_changes(self):
        a, b = self.draft(), self.draft()
        with self.assertRaisesRegex(Refused, 'doppelt'):
            self.imp.commit('test-user', [self.item(a), self.item(b)])
        self.assertEqual(read(self.p.manifest), self.original)
        self.assertEqual(list(self.p.c64.iterdir()), [])

    def test_existing_target_never_overwritten(self):
        p = self.draft()
        meta, _ = self.imp._draft(p['token'], 'test-user')
        entry = self.imp._entry(meta['profile'], 'Example', json.loads(self.original))
        target = self.imp._target(entry)
        target.write_bytes(b'foreign')
        with self.assertRaisesRegex(Refused, 'existiert'):
            self.imp.commit('test-user', [self.item(p)])
        self.assertEqual(target.read_bytes(), b'foreign')

    def test_stale_preview(self):
        a, b = self.draft(), self.draft('Lab.bin', self.bin)
        self.imp.commit('test-user', [self.item(a)])
        with self.assertRaisesRegex(Refused, 'Vorschau neu'):
            self.imp.commit('test-user', [self.item(b)])

    def test_unconfirmed_not_public_and_discard(self):
        p = self.draft()
        with self.assertRaises(Refused):
            self.imp.resource('roms/c64/guess.d64')
        self.imp.discard('test-user', p['token'])
        self.assertFalse((self.p.state/(p['token']+'.rom')).exists())
        self.assertEqual(read(self.p.manifest), self.original)

    def test_unknown_mapper_and_region(self):
        unknown=self.draft('Unknown.bin', bytes(8192))
        self.assertIsNone(unknown['profile']['mapper'])
        with self.assertRaisesRegex(Refused, 'Mapper ausdrücklich'):
            self.imp.commit('test-user',[self.item(unknown)])
        p = self.draft('Known.bin', self.bin)
        self.assertEqual(p['profile']['region'], 'auto')

    def test_wrong_sizes_formats_and_names(self):
        for name, data in [('x.zip', b'a'), ('x.prg', b'a'), ('x.t64', b'a'),
                           ('x.bin', bytes(16385)), ('x.d64', bytes(174849)),
                           ('../x.bin', self.bin), ('x\\a.bin', self.bin), ('a\x00.bin', self.bin)]:
            with self.subTest(name=name):
                with self.assertRaises(Refused):
                    self.draft(name, data)

    def test_d64_corruption(self):
        offsets = [OFFSETS[17]+2, OFFSETS[17]+4, 0, OFFSETS[17]+256, OFFSETS[17]+256+30]
        for offset in offsets:
            damaged = bytearray(disk())
            damaged[offset] ^= 1
            with self.subTest(offset=offset):
                with self.assertRaises(Refused):
                    d64(damaged)

    def test_d64_crosslink_and_unsupported_rel(self):
        data = bytearray(disk())
        directory = OFFSETS[17]+256
        data[directory+32+2:directory+32+5] = bytes([0x82, 1, 0])
        data[directory+32+30] = 1
        with self.assertRaisesRegex(Refused, 'überlappt'):
            d64(data)
        data = bytearray(disk());data[directory+2] = 0x84
        with self.assertRaisesRegex(Refused, 'Dateityp'):
            d64(data)

    def test_cover_failures_do_not_block_rom(self):
        p = self.draft()
        item = self.item(p, work=2562)
        self.imp.catalog.cover = lambda wid: (_ for _ in ()).throw(ValueError('offline'))
        r = self.imp.commit('test-user', [item])
        self.assertNotIn('cover', r['games'][0])
        self.assertTrue(r['warnings'])

    def test_catalog_privacy_ambiguity_and_normalization(self):
        works = self.catalog.works()
        self.assertEqual(set(works[0]), {'id', 'title', 'cover'})
        self.assertEqual(normal('  A ’ B  '), "a ' b")
        self.catalog.cached += [{'id': 9, 'title': 'EXAMPLE', 'cover': None}]
        hits, _ = self.catalog.matches('Example')
        self.assertEqual(len(hits), 2)
        self.assertEqual(len(self.requests), 1)
        self.assertNotEqual(normal('Game 2'), normal('Game'))

    def test_catalog_rejects_external_cover_and_invalid_image(self):
        c = Catalog(fetch=lambda url, limit: encode({'games': [{'id': 1, 'title': 'X', 'cover': 'http://evil/x.jpg'}]}))
        self.assertIsNone(c.works()[0]['cover'])
        with self.assertRaises(Refused):
            c.cover(1)
        self.catalog.fetch = lambda url, limit: b'<html>not a picture</html>'
        self.catalog.works = lambda: [{'id': 1, 'title': 'X', 'cover': 'assets/covers/x.jpg'}]
        with self.assertRaises(Exception):
            self.catalog.cover(1)
        with self.assertRaises(Refused):
            Catalog('http://elsewhere/')

    def test_expired_foreign_and_changed_draft(self):
        p = self.draft()
        with self.assertRaisesRegex(Refused, 'anderen'):
            self.imp.discard('other', p['token'])
        meta_path = self.p.state/(p['token']+'.json')
        meta = json.loads(read(meta_path));meta['expires'] = 1;atomic(meta_path, encode(meta))
        with self.assertRaisesRegex(Refused, 'abgelaufen'):
            self.imp.commit('test-user', [self.item(p)])
        p = self.draft()
        (self.p.state/(p['token']+'.rom')).write_bytes(b'changed')
        with self.assertRaisesRegex(Refused, 'beschädigt'):
            self.imp.commit('test-user', [self.item(p)])

    def test_failure_before_manifest_cleans_only_new_files(self):
        import service
        p = self.draft()
        original_atomic = service.atomic
        def fail(path, data, replace=True):
            if Path(path) == self.p.manifest:
                raise OSError('injected disk failure')
            return original_atomic(path, data, replace)
        with patch('service.atomic', fail):
            with self.assertRaises(OSError):
                self.imp.commit('test-user', [self.item(p)])
        self.assertEqual(read(self.p.manifest), self.original)
        self.assertEqual(list(self.p.c64.iterdir()), [])
        self.assertEqual(self.imp.status('test-user', p['token'])['state'], 'rolled-back')

    def test_crash_checkpoints_and_recovery(self):
        for phase in ('prepared', 'files', 'manifest'):
            with self.subTest(phase=phase):
                # Reset only this isolated fixture, not a server or a real ROM.
                atomic(self.p.manifest, self.original)
                for x in self.p.c64.iterdir():
                    x.unlink()
                p = self.draft()
                def crash(at):
                    if at == phase:
                        raise SystemExit('simulated hard exit')
                self.imp.checkpoint = crash
                with self.assertRaises(SystemExit):
                    self.imp.commit('test-user', [self.item(p)])
                self.assertTrue((self.p.state/'active.json').exists())
                self.imp.checkpoint = lambda _: None
                with locked(self.p.state/'import.lock'):
                    self.imp._recover()
                self.assertFalse((self.p.state/'active.json').exists())
                self.assertEqual(len(json.loads(read(self.p.manifest))['games']), 6 if phase == 'manifest' else 5)

    def test_recovery_conflict_blocks(self):
        p = self.draft()
        def crash(at):
            if at == 'files':
                raise SystemExit()
        self.imp.checkpoint = crash
        with self.assertRaises(SystemExit):
            self.imp.commit('test-user', [self.item(p)])
        next(self.p.c64.iterdir()).write_bytes(b'foreign')
        with self.assertRaisesRegex(Refused, 'Recovery-Konflikt'):
            self.imp._recover()
        self.assertTrue((self.p.state/'active.json').exists())

    def test_schema_rejects_manifest_corruption(self):
        bad = json.loads(self.original)
        bad['games'].append(dict(bad['games'][0]))
        self.p.manifest.write_bytes(encode(bad))
        with self.assertRaisesRegex(Refused, 'Manifestvalidierung'):
            self.draft()

    def test_wsgi_auth_csrf_methods_hosts_and_limits(self):
        self.assertEqual(self.call('/session')['status'], 200)
        for headers in ({'REMOTE_USER': ''}, {'HTTP_HOST': 'evil'}, {'REMOTE_ADDR': '8.8.8.8'}):
            self.assertIn(self.call('/session', headers=headers)['status'], (401, 403))
        for headers in ({'HTTP_ORIGIN': 'http://evil'}, {'HTTP_X_CSRF_TOKEN': ''},
                        {'HTTP_X_CSRF_TOKEN': self.app.csrf('other')},
                        {'HTTP_X_CSRF_TOKEN': self.app.csrf('test-user', 1)}):
            self.assertEqual(self.call('/commit', 'POST', [], headers=headers)['status'], 403)
        self.assertEqual(self.call('/commit')['status'], 405)
        self.assertEqual(self.call('/preview', 'POST', raw=b'a', headers={'CONTENT_LENGTH': '999999', 'CONTENT_TYPE': 'application/octet-stream'})['status'], 413)
        self.assertEqual(self.call('/preview', 'POST', raw=b'a', headers={'CONTENT_TYPE': 'text/plain'})['status'], 415)

    def test_wsgi_preview_commit_file_and_status(self):
        p = self.call('/preview', 'POST', raw=disk(), headers={'CONTENT_TYPE': 'application/octet-stream', 'HTTP_X_FILENAME': 'Browser.d64'})
        self.assertEqual(p['status'], 200)
        token = p['body']['token']
        r = self.call('/commit', 'POST', [self.item(p['body'], 'Browser')])
        self.assertEqual(r['status'], 200)
        g = r['body']['games'][0]
        resource = self.call('/c64/'+g['serverFile'], mount='/emulator/roms')
        self.assertEqual(resource['body'], disk())
        self.assertEqual(self.call('/status/'+token)['body']['state'], 'committed')
        self.assertEqual(resource['headers']['X-Content-Type-Options'], 'nosniff')
        for path in ('/../state', '/c64/x.d64/extra', '/c64/x.d64', '/c64/%2e%2e.bin'):
            self.assertEqual(self.call(path, mount='/emulator/roms')['status'], 404)

    def test_hardlink_and_no_replace(self):
        a, b = self.p.state/'a', self.p.state/'b'
        a.write_bytes(b'original');os.link(a, b)
        with self.assertRaises(Refused):
            read(a)
        b.unlink()
        with self.assertRaises(OSError):
            atomic(a, b'new', replace=False)
        self.assertEqual(a.read_bytes(), b'original')

    def test_lock_contention(self):
        with locked(self.p.state/'import.lock'):
            with self.assertRaisesRegex(Refused, 'belegt'):
                with locked(self.p.state/'import.lock', timeout=.1):
                    pass

    def test_actual_process_exit_releases_lock_and_recovers(self):
        p = self.draft()
        config = self.p.state/'test-process.json'
        config.write_bytes(encode({'paths': [str(getattr(self.p, k)) for k in ('manifest', 'state', 'vcs', 'c64', 'covers')],
                                  'node': shutil.which('node'), 'bridge': str(HERE/'validate.cjs'),
                                  'items': [self.item(p)]}))
        code = """
import json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from service import Importer,Paths,Schema
c=json.loads(Path(sys.argv[2]).read_bytes())
def checkpoint(phase):
    if phase=='files':os._exit(77)
i=Importer(Paths(*map(Path,c['paths'])),Schema(c['node'],c['bridge']),{},checkpoint=checkpoint)
i.commit('test-user',c['items'])
"""
        child = subprocess.run([sys.executable, '-B', '-c', code, str(HERE), str(config)], timeout=15)
        self.assertEqual(child.returncode, 77)
        self.assertTrue((self.p.state/'active.json').exists())
        self.assertEqual(self.imp.status('test-user', p['token'])['state'], 'recovery-required')
        with locked(self.p.state/'import.lock'):
            self.imp._recover()
        self.assertEqual(read(self.p.manifest), self.original)
        self.assertEqual(list(self.p.c64.iterdir()), [])

    def test_concurrent_commits_preserve_all_old_games(self):
        from concurrent.futures import ThreadPoolExecutor
        a, b = self.draft(), self.draft('Lab.bin', self.bin)
        def commit(p):
            try:
                return self.imp.commit('test-user', [self.item(p)])['state']
            except Refused as e:
                return e.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(commit, [a, b]))
        self.assertEqual(sorted(map(str, results)), ['409', 'committed'])
        actual = json.loads(read(self.p.manifest))['games']
        self.assertEqual(len(actual), 6)
        self.assertEqual(actual[:5], json.loads(self.original)['games'])

    def test_status_and_manifest_get_do_not_write(self):
        p = self.draft()
        before = {str(x): x.read_bytes() for x in self.p.state.iterdir() if x.is_file()}
        self.assertEqual(self.call('/status/'+p['token'])['status'], 200)
        self.assertEqual(self.call('', mount='/emulator/games.json')['body'], json.loads(self.original))
        after = {str(x): x.read_bytes() for x in self.p.state.iterdir() if x.is_file()}
        self.assertEqual(before, after)

    def test_oversized_cover_and_offline_catalog(self):
        self.catalog.works = lambda: [{'id': 1, 'title': 'X', 'cover': 'assets/covers/x.jpg'}]
        self.catalog.fetch = lambda url, limit: b'a'*(limit+1)
        with self.assertRaisesRegex(Refused, 'Cover zu groß'):
            self.catalog.cover(1)
        c = Catalog(fetch=lambda *args: (_ for _ in ()).throw(TimeoutError()))
        hits, warning = c.matches('X')
        self.assertEqual(hits, [])
        self.assertTrue(warning)

    def test_changed_cover_falls_back_without_wrong_image(self):
        p = self.draft()
        item = self.item(p, work=2562)
        item['coverSha256'] = '0'*64
        result = self.imp.commit('test-user', [item])
        self.assertNotIn('cover', result['games'][0])
        self.assertTrue(result['warnings'])

    def test_atomic_manifest_can_use_existing_dedicated_data_path(self):
        # No physical move is required by the importer itself; only a safe
        # dedicated writable parent is needed, never the protected webroot.
        old = self.p.manifest
        p = self.draft()
        self.imp.commit('test-user', [self.item(p)])
        self.assertEqual(self.p.manifest, old)
        self.assertEqual(len(json.loads(read(old))['games']), 6)


    def test_delete_import_and_reimport(self):
        g = self.imp.commit('test-user', [self.item(self.draft(), work=2562)])['games'][0]
        listing = self.imp.removable()
        self.assertEqual([x['id'] for x in listing['games']], [g['id']])
        self.imp.delete('test-user', g['id'], listing['base'])
        self.assertEqual(json.loads(read(self.p.manifest)), json.loads(self.original))
        self.assertFalse(self.imp._target(g).exists())
        self.assertFalse(self.imp._target(g, True).exists())
        self.assertEqual(self.draft()['state'], 'ready')

    def test_reimport_receipts_all_orders_and_changed_profile_protection(self):
        import itertools
        for _ in range(2):
            g = self.imp.commit('test-user', [self.item(self.draft())])['games'][0]
            self.imp.delete('test-user', g['id'], self.imp.removable()['base'])
        g = self.imp.commit('test-user', [self.item(self.draft())])['games'][0]
        receipts = list(self.p.state.glob('result-*.json'))
        self.assertEqual(len(receipts), 3)
        for order in itertools.permutations(receipts):
            with patch.object(Path, 'glob', return_value=iter(order)):
                records = self.imp._managed()
            self.assertTrue(self.imp._is_managed(g, records))
            altered = dict(g, loadProfile=dict(g['loadProfile'], gameId=123456))
            self.assertFalse(self.imp._is_managed(altered, records))
        self.assertTrue(next(x for x in self.imp.administration()['games'] if x['id']==g['id'])['removable'])
        self.imp.delete('test-user', g['id'], self.imp.removable()['base'])
        self.assertEqual(json.loads(read(self.p.manifest)), json.loads(self.original))

    def test_delete_protection_stale_and_bad_id(self):
        base = digest(read(self.p.manifest))
        for gid in ('baseline-one', '../baseline-one'):
            with self.assertRaises(Refused): self.imp.delete('test-user', gid, base)
        g = self.imp.commit('test-user', [self.item(self.draft())])['games'][0]
        with self.assertRaises(Refused): self.imp.delete('test-user', g['id'], base)
        response = self.call('/delete', 'POST', {'id': g['id'], 'base': base}, {'HTTP_ORIGIN': 'http://evil'})
        self.assertEqual(response['status'], 403)

    def test_delete_interruption_recovery(self):
        for checkpoint in ('delete-prepared', 'delete-manifest'):
            if not self.imp.removable()['games']:
                self.imp.commit('test-user', [self.item(self.draft())])
            listing = self.imp.removable(); g = listing['games'][0]
            def fail(p):
                if p == checkpoint: raise RuntimeError('interrupted')
            self.imp.checkpoint = fail
            with self.assertRaises(RuntimeError): self.imp.delete('test-user', g['id'], listing['base'])
            self.imp.checkpoint = lambda _: None
            with locked(self.p.state/'import.lock'): self.imp._recover()
            self.assertEqual(self.imp._target(g).exists(), checkpoint == 'delete-prepared')

    def test_delete_changed_rom_refused(self):
        g = self.imp.commit('test-user', [self.item(self.draft())])['games'][0]
        listing = self.imp.removable()
        atomic(self.imp._target(g), b'changed')
        with self.assertRaises(Refused): self.imp.delete('test-user', g['id'], listing['base'])
        self.assertEqual(len(self.imp.manifest()[1]['games']), 6)

    def test_delete_recovery_conflict_blocks(self):
        g = self.imp.commit('test-user', [self.item(self.draft())])['games'][0]
        def fail(p):
            if p == 'delete-manifest': raise RuntimeError('interrupted')
        self.imp.checkpoint = fail
        with self.assertRaises(RuntimeError): self.imp.delete('test-user', g['id'], self.imp.removable()['base'])
        atomic(self.imp._target(g), b'foreign')
        with self.assertRaises(Refused): self.imp._recover()
        self.assertEqual(read(self.imp._target(g)), b'foreign')

    def test_atari_reference_lookup_filename_independent(self):
        import hashlib, zlib
        from formats import inspect
        data=self.bin
        key='sha1:'+hashlib.sha1(data).hexdigest()
        reference={key:{'mapper':'F8','bytes':len(data),'crc32':f'{zlib.crc32(data):08x}',
                        'region':'auto','evidence':'synthetic reference fixture'}}
        actual=inspect('Misleading (PAL) (E0).bin',data,reference)
        self.assertEqual(actual['mapper'],'F8');self.assertEqual(actual['region'],'auto')
        self.assertEqual(actual['sha256'],digest(data))
        self.assertEqual(inspect('Renamed.bin',data,reference),actual)
        with self.assertRaises(Refused): inspect('Known title.bin', data+b'x', reference)

    def test_atari_reference_conflicts_and_scope(self):
        import hashlib, zlib
        from formats import inspect
        key='sha1:'+hashlib.sha1(self.bin).hexdigest()
        profile={'mapper':'F8','bytes':len(self.bin),'crc32':f'{zlib.crc32(self.bin):08x}',
                 'region':'PAL','evidence':'synthetic'}
        for change in ({'bytes':4096},{'crc32':'00000000'},{'mapper':'AR'}, {'mapper':'a26_harmony'}):
            with self.assertRaises(Refused): inspect('Example.bin',self.bin,{key:{**profile,**change}})
        self.assertIsNone(inspect('Example.bin', self.bin, {})['mapper'])

    def test_own_cover_import_and_delete(self):
        upload=self.imp.upload_cover('test-user',image())
        item=self.item(self.draft());item['uploadToken']=upload['token']
        g=self.imp.commit('test-user',[item])['games'][0]
        self.assertTrue(self.imp._target(g,True).exists())
        self.imp.delete('test-user',g['id'],self.imp.removable()['base'])
        self.assertFalse(self.imp._target(g,True).exists())

    def test_cover_update_baseline_and_imported(self):
        upload=self.imp.upload_cover('test-user',image())
        self.imp.set_cover('test-user','baseline-five',digest(read(self.p.manifest)),upload['token'])
        games=self.imp.manifest()[1]['games'];original=json.loads(self.original)['games']
        self.assertEqual(games[:4],original[:4])
        self.assertEqual({k:v for k,v in games[4].items() if k!='cover'},original[4])
        self.assertEqual(self.imp.removable()['games'],[])
        g=self.imp.commit('test-user',[self.item(self.draft())])['games'][0]
        self.imp.set_cover('test-user',g['id'],digest(read(self.p.manifest)),upload['token'])
        self.assertEqual(len(self.imp.removable()['games']),1)

    def test_cover_security_and_stale(self):
        for data in (b'<svg/>',b'bad',b'x'*2097153):
            with self.assertRaises(Refused):self.imp.upload_cover('test-user',data)
        upload=self.imp.upload_cover('test-user',image())
        with self.assertRaises(Refused):self.imp.uploaded_cover('other',upload['token'])
        with self.assertRaises(Refused):self.imp.set_cover('test-user','baseline-one','bad',upload['token'])
        with self.assertRaises(Refused):self.imp.set_cover('test-user','../baseline-one',digest(read(self.p.manifest)),upload['token'])
        self.assertEqual(read(self.p.manifest),self.original)

    def test_cover_failure_recovery(self):
        upload=self.imp.upload_cover('test-user',image())
        for point in ('cover-prepared','cover-file'):
            def fail(p):
                if p==point:raise RuntimeError('fail')
            self.imp.checkpoint=fail
            with self.assertRaises(RuntimeError):self.imp.set_cover('test-user','baseline-one',digest(read(self.p.manifest)),upload['token'])
            self.assertEqual(read(self.p.manifest),self.original)
            self.assertFalse((self.p.covers/'baseline-one.jpg').exists())

if __name__ == '__main__':
    unittest.main(verbosity=2)
