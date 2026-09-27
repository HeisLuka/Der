#!/usr/bin/env python3
"""Per-entry variability analysis for Canyua's 143-entry Contents pre-chunk table.

The parser intentionally uses only the public physical framing rules already
implemented by libmspub for Publisher 2002+ (0x2C) Contents streams. It does
not assign a semantic name to the table or to unknown field IDs.

Dependency:
    python -m pip install olefile
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import List, Tuple

import olefile  # type: ignore

SCHEMA = "der/canyua-contents-prechunk-entry-variability/v1"
TEMPLATE_PREFIX = "assets/Publisher Templates/2013/BUILT-IN/"
SEED_PATH = (
    "assets/Publisher Data/Publication Types/Blank Page Sizes/Standard/"
    "New Page Size/Contents.dat"
)

_FIXED_BLOCK_LENGTH = {
    0x78: 0, 0x05: 0, 0x08: 0, 0x0A: 0,
    0x10: 2, 0x12: 2, 0x18: 2, 0x1A: 2, 0x07: 2,
    0x20: 4, 0x22: 4, 0x58: 4, 0x68: 4, 0x70: 4, 0xB8: 4,
    0x28: 8, 0x38: 16, 0x48: 24,
}
_VARIABLE_BLOCK_TYPES = {0xC0, 0x80, 0x82, 0x88, 0x8A, 0x90, 0x98, 0xA0}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def parse_block(data: bytes, offset: int) -> dict:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError(f"block header outside stream at 0x{offset:X}")

    block_id = data[offset]
    block_type = data[offset + 1]
    data_offset = offset + 2

    if block_type in _VARIABLE_BLOCK_TYPES:
        if data_offset + 4 > len(data):
            raise ValueError(f"variable length outside stream at 0x{offset:X}")
        data_length = u32(data, data_offset)
        payload_offset = data_offset + 4
    else:
        data_length = _FIXED_BLOCK_LENGTH.get(block_type, 0)
        payload_offset = data_offset

    end = data_offset + data_length
    if end < data_offset or end > len(data):
        raise ValueError(
            f"block 0x{offset:X} type=0x{block_type:02X} ends outside stream: 0x{end:X}"
        )

    value = None
    if block_type not in _VARIABLE_BLOCK_TYPES:
        if data_length == 2:
            value = u16(data, data_offset)
        elif data_length == 4:
            value = u32(data, data_offset)

    return {
        "start": offset,
        "id": block_id,
        "type": block_type,
        "data_offset": data_offset,
        "payload_offset": payload_offset,
        "data_length": data_length,
        "end": end,
        "value": value,
    }


def children(data: bytes, container: dict) -> List[dict]:
    rows = []
    pos = container["payload_offset"]
    while pos < container["end"]:
        child = parse_block(data, pos)
        if child["end"] <= pos:
            raise ValueError(f"non-advancing child at 0x{pos:X}")
        rows.append(child)
        pos = child["end"]
    if pos != container["end"]:
        raise ValueError(
            f"children miss boundary: 0x{pos:X} != 0x{container['end']:X}"
        )
    return rows


def extract_contents_from_pub(blob: bytes) -> bytes:
    if not olefile.isOleFile(io.BytesIO(blob)):
        raise ValueError("not OLE/CFB")
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:
        return ole.openstream(["Contents"]).read()


def find_prechunk_table(contents: bytes) -> Tuple[dict, List[dict]]:
    if len(contents) < 0x30 or contents[2] != 0x2C:
        raise ValueError("not Publisher 2002+ 0x2C Contents")

    trailer_offset = u32(contents, 0x1A)
    if trailer_offset + 4 > len(contents):
        raise ValueError("trailer outside stream")

    trailer_parts = []
    pos = trailer_offset + 4
    for _ in range(3):
        part = parse_block(contents, pos)
        trailer_parts.append(part)
        pos = part["end"]

    directory = next((p for p in trailer_parts if p["type"] == 0x90), None)
    if directory is None:
        raise ValueError("no trailer directory type=0x90")

    offsets = []
    for entry in children(contents, directory):
        if entry["type"] != 0x88:
            continue
        vals = {}
        for field in children(contents, entry):
            if field["id"] in (0x02, 0x04, 0x05):
                vals[field["id"]] = field["value"]
        if vals.get(0x04) is not None:
            offsets.append(vals[0x04])

    if not offsets:
        raise ValueError("no chunk offsets")
    first_chunk = min(offsets)

    pos = 0x30
    prelude = []
    while pos < first_chunk:
        block = parse_block(contents, pos)
        prelude.append(block)
        pos = block["end"]
    if pos != first_chunk:
        raise ValueError("prelude does not meet first chunk")

    table = prelude[-1]
    if table["id"] != 0x03 or table["type"] != 0x90:
        raise ValueError(
            f"unexpected final pre-chunk block id=0x{table['id']:02X} "
            f"type=0x{table['type']:02X}"
        )
    if table["end"] != first_chunk:
        raise ValueError("pre-chunk table does not end at first chunk")

    entries = children(contents, table)
    if len(entries) != 143 or any(entry["type"] != 0x88 for entry in entries):
        raise ValueError("pre-chunk table is not the expected 143 x type=0x88 shape")
    return table, entries


def entry_record(contents: bytes, entry: dict, index: int) -> dict:
    raw = contents[entry["start"]:entry["end"]]
    fields = []
    for ordinal, field in enumerate(children(contents, entry)):
        fraw = contents[field["start"]:field["end"]]
        fields.append({
            "ordinal": ordinal,
            "id": field["id"],
            "type": field["type"],
            "data_length": field["data_length"],
            "value": field["value"],
            "raw_sha256": sha256(fraw),
        })
    seq = [
        f["value"] for f in fields
        if f["id"] == 0x01 and f["type"] == 0x18
    ]
    return {
        "index": index,
        "len": len(raw),
        "sha256": sha256(raw),
        "field_schema": [
            [f["ordinal"], f["id"], f["type"], f["data_length"]]
            for f in fields
        ],
        "fields": fields,
        "seq_value": seq[0] if len(seq) == 1 else None,
    }


def category_of(path: str) -> Tuple[str, str]:
    rel = path[len(TEMPLATE_PREFIX):]
    parts = rel.split("/")
    return (
        parts[0] if len(parts) > 1 else "",
        parts[1] if len(parts) > 2 else "",
    )


def compact_ranges(indices: List[int]) -> List[str]:
    if not indices:
        return []
    values = sorted(set(indices))
    out = []
    start = prev = values[0]
    for value in values[1:]:
        if value == prev + 1:
            prev = value
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        start = prev = value
    out.append(str(start) if start == prev else f"{start}-{prev}")
    return out


def analyze(apk_path: Path):
    with zipfile.ZipFile(apk_path) as apk:
        seed = apk.read(SEED_PATH)
        seed_table, seed_entries = find_prechunk_table(seed)
        seed_records = {
            i: entry_record(seed, entry, i)
            for i, entry in enumerate(seed_entries, 1)
        }

        pubs = sorted(
            n for n in apk.namelist()
            if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub")
        )
        observations = defaultdict(list)
        errors = []

        for pub_path in pubs:
            try:
                contents = extract_contents_from_pub(apk.read(pub_path))
                table, entries = find_prechunk_table(contents)
            except Exception as exc:
                errors.append({"template": pub_path, "error": repr(exc)})
                continue

            category, subcategory = category_of(pub_path)
            for index, entry in enumerate(entries, 1):
                record = entry_record(contents, entry, index)
                observations[index].append({
                    "template": pub_path,
                    "category": category,
                    "subcategory": subcategory,
                    "table_start": table["start"],
                    "entry_start": entry["start"],
                    **record,
                })

    entry_rows = []
    field_rows = []

    for index in range(1, 144):
        items = observations[index]
        seed_record = seed_records[index]
        raw_hashes = Counter(item["sha256"] for item in items)
        lengths = [item["len"] for item in items]
        schemas = Counter(
            json.dumps(item["field_schema"], separators=(",", ":"))
            for item in items
        )

        seed_equal_count = sum(
            1 for item in items if item["sha256"] == seed_record["sha256"]
        )
        dominant_hash, dominant_count = raw_hashes.most_common(1)[0]

        field_keys = sorted({
            (field["ordinal"], field["id"], field["type"])
            for item in items
            for field in item["fields"]
        } | {
            (field["ordinal"], field["id"], field["type"])
            for field in seed_record["fields"]
        })

        varying_field_count = 0
        seed_different_field_count = 0
        varying_fields = []

        seed_fields = {
            (f["ordinal"], f["id"], f["type"]): f
            for f in seed_record["fields"]
        }

        for key in field_keys:
            raw_hash_vals = []
            value_vals = []
            present = 0
            for item in items:
                fields = {
                    (f["ordinal"], f["id"], f["type"]): f
                    for f in item["fields"]
                }
                field = fields.get(key)
                if field is None:
                    raw_hash_vals.append("__MISSING__")
                    value_vals.append("__MISSING__")
                else:
                    present += 1
                    raw_hash_vals.append(field["raw_sha256"])
                    value_vals.append(
                        "null" if field["value"] is None else str(field["value"])
                    )

            unique_raw = Counter(raw_hash_vals)
            seed_field = seed_fields.get(key)
            seed_raw_sha = seed_field["raw_sha256"] if seed_field else None
            seed_value = seed_field["value"] if seed_field else None
            equal_seed = sum(1 for value in raw_hash_vals if value == seed_raw_sha)

            if len(unique_raw) > 1:
                varying_field_count += 1
                varying_fields.append(
                    f"ord={key[0]} id=0x{key[1]:02X} type=0x{key[2]:02X}"
                )
            if equal_seed != len(items):
                seed_different_field_count += 1

            value_counts = Counter(value_vals)
            field_rows.append({
                "entry_index": index,
                "ordinal": key[0],
                "id_hex": f"0x{key[1]:02X}",
                "type_hex": f"0x{key[2]:02X}",
                "templates_present": present,
                "unique_raw_variants": len(unique_raw),
                "seed_equal_count": equal_seed,
                "seed_value": seed_value,
                "value_variant_count": len(value_counts),
                "top_values": json.dumps(
                    value_counts.most_common(12),
                    separators=(",", ":"),
                ),
            })

        entry_rows.append({
            "index": index,
            "seed_len": seed_record["len"],
            "seed_sha256": seed_record["sha256"],
            "templates": len(items),
            "unique_raw_hashes": len(raw_hashes),
            "seed_equal_count": seed_equal_count,
            "dominant_hash_count": dominant_count,
            "dominant_hash_is_seed": dominant_hash == seed_record["sha256"],
            "min_len": min(lengths),
            "max_len": max(lengths),
            "schema_variant_count": len(schemas),
            "varying_field_count": varying_field_count,
            "seed_different_field_count": seed_different_field_count,
            "varying_fields": "; ".join(varying_fields),
        })

    exact_seed_all = [
        row["index"] for row in entry_rows
        if row["seed_equal_count"] == len(pubs)
    ]
    invariant_all = [
        row["index"] for row in entry_rows
        if row["unique_raw_hashes"] == 1
    ]
    variable = [
        row["index"] for row in entry_rows
        if row["unique_raw_hashes"] > 1
    ]
    invariant_but_not_seed = [
        row["index"] for row in entry_rows
        if row["unique_raw_hashes"] == 1
        and row["seed_equal_count"] != len(pubs)
    ]

    report = {
        "schema": SCHEMA,
        "apk": str(apk_path),
        "template_count": len(pubs),
        "parsed_template_count": len(pubs) - len(errors),
        "errors": errors,
        "seed": {
            "path": SEED_PATH,
            "table_start": seed_table["start"],
            "table_end": seed_table["end"],
            "entry_count": len(seed_entries),
        },
        "entry_summary": {
            "exact_seed_in_all_count": len(exact_seed_all),
            "exact_seed_in_all_ranges": compact_ranges(exact_seed_all),
            "invariant_across_corpus_count": len(invariant_all),
            "invariant_across_corpus_ranges": compact_ranges(invariant_all),
            "variable_across_corpus_count": len(variable),
            "variable_across_corpus_ranges": compact_ranges(variable),
            "invariant_but_not_seed_count": len(invariant_but_not_seed),
            "invariant_but_not_seed_ranges": compact_ranges(invariant_but_not_seed),
        },
        "entries": entry_rows,
        "interpretation_boundary": (
            "Per-entry equality and field variability are physical evidence. "
            "Unknown field IDs and the 143-entry table remain semantically unnamed."
        ),
    }
    return report, entry_rows, field_rows


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = list(rows[0].keys()) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, report: dict) -> None:
    s = report["entry_summary"]
    lines = [
        "# Canyua Contents pre-chunk table variability",
        "",
        f"- templates: **{report['template_count']}**",
        f"- parsed: **{report['parsed_template_count']}**",
        f"- entries: **{report['seed']['entry_count']}**",
        "",
        "## Entry-level result",
        "",
        f"- exact seed bytes in all templates: **{s['exact_seed_in_all_count']}** — {', '.join(s['exact_seed_in_all_ranges'])}",
        f"- invariant across corpus: **{s['invariant_across_corpus_count']}** — {', '.join(s['invariant_across_corpus_ranges'])}",
        f"- variable across corpus: **{s['variable_across_corpus_count']}** — {', '.join(s['variable_across_corpus_ranges'])}",
        f"- invariant but not seed-identical: **{s['invariant_but_not_seed_count']}** — {', '.join(s['invariant_but_not_seed_ranges']) or 'none'}",
        "",
        "## Variable entries",
        "",
        "| index | variants | seed-equal | schema variants | varying fields |",
        "|---:|---:|---:|---:|---|",
    ]
    for row in report["entries"]:
        if row["unique_raw_hashes"] <= 1:
            continue
        lines.append(
            f"| {row['index']} | {row['unique_raw_hashes']} | "
            f"{row['seed_equal_count']} | {row['schema_variant_count']} | "
            f"{row['varying_fields'] or '-'} |"
        )
    lines += [
        "",
        "## Interpretation boundary",
        "",
        report["interpretation_boundary"],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base_apk", type=Path)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("work/canyua-prechunk-variability"),
    )
    args = parser.parse_args()

    report, entries, fields = analyze(args.base_apk)
    args.out.mkdir(parents=True, exist_ok=True)

    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_csv(args.out / "entries.csv", entries)
    write_csv(args.out / "fields.csv", fields)
    write_summary(args.out / "SUMMARY.md", report)

    print(json.dumps({
        "template_count": report["template_count"],
        "parsed_template_count": report["parsed_template_count"],
        "entry_summary": report["entry_summary"],
        "variable_entries": [
            {
                "index": row["index"],
                "variants": row["unique_raw_hashes"],
                "seed_equal_count": row["seed_equal_count"],
                "schema_variants": row["schema_variant_count"],
                "varying_fields": row["varying_fields"],
            }
            for row in report["entries"]
            if row["unique_raw_hashes"] > 1
        ],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
