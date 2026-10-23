"""Reproducible offline MAME metadata import. No ROM input/network required."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

HERE=Path(__file__).resolve().parent
REV='c993311c3074fa0dc6395e37aa44d7b4adce28ae'
XML_SHA='efe03008c6c2a4aa197eac1242d838913b3ec4eb434d04f2b59bb769a726197c'

def build(source):
    raw=source.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==XML_SHA, 'Source snapshot changed'
    result={}
    blocked=set()
    for software in ET.fromstring(raw).findall('software'):
        for part in software.findall('part'):
            if part.get('interface')!='a2600_cart': continue
            roms=part.findall("dataarea[@name='rom']/rom")
            if len(roms)!=1: continue
            rom=roms[0];sha=rom.get('sha1','');crc=rom.get('crc','')
            if not re.fullmatch('[0-9a-f]{40}',sha) or not re.fullmatch('[0-9a-f]{8}',crc) or rom.get('status') in ('baddump','nodump'): continue
            size_text=rom.get('size','0')
            size=int(size_text,16 if size_text.startswith('0x') else 10)
            feature=part.find("feature[@name='slot']")
            slot=feature.get('value') if feature is not None else 'a26_2k_4k'
            mapper={'a26_2k_4k':'4K','a26_f8':'F8','a26_f6':'F6'}.get(slot,slot)
            if part.find("dataarea[@name='ram']") is not None: mapper += '+RAM'
            desc=software.findtext('description','')
            # Only explicit source metadata, never the uploaded filename.
            region='PAL' if re.search(r'\bPAL\b',desc) else 'NTSC' if re.search(r'\bNTSC\b',desc) else 'auto'
            entry={'mapper':mapper,'bytes':size,'crc32':crc,'region':region,
                   'evidence':f'MAME a2600.xml {REV}; software={software.get("name")}; slot={slot}; CC0-1.0'}
            key='sha1:'+sha
            if key in result:
                previous=result[key]
                if any(previous[k]!=entry[k] for k in ('mapper','bytes','crc32')): blocked.add(key)
                elif previous['region']!=region: previous['region']='auto'
            else: result[key]=entry
    for key in blocked: result.pop(key,None)
    return result

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    print(json.dumps(build(parser.parse_args().input), indent=2))
