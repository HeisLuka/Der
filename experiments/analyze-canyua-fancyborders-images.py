#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, importlib.util, io, json, sys, zipfile
from collections import Counter
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

def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole: return ole.openstream(["Contents"]).read()

def refs(mod,c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little"); pos=trailer+4; parts=[]
    for _ in range(3):
        p=mod._parse_block(c,pos);parts.append(p);pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90)
    out=[];seq=-1
    for e in mod._children(c,d):
        seq+=1
        if e["type"]!=0x88: continue
        vals={}
        for ch in mod._children(c,e):
            if ch["id"] in (0x02,0x04,0x05): vals[ch["id"]]=ch["value"]
        if vals.get(0x04) is not None:
            out.append({"seq":seq,"type":vals.get(0x02),"off":vals.get(0x04),"parent":vals.get(0x05)})
    return sorted(out,key=lambda r:r["off"])

def raw_payload(data,b):
    return data[b["payload_offset"]:b["end"]]

def parse_ba(mod,raw):
    pos=4; top=[]
    while pos<len(raw):
        b=mod._parse_block(raw,pos);top.append(b);pos=b["end"]
    count=next((b["value"] for b in top if b["id"]==0x01),None)
    arr=next(b for b in top if b["id"]==0x02)
    definitions=mod._children(raw,arr)
    out=[]
    for definition in definitions:
        fields=mod._children(raw,definition)
        namef=next((b for b in fields if b["id"]==0x03 and b["type"]==0xC0),None)
        name=None
        if namef:
            p=raw_payload(raw,namef)
            try: name=(p[:-2] if p.endswith(b"\x00\x00") else p).decode("utf-16le")
            except Exception: name=None
        offsets=[]
        offc=next((b for b in fields if b["id"]==0x08),None)
        if offc:
            for x in mod._children(raw,offc):
                if x["id"]==0x00:
                    offsets.append(x["value"])
        images=[]
        ia=next((b for b in fields if b["id"]==0x0A),None)
        if ia:
            for idx,container in enumerate(mod._children(raw,ia)):
                inner=mod._children(raw,container)
                img=next((b for b in inner if b["id"]==0x01),None)
                if img is None:
                    images.append({"index":idx,"missing":True})
                    continue
                payload=raw_payload(raw,img)
                images.append({
                  "index":idx,
                  "block_type":img["type"],
                  "declared_data_length":img["data_length"],
                  "payload_len":len(payload),
                  "sha256":hashlib.sha256(payload).hexdigest(),
                  "head32":payload[:32].hex(),
                  "placeable_wmf_key":payload[:4].hex()=="d7cdc69a",
                })
        scalars={b["id"]:b["value"] for b in fields if b["value"] is not None}
        out.append({"name":name,"scalars":scalars,"offsets":offsets,"images":images})
    return {"count":count,"definitions":out}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);ap.add_argument("--out",type=Path,default=Path("work/fancy-images"));a=ap.parse_args()
    mod=load_base();docs=[];errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            try:
                c=contents(z.read(name)); rr=refs(mod,c); r=next(x for x in rr if x["seq"]==261 and x["type"]==0x46)
                n=int.from_bytes(c[r["off"]:r["off"]+4],"little")
                if n==4: continue
                raw=c[r["off"]:r["off"]+n]
                docs.append({"template":name,"chunk_len":n,**parse_ba(mod,raw)})
            except Exception as exc: errors.append({"template":name,"error":repr(exc)})
    profiles={}
    for d in docs:
        for definition in d["definitions"]:
            p=definition["name"] or "<none>"
            pr=profiles.setdefault(p,{"docs":0,"offset_sets":Counter(),"image_positions":[Counter() for _ in range(8)],"payload_lens":[Counter() for _ in range(8)],"heads":[Counter() for _ in range(8)]})
            pr["docs"]+=1
            pr["offset_sets"][tuple(definition["offsets"])]+=1
            for im in definition["images"]:
                i=im["index"]
                pr["image_positions"][i][im.get("sha256")]+=1
                pr["payload_lens"][i][im.get("payload_len")]+=1
                pr["heads"][i][im.get("head32")]+=1
    outprofiles={}
    for name,p in profiles.items():
        outprofiles[name]={
          "docs":p["docs"],
          "offset_sets":p["offset_sets"].most_common(),
          "unique_image_hashes_by_position":[len(x) for x in p["image_positions"]],
          "image_hashes_by_position":[x.most_common() for x in p["image_positions"]],
          "payload_lens_by_position":[x.most_common() for x in p["payload_lens"]],
          "heads_by_position":[x.most_common(3) for x in p["heads"]],
        }
    report={"documents":len(docs),"errors":errors,"profiles":outprofiles,"docs":docs}
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# FancyBorders WMF image profile","", "- documents: **%d**"%len(docs),""]
    for name,p in outprofiles.items():
        lines.append("## %s"%name)
        lines.append("- docs: **%d**"%p["docs"])
        lines.append("- offsets: **%s**"%p["offset_sets"])
        for i in range(8):
            lines.append("- image #%d: lens=%s unique_hashes=%d hashes=%s head=%s"%(i,p["payload_lens_by_position"][i],p["unique_image_hashes_by_position"][i],[(h[:16]+"...",n) for h,n in p["image_hashes_by_position"][i]],p["heads_by_position"][i]))
        lines.append("")
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))
if __name__=="__main__": main()
