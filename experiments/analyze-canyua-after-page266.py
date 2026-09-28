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
    d=next(p for p in parts if p["type"]==0x90);out=[];seq=-1
    for e in mod._children(c,d):
        seq+=1
        if e["type"]!=0x88:continue
        vals={}
        for ch in mod._children(c,e):
            if ch["id"] in (2,4,5):vals[ch["id"]]=ch["value"]
        if vals.get(4) is not None:out.append({"seq":seq,"type":vals.get(2),"off":vals.get(4),"parent":vals.get(5)})
    return sorted(out,key=lambda r:r["off"]),trailer
def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);ap.add_argument("--out",type=Path,default=Path("work/after-page266"));a=ap.parse_args()
    mod=load_base();rows=[];errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
      pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
      for name in pubs:
        try:
          c=contents(z.read(name));rr,trailer=refs(mod,c);i=next(i for i,r in enumerate(rr) if r["seq"]==266 and r["type"]==0x43 and r["parent"]==256)
          r=rr[i+1];nxt=rr[i+2]["off"] if i+2<len(rr) else trailer;n=int.from_bytes(c[r["off"]:r["off"]+4],"little")
          if n!=nxt-r["off"]:raise ValueError("length mismatch")
          raw=c[r["off"]:r["off"]+n]
          rows.append({"template":name,"seq":r["seq"],"type":r["type"],"parent":r["parent"],"length":n,"hash":hashlib.sha256(raw).hexdigest()})
        except Exception as exc:errors.append({"template":name,"error":repr(exc)})
    prof=Counter((r["seq"],r["type"],r["parent"],r["length"],r["hash"]) for r in rows)
    report={"templates":len(rows),"errors":errors,
      "seq_hist":Counter(r["seq"] for r in rows).most_common(),
      "type_hist":Counter(r["type"] for r in rows).most_common(),
      "parent_hist":Counter(r["parent"] for r in rows).most_common(),
      "length_hist":Counter(r["length"] for r in rows).most_common(),
      "hash_count":len({r["hash"] for r in rows}),
      "profiles":[{"seq":k[0],"type":k[1],"parent":k[2],"length":k[3],"hash":k[4],"count":v} for k,v in prof.most_common()]}
    a.out.mkdir(parents=True,exist_ok=True);(a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# Physical chunk immediately after PAGE266","", "- templates: **%d**"%len(rows),"- seq: **%s**"%report["seq_hist"],"- types: **%s**"%report["type_hist"],"- parents: **%s**"%report["parent_hist"],"- lengths: **%s**"%report["length_hist"],"- hashes: **%d**"%report["hash_count"],"","## Profiles",""]
    for p in report["profiles"][:30]:lines.append("- seq=%s type=0x%02X parent=%s len=%d count=%d sha=%s..."%(p["seq"],p["type"],p["parent"],p["length"],p["count"],p["hash"][:16]))
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8");print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))
if __name__=="__main__":main()
