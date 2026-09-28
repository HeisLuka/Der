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
    mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod);return mod

def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:return ole.openstream(["Contents"]).read()

def refs(mod,c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little");pos=trailer+4;parts=[]
    for _ in range(3):
        p=mod._parse_block(c,pos);parts.append(p);pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90)
    out=[];seq=-1
    for e in mod._children(c,d):
        seq+=1
        if e["type"]!=0x88:continue
        vals={}
        for ch in mod._children(c,e):
            if ch["id"] in (2,4,5):vals[ch["id"]]=ch["value"]
        if vals.get(4) is not None:out.append({"seq":seq,"type":vals.get(2),"off":vals.get(4),"parent":vals.get(5)})
    return sorted(out,key=lambda r:r["off"]),trailer

def fields(mod,raw):
    pos=4;out=[]
    while pos<len(raw):
        b=mod._parse_block(raw,pos);p=raw[b["payload_offset"]:b["end"]]
        item={"id":b["id"],"type":b["type"],"length":b["data_length"],"value":b["value"],"sha256":hashlib.sha256(p).hexdigest()}
        if b["type"]==0xC0:
            try:item["text"]=(p[:-2] if p.endswith(b"\x00\x00") else p).decode("utf-16le")
            except Exception:pass
        if b["type"] in (0x88,0x90,0xA0):
            try:
                ch=mod._children(raw,b);item["child_count"]=len(ch);item["child_schema"]="|".join("%02X:%02X:%d"%(x["id"],x["type"],x["data_length"]) for x in ch)
                item["child_values"]=[x["value"] for x in ch]
            except Exception as exc:item["child_error"]=repr(exc)
        out.append(item);pos=b["end"]
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);ap.add_argument("--out",type=Path,default=Path("work/page266"));a=ap.parse_args()
    mod=load_base();rows=[];errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            try:
                c=contents(z.read(name));rr,trailer=refs(mod,c);r=next(x for x in rr if x["seq"]==266 and x["type"]==0x43 and x["parent"]==256)
                idx=rr.index(r);nxt=rr[idx+1]["off"] if idx+1<len(rr) else trailer;n=int.from_bytes(c[r["off"]:r["off"]+4],"little")
                if n!=nxt-r["off"]:raise ValueError("length mismatch")
                raw=c[r["off"]:r["off"]+n];rows.append({"template":name,"length":n,"hash":hashlib.sha256(raw).hexdigest(),"fields":fields(mod,raw)})
            except Exception as exc:errors.append({"template":name,"error":repr(exc)})
    ids=sorted({f["id"] for r in rows for f in r["fields"]});stats=[]
    for fid in ids:
        vals=[next((f for f in r["fields"] if f["id"]==fid),None) for r in rows];present=[f for f in vals if f]
        nums=[f["value"] for f in present if f["value"] is not None];texts=[f.get("text") for f in present if f.get("text") is not None]
        stats.append({"id":fid,"present":len(present),"types":Counter(f["type"] for f in present).most_common(),"lengths":Counter(f["length"] for f in present).most_common(),
                      "unique_values":len(set(nums)) if nums else None,"top_values":Counter(nums).most_common(30) if nums else [],
                      "unique_texts":sorted(set(texts)),"payload_hashes":len({f["sha256"] for f in present}),
                      "child_schemas":Counter(f.get("child_schema","") for f in present if f.get("child_schema") is not None).most_common(20)})
    schemas=Counter("|".join("%02X:%02X:%d"%(f["id"],f["type"],f["length"]) for f in r["fields"]) for r in rows)
    report={"templates":len(rows),"errors":errors,"lengths":Counter(r["length"] for r in rows).most_common(),"hash_count":len({r["hash"] for r in rows}),"schema_count":len(schemas),"schemas":schemas.most_common(),"fields":stats}
    a.out.mkdir(parents=True,exist_ok=True);(a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# PAGE seq266 matrix","", "- templates: **%d**"%len(rows),"- lengths: **%s**"%report["lengths"],"- hashes: **%d**"%report["hash_count"],"- schemas: **%d**"%report["schema_count"],"","## Fields",""]
    for s in stats:
        lines.append("- 0x%02X: present=%d/%d types=%s lengths=%s unique_values=%s payload_hashes=%d texts=%s"%(s["id"],s["present"],len(rows),s["types"],s["lengths"],s["unique_values"],s["payload_hashes"],s["unique_texts"]))
        if s["top_values"]:lines.append("  - values: %s"%s["top_values"])
        if s["child_schemas"]:lines.append("  - child schemas: %s"%s["child_schemas"][:5])
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8");print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))
if __name__=="__main__":main()
