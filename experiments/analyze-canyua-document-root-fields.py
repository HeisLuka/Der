#!/usr/bin/env python3
from __future__ import annotations
import argparse, collections, hashlib, importlib.util, io, json, sys, zipfile
from pathlib import Path
try:
    import olefile
except ImportError as exc:
    raise SystemExit("Missing dependency: python -m pip install olefile") from exc

TEMPLATE_PREFIX="assets/Publisher Templates/2013/BUILT-IN/"
BASE=Path(__file__).with_name("analyze-canyua-template-corpus.py")

def load_base():
    spec=importlib.util.spec_from_file_location("canyua_template_corpus", BASE)
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod

def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole: return ole.openstream(["Contents"]).read()

def first_document(mod,c):
    s=mod.analyze_contents_0x2c(c,b""); off=s["first_chunk_offset"]
    n=int.from_bytes(c[off:off+4],"little"); raw=c[off:off+n]
    pos=4; fields=[]
    while pos<len(raw):
        b=mod._parse_block(raw,pos)
        item={"id":b["id"],"type":b["type"],"length":b["data_length"],"value":b["value"]}
        payload=raw[b["payload_offset"]:b["end"]]
        item["payload_sha256"]=hashlib.sha256(payload).hexdigest()
        if b["type"] in (0x88,0x90,0xA0):
            try:
                ch=mod._children(raw,b)
                item["child_schema"]="|".join("%02X:%02X:%d"%(x["id"],x["type"],x["data_length"]) for x in ch)
                item["child_count"]=len(ch)
                if b["id"]==0x02 and b["type"]==0xA0:
                    item["page_handles"]=[x["value"] for x in ch if x["type"]==0x70]
            except Exception as exc:
                item["child_error"]=repr(exc)
        fields.append(item); pos=b["end"]
    return off,n,fields

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("base_apk",type=Path); ap.add_argument("--out",type=Path,default=Path("work/document-root-fields")); a=ap.parse_args()
    mod=load_base(); rows=[]; errors=[]
    with zipfile.ZipFile(a.base_apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            try:
                c=contents(z.read(name)); off,n,fields=first_document(mod,c)
                rows.append({"template":name,"offset":off,"length":n,"fields":fields})
            except Exception as exc: errors.append({"template":name,"error":repr(exc)})
    all_ids=sorted({f["id"] for r in rows for f in r["fields"]})
    stats=[]
    for fid in all_ids:
        fs=[next((f for f in r["fields"] if f["id"]==fid),None) for r in rows]
        present=[f for f in fs if f is not None]
        vals=[f["value"] for f in present if f["value"] is not None]
        lengths=collections.Counter(f["length"] for f in present)
        types=collections.Counter(f["type"] for f in present)
        hashes=collections.Counter(f["payload_sha256"] for f in present)
        child_schemas=collections.Counter(f.get("child_schema","") for f in present if "child_schema" in f)
        page_counts=collections.Counter(len(f.get("page_handles",[])) for f in present if "page_handles" in f)
        stats.append({
          "id":fid,"present":len(present),"types":dict(types),"lengths":dict(lengths),
          "unique_values":len(set(vals)) if vals else None,
          "top_values":collections.Counter(vals).most_common(20) if vals else [],
          "payload_hashes":len(hashes),"top_payload_hashes":hashes.most_common(5),
          "child_schema_count":len(child_schemas),"top_child_schemas":child_schemas.most_common(10),
          "page_count_histogram":dict(page_counts),
        })
    cpd_page_rows=[]
    for r in rows:
        byid={f["id"]:f for f in r["fields"]}
        cpd=byid.get(0x01,{}).get("value")
        page_count=len(byid.get(0x02,{}).get("page_handles",[]))
        cpd_page_rows.append((cpd,page_count))
    cpd_page_match=sum(1 for cpd,pc in cpd_page_rows if cpd==pc)
    report={"templates":len(rows),"errors":errors,"document_lengths":dict(collections.Counter(r["length"] for r in rows)),"fields":stats,
            "cpd_page_count_match":cpd_page_match,
            "cpd_page_count_total":len(cpd_page_rows),
            "cpd_page_pairs":dict(collections.Counter("%s->%s"%(a,b) for a,b in cpd_page_rows))}
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/"report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
    lines=["# Root DOCUMENT field matrix","",f"- analyzed: **{len(rows)}**",f"- CPd == PageList count: **{report['cpd_page_count_match']} / {report['cpd_page_count_total']}**",f"- CPd/PageList pairs: **{report['cpd_page_pairs']}**","", "## Fields",""]
    for s in stats:
        lines.append(f"- field 0x{s['id']:02X}: present **{s['present']}/{len(rows)}**, types={s['types']}, lengths={s['lengths']}, unique_values={s['unique_values']}, payload_hashes={s['payload_hashes']}, page_counts={s['page_count_histogram']}")
        if s["top_values"]: lines.append(f"  - top values: {s['top_values']}")
        if s["top_child_schemas"]: lines.append(f"  - child schemas: {s['top_child_schemas'][:3]}")
    (a.out/"SUMMARY.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print((a.out/"SUMMARY.md").read_text(encoding="utf-8"))
    return 0
if __name__=="__main__": raise SystemExit(main())
