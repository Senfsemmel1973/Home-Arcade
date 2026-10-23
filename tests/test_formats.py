"""Synthetic DEL compatibility regressions; no game files or VM access."""
import hashlib,importlib.util,json,sys,unittest
from pathlib import Path
from unittest.mock import patch
P=Path(__file__).resolve().parent;ROOT=P.parent
sys.path.insert(0,str(ROOT/'app'))
import formats
import test_import
from storage import Refused,read
from service import Importer

def decorated(pointer=(18,0),typ=0x80):
    b=bytearray(test_import.disk());o=formats.OFFSETS[17]+256+32
    b[o+2:o+5]=bytes([typ,*pointer]);b[o+5:o+21]=b'-'*16
    return b,o

class Compatibility(unittest.TestCase):
    def test_zero_block_del_bam_and_null_pointer(self):
        for pointer in ((18,0),(0,0)):
            with self.subTest(pointer=pointer):self.assertEqual(formats.d64(decorated(pointer)[0])['files'],1)
    def test_del_name_not_game_or_separator_heuristic(self):
        b,o=decorated();b[o+5:o+21]=bytes(range(16))
        self.assertEqual(formats.d64(b)['files'],1)
    def test_del_nonzero_block_count_rejected(self):
        for byte in (30,31):
            b,o=decorated();b[o+byte]=1
            with self.subTest(byte=byte),self.assertRaises(Refused):formats.d64(b)
    def test_del_auxiliary_metadata_rejected(self):
        for byte in range(21,30):
            b,o=decorated();b[o+byte]=1
            with self.subTest(byte=byte),self.assertRaises(Refused):formats.d64(b)
    def test_del_payload_or_invalid_pointer_rejected(self):
        for pointer in ((1,0),(18,1),(0,1),(35,17),(255,255)):
            with self.subTest(pointer=pointer),self.assertRaises(Refused):formats.d64(decorated(pointer)[0])
    def test_unclosed_locked_unknown_del_and_rel_still_rejected(self):
        for typ in (0x01,0x02,0x03,0x04,0x84,0xc0,0x88,0x90,0xa0):
            with self.subTest(typ=typ),self.assertRaises(Refused):formats.d64(decorated(typ=typ)[0])
    def test_del_cannot_replace_required_prg(self):
        b,o=decorated();b[formats.OFFSETS[17]+256+2]=0
        with self.assertRaisesRegex(Refused,'PRG'):formats.d64(b)
    def test_active_file_cycle_not_hidden_by_decoration(self):
        b,_=decorated();b[:2]=bytes([1,0])
        with self.assertRaisesRegex(Refused,'überlappt'):formats.d64(b)
    def test_active_file_free_sector_not_hidden_by_decoration(self):
        b,_=decorated();b[formats.OFFSETS[17]+256+4]=1
        with self.assertRaisesRegex(Refused,'frei'):formats.d64(b)
    def test_directory_cycle_not_hidden_by_decoration(self):
        b,_=decorated();b[formats.OFFSETS[17]+256:formats.OFFSETS[17]+258]=bytes([18,1])
        with self.assertRaisesRegex(Refused,'schleife'):formats.d64(b)
    def test_active_crosslink_still_rejected(self):
        b,o=decorated();o+=32;b[o+2:o+5]=bytes([0x82,1,0]);b[o+30]=1
        with self.assertRaisesRegex(Refused,'überlappt'):formats.d64(b)
    def test_closed_seq_usr_and_locked_prg_unchanged(self):
        for typ in (0x81,0x83,0xc2):
            b,o=decorated((1,1),typ);b[o+30]=1;b[256:258]=bytes([0,1])
            b[formats.OFFSETS[17]+4]=19;b[formats.OFFSETS[17]+5]&=~2
            with self.subTest(typ=typ):self.assertEqual(formats.d64(b)['files'],2)

if __name__=='__main__':unittest.main()
