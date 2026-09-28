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
    mod=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    return mod

def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:
        return ole.openstream(["Contents"]).read()

def refs(mod,c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little")
    pos=trailer+4
    parts=[]
    for _ in range(3):
        p=mod._parse_block(c,pos);parts.append(p);pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90)
    out=[];seq=-1
    for entry in mod._children(c,d):
        seq+=1
        if entry["type"]!=0x88:
            continue
        vals={}
        for ch in mod._children(c,entry):
            if ch["id"] in (0x02,0x04,0x05):
                vals[ch["id"]]=ch["value"]
        if vals.get(0x04) is not None:
            out.append({"seq":seq,"type":vals.get(0x02),"off":vals.get(0x04),"parent":vals.get(0x05)})
    return sorted(out,key=lambda r:r["off"]),trailer

def summarize_block(mod,raw):
    pos=4
    fields=[]
    while pos<len(raw):
        b=mod._parse_block(raw,pos)
        item={"id":b["id"],"type":b["type"],"length":b["data_length"],"value":b["value"]}
        payload=raw[b["payload_offset"]:b["end"]]
        item["payload_sha256"]=hashlib.sha256(payload).hexdigest()
        if b["type"] in (0x80,0x82,0x88,0x8A,0x90,0x98,0xA0,0xC0):
            try:
                ch=mod._children(raw,b)
                item["child_count"]=len(ch)
                item["child_schema"]="|".join("%02X:%02X:%d"%(x["id"],x["type"],x["data_length"]) for x in ch)
                item["children"]=[]
                for x in ch:
                    xi={"id":x["id"],"type":x["type"],"length":x["data_length"],"value":x["value"]}
                    xp=raw[x["payload_offset"]:x["end"]]
                    xi["payload_sha256"]=hashlib.sha256(xp).hexdigest()
                    if x["type"] in (0x80,0x82,0x88,0x8A,0x90,0x98,0xA0,0xC0):
                        try:
                            xch=mod._children(raw,x)
                            xi["child_count"]=len(xch)
                            xi["child_schema"]="|".join("%02X:%02X:%d"%(y["id"],y["type"],y["data_length"]) for y in xch)
                            xi["grandchildren"]=[{"id":y["id"],"type":y["type"],"length":y["data_length"],"value":y["value"],"payload_sha256":hashlib.sha256(raw[y["payload_offset"]:y["end"]]).hexdigest()} for y in xch]
                        except Exception as xexc:
                            xi["child_error"]=repr(xexc)
                    item["children"].append(xi)
            except Exception as exc:
                item["child_error"]=repr(exc)
        fields.append(item)
        pos=b["end"]
    return fields

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("base_apk",type=Path)
    ap.add_argument("--out",type=Path,default=Path("work/fancy-borders"))
    a=ap.parse_args()
    mod=load_base()
    rows=[];errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            try:
                c=contents(z.read(name));rr,trailer=refs(mod,c)
                target=next(r for r in rr if r["seq"]==261 and r["type"]==0x46 and r["parent"]==256)
                idx=rr.index(target)
                nxt=rr[idx+1]["off"] if idx+1<len(rr) else trailer
                n=int.from_bytes(c[target["off"]:target["off"]+4],"little")
                raw=c[target["off"]:target["off"]+n]
                if n!=nxt-target["off"]:
                    raise ValueError("length mismatch")
                fields=summarize_block(mod,raw)
                rows.append({"template":name,"length":n,"sha256":hashlib.sha256(raw).hexdigest(),"fields":fields})
            except Exception as exc:
                errors.append({"template":name,"error":repr(exc)})

    nonempty=[r for r in rows if r["length"]>4]
    schemas=Counter("|".join("%02X:%02X:%d"%(f["id"],f["type"],f["length"]) for f in r["fields"]) for r in nonempty)
    field_stats=[]
    ids=sorted({f["id"] for r in nonempty for f in r["fields"]})
    for fid in ids:
        ff=[next((f for f in r["fields"] if f["id"]==fid),None) for r in nonempty]
        present=[f for f in ff if f]
        vals=[f["value"] for f in present if f["value"] is not None]
        field_stats.append({
          "id":fid,
          "present":len(present),
          "types":Counter(f["type"] for f in present).most_common(),
          "lengths":Counter(f["length"] for f in present).most_common(),
          "unique_values":len(set(vals)) if vals else None,
          "top_values":Counter(vals).most_common(20) if vals else [],
          "payload_hashes":len({f["payload_sha256"] for f in present}),
          "child_schemas":Counter(f.get("child_schema","") for f in present if "child_schema" in f).most_common(20),
        })
    nested=[]
    for r in nonempty:
        f02=next((f for f in r["fields"] if f["id"]==0x02),None)
        child=(f02.get("children") or [None])[0] if f02 else None
        nested.append({"template":r["template"],"outer_length":r["length"],"child":child})
    nested_schema=Counter((n["child"] or {}).get("child_schema","") for n in nested)
    nested_len=Counter((n["child"] or {}).get("length") for n in nested)
    nested_field_stats=[]
    gids=sorted({g["id"] for n in nested if n["child"] for g in n["child"].get("grandchildren",[])})
    for gid in gids:
        gs=[]
        for n in nested:
            if not n["child"]: continue
            gs.extend([g for g in n["child"].get("grandchildren",[]) if g["id"]==gid])
        vals=[g["value"] for g in gs if g["value"] is not None]
        nested_field_stats.append({"id":gid,"count":len(gs),"types":Counter(g["type"] for g in gs).most_common(),"lengths":Counter(g["length"] for g in gs).most_common(),"unique_values":len(set(vals)) if vals else None,"top_values":Counter(vals).most_common(20) if vals else [],"payload_hashes":len({g["payload_sha256"] for g in gs})})
    report={
      "templates":len(rows),"errors":errors,
      "empty_count":sum(1 for r in rows if r["length"]==4),
      "nonempty_count":len(nonempty),
      "length_hist":Counter(r["length"] for r in rows).most_common(),
      "hash_count":len({r["sha256"] for r in rows}),
      "nonempty_schema_count":len(schemas),
      "nonempty_schemas":schemas.most_common(),
      "nonempty_templates":[{"template":r["template"],"length":r["length"],"sha256":r["sha256"]} for r in nonempty],
      "field_stats":field_stats,
      "nested_lengths":nested_len.most_common(),
      "nested_schema_count":len(nested_schema),
      "nested_schemas":nested_schema.most_common(),
      "nested_field_stats":nested_field_stats,
    }
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=[
      "# FancyBorders raw 0x46 profile",
      "",
      "- templates: **%d**" % len(rows),
      "- empty: **%d**" % report["empty_count"],
      "- nonempty: **%d**" % report["nonempty_count"],
      "- lengths: **%s**" % report["length_hist"],
      "- hashes: **%d**" % report["hash_count"],
      "- nonempty schemas: **%d**" % report["nonempty_schema_count"],
      "",
      "## Nonempty templates",
      ""
    ]
    for r in report["nonempty_templates"]:
        lines.append("- %s — %d bytes — %s..."%(r["template"],r["length"],r["sha256"][:16]))
    lines += ["","## Nested 00/88 object","", "- nested lengths: **%s**" % report["nested_lengths"], "- nested schemas: **%d**" % report["nested_schema_count"], ""]
    for s in report["nested_field_stats"]:
        lines.append("- nested field 0x%02X: count=%d types=%s lengths=%s unique_values=%s payload_hashes=%d"%(s["id"],s["count"],s["types"],s["lengths"],s["unique_values"],s["payload_hashes"]))
        if s["top_values"]: lines.append("  - top values: %s"%s["top_values"])
    lines += ["","## Fields",""]
    for s in field_stats:
        lines.append("- field 0x%02X: present %d/%d types=%s lengths=%s unique_values=%s payload_hashes=%d child_schemas=%s"%(
          s["id"],s["present"],len(nonempty),s["types"],s["lengths"],s["unique_values"],s["payload_hashes"],s["child_schemas"][:3]))
        if s["top_values"]:
            lines.append("  - top values: %s"%s["top_values"])
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))

if __name__=="__main__":
    main()
