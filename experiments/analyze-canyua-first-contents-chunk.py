#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, hashlib, importlib.util, io, json, sys, zipfile
from collections import Counter
from pathlib import Path
try:
    import olefile
except ImportError as exc:
    raise SystemExit("Missing dependency: python -m pip install olefile") from exc

TEMPLATE_PREFIX = "assets/Publisher Templates/2013/BUILT-IN/"
BASE_ANALYZER = Path(__file__).with_name("analyze-canyua-template-corpus.py")

def load_base():
    spec = importlib.util.spec_from_file_location("canyua_template_corpus", BASE_ANALYZER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load base analyzer")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod

def h(data):
    return hashlib.sha256(data).hexdigest()

def read_contents(blob):
    if not olefile.isOleFile(io.BytesIO(blob)):
        raise ValueError("not OLE/CFB")
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:
        return ole.openstream(["Contents"]).read()

def field_schema(mod, chunk):
    pos = 4
    parts = []
    count = 0
    while pos < len(chunk):
        b = mod._parse_block(chunk, pos)
        if b["end"] <= pos:
            raise ValueError("non-advancing field")
        parts.append("%02X:%02X:%d" % (b["id"], b["type"], b["data_length"]))
        count += 1
        pos = b["end"]
    if pos != len(chunk):
        raise ValueError("field parse did not end at chunk boundary")
    return "|".join(parts), count

def parse_first(mod, contents):
    s = mod.analyze_contents_0x2c(contents, b"")
    first = s["first_chunk_offset"]
    if first is None:
        raise ValueError("no first chunk")

    trailer_offset = int.from_bytes(contents[0x1A:0x1E], "little")
    pos = trailer_offset + 4
    trailer_parts = []
    for _ in range(3):
        part = mod._parse_block(contents, pos)
        trailer_parts.append(part)
        pos = part["end"]
    directory = next((p for p in trailer_parts if p["type"] == 0x90), None)
    if directory is None:
        raise ValueError("no directory")

    refs = []
    seq_num = -1
    for entry in mod._children(contents, directory):
        seq_num += 1
        if entry["type"] != 0x88:
            continue
        vals = {}
        for child in mod._children(contents, entry):
            if child["id"] in (0x02, 0x04, 0x05):
                vals[child["id"]] = child["value"]
        if vals.get(0x04) is not None:
            refs.append({
                "seq_num": seq_num,
                "chunk_type": vals.get(0x02),
                "chunk_offset": vals.get(0x04),
                "parent_seq_num": vals.get(0x05),
            })

    refs.sort(key=lambda r: r["chunk_offset"])
    first_ref = refs[0]
    next_offset = refs[1]["chunk_offset"] if len(refs) > 1 else trailer_offset
    declared = int.from_bytes(contents[first:first+4], "little")
    if declared != next_offset - first:
        raise ValueError("declared length does not match physical span")
    raw = contents[first:first+declared]
    schema, field_count = field_schema(mod, raw)
    return {
        "first_offset": first,
        "first_type": first_ref["chunk_type"],
        "first_seq_num": first_ref["seq_num"],
        "first_parent_seq_num": first_ref["parent_seq_num"],
        "declared_length": declared,
        "next_offset": next_offset,
        "sha256": h(raw),
        "body_sha256": h(raw[4:]),
        "field_count": field_count,
        "field_schema": schema,
        "head32_hex": raw[:32].hex(),
    }

def category(path):
    rel = path[len(TEMPLATE_PREFIX):]
    parts = rel.split("/")
    return (parts[0] if len(parts) > 1 else "", parts[1] if len(parts) > 2 else "")

def analyze(apk_path):
    mod = load_base()
    rows, errors = [], []
    with zipfile.ZipFile(apk_path) as apk:
        pubs = sorted(n for n in apk.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            try:
                c = read_contents(apk.read(name))
                row = parse_first(mod, c)
                cat, sub = category(name)
                row.update({"template": name, "category": cat, "subcategory": sub, "contents_len": len(c)})
                rows.append(row)
            except Exception as exc:
                errors.append({"template": name, "error": repr(exc)})

    def hist(key):
        return [{"value": v, "count": n} for v, n in Counter(r[key] for r in rows).most_common()]

    combos = Counter((r["first_type"], r["declared_length"], r["sha256"], r["field_schema"]) for r in rows)
    report = {
        "template_count": len(rows) + len(errors),
        "analyzed_count": len(rows),
        "errors": errors,
        "first_type_histogram": hist("first_type"),
        "first_seq_num_histogram": hist("first_seq_num"),
        "first_parent_histogram": hist("first_parent_seq_num"),
        "declared_length_histogram": hist("declared_length"),
        "raw_hash_count": len({r["sha256"] for r in rows}),
        "body_hash_count": len({r["body_sha256"] for r in rows}),
        "field_schema_count": len({r["field_schema"] for r in rows}),
        "field_count_histogram": hist("field_count"),
        "offset_count": len({r["first_offset"] for r in rows}),
        "offset_histogram": hist("first_offset"),
        "profile_clusters": [
            {"first_type": k[0], "declared_length": k[1], "sha256": k[2], "field_schema": k[3], "count": v}
            for k, v in combos.most_common()
        ],
    }
    return report, rows

def write_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

def write_summary(path, report):
    lines = [
        "# First directory-addressed Contents chunk profile",
        "",
        "- analyzed: **%d / %d**" % (report["analyzed_count"], report["template_count"]),
        "- first raw chunk types: **%d**" % len(report["first_type_histogram"]),
        "- first chunk lengths: **%d**" % len(report["declared_length_histogram"]),
        "- first chunk raw hashes: **%d**" % report["raw_hash_count"],
        "- first chunk body hashes: **%d**" % report["body_hash_count"],
        "- first chunk top-level schemas: **%d**" % report["field_schema_count"],
        "- absolute first offsets: **%d**" % report["offset_count"],
        "",
        "## First type histogram",
        "",
    ]
    for x in report["first_type_histogram"]:
        v = x["value"]
        label = "None" if v is None else "0x%02X" % v
        lines.append("- %s: **%d**" % (label, x["count"]))
    lines += ["", "## Length histogram", ""]
    for x in report["declared_length_histogram"][:30]:
        lines.append("- %d bytes: **%d**" % (x["value"], x["count"]))
    lines += ["", "## Dominant exact profiles", ""]
    for x in report["profile_clusters"][:20]:
        t = x["first_type"]
        label = "None" if t is None else "0x%02X" % t
        lines.append("- type %s, len %d, count **%d**, sha %s..., schema %s" % (
            label, x["declared_length"], x["count"], x["sha256"][:16], x["field_schema"]))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_apk", type=Path)
    ap.add_argument("--out", type=Path, default=Path("work/canyua-first-chunk"))
    args = ap.parse_args()
    report, rows = analyze(args.base_apk)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if rows:
        write_csv(args.out / "rows.csv", rows)
    write_summary(args.out / "SUMMARY.md", report)
    print((args.out / "SUMMARY.md").read_text(encoding="utf-8"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
