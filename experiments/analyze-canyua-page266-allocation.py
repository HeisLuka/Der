#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, io, json, sys, zipfile
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
    return out
def page_fields(mod,c,r):
    n=int.from_bytes(c[r["off"]:r["off"]+4],"little");raw=c[r["off"]:r["off"]+n];fs={};pos=4
    while pos<len(raw):
        b=mod._parse_block(raw,pos);fs[b["id"]]=b;pos=b["end"]
    objects=[x["value"] for x in mod._children(raw,fs[0x02])]
    return {"objects":objects,"web":fs[0x09]["value"],"form":fs[0x0B]["value"],"controlling":fs[0x08]["value"],"master":fs[0x0D]["value"]}
def main():
    ap=argparse.ArgumentParser();ap.add_argument("base_apk",type=Path);ap.add_argument("--out",type=Path,default=Path("work/page266-allocation"));a=ap.parse_args()
    mod=load_base();rows=[];errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
      pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
      for name in pubs:
        try:
          c=contents(z.read(name));directory=refs(mod,c);byseq={r["seq"]:r for r in directory};physical=sorted(directory,key=lambda r:r["off"]);rank={r["seq"]:i for i,r in enumerate(physical)}
          p=byseq[266];pf=page_fields(mod,c,p);i=rank[266];nxt=physical[i+1]
          wr=byseq[pf["web"]];fr=byseq[pf["form"]]
          object_ranks=[rank[x] for x in pf["objects"] if x in rank]
          controlling_rank=rank.get(pf["controlling"])
          service_ranks=sorted([rank[pf["web"]],rank[pf["form"]]])
          rows.append({
            "template":name,
            "object_count":len(pf["objects"]),
            "web":pf["web"],"form":pf["form"],"controlling":pf["controlling"],
            "web_type":wr["type"],"form_type":fr["type"],"web_parent":wr["parent"],"form_parent":fr["parent"],
            "web_form_delta":pf["form"]-pf["web"],"web_form_abs_delta":abs(pf["form"]-pf["web"]),
            "web_in_objects":pf["web"] in pf["objects"],"form_in_objects":pf["form"] in pf["objects"],"controlling_in_objects":pf["controlling"] in pf["objects"],
            "next_seq":nxt["seq"],"next_type":nxt["type"],"next_parent":nxt["parent"],
            "web_physical_rank_delta":rank[pf["web"]]-i,"form_physical_rank_delta":rank[pf["form"]]-i,
            "service_pair_phys_adjacent":abs(rank[pf["web"]]-rank[pf["form"]])==1,
            "service_pair_first_rank_delta":service_ranks[0]-i,
            "service_pair_after_all_rgohpo":bool(object_ranks) and service_ranks[0]>max(object_ranks),
            "service_pair_after_controlling":controlling_rank is not None and service_ranks[0]>controlling_rank,
            "service_pair_last_to_rgohpo_first_rank_gap":min(object_ranks)-service_ranks[-1] if object_ranks else None,
            "service_pair_first_seq":min(pf["web"],pf["form"]),
            "service_pair_last_seq":max(pf["web"],pf["form"]),
            "rgohpo_min_seq":min(pf["objects"]) if pf["objects"] else None,
            "rgohpo_max_seq":max(pf["objects"]) if pf["objects"] else None,
            "service_last_to_rgohpo_min_seq_gap":min(pf["objects"])-max(pf["web"],pf["form"]) if pf["objects"] else None,
            "rgohpo_min_rank_delta":min(object_ranks)-i if object_ranks else None,
            "rgohpo_max_rank_delta":max(object_ranks)-i if object_ranks else None,
            "rgohpo_phys_span":max(object_ranks)-min(object_ranks)+1 if object_ranks else 0,
            "rgohpo_phys_contiguous":bool(object_ranks) and (max(object_ranks)-min(object_ranks)+1==len(set(object_ranks))),
            "controlling_rank_delta":controlling_rank-i if controlling_rank is not None else None,
            "seq267_type":byseq.get(267,{}).get("type"),"seq267_parent":byseq.get(267,{}).get("parent"),"seq267_phys_delta":rank.get(267,None)-i if 267 in rank else None,
            "seq268_type":byseq.get(268,{}).get("type"),"seq268_parent":byseq.get(268,{}).get("parent"),"seq268_phys_delta":rank.get(268,None)-i if 268 in rank else None,
          })
        except Exception as exc:errors.append({"template":name,"error":repr(exc)})
    keys=["object_count","web_form_delta","web_form_abs_delta","web_type","form_type","web_parent","form_parent","web_in_objects","form_in_objects","controlling_in_objects","next_seq","next_type","next_parent","web_physical_rank_delta","form_physical_rank_delta","service_pair_phys_adjacent","service_pair_first_rank_delta","service_pair_after_all_rgohpo","service_pair_after_controlling","service_pair_last_to_rgohpo_first_rank_gap","service_pair_first_seq","service_pair_last_seq","rgohpo_min_seq","rgohpo_max_seq","service_last_to_rgohpo_min_seq_gap","rgohpo_min_rank_delta","rgohpo_max_rank_delta","rgohpo_phys_span","rgohpo_phys_contiguous","controlling_rank_delta","seq267_type","seq267_parent","seq267_phys_delta","seq268_type","seq268_parent","seq268_phys_delta"]
    hist={k:Counter(r[k] for r in rows).most_common() for k in keys}
    branches=Counter((r["next_seq"],r["next_type"],r["next_parent"],r["web_physical_rank_delta"],r["form_physical_rank_delta"],r["web_form_delta"]) for r in rows)
    error_hist=Counter(e["error"] for e in errors).most_common()
    report={"templates":len(rows),"source_templates":len(rows)+len(errors),"errors":errors,"error_hist":error_hist,"hist":hist,"branches":[{"next_seq":k[0],"next_type":k[1],"next_parent":k[2],"web_rank_delta":k[3],"form_rank_delta":k[4],"form_minus_web":k[5],"count":v} for k,v in branches.most_common()],"rows":rows}
    a.out.mkdir(parents=True,exist_ok=True);(a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# PAGE266 allocation/order profile","", "- analyzed: **%d / %d**"%(len(rows),len(rows)+len(errors)),"- errors: **%s**"%error_hist,"","## Histograms",""]
    for k in keys:lines.append("- %s: **%s**"%(k,hist[k][:20]))
    lines+=["","## Branches",""]
    for b in report["branches"][:30]:lines.append("- %s"%b)
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8");print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))
if __name__=="__main__":main()
