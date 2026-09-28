#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, io, json, sys, zipfile, hashlib
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

def get_contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:
        return ole.openstream(["Contents"]).read()

def directory_refs(mod,c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little"); pos=trailer+4; parts=[]
    for _ in range(3):
        p=mod._parse_block(c,pos); parts.append(p); pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90)
    refs=[]; seq=-1
    for entry in mod._children(c,d):
        seq+=1
        if entry["type"]!=0x88: continue
        vals={}
        for ch in mod._children(c,entry):
            if ch["id"] in (0x02,0x04,0x05): vals[ch["id"]]=ch["value"]
        if vals.get(0x04) is not None:
            refs.append({"seq":seq,"type":vals.get(0x02),"off":vals.get(0x04),"parent":vals.get(0x05)})
    return sorted(refs,key=lambda r:r["off"])

def summarize_record(mod, raw, b):
    fields=mod._children(raw,b)
    out=[]
    for x in fields:
        payload=raw[x["payload_offset"]:x["end"]]
        item={"id":x["id"],"type":x["type"],"length":x["data_length"],"value":x["value"],"sha256":hashlib.sha256(payload).hexdigest()}
        if x["type"]==0xC0:
            try:
                item["text"]=payload[:-2].decode("utf-16le") if payload.endswith(b"\x00\x00") else payload.decode("utf-16le")
            except Exception:
                pass
        if x["type"] in (0x80,0x82,0x88,0x8A,0x90,0x98,0xA0):
            try:
                ch=mod._children(raw,x)
                item["child_count"]=len(ch)
                item["child_schema"]="|".join("%02X:%02X:%d"%(y["id"],y["type"],y["data_length"]) for y in ch)
                item["children"]=[]
                for y in ch:
                    yp=raw[y["payload_offset"]:y["end"]]
                    yi={"id":y["id"],"type":y["type"],"length":y["data_length"],"value":y["value"],"sha256":hashlib.sha256(yp).hexdigest()}
                    if y["type"]==0xC0:
                        try:
                            yi["text"]=yp[:-2].decode("utf-16le") if yp.endswith(b"\\x00\\x00") else yp.decode("utf-16le")
                        except Exception:
                            pass
                    item["children"].append(yi)
            except Exception as exc:
                item["child_error"]=repr(exc)
        out.append(item)
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("base_apk",type=Path); ap.add_argument("--out",type=Path,default=Path("work/fancy-records")); a=ap.parse_args()
    mod=load_base(); docs=[]; errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            try:
                c=get_contents(z.read(name)); refs=directory_refs(mod,c)
                r=next(x for x in refs if x["seq"]==261 and x["type"]==0x46)
                n=int.from_bytes(c[r["off"]:r["off"]+4],"little")
                if n==4: continue
                raw=c[r["off"]:r["off"]+n]
                top=[];pos=4
                while pos<len(raw):
                    b=mod._parse_block(raw,pos);top.append(b);pos=b["end"]
                f02=next(x for x in top if x["id"]==0x02 and x["type"]==0xA0)
                outer=mod._children(raw,f02)[0]
                nested=mod._children(raw,outer)
                namef=next(x for x in nested if x["id"]==0x03 and x["type"]==0xC0)
                p=raw[namef["payload_offset"]:namef["end"]]
                profile=p[:-2].decode("utf-16le") if p.endswith(b"\x00\x00") else p.decode("utf-16le")
                arr=next(x for x in nested if x["id"]==0x0A and x["type"]==0xA0)
                recs=mod._children(raw,arr)
                docs.append({"template":name,"profile":profile,"record_count":len(recs),"records":[
                    {"index":i,"length":rec["data_length"],"schema":"|".join("%02X:%02X:%d"%(f["id"],f["type"],f["data_length"]) for f in mod._children(raw,rec)),
                     "fields":summarize_record(mod,raw,rec)}
                    for i,rec in enumerate(recs)
                ]})
            except Exception as exc:
                errors.append({"template":name,"error":repr(exc)})
    position=[]
    for i in range(8):
        rows=[d["records"][i] for d in docs]
        position.append({
          "index":i,
          "lengths":Counter(r["length"] for r in rows).most_common(),
          "schema_count":len({r["schema"] for r in rows}),
          "schemas":Counter(r["schema"] for r in rows).most_common(),
          "profile_lengths":{p:Counter(d["records"][i]["length"] for d in docs if d["profile"]==p).most_common() for p in sorted({d["profile"] for d in docs})},
        })
    field_stats={}
    for d in docs:
        for r in d["records"]:
            for f in r["fields"]:
                key="0x%02X"%f["id"]; field_stats.setdefault(key,[]).append(f)
    inner_stats={}
    for d in docs:
        for r in d["records"]:
            for f in r["fields"]:
                for ch in f.get("children",[]):
                    key="0x%02X"%ch["id"]
                    inner_stats.setdefault(key,[]).append(ch)
    inner=[]
    for key,vals in sorted(inner_stats.items()):
        nums=[v["value"] for v in vals if v["value"] is not None]
        texts=[v.get("text") for v in vals if v.get("text") is not None]
        inner.append({"field":key,"count":len(vals),"types":Counter(v["type"] for v in vals).most_common(),"lengths":Counter(v["length"] for v in vals).most_common(),"unique_values":len(set(nums)) if nums else None,"top_values":Counter(nums).most_common(30) if nums else [],"unique_texts":sorted(set(texts)),"payload_hashes":len({v["sha256"] for v in vals})})
    fs=[]
    for key,vals in sorted(field_stats.items()):
        nums=[v["value"] for v in vals if v["value"] is not None]
        texts=[v.get("text") for v in vals if v.get("text") is not None]
        fs.append({"field":key,"count":len(vals),"types":Counter(v["type"] for v in vals).most_common(),"lengths":Counter(v["length"] for v in vals).most_common(),"unique_values":len(set(nums)) if nums else None,"top_values":Counter(nums).most_common(20) if nums else [],"unique_texts":sorted(set(texts)),"payload_hashes":len({v["sha256"] for v in vals})})
    report={"documents":len(docs),"errors":errors,"profiles":Counter(d["profile"] for d in docs).most_common(),"positions":position,"field_stats":fs,"inner_field_stats":inner,"docs":docs}
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# FancyBorders record-level profile","", "- documents: **%d**"%len(docs), "- profiles: **%s**"%report["profiles"], "", "## Positions",""]
    for p in position: lines.append("- #%d lengths=%s schema_count=%d profile_lengths=%s"%(p["index"],p["lengths"],p["schema_count"],p["profile_lengths"]))
    lines+=["","## Inner record fields",""]
    for s in inner:
        lines.append("- %s count=%d types=%s lengths=%s unique_values=%s payload_hashes=%d texts=%s"%(s["field"],s["count"],s["types"],s["lengths"],s["unique_values"],s["payload_hashes"],s["unique_texts"]))
        if s["top_values"]: lines.append("  - values: %s"%s["top_values"])
    lines+=["","## Field stats",""]
    for s in fs:
        lines.append("- %s count=%d types=%s lengths=%s unique_values=%s payload_hashes=%d texts=%s"%(s["field"],s["count"],s["types"],s["lengths"],s["unique_values"],s["payload_hashes"],s["unique_texts"]))
        if s["top_values"]: lines.append("  - values: %s"%s["top_values"])
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))
if __name__=="__main__": main()
