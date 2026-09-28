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

def fixed(fid,typ,payload=b""): return bytes((fid,typ))+payload
def u16(fid,typ,v): return fixed(fid,typ,struct.pack("<H",v))
def u32(fid,typ,v): return fixed(fid,typ,struct.pack("<I",v))
def var(fid,typ,payload): return bytes((fid,typ))+struct.pack("<I",len(payload)+4)+payload
def container(fid,typ,children): return var(fid,typ,b"".join(children))

@dataclass(frozen=True)
class FancyBorderDef:
    optional_02:int|None
    name:str
    scalar_04:int
    scalar_05:int
    scalar_06:int
    scalar_07:int
    order_keys:tuple[int,...]
    scalar_09:int
    wmfs:tuple[bytes,...]

def build_definition(d:FancyBorderDef)->bytes:
    fields=[]
    if d.optional_02 is not None: fields.append(u32(0x02,0x20,d.optional_02))
    fields.append(var(0x03,0xC0,d.name.encode("utf-16le")+b"\x00\x00"))
    fields += [u32(0x04,0x20,d.scalar_04),u32(0x05,0x20,d.scalar_05),u32(0x06,0x20,d.scalar_06),u32(0x07,0x20,d.scalar_07)]
    fields.append(container(0x08,0x90,[u16(0x00,0x18,x) for x in d.order_keys]))
    fields.append(u16(0x09,0x18,d.scalar_09))
    image_entries=[]
    for wmf in d.wmfs:
        image_entries.append(container(0x00,0x88,[var(0x01,0x80,wmf)]))
    fields.append(container(0x0A,0xA0,image_entries))
    return container(0x00,0x88,fields)

def build_fancy_borders(defs:tuple[FancyBorderDef,...])->bytes:
    if not defs:
        return struct.pack("<I",4)
    body=u32(0x01,0x20,len(defs))+container(0x02,0xA0,[build_definition(d) for d in defs])
    return struct.pack("<I",len(body)+4)+body

def read_contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:return ole.openstream(["Contents"]).read()

def directory_refs(c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little");pos=trailer+4;parts=[]
    for _ in range(3):
        p=base._parse_block(c,pos);parts.append(p);pos=p["end"]
    directory=next(p for p in parts if p["type"]==0x90)
    out=[];seq=-1
    for e in base._children(c,directory):
        seq+=1
        if e["type"]!=0x88:continue
        vals={}
        for ch in base._children(c,e):
            if ch["id"] in (2,4,5):vals[ch["id"]]=ch["value"]
        if vals.get(4) is not None:out.append({"seq":seq,"type":vals.get(2),"off":vals.get(4),"parent":vals.get(5)})
    return sorted(out,key=lambda r:r["off"])

def payload(raw,b): return raw[b["payload_offset"]:b["end"]]

def parse_fancy_borders(raw:bytes)->tuple[FancyBorderDef,...]:
    if len(raw)==4:
        return ()
    pos=4;top=[]
    while pos<len(raw):
        b=base._parse_block(raw,pos);top.append(b);pos=b["end"]
    declared_count=next(b["value"] for b in top if b["id"]==0x01)
    arr=next(b for b in top if b["id"]==0x02 and b["type"]==0xA0)
    defs=[]
    for entry in base._children(raw,arr):
        fs=base._children(raw,entry)
        byid={b["id"]:b for b in fs}
        p=payload(raw,byid[0x03]); name=(p[:-2] if p.endswith(b"\x00\x00") else p).decode("utf-16le")
        order_keys=tuple(x["value"] for x in base._children(raw,byid[0x08]) if x["id"]==0x00)
        wmfs=[]
        for imc in base._children(raw,byid[0x0A]):
            inner=base._children(raw,imc)
            img=next(x for x in inner if x["id"]==0x01)
            wmfs.append(payload(raw,img))
        defs.append(FancyBorderDef(
          optional_02=byid[0x02]["value"] if 0x02 in byid else None,
          name=name,
          scalar_04=byid[0x04]["value"],
          scalar_05=byid[0x05]["value"],
          scalar_06=byid[0x06]["value"],
          scalar_07=byid[0x07]["value"],
          order_keys=order_keys,
          scalar_09=byid[0x09]["value"],
          wmfs=tuple(wmfs),
        ))
    if len(defs)!=declared_count: raise ValueError("definition count mismatch")
    return tuple(defs)

def validate(apk):
    total=empty=pop=ok=0;fails=[]
    with zipfile.ZipFile(apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            c=read_contents(z.read(name));rr=directory_refs(c);r=next(x for x in rr if x["seq"]==261 and x["type"]==0x46 and x["parent"]==256)
            n=int.from_bytes(c[r["off"]:r["off"]+4],"little");raw=c[r["off"]:r["off"]+n]
            defs=parse_fancy_borders(raw);got=build_fancy_borders(defs)
            total+=1;empty+=not defs;pop+=bool(defs)
            if got==raw:ok+=1
            else:
                lim=min(len(got),len(raw));at=next((i for i in range(lim) if got[i]!=raw[i]),lim)
                fails.append((name,len(raw),len(got),at,raw[at:at+16].hex(),got[at:at+16].hex()))
    print("validated",total)
    print("empty",empty,"populated",pop)
    print("byte_identical",ok,"/",total)
    if fails:
        print("first_failure",fails[0]);raise SystemExit(1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);a=ap.parse_args();validate(a.base_apk)
if __name__=="__main__":main()
