#!/usr/bin/env python3
from __future__ import annotations
import importlib.util, struct, sys, unittest
from pathlib import Path

GEN=Path(__file__).with_name("generate-pub2c-root-document.py")
spec=importlib.util.spec_from_file_location("pub2c_root_document",GEN)
assert spec and spec.loader
m=importlib.util.module_from_spec(spec); sys.modules[spec.name]=m; spec.loader.exec_module(m)
base=m.load_base()

def parse_fields(data:bytes):
    declared=struct.unpack_from("<I",data,0)[0]
    assert declared==len(data)
    out=[]; pos=4
    while pos<len(data):
        b=base._parse_block(data,pos)
        out.append(b)
        pos=b["end"]
    assert pos==len(data)
    return out

def byid(data:bytes):
    return {b["id"]:b for b in parse_fields(data)}

def model(**kw):
    d=dict(
      pages=(300,301,302,303,304,305),
      dimensions=(10058400,7772400),
      dw_next_unique_oid=3,
      c_times_edited=1,
      slam=4,
    )
    d.update(kw)
    return m.DocumentModel(**d)

class RootDocumentMetamorphic(unittest.TestCase):
    def test_declared_length_is_exact(self):
        for n in (1,2,6,7,9,20):
            data=m.build_document(model(pages=tuple(range(300,300+n))))
            self.assertEqual(struct.unpack_from("<I",data,0)[0],len(data))

    def test_cpd_equals_page_count_and_page_list_payload(self):
        for n in (1,2,6,7,9):
            pages=tuple(range(500,500+n))
            data=m.build_document(model(pages=pages))
            fs=byid(data)
            self.assertEqual(fs[0x01]["value"],n)
            children=base._children(data,fs[0x02])
            self.assertEqual([x["value"] for x in children],list(pages))
            self.assertEqual(fs[0x02]["data_length"],4+6*n)

    def test_each_added_page_adds_exactly_six_bytes(self):
        a=m.build_document(model(pages=(1,2,3)))
        b=m.build_document(model(pages=(1,2,3,4)))
        self.assertEqual(len(b)-len(a),6)

    def test_dimensions_roundtrip(self):
        dims=[(10058400,7772400),(7772400,10058400),(6400800,3346704),(5029200,3886200)]
        for pair in dims:
            data=m.build_document(model(dimensions=pair))
            fs=byid(data); ch=base._children(data,fs[0x12])
            self.assertEqual(tuple(x["value"] for x in ch),pair)

    def test_optional_field_size_laws(self):
        base_doc=m.build_document(model())
        cases=[
          ("lo_page_layout",9,6,0x11),
          ("dxl_default_tab",12700,6,0x15),
          ("navbar_handle",327,6,0x3B),
          ("print_settings_saved",True,2,0x4A),
        ]
        for name,value,delta,fid in cases:
            data=m.build_document(model(**{name:value}))
            self.assertEqual(len(data)-len(base_doc),delta)
            self.assertIn(fid,byid(data))
            self.assertNotIn(fid,byid(base_doc))

    def test_lifecycle_scalars_are_independent(self):
        a=m.build_document(model(dw_next_unique_oid=3,c_times_edited=1,slam=4))
        b=m.build_document(model(dw_next_unique_oid=7,c_times_edited=3,slam=23))
        fa,fb=byid(a),byid(b)
        self.assertEqual(fb[0x23]["value"],7)
        self.assertEqual(fb[0x3C]["value"],3)
        self.assertEqual(fb[0x46]["value"],23)
        ids=[x["id"] for x in parse_fields(a)]
        self.assertEqual(ids,[x["id"] for x in parse_fields(b)])
        for fid in ids:
            if fid not in (0x23,0x3C,0x46):
                sa=a[fa[fid]["start"]:fa[fid]["end"]]
                sb=b[fb[fid]["start"]:fb[fid]["end"]]
                self.assertEqual(sa,sb,f"unexpected change at field 0x{fid:02X}")

    def test_corpus_stable_named_handles_default(self):
        fs=byid(m.build_document(model()))
        expected={0x03:287,0x04:291,0x14:293,0x18:259,0x19:261,0x1A:257,
                  0x20:282,0x21:262,0x22:285,0x31:278,0x44:292}
        for fid,value in expected.items():
            self.assertEqual(fs[fid]["value"],value)

    def test_ident_guid_is_explicit_zero_fixed16(self):
        data=m.build_document(model()); fs=byid(data); b=fs[0x2A]
        self.assertEqual(b["type"],0x38)
        self.assertEqual(data[b["data_offset"]:b["end"]],b"\x00"*16)

if __name__=="__main__":
    unittest.main(verbosity=2)
