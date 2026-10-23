"""Technical image checks only. No trainer or game-content identification."""
import re
import hashlib
import zlib
from storage import demand, digest


SECTORS = [21]*17 + [19]*7 + [18]*6 + [17]*5
OFFSETS = [sum(SECTORS[:i])*256 for i in range(35)]


def d64(data):
    demand(len(data) == 174848, 'D64 muss genau 174848 Bytes haben.')
    def sector(t, s):
        demand(1 <= t <= 35 and 0 <= s < SECTORS[t-1], 'Ungültige D64-Spur/Sektornummer.')
        i = OFFSETS[t-1] + s*256
        return data[i:i+256]
    bam = sector(18, 0)
    demand(bam[:3] == bytes([18, 1, 65]), 'D64-BAM-Kennung nicht unterstützt.')
    free = set()
    for t, n in enumerate(SECTORS, 1):
        row = bam[4+(t-1)*4:8+(t-1)*4]
        bits = int.from_bytes(row[1:], 'little')
        demand(bits >> n == 0 and row[0] == bits.bit_count(), 'D64-BAM-Freiblöcke inkonsistent.')
        free.update((t, s) for s in range(n) if bits & (1 << s))
    used = {(18, 0)}
    demand((18, 0) not in free, 'D64-BAM-Sektor ist als frei markiert.')
    entries = []
    t, s = bam[0], bam[1]
    while t:
        demand((t, s) not in used and (t, s) not in free, 'D64-Verzeichnisschleife oder freier Verzeichnisblock.')
        used.add((t, s))
        block = sector(t, s)
        for i in range(8):
            e = block[i*32:i*32+32]
            typ = e[2]
            if typ == 0:
                continue
            if typ == 0x80:
                # Closed DEL entries with no blocks are directory decoration,
                # not live files. Never follow their conventional BAM pointer.
                demand(e[3:5] in (bytes([0, 0]), bytes([18, 0])) and
                       e[21:32] == bytes(11),
                       'DEL-Verzeichniseintrag mit Nutzdaten/ungewoehnlichem Zeiger nicht unterstuetzt.')
                continue
            demand(typ & 0x80 and typ & 7 in (1, 2, 3) and not typ & 0x38,
                   'D64-Dateityp/offene Datei nicht unterstützt (nur geschlossene SEQ/PRG/USR).')
            entries.append((e[3], e[4], int.from_bytes(e[30:32], 'little'), typ & 7))
        t, s = block[0], block[1]
    demand(any(x[3] == 2 for x in entries), 'Kein geschlossenes PRG für generisches Laden vorhanden.')
    for t, s, count, _ in entries:
        actual = 0
        while t:
            demand((t, s) not in used and (t, s) not in free, 'D64-Dateikette überlappt oder verweist auf freien Block.')
            used.add((t, s))
            block = sector(t, s)
            actual += 1
            t, s = block[0], block[1]
            if t == 0:
                demand(s >= 1, 'Ungültige D64-Endsektorlänge.')
        demand(count == actual and actual > 0, 'D64-Dateiblockzahl inkonsistent.')
    return {'format': 'd64', 'bytes': len(data), 'files': len(entries)}


# These names and sizes match the pinned Javatari 5.0.4 CartridgeFormats.
# AR is deliberately absent: Supercharger requires an additional tape protocol.
MAX_IMAGE = 524288
MAPPER_ALIASES = {
    'F8+RAM': 'F8', 'F6+RAM': 'F6', 'a26_f4': 'F4', 'a26_f4+RAM': 'F4',
    'a26_e0': 'E0', 'a26_fe': 'FE', 'a26_e7+RAM': 'E7', 'a26_cv+RAM': 'CV',
    'a26_fa+RAM': 'FA', 'a26_dpc': 'DPC', 'a26_3f': '3F', 'a26_3e+RAM': '3E',
    'a26_ua': 'UA', 'a26_f0': 'F0', 'a26_x07': 'X07',
}


def mapper_choices(size, data=None):
    choices = []
    fixed = {'CV': (2048, 4096), 'E0': (8192,), 'F0': (65536,),
             'FE': (8192,), 'E7': (16384,), 'F8': (8192,), 'F6': (16384,),
             'F4': (32768,), 'FA2': (24576, 28672, 32768), 'FA': (12288,),
             'X07': (65536,), '0840': (8192,), 'UA': (8192,)}
    if 8 <= size <= 4096 and 4096 % size == 0:
        choices.append('4K')
    choices.extend(m for m, sizes in fixed.items() if size in sizes)
    if size == 32768 and (data is None or data[32:36] == bytes.fromhex('1eabad10')):
        choices.append('FA2cu')
    if 8192 <= size <= 65536 and size % 4096 == 0:
        choices.append('EF')
    if 10240 <= size <= 10496:
        choices.append('DPC')
    if 2048 <= size <= MAX_IMAGE and size % 2048 == 0:
        choices.extend(('3F', '3E'))
    if 8192 <= size <= 262144 and size % 4096 == 0:
        choices.append('SB')
    return choices


def prg(data):
    demand(3 <= len(data) <= 65537, 'PRG muss Ladeadresse und 1 bis 65535 Nutzbytes enthalten.')
    start = int.from_bytes(data[:2], 'little')
    demand(start >= 2 and start + len(data) - 2 <= 65536,
           'PRG-Ladeadresse oder Adressüberlauf ungültig.')
    return {'loadAddress': start, 'payloadBytes': len(data)-2}


def t64(data):
    demand(96 <= len(data) <= MAX_IMAGE, 'T64-Größe ungültig (maximal 512 KiB).')
    magic = data[:32].split(b'\0', 1)[0].rstrip(b' ')
    demand(magic in (b'C64 tape image file', b'C64S tape image file', b'C64S tape file'),
           'T64-Kennung nicht unterstützt.')
    word = lambda n: int.from_bytes(data[n:n+2], 'little')
    capacity, used = word(34), word(36)
    demand(word(32) in (0x100, 0x101) and 1 <= used <= capacity <= 1024 and
           64 + capacity*32 <= len(data), 'T64-Version, Zähler oder Verzeichnis ungültig.')
    entries, spans = [], []
    for index in range(capacity):
        o = 64+index*32
        e = data[o:o+32]
        if e[0] == 0:
            demand(e == bytes(32), 'T64-Leereintrag mit widersprüchlichen Metadaten.')
            continue
        demand(e[0] == 1 and e[1] in (0x82, 0x02) and e[6:8] == bytes(2) and e[12:16] == bytes(4),
               'T64 unterstützt nur reguläre PRG-Einträge ohne Zusatzmetadaten.')
        start, end = int.from_bytes(e[2:4], 'little'), int.from_bytes(e[4:6], 'little')
        offset = int.from_bytes(e[8:12], 'little')
        demand(2 <= start < end <= 65535 and offset >= 64+capacity*32 and
               offset+end-start <= len(data), 'T64-Programmadresse/Datenbereich ungültig.')
        stop = offset+end-start
        demand(all(stop <= a or offset >= b for a, b in spans), 'T64-Programmdaten überlappen.')
        spans.append((offset, stop))
        # Display only; never use PETSCII names as host filenames or commands.
        name = ''.join(chr(c) if 32 <= c <= 126 else '?' for c in e[16:32]).strip(' ?')
        entries.append({'index': index, 'name': name or 'Programm '+str(index+1),
                        'loadAddress': start, 'bytes': end-start})
    demand(len(entries) == used, 'T64-Eintragszähler widerspricht dem Inhalt.')
    return entries


def inspect(filename, data, profiles, mapper=None):
    demand(isinstance(filename, str) and 0 < len(filename) <= 240 and
           not re.search(r'[\\/\x00-\x1f\x7f]', filename), 'Ungültiger Dateiname.')
    demand(0 < len(data) <= MAX_IMAGE, 'Dateigröße ungültig.', 413)
    sha = digest(data)
    ext = filename.rsplit('.', 1)[-1].lower()
    if ext in ('d64', 'prg', 't64'):
        demand(mapper is None, 'Mapperwahl ist nur bei unbekannten Atari-Dateien zulässig.')
        details = {}
        if ext == 'd64':
            d64(data)
        elif ext == 'prg':
            details = prg(data)
        else:
            details = {'programs': t64(data)}
        return {'system': 'c64', 'format': ext, 'sha256': sha, 'bytes': len(data), 'joyPort': 1, **details}
    demand(ext == 'bin', 'Nur BIN, D64, PRG und T64 sind freigegeben.')
    choices = mapper_choices(len(data), data)
    demand(bool(choices), 'Keine unterstützte Atari-Modulgröße; Datei zurückgestellt.', 422)
    profile = profiles.get(sha)
    if profile is None:
        profile = profiles.get('sha1:'+hashlib.sha1(data).hexdigest())
        if profile is not None:
            demand(isinstance(profile, dict) and profile.get('bytes') == len(data) and
                   profile.get('crc32') == f'{zlib.crc32(data):08x}',
                   'Referenzprofil widerspricht Größe/CRC32; Datei zurückgestellt.', 422)
    if profile is None:
        demand(mapper is None or isinstance(mapper, str) and mapper in choices,
               'Mapperwahl passt nicht zur Datei.', 422)
        return {'system': 'vcs2600', 'format': 'bin', 'bytes': len(data), 'sha256': sha,
                'mapper': mapper, 'region': 'auto', 'mapperChoices': choices}
    demand(isinstance(profile, dict) and profile.get('evidence'), 'Referenzprofil nicht belegt.', 422)
    native = MAPPER_ALIASES.get(profile.get('mapper'), profile.get('mapper'))
    demand(native in choices, 'Cartridge-Typ '+str(profile.get('mapper'))+' nicht unterstützt oder Größe unpassend.', 422)
    demand(mapper is None or mapper == native, 'Belegter Mapper darf nicht überschrieben werden.', 422)
    region = profile.get('region', 'auto')
    demand(region in ('auto', 'PAL', 'NTSC'), 'Ungültige Regionsmetadaten.')
    return {'system': 'vcs2600', 'format': 'bin', 'bytes': len(data), 'sha256': sha,
            'mapper': native, 'region': region}
