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
def pair(fid,a,b):return var(fid,0x88,u32(0x01,0x20,a)+u32(0x02,0x20,b))
def text(fid,s):return var(fid,0xC0,s.encode("utf-16le")+b"\x00\x00")

@dataclass(frozen=True)
class Page266:
    objects:tuple[int,...]
    origin:tuple[int,int]
    oid:bytes
    oh_controlling:int
    oh_web_page_props:int
    oh_form_properties:int
    master:int
    short_name:str
    long_name:str
    pgt_type:int
    origin_ex:tuple[int,int]

def build_page(m:Page266)->bytes:
    if len(m.oid)!=8:raise ValueError("Oid must be 8 bytes")
    obj_payload=b"".join(u32(0x00,0x70,x) for x in m.objects)
    body=b"".join([
      u32(0x01,0x20,len(m.objects)),
      var(0x02,0xA0,obj_payload),
      pair(0x05,*m.origin),
      fixed(0x06,0x28,m.oid),
      u32(0x08,0x70,m.oh_controlling),
      u32(0x09,0x70,m.oh_web_page_props),
      u32(0x0B,0x70,m.oh_form_properties),
      u32(0x0D,0x68,m.master),
      text(0x0E,m.short_name),
      text(0x0F,m.long_name),
      u32(0x10,0x20,m.pgt_type),
      pair(0x11,*m.origin_ex),
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
def parse_pair(raw,b):
    by={x["id"]:x for x in base._children(raw,b)};return (by[1]["value"],by[2]["value"])
def parse_text(raw,b):
    p=payload(raw,b);return (p[:-2] if p.endswith(b"\x00\x00") else p).decode("utf-16le")
def parse_page(raw):
    fs={};pos=4
    while pos<len(raw):
        b=base._parse_block(raw,pos);fs[b["id"]]=b;pos=b["end"]
    objects=tuple(x["value"] for x in base._children(raw,fs[0x02]))
    if fs[0x01]["value"]!=len(objects):raise ValueError("CPo mismatch")
    return Page266(objects=objects,origin=parse_pair(raw,fs[0x05]),oid=payload(raw,fs[0x06]),
                   oh_controlling=fs[0x08]["value"],oh_web_page_props=fs[0x09]["value"],oh_form_properties=fs[0x0B]["value"],
                   master=fs[0x0D]["value"],short_name=parse_text(raw,fs[0x0E]),long_name=parse_text(raw,fs[0x0F]),
                   pgt_type=fs[0x10]["value"],origin_ex=parse_pair(raw,fs[0x11]))

def validate(apk):
    total=ok=0;fails=[];counts=set()
    with zipfile.ZipFile(apk) as z:
      pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
      for name in pubs:
        c=contents(z.read(name));rr=refs(c);r=next(x for x in rr if x["seq"]==266 and x["type"]==0x43 and x["parent"]==256)
        n=int.from_bytes(c[r["off"]:r["off"]+4],"little");raw=c[r["off"]:r["off"]+n];m=parse_page(raw);got=build_page(m)
        total+=1;counts.add(len(m.objects))
        if got==raw:ok+=1
        else:
          lim=min(len(got),len(raw));at=next((i for i in range(lim) if got[i]!=raw[i]),lim);fails.append((name,at,raw[at:at+16].hex(),got[at:at+16].hex()))
    print("validated",total)
    print("byte_identical",ok,"/",total)
    print("object_count_variants",sorted(counts))
    if fails:print("first_failure",fails[0]);raise SystemExit(1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);a=ap.parse_args();validate(a.base_apk)
if __name__=="__main__":main()
