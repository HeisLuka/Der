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
N=12

def load_base():
    spec=importlib.util.spec_from_file_location("canyua_template_corpus",BASE)
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod

def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole: return ole.openstream(["Contents"]).read()

def refs(mod,c):
    trailer=int.from_bytes(c[0x1A:0x1E],"little"); pos=trailer+4; parts=[]
    for _ in range(3):
        p=mod._parse_block(c,pos); parts.append(p); pos=p["end"]
    d=next(p for p in parts if p["type"]==0x90)
    out=[]; seq=-1
    for entry in mod._children(c,d):
        seq+=1
        if entry["type"]!=0x88: continue
        vals={}
        for ch in mod._children(c,entry):
            if ch["id"] in (0x02,0x04,0x05): vals[ch["id"]]=ch["value"]
        if vals.get(0x04) is not None:
            out.append({"seq":seq,"type":vals.get(0x02),"off":vals.get(0x04),"parent":vals.get(0x05)})
    return sorted(out,key=lambda r:r["off"]),trailer

def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);ap.add_argument("--out",type=Path,default=Path("work/early-chunk-sequence"));a=ap.parse_args()
    mod=load_base(); positions=[[] for _ in range(N)]; errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
      pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
      for name in pubs:
        try:
          c=contents(z.read(name)); rr,trailer=refs(mod,c)
          for i,r in enumerate(rr[:N]):
            nxt=rr[i+1]["off"] if i+1<len(rr) else trailer
            n=int.from_bytes(c[r["off"]:r["off"]+4],"little")
            raw=c[r["off"]:r["off"]+n]
            if n!=nxt-r["off"]: raise ValueError("length mismatch at index %d"%i)
            positions[i].append({"template":name,"seq":r["seq"],"type":r["type"],"parent":r["parent"],"length":n,"hash":hashlib.sha256(raw).hexdigest()})
        except Exception as exc:
          errors.append({"template":name,"error":repr(exc)})
    summary=[]
    for i,rows in enumerate(positions):
      summary.append({
        "index":i,
        "count":len(rows),
        "seq_hist":Counter(r["seq"] for r in rows).most_common(),
        "type_hist":Counter(r["type"] for r in rows).most_common(),
        "parent_hist":Counter(r["parent"] for r in rows).most_common(),
        "length_hist":Counter(r["length"] for r in rows).most_common(),
        "hash_count":len({r["hash"] for r in rows}),
      })
    report={"templates":len(positions[0]),"errors":errors,"positions":summary}
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# Early physical Contents chunk sequence",""]
    for s in summary:
      lines.append("- #%d: seq=%s type=%s parent=%s lengths=%s hashes=%d" % (
        s["index"],s["seq_hist"],s["type_hist"],s["parent_hist"],s["length_hist"],s["hash_count"]))
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))
if __name__=="__main__": main()
