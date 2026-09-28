#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, io, struct, sys, zipfile
from dataclasses import dataclass
from pathlib import Path
try:
    import olefile
except ImportError as exc:
    raise SystemExit("Missing dependency: python -m pip install olefile") from exc

TEMPLATE_PREFIX="assets/Publisher Templates/2013/BUILT-IN/"
BASE=Path(__file__).with_name("analyze-canyua-template-corpus.py")

def load_base():
    spec=importlib.util.spec_from_file_location("canyua_template_corpus",BASE)
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod

def fixed(fid,typ,payload=b""):
    return bytes((fid,typ))+payload
def u16(fid,typ,v): return fixed(fid,typ,struct.pack("<H",v))
def u32(fid,typ,v): return fixed(fid,typ,struct.pack("<I",v))
def var(fid,typ,payload): return bytes((fid,typ))+struct.pack("<I",len(payload)+4)+payload
def handle(fid,v): return u32(fid,0x70,v)
def presence(fid,typ): return bytes((fid,typ))

FIELD_ORDER=(0x01,0x02,0x03,0x04,0x08,0x0E,0x11,0x12,0x14,0x15,0x18,0x19,0x1A,0x20,0x21,0x22,0x23,0x2A,0x2C,0x2D,0x31,0x39,0x3B,0x3C,0x41,0x44,0x46,0x4A,0x4D)

@dataclass(frozen=True)
class DocumentModel:
    pages: tuple[int,...]
    dimensions: tuple[int,int]
    dw_next_unique_oid: int
    c_times_edited: int
    slam: int
    lo_page_layout: int|None=None
    dxl_default_tab: int|None=None
    navbar_handle: int|None=None
    print_settings_saved: bool=False
    # Corpus-stable service handles/defaults.
    oh_print_block:int=287
    oh_bullet_list:int=291
    oh_morphing_context:int=293
    oh_gallery:int=259
    oh_fancy_borders:int=261
    oh_captions:int=257
    oh_quill_doc:int=282
    oh_mail_merge_data:int=262
    oh_color_scheme:int=285
    ohpl_dgcat:int=278
    oh_imposition_engine:int=292
    dpg_special:int=5
    dpg_master:int=1
    nu_default_units_ex:int=0

def build_document(m:DocumentModel)->bytes:
    fields=[]
    page_payload=b"".join(handle(0x00,v) for v in m.pages)
    dims_payload=u32(0x01,0x20,m.dimensions[0])+u32(0x02,0x20,m.dimensions[1])
    values={
      0x01:u32(0x01,0x20,len(m.pages)),
      0x02:var(0x02,0xA0,page_payload),
      0x03:handle(0x03,m.oh_print_block),
      0x04:handle(0x04,m.oh_bullet_list),
      0x08:presence(0x08,0x08),
      0x0E:presence(0x0E,0x08),
      0x12:var(0x12,0x88,dims_payload),
      0x14:handle(0x14,m.oh_morphing_context),
      0x18:handle(0x18,m.oh_gallery),
      0x19:handle(0x19,m.oh_fancy_borders),
      0x1A:handle(0x1A,m.oh_captions),
      0x20:handle(0x20,m.oh_quill_doc),
      0x21:handle(0x21,m.oh_mail_merge_data),
      0x22:handle(0x22,m.oh_color_scheme),
      0x23:u32(0x23,0x20,m.dw_next_unique_oid),
      0x2A:fixed(0x2A,0x38,b"\x00"*16),
      0x2C:u16(0x2C,0x18,m.dpg_special),
      0x2D:u16(0x2D,0x18,m.dpg_master),
      0x31:u32(0x31,0x68,m.ohpl_dgcat),
      0x39:presence(0x39,0x00),
      0x3C:u32(0x3C,0x20,m.c_times_edited),
      0x41:u32(0x41,0x20,m.nu_default_units_ex),
      0x44:handle(0x44,m.oh_imposition_engine),
      0x46:u32(0x46,0x20,m.slam),
      0x4D:presence(0x4D,0x08),
    }
    if m.lo_page_layout is not None: values[0x11]=u32(0x11,0x20,m.lo_page_layout)
    if m.dxl_default_tab is not None: values[0x15]=u32(0x15,0x20,m.dxl_default_tab)
    if m.navbar_handle is not None: values[0x3B]=handle(0x3B,m.navbar_handle)
    if m.print_settings_saved: values[0x4A]=presence(0x4A,0x08)
    for fid in FIELD_ORDER:
        if fid in values: fields.append(values[fid])
    body=b"".join(fields)
    return struct.pack("<I",len(body)+4)+body

def read_contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole: return ole.openstream(["Contents"]).read()

def parse_model(mod,c):
    s=mod.analyze_contents_0x2c(c,b""); off=s["first_chunk_offset"]; n=int.from_bytes(c[off:off+4],"little"); raw=c[off:off+n]
    fields={}; pos=4
    while pos<len(raw):
        b=mod._parse_block(raw,pos); fields[b["id"]]=b; pos=b["end"]
    def val(fid,default=None):
        b=fields.get(fid); return default if b is None else b["value"]
    pages=[x["value"] for x in mod._children(raw,fields[0x02]) if x["type"]==0x70]
    dims=[x["value"] for x in mod._children(raw,fields[0x12]) if x["id"] in (1,2)]
    model=DocumentModel(
      pages=tuple(pages),dimensions=(dims[0],dims[1]),
      dw_next_unique_oid=val(0x23),c_times_edited=val(0x3C),slam=val(0x46),
      lo_page_layout=val(0x11),dxl_default_tab=val(0x15),navbar_handle=val(0x3B),
      print_settings_saved=0x4A in fields,
      oh_print_block=val(0x03),oh_bullet_list=val(0x04),oh_morphing_context=val(0x14),
      oh_gallery=val(0x18),oh_fancy_borders=val(0x19),oh_captions=val(0x1A),
      oh_quill_doc=val(0x20),oh_mail_merge_data=val(0x21),oh_color_scheme=val(0x22),
      ohpl_dgcat=val(0x31),oh_imposition_engine=val(0x44),
      dpg_special=val(0x2C),dpg_master=val(0x2D),nu_default_units_ex=val(0x41),
    )
    return off,raw,model,fields

def validate(apk):
    mod=load_base(); checked=0; schemas=set(); failures=[]; constant_mismatch=[]
    with zipfile.ZipFile(apk) as z:
      pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
      for name in pubs:
        c=read_contents(z.read(name)); off,raw,m,fields=parse_model(mod,c); got=build_document(m)
        schemas.add(tuple(fields))
        # These fields are expected corpus constants, but keep validation explicit.
        defaults=(m.oh_print_block,m.oh_bullet_list,m.oh_morphing_context,m.oh_gallery,m.oh_fancy_borders,m.oh_captions,m.oh_quill_doc,m.oh_mail_merge_data,m.oh_color_scheme,m.ohpl_dgcat,m.oh_imposition_engine,m.dpg_special,m.dpg_master,m.nu_default_units_ex)
        expected=(287,291,293,259,261,257,282,262,285,278,292,5,1,0)
        if defaults!=expected: constant_mismatch.append((name,defaults))
        if got!=raw:
          lim=min(len(got),len(raw)); at=next((i for i in range(lim) if got[i]!=raw[i]),lim)
          failures.append((name,len(raw),len(got),at,raw[at:at+16].hex(),got[at:at+16].hex()))
        checked+=1
    print("validated",checked)
    print("byte_identical",checked-len(failures),"/",checked)
    print("schema_count",len(schemas))
    print("constant_mismatch",len(constant_mismatch))
    if failures:
      print("first_failure",failures[0]); raise SystemExit(1)
    if constant_mismatch:
      print("first_constant_mismatch",constant_mismatch[0]); raise SystemExit(2)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("base_apk",type=Path); a=ap.parse_args(); validate(a.base_apk)
if __name__=="__main__": main()
