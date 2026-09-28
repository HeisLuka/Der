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
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod
base=load_base()

def fixed(fid,typ,p=b""):return bytes((fid,typ))+p
def u32(fid,typ,v):return fixed(fid,typ,struct.pack("<I",v))
def var(fid,typ,p):return bytes((fid,typ))+struct.pack("<I",len(p)+4)+p
def nested_pair(fid,a,b):return var(fid,0x88,u32(0x01,0x20,a)+u32(0x02,0x20,b))

@dataclass(frozen=True)
class Page263:
    oh_mg_page:int
    origin:tuple[int,int]
    oid:bytes
    oh_web_page_props:int
    oh_form_properties:int
    short_name:str
    long_name:str
    pgt_type:int
    origin_ex:tuple[int,int]

def build_page(m:Page263)->bytes:
    if len(m.oid)!=8:raise ValueError("Oid must be 8 bytes")
    body=b"".join([
      u32(0x03,0x70,m.oh_mg_page),
      nested_pair(0x05,*m.origin),
      fixed(0x06,0x28,m.oid),
      u32(0x09,0x70,m.oh_web_page_props),
      u32(0x0B,0x70,m.oh_form_properties),
      var(0x0E,0xC0,m.short_name.encode("utf-16le")+b"\x00\x00"),
      var(0x0F,0xC0,m.long_name.encode("utf-16le")+b"\x00\x00"),
      u32(0x10,0x20,m.pgt_type),
      nested_pair(0x11,*m.origin_ex),
    ])
    return struct.pack("<I",len(body)+4)+body

def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:return ole.openstream(["Contents"]).read()

def refs(c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little");pos=trailer+4;parts=[]
    for _ in range(3):
        p=base._parse_block(c,pos);parts.append(p);pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90);out=[];seq=-1
    for e in base._children(c,d):
        seq+=1
        if e["type"]!=0x88:continue
        vals={}
        for ch in base._children(c,e):
            if ch["id"] in (2,4,5):vals[ch["id"]]=ch["value"]
        if vals.get(4) is not None:out.append({"seq":seq,"type":vals.get(2),"off":vals.get(4),"parent":vals.get(5)})
    return sorted(out,key=lambda r:r["off"])

def payload(raw,b):return raw[b["payload_offset"]:b["end"]]
def pair(raw,b):
    ch=base._children(raw,b);by={x["id"]:x for x in ch};return (by[1]["value"],by[2]["value"])
def text(raw,b):
    p=payload(raw,b);return (p[:-2] if p.endswith(b"\x00\x00") else p).decode("utf-16le")

def parse_page(raw:bytes)->Page263:
    pos=4;fs={}
    while pos<len(raw):
        b=base._parse_block(raw,pos);fs[b["id"]]=b;pos=b["end"]
    return Page263(
      oh_mg_page=fs[0x03]["value"],
      origin=pair(raw,fs[0x05]),
      oid=payload(raw,fs[0x06]),
      oh_web_page_props=fs[0x09]["value"],
      oh_form_properties=fs[0x0B]["value"],
      short_name=text(raw,fs[0x0E]),
      long_name=text(raw,fs[0x0F]),
      pgt_type=fs[0x10]["value"],
      origin_ex=pair(raw,fs[0x11]),
    )

def validate(apk):
    total=ok=0;fails=[];profiles=set()
    with zipfile.ZipFile(apk) as z:
      pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
      for name in pubs:
        c=contents(z.read(name));rr=refs(c);r=next(x for x in rr if x["seq"]==263 and x["type"]==0x43 and x["parent"]==256)
        n=int.from_bytes(c[r["off"]:r["off"]+4],"little");raw=c[r["off"]:r["off"]+n];m=parse_page(raw);got=build_page(m)
        profiles.add((m.origin,m.oid,m.origin_ex))
        total+=1
        if got==raw:ok+=1
        else:
          lim=min(len(got),len(raw));at=next((i for i in range(lim) if got[i]!=raw[i]),lim);fails.append((name,at,raw[at:at+16].hex(),got[at:at+16].hex()))
    print("validated",total)
    print("byte_identical",ok,"/",total)
    print("identity_origin_profiles",len(profiles))
    if fails:print("first_failure",fails[0]);raise SystemExit(1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);a=ap.parse_args();validate(a.base_apk)
if __name__=="__main__":main()
