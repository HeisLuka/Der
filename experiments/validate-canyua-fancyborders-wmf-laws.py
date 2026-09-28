#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, io, struct, sys, zipfile
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
def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:return ole.openstream(["Contents"]).read()
def refs(mod,c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little");pos=trailer+4;parts=[]
    for _ in range(3):
        p=mod._parse_block(c,pos);parts.append(p);pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90);out=[];seq=-1
    for e in mod._children(c,d):
        seq+=1
        if e["type"]!=0x88:continue
        vals={}
        for ch in mod._children(c,e):
            if ch["id"] in (2,4,5):vals[ch["id"]]=ch["value"]
        if vals.get(4) is not None:out.append({"seq":seq,"type":vals.get(2),"off":vals.get(4),"parent":vals.get(5)})
    return sorted(out,key=lambda r:r["off"])
def payload(raw,b):return raw[b["payload_offset"]:b["end"]]
def parse(mod,raw):
    pos=4;top=[]
    while pos<len(raw):
        b=mod._parse_block(raw,pos);top.append(b);pos=b["end"]
    arr=next(x for x in top if x["id"]==2)
    defs=[]
    for definition in mod._children(raw,arr):
        fs=mod._children(raw,definition)
        offc=next(x for x in fs if x["id"]==8); offs=[x["value"] for x in mod._children(raw,offc)]
        ia=next(x for x in fs if x["id"]==10); imgs=[]
        for cont in mod._children(raw,ia):
            img=next(x for x in mod._children(raw,cont) if x["id"]==1)
            p=payload(raw,img)
            mt_type,mt_hsz,mt_ver=struct.unpack_from("<HHH",p,0)
            mt_size=struct.unpack_from("<I",p,6)[0]
            mt_objects=struct.unpack_from("<H",p,10)[0]
            mt_maxrec=struct.unpack_from("<I",p,12)[0]
            mt_params=struct.unpack_from("<H",p,16)[0]
            imgs.append({"len":len(p),"mt_type":mt_type,"mt_header_size":mt_hsz,"mt_version":mt_ver,"mt_size_words":mt_size,"mt_size_bytes":mt_size*2,"mt_objects":mt_objects,"mt_max_record":mt_maxrec,"mt_params":mt_params})
        defs.append((offs,imgs))
    return defs
def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);a=ap.parse_args();mod=load_base()
    total=0; sizeok=0; deltaok=0; headers=set(); firstbases=set()
    with zipfile.ZipFile(a.base_apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            c=contents(z.read(name));rr=refs(mod,c);r=next(x for x in rr if x["seq"]==261 and x["type"]==0x46);n=int.from_bytes(c[r["off"]:r["off"]+4],"little")
            if n==4:continue
            raw=c[r["off"]:r["off"]+n]
            for offs,imgs in parse(mod,raw):
                total+=1; firstbases.add(offs[0])
                if all(im["len"]==im["mt_size_bytes"] for im in imgs):sizeok+=1
                if all(offs[i+1]-offs[i]==imgs[i]["len"] for i in range(len(imgs)-1)):deltaok+=1
                headers.update((im["mt_type"],im["mt_header_size"],im["mt_version"],im["mt_params"]) for im in imgs)
    print("definitions",total)
    print("wmf_metaheader_size_matches_payload",sizeok,"/",total)
    print("offset_delta_matches_payload_len",deltaok,"/",total)
    print("first_offset_values",sorted(firstbases))
    print("wmf_header_profiles",sorted(headers))
if __name__=="__main__":main()
