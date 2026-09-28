#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, io, json, sys, zipfile
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

def directory_refs(mod,c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little")
    pos=trailer+4
    parts=[]
    for _ in range(3):
        p=mod._parse_block(c,pos)
        parts.append(p)
        pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90)
    refs=[]
    seq=-1
    for entry in mod._children(c,d):
        seq+=1
        if entry["type"]!=0x88:
            continue
        vals={}
        for ch in mod._children(c,entry):
            if ch["id"] in (0x02,0x04,0x05):
                vals[ch["id"]]=ch["value"]
        if vals.get(0x04) is not None:
            refs.append({"seq":seq,"type":vals.get(0x02),"off":vals.get(0x04),"parent":vals.get(0x05)})
    return sorted(refs,key=lambda r:r["off"]),trailer

def schema(mod,raw):
    pos=4
    parts=[]
    count=0
    while pos<len(raw):
        b=mod._parse_block(raw,pos)
        parts.append("%02X:%02X:%d"%(b["id"],b["type"],b["data_length"]))
        count+=1
        pos=b["end"]
    return "|".join(parts),count

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("base_apk",type=Path)
    ap.add_argument("--out",type=Path,default=Path("work/second-chunk"))
    a=ap.parse_args()
    mod=load_base()
    rows=[]
    errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            try:
                c=contents(z.read(name))
                refs,trailer=directory_refs(mod,c)
                if len(refs)<2:
                    raise ValueError("fewer than 2 refs")
                r=refs[1]
                nxt=refs[2]["off"] if len(refs)>2 else trailer
                n=int.from_bytes(c[r["off"]:r["off"]+4],"little")
                raw=c[r["off"]:r["off"]+n]
                if n!=nxt-r["off"]:
                    raise ValueError("declared length mismatch")
                sch,count=schema(mod,raw)
                rows.append({"template":name,"seq":r["seq"],"type":r["type"],"parent":r["parent"],"offset":r["off"],"length":n,
                             "sha256":hashlib.sha256(raw).hexdigest(),"schema":sch,"field_count":count})
            except Exception as exc:
                errors.append({"template":name,"error":repr(exc)})
    report={
      "analyzed":len(rows),
      "errors":errors,
      "type_hist":Counter(r["type"] for r in rows).most_common(),
      "seq_hist":Counter(r["seq"] for r in rows).most_common(),
      "parent_hist":Counter(r["parent"] for r in rows).most_common(),
      "length_hist":Counter(r["length"] for r in rows).most_common(),
      "hash_count":len({r["sha256"] for r in rows}),
      "schema_count":len({r["schema"] for r in rows}),
      "profiles":[{"type":k[0],"length":k[1],"schema":k[2],"count":v} for k,v in Counter((r["type"],r["length"],r["schema"]) for r in rows).most_common()]
    }
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    with (a.out/"rows.csv").open("w",newline="",encoding="utf-8") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    lines=[
      "# Second directory-addressed Contents chunk",
      "",
      "- analyzed: **%d**" % len(rows),
      "- types: **%s**" % report["type_hist"],
      "- seq: **%s**" % report["seq_hist"],
      "- parents: **%s**" % report["parent_hist"],
      "- lengths: **%s**" % report["length_hist"],
      "- raw hashes: **%d**" % report["hash_count"],
      "- schemas: **%d**" % report["schema_count"],
      "",
      "## Profiles",
      ""
    ]
    for p in report["profiles"][:20]:
        lines.append("- type 0x%02X, len %d, count **%d**, schema %s" % (p["type"],p["length"],p["count"],p["schema"]))
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))

if __name__=="__main__":
    main()
