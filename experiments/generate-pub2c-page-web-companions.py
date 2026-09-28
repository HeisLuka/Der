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
def text(fid,s):return var(fid,0xC0,s.encode("utf-16le")+b"\x00\x00")

@dataclass(frozen=True)
class WebPageInfo:
    leave_off_nav_bar:bool=True

@dataclass(frozen=True)
class FormProperties:
    retrieval_method:int=2
    email_address:str="someone@example.com"
    email_subject:str="Web Site Form Response"
    confirm_text:str="Your information was received"
    data_file_name:str="FORMDATA.HTM"
    page_number:int=1
    action_url:str="http://example.com/~user/ispscript.cgi"

def chunk(body:bytes)->bytes:return struct.pack("<I",len(body)+4)+body

def build_web_page_info(m:WebPageInfo)->bytes:
    if not m.leave_off_nav_bar:return struct.pack("<I",4)
    return chunk(u32(0x05,0x20,1))

def build_form_properties(m:FormProperties)->bytes:
    return chunk(b"".join([
      u32(0x0C,0x20,m.retrieval_method),
      text(0x0E,m.email_address),
      text(0x0F,m.email_subject),
      text(0x10,m.confirm_text),
      text(0x13,m.data_file_name),
      u32(0x17,0x20,m.page_number),
      text(0x18,m.action_url),
    ]))

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

def validate(apk):
    total=0;webok=formok=0;fails=[]
    with zipfile.ZipFile(apk) as z:
      pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
      for name in pubs:
        c=contents(z.read(name));rr=refs(c)
        wr=next(x for x in rr if x["seq"]==264 and x["type"]==0x60 and x["parent"]==263)
        fr=next(x for x in rr if x["seq"]==265 and x["type"]==0x77 and x["parent"]==263)
        wn=int.from_bytes(c[wr["off"]:wr["off"]+4],"little");fn=int.from_bytes(c[fr["off"]:fr["off"]+4],"little")
        wraw=c[wr["off"]:wr["off"]+wn];fraw=c[fr["off"]:fr["off"]+fn]
        wg=build_web_page_info(WebPageInfo());fg=build_form_properties(FormProperties())
        total+=1;webok+=wg==wraw;formok+=fg==fraw
        if wg!=wraw or fg!=fraw:fails.append((name,wn,fn,wraw.hex(),wg.hex(),fraw[:32].hex(),fg[:32].hex()))
    print("validated",total)
    print("web_page_info_byte_identical",webok,"/",total)
    print("form_properties_byte_identical",formok,"/",total)
    if fails:print("first_failure",fails[0]);raise SystemExit(1)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);a=ap.parse_args();validate(a.base_apk)
if __name__=="__main__":main()
