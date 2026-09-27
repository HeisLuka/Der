#!/usr/bin/env python3
"""Cross-reference 32-bit field-0x03 values from the fixed Contents pre-chunk table.

This does not assign semantics. It asks one narrow physical question:
do the table's distinctive 0x03/type-0x20 values recur outside that table in
Contents document data, Quill or Escher streams?

Dependency:
    python -m pip install olefile
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import struct
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import olefile  # type: ignore

HERE = Path(__file__).resolve().parent
ANALYZER_PATH = HERE / "analyze-canyua-prechunk-table.py"
TEMPLATE_PREFIX = "assets/Publisher Templates/2013/BUILT-IN/"

def load_analyzer():
    spec = importlib.util.spec_from_file_location("prechunk", ANALYZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load pre-chunk analyzer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

A = load_analyzer()


def count_bytes(haystack: bytes, needle: bytes) -> int:
    count = 0
    pos = 0
    while True:
        pos = haystack.find(needle, pos)
        if pos < 0:
            return count
        count += 1
        pos += 1


def read_streams(pub_blob: bytes) -> dict[str, bytes]:
    if not olefile.isOleFile(io.BytesIO(pub_blob)):
        raise ValueError("not OLE/CFB")
    result = {}
    with olefile.OleFileIO(io.BytesIO(pub_blob)) as ole:
        for parts in ole.listdir(streams=True, storages=False):
            path = "/" + "/".join(parts)
            result[path] = ole.openstream(parts).read()
    return result


def table_field03(contents: bytes):
    table, entries = A.find_prechunk_table(contents)
    values = defaultdict(list)
    for index, entry in enumerate(entries, 1):
        for field in A.children(contents, entry):
            if field["id"] == 0x03 and field["type"] == 0x20 and field["data_length"] == 4:
                value = A.u32(contents, field["data_offset"])
                values[value].append(index)
    return table, dict(values)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("base_apk", type=Path)
    p.add_argument("--out", type=Path, default=Path("work/canyua-pretable-xrefs.json"))
    args = p.parse_args()

    aggregate = {}
    sample_count = 0
    errors = []

    with zipfile.ZipFile(args.base_apk) as apk:
        pubs = sorted(
            n for n in apk.namelist()
            if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub")
        )

        for pub_path in pubs:
            try:
                streams = read_streams(apk.read(pub_path))
                contents = streams["/Contents"]
                table, values = table_field03(contents)
            except Exception as exc:
                errors.append({"template": pub_path, "error": repr(exc)})
                continue

            sample_count += 1
            outside_contents = contents[:table["start"]] + contents[table["end"]:]
            targets = {
                "contents_outside_table": outside_contents,
                "quill": streams.get("/Quill/QuillSub/CONTENTS", b""),
                "escher": streams.get("/Escher/EscherStm", b""),
                "escher_delay": streams.get("/Escher/EscherDelayStm", b""),
            }

            for value, indices in values.items():
                key = str(value)
                if key not in aggregate:
                    aggregate[key] = {
                        "value": value,
                        "hex": f"0x{value:08X}",
                        "upper16": value >> 16,
                        "lower16": value & 0xFFFF,
                        "entry_indices": sorted(indices),
                        "templates_with_value": 0,
                        "streams": {
                            name: {"template_hits": 0, "total_occurrences": 0}
                            for name in targets
                        },
                    }

                row = aggregate[key]
                row["templates_with_value"] += 1
                needle = struct.pack("<I", value)
                for name, data in targets.items():
                    n = count_bytes(data, needle)
                    if n:
                        row["streams"][name]["template_hits"] += 1
                        row["streams"][name]["total_occurrences"] += n

    rows = sorted(aggregate.values(), key=lambda x: x["value"])
    any_xrefs = []
    for row in rows:
        hits = {
            name: info
            for name, info in row["streams"].items()
            if info["template_hits"] > 0
        }
        if hits:
            any_xrefs.append({
                "value": row["value"],
                "hex": row["hex"],
                "upper16": row["upper16"],
                "lower16": row["lower16"],
                "entry_indices": row["entry_indices"],
                "hits": hits,
            })

    report = {
        "schema": "der/canyua-prechunk-field03-xrefs/v1",
        "template_count": len(pubs),
        "parsed_template_count": sample_count,
        "errors": errors,
        "distinct_field03_values": len(rows),
        "value_rows": rows,
        "values_with_external_occurrences": any_xrefs,
        "values_with_external_occurrence_count": len(any_xrefs),
        "boundary": (
            "Raw 4-byte equality is only a cross-reference candidate. "
            "Even repeated external occurrences do not establish semantic identity."
        ),
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({
        "template_count": report["template_count"],
        "parsed_template_count": report["parsed_template_count"],
        "distinct_field03_values": report["distinct_field03_values"],
        "values_with_external_occurrence_count": report["values_with_external_occurrence_count"],
        "values_with_external_occurrences": any_xrefs,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
