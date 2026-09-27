#!/usr/bin/env python3
"""Analyze the 252 Publisher templates bundled with Canyua.

This is corpus/provenance analysis only. It does not infer semantic field
meaning from byte coincidences.

Dependency:
    python -m pip install olefile
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import statistics
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    import olefile  # type: ignore
except ImportError as exc:
    raise SystemExit("Missing dependency: python -m pip install olefile") from exc

SCHEMA = "der/canyua-template-corpus/v1"
TEMPLATE_PREFIX = "assets/Publisher Templates/2013/BUILT-IN/"
SEEDS = {
    "contents": (
        "assets/Publisher Data/Publication Types/Blank Page Sizes/Standard/New Page Size/Contents.dat",
        "/Contents",
    ),
    "escher": (
        "assets/Publisher Data/Publication Types/Blank Page Sizes/Standard/New Page Size/EscherStm.dat",
        "/Escher/EscherStm",
    ),
    "quill": (
        "assets/Publisher Data/Publication Types/Blank Page Sizes/Standard/New Page Size/QUILL_CONTENTS.dat",
        "/Quill/QuillSub/CONTENTS",
    ),
    "summary": (
        "assets/Publisher Data/Publication Types/Blank Page Sizes/Standard/New Page Size/SummaryInformation.dat",
        "/\x05SummaryInformation",
    ),
}
KEY_PATHS = {
    "/Contents": "contents",
    "/Quill/QuillSub/CONTENTS": "quill",
    "/Escher/EscherStm": "escher",
    "/Escher/EscherDelayStm": "escher_delay",
    "/\x05SummaryInformation": "summary",
    "/\x05DocumentSummaryInformation": "document_summary",
}


def h(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def common_prefix(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def common_suffix(a: bytes, b: bytes) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[len(a) - 1 - i] == b[len(b) - 1 - i]:
        i += 1
    return i


def seed_block_matches(seed: bytes, actual: bytes, block_size: int = 64) -> dict:
    """Measure exact seed blocks that survive anywhere in the target stream.

    Blocks are sampled at non-overlapping seed offsets. This is relocation-aware:
    a block counts even when it moved to a different stream offset. The metric is
    physical evidence only and must not be promoted to semantic attribution.
    """
    total = len(seed) // block_size
    if total == 0:
        return {
            "block_size": block_size,
            "total_blocks": 0,
            "matched_blocks": 0,
            "matched_pct": 0.0,
            "longest_same_delta_run_bytes": 0,
        }

    matches = []
    for seed_offset in range(0, total * block_size, block_size):
        block = seed[seed_offset:seed_offset + block_size]
        actual_offset = actual.find(block)
        if actual_offset >= 0:
            matches.append((seed_offset, actual_offset, actual_offset - seed_offset))

    best_run_blocks = 0
    best_run_start = None
    run_blocks = 0
    run_start = None
    previous = None
    for item in matches:
        if (
            previous is not None
            and item[0] == previous[0] + block_size
            and item[2] == previous[2]
        ):
            run_blocks += 1
        else:
            run_blocks = 1
            run_start = item

        if run_blocks > best_run_blocks:
            best_run_blocks = run_blocks
            best_run_start = run_start
        previous = item

    best_seed_start = best_run_start[0] if best_run_start is not None else None
    best_actual_start = best_run_start[1] if best_run_start is not None else None
    best_delta = best_run_start[2] if best_run_start is not None else None

    return {
        "block_size": block_size,
        "total_blocks": total,
        "matched_blocks": len(matches),
        "matched_pct": round(100.0 * len(matches) / total, 2),
        "longest_same_delta_run_bytes": best_run_blocks * block_size,
        "longest_run_seed_start": best_seed_start,
        "longest_run_actual_start": best_actual_start,
        "longest_run_delta": best_delta,
    }



_FIXED_BLOCK_LENGTH = {
    0x78: 0, 0x05: 0, 0x08: 0, 0x0A: 0,
    0x10: 2, 0x12: 2, 0x18: 2, 0x1A: 2, 0x07: 2,
    0x20: 4, 0x22: 4, 0x58: 4, 0x68: 4, 0x70: 4, 0xB8: 4,
    0x28: 8, 0x38: 16, 0x48: 24,
}
_VARIABLE_BLOCK_TYPES = {0xC0, 0x80, 0x82, 0x88, 0x8A, 0x90, 0x98, 0xA0}


def _u16(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 2], "little")


def _u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset:offset + 4], "little")


def _parse_block(data: bytes, offset: int) -> dict:
    if offset < 0 or offset + 2 > len(data):
        raise ValueError(f"block header outside stream at 0x{offset:X}")

    block_id = data[offset]
    block_type = data[offset + 1]
    data_offset = offset + 2

    if block_type in _VARIABLE_BLOCK_TYPES:
        if data_offset + 4 > len(data):
            raise ValueError(f"variable block length outside stream at 0x{offset:X}")
        data_length = _u32(data, data_offset)
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
    if data_length == 2 and block_type not in _VARIABLE_BLOCK_TYPES:
        value = _u16(data, data_offset)
    elif data_length == 4 and block_type not in _VARIABLE_BLOCK_TYPES:
        value = _u32(data, data_offset)

    return {
        "start": offset,
        "id": block_id,
        "type": block_type,
        "data_offset": data_offset,
        "payload_offset": payload_offset,
        "data_length": data_length,
        "end": end,
        "value": value,
        "variable": block_type in _VARIABLE_BLOCK_TYPES,
    }


def _children(data: bytes, container: dict) -> List[dict]:
    rows = []
    pos = container["payload_offset"]
    while pos < container["end"]:
        child = _parse_block(data, pos)
        if child["end"] <= pos:
            raise ValueError(f"non-advancing child at 0x{pos:X}")
        rows.append(child)
        pos = child["end"]
    if pos != container["end"]:
        raise ValueError(
            f"children do not end at container boundary: 0x{pos:X} != 0x{container['end']:X}"
        )
    return rows


def analyze_contents_0x2c(contents: bytes, seed_scaffold: bytes) -> dict:
    """Describe the physical pre-chunk/trailer geometry of a 0x2C Contents stream.

    The block framing follows the public libmspub parser's physical rules.
    Names are intentionally conservative: the large pre-chunk type-0x90 table
    remains semantically unnamed until independent evidence identifies it.
    """
    if len(contents) < 0x30:
        raise ValueError("Contents stream too short")
    if contents[2] != 0x2C:
        raise ValueError(f"not a 0x2C Contents stream: magic={contents[:4].hex()}")

    trailer_offset = _u32(contents, 0x1A)
    if trailer_offset + 4 > len(contents):
        raise ValueError(f"trailer offset outside stream: 0x{trailer_offset:X}")
    trailer_length = _u32(contents, trailer_offset)
    trailer_end = trailer_offset + trailer_length

    trailer_parts = []
    pos = trailer_offset + 4
    for _ in range(3):
        part = _parse_block(contents, pos)
        trailer_parts.append(part)
        pos = part["end"]

    directory = next((p for p in trailer_parts if p["type"] == 0x90), None)
    refs = []
    if directory is not None:
        seq_num = -1
        for entry in _children(contents, directory):
            seq_num += 1
            if entry["type"] != 0x88:
                continue
            values = {}
            for child in _children(contents, entry):
                if child["id"] in (0x02, 0x04, 0x05):
                    values[child["id"]] = child["value"]
            if values.get(0x04) is not None:
                refs.append({
                    "seq_num": seq_num,
                    "chunk_type": values.get(0x02),
                    "chunk_offset": values.get(0x04),
                    "parent_seq_num": values.get(0x05),
                })

    first_chunk_offset = min(
        (r["chunk_offset"] for r in refs if r["chunk_offset"] is not None),
        default=None,
    )
    first_chunk_type = None
    if first_chunk_offset is not None:
        for ref in refs:
            if ref["chunk_offset"] == first_chunk_offset:
                first_chunk_type = ref["chunk_type"]
                break

    prelude_blocks = []
    if first_chunk_offset is not None:
        pos = 0x30
        while pos < first_chunk_offset:
            block = _parse_block(contents, pos)
            if block["end"] <= pos:
                raise ValueError(f"non-advancing prelude block at 0x{pos:X}")
            prelude_blocks.append(block)
            pos = block["end"]
        if pos != first_chunk_offset:
            raise ValueError(
                f"prelude blocks do not meet first chunk: 0x{pos:X} != 0x{first_chunk_offset:X}"
            )

    prechunk_table = prelude_blocks[-1] if prelude_blocks else None
    table_children = []
    sequential_ids = False
    child_types = Counter()
    if (
        prechunk_table is not None
        and prechunk_table["id"] == 0x03
        and prechunk_table["type"] == 0x90
    ):
        table_children = _children(contents, prechunk_table)
        child_types.update(child["type"] for child in table_children)

        seq_values = []
        for entry in table_children:
            if entry["type"] != 0x88:
                seq_values.append(None)
                continue
            id1 = [
                child for child in _children(contents, entry)
                if child["id"] == 0x01 and child["type"] == 0x18
            ]
            seq_values.append(id1[0]["value"] if len(id1) == 1 else None)
        sequential_ids = seq_values == list(range(1, len(table_children) + 1))

    scaffold_offset = contents.find(seed_scaffold)
    scaffold_end = scaffold_offset + len(seed_scaffold) if scaffold_offset >= 0 else None
    scaffold_inside_table = bool(
        scaffold_offset >= 0
        and prechunk_table is not None
        and prechunk_table["start"] <= scaffold_offset
        and scaffold_end <= prechunk_table["end"]
    )

    return {
        "magic_hex": contents[:4].hex(),
        "stream_len": len(contents),
        "trailer_offset": trailer_offset,
        "trailer_length": trailer_length,
        "trailer_end": trailer_end,
        "trailer_part_types": [p["type"] for p in trailer_parts],
        "chunk_reference_count": len(refs),
        "first_chunk_offset": first_chunk_offset,
        "first_chunk_type": first_chunk_type,
        "prelude_block_count": len(prelude_blocks),
        "prechunk_table_start": prechunk_table["start"] if prechunk_table else None,
        "prechunk_table_end": prechunk_table["end"] if prechunk_table else None,
        "prechunk_table_id": prechunk_table["id"] if prechunk_table else None,
        "prechunk_table_type": prechunk_table["type"] if prechunk_table else None,
        "prechunk_table_child_count": len(table_children),
        "prechunk_table_child_types": {
            f"0x{k:02X}": v for k, v in sorted(child_types.items())
        },
        "prechunk_table_seq_1_to_n": sequential_ids,
        "scaffold_offset": scaffold_offset if scaffold_offset >= 0 else None,
        "scaffold_len": len(seed_scaffold),
        "scaffold_inside_prechunk_table": scaffold_inside_table,
        "scaffold_delta_from_table_start": (
            scaffold_offset - prechunk_table["start"]
            if scaffold_inside_table and prechunk_table is not None
            else None
        ),
        "scaffold_gap_to_first_chunk": (
            first_chunk_offset - scaffold_end
            if scaffold_end is not None and first_chunk_offset is not None
            else None
        ),
        "prechunk_table_ends_at_first_chunk": bool(
            prechunk_table is not None
            and first_chunk_offset is not None
            and prechunk_table["end"] == first_chunk_offset
        ),
    }


def stats(values: Iterable[int]) -> dict:
    vals = sorted(values)
    if not vals:
        return {"count": 0}
    return {
        "count": len(vals),
        "min": vals[0],
        "median": statistics.median(vals),
        "mean": round(statistics.fmean(vals), 2),
        "max": vals[-1],
    }


def parse_pub(blob: bytes) -> Tuple[List[str], Dict[str, bytes]]:
    if not olefile.isOleFile(io.BytesIO(blob)):
        raise ValueError("not an OLE/CFB file")
    streams: Dict[str, bytes] = {}
    with olefile.OleFileIO(io.BytesIO(blob)) as ole:
        for parts in ole.listdir(streams=True, storages=False):
            path = "/" + "/".join(parts)
            streams[path] = ole.openstream(parts).read()
    return sorted(streams), streams


def category_of(path: str) -> Tuple[str, str]:
    rel = path[len(TEMPLATE_PREFIX):]
    parts = rel.split("/")
    level1 = parts[0] if len(parts) > 1 else ""
    level2 = parts[1] if len(parts) > 2 else ""
    return level1, level2


def analyze(apk_path: Path) -> Tuple[dict, List[dict], List[dict]]:
    with zipfile.ZipFile(apk_path) as apk:
        names = apk.namelist()
        pubs = sorted(
            n for n in names
            if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub")
        )
        if not pubs:
            raise SystemExit("No Publisher templates found in base APK")

        seed_bytes = {}
        for name, (zip_path, expected_stream) in SEEDS.items():
            seed_bytes[name] = {
                "zip_path": zip_path,
                "expected_stream": expected_stream,
                "bytes": apk.read(zip_path),
            }

        presence = Counter()
        stream_set_clusters = Counter()
        whole_hashes = Counter()
        key_hashes = defaultdict(Counter)
        key_sizes = defaultdict(list)
        categories = Counter()
        parse_errors = []
        rows: List[dict] = []
        stream_rows: List[dict] = []
        seed_similarity = defaultdict(list)
        contents_structures = []
        universal_contents_scaffold = seed_bytes["contents"]["bytes"][0x100:0xF80]

        for index, pub_path in enumerate(pubs, 1):
            blob = apk.read(pub_path)
            pub_hash = h(blob)
            whole_hashes[pub_hash] += 1
            level1, level2 = category_of(pub_path)
            categories[(level1, level2)] += 1

            try:
                stream_paths, streams = parse_pub(blob)
            except Exception as exc:
                parse_errors.append({"path": pub_path, "error": repr(exc)})
                continue

            for path in stream_paths:
                presence[path] += 1

            signature_text = "\n".join(stream_paths).encode()
            signature = h(signature_text)
            stream_set_clusters[signature] += 1

            row = {
                "index": index,
                "path": pub_path,
                "category": level1,
                "subcategory": level2,
                "pub_size": len(blob),
                "pub_sha256": pub_hash,
                "stream_count": len(stream_paths),
                "stream_set_sha256": signature,
            }

            for path, data in streams.items():
                family = KEY_PATHS.get(path)
                stream_rows.append({
                    "template": pub_path,
                    "category": level1,
                    "subcategory": level2,
                    "stream_path": path,
                    "family": family or "",
                    "len": len(data),
                    "sha256": h(data),
                })
                if family:
                    key_hashes[family][h(data)] += 1
                    key_sizes[family].append(len(data))
                    row[f"{family}_len"] = len(data)
                    row[f"{family}_sha256"] = h(data)

            if "/Contents" in streams:
                try:
                    structure = analyze_contents_0x2c(
                        streams["/Contents"],
                        universal_contents_scaffold,
                    )
                    structure["template"] = pub_path
                    contents_structures.append(structure)
                    for key in (
                        "first_chunk_offset",
                        "first_chunk_type",
                        "prechunk_table_start",
                        "prechunk_table_end",
                        "prechunk_table_child_count",
                        "scaffold_offset",
                        "scaffold_delta_from_table_start",
                        "scaffold_gap_to_first_chunk",
                    ):
                        row[f"contents_{key}"] = structure.get(key)
                    row["contents_prechunk_table_seq_1_to_n"] = structure[
                        "prechunk_table_seq_1_to_n"
                    ]
                except Exception as exc:
                    row["contents_structure_error"] = repr(exc)

            for seed_name, seed in seed_bytes.items():
                target = seed["expected_stream"]
                if target not in streams:
                    continue
                actual = streams[target]
                seed_blob = seed["bytes"]
                block_match = seed_block_matches(seed_blob, actual)
                seed_similarity[seed_name].append({
                    "template": pub_path,
                    "stream_len": len(actual),
                    "seed_len": len(seed_blob),
                    "exact": actual == seed_blob,
                    "common_prefix": common_prefix(seed_blob, actual),
                    "common_suffix": common_suffix(seed_blob, actual),
                    **block_match,
                })

            rows.append(row)

    n = len(pubs)
    ubiquitous = [
        {"path": path, "count": count, "pct": round(100 * count / n, 2)}
        for path, count in presence.most_common()
        if count == n
    ]
    variable = [
        {"path": path, "count": count, "pct": round(100 * count / n, 2)}
        for path, count in presence.most_common()
        if count != n
    ]

    seed_report = {}
    for seed_name, items in seed_similarity.items():
        by_prefix = sorted(items, key=lambda x: (x["common_prefix"], x["common_suffix"]), reverse=True)
        by_suffix = sorted(items, key=lambda x: (x["common_suffix"], x["common_prefix"]), reverse=True)
        seed_blob = seed_bytes[seed_name]["bytes"]
        seed_report[seed_name] = {
            "zip_path": seed_bytes[seed_name]["zip_path"],
            "expected_stream": seed_bytes[seed_name]["expected_stream"],
            "seed_len": len(seed_blob),
            "seed_sha256": h(seed_blob),
            "templates_with_stream": len(items),
            "exact_matches": sum(1 for x in items if x["exact"]),
            "best_common_prefix": by_prefix[:10],
            "best_common_suffix": by_suffix[:10],
            "block_match": {
                "block_size": items[0]["block_size"] if items else 64,
                "matched_pct": stats(int(round(x["matched_pct"] * 100)) for x in items),
                "matched_blocks": stats(x["matched_blocks"] for x in items),
                "longest_same_delta_run_bytes": stats(
                    x["longest_same_delta_run_bytes"] for x in items
                ),
                "best_templates": sorted(
                    (
                        {
                            "template": x["template"],
                            "matched_blocks": x["matched_blocks"],
                            "total_blocks": x["total_blocks"],
                            "matched_pct": x["matched_pct"],
                            "longest_same_delta_run_bytes": x["longest_same_delta_run_bytes"],
                            "longest_run_seed_start": x["longest_run_seed_start"],
                            "longest_run_actual_start": x["longest_run_actual_start"],
                            "longest_run_delta": x["longest_run_delta"],
                        }
                        for x in items
                    ),
                    key=lambda x: (
                        x["matched_pct"],
                        x["longest_same_delta_run_bytes"],
                    ),
                    reverse=True,
                )[:10],
                "run_seed_start_counts": [
                    {"offset": offset, "count": count}
                    for offset, count in Counter(
                        x["longest_run_seed_start"] for x in items
                    ).most_common()
                ],
                "run_actual_start_counts": [
                    {"offset": offset, "count": count}
                    for offset, count in Counter(
                        x["longest_run_actual_start"] for x in items
                    ).most_common()
                ],
                "run_delta_counts": [
                    {"delta": delta, "count": count}
                    for delta, count in Counter(
                        x["longest_run_delta"] for x in items
                    ).most_common()
                ],
                "largest_contiguous_runs": sorted(
                    (
                        {
                            "template": x["template"],
                            "run_bytes": x["longest_same_delta_run_bytes"],
                            "seed_start": x["longest_run_seed_start"],
                            "actual_start": x["longest_run_actual_start"],
                            "delta": x["longest_run_delta"],
                        }
                        for x in items
                    ),
                    key=lambda x: x["run_bytes"],
                    reverse=True,
                )[:20],
            },
        }

    duplicate_whole_files = [
        {"sha256": digest, "count": count}
        for digest, count in whole_hashes.most_common()
        if count > 1
    ]

    key_streams = {}
    for family in sorted(key_sizes):
        hashes = key_hashes[family]
        key_streams[family] = {
            "size": stats(key_sizes[family]),
            "unique_hashes": len(hashes),
            "largest_hash_clusters": [
                {"sha256": digest, "count": count}
                for digest, count in hashes.most_common(15)
            ],
        }

    contents_structure_report = {
        "analyzed": len(contents_structures),
        "magic_counts": [
            {"magic_hex": value, "count": count}
            for value, count in Counter(
                row["magic_hex"] for row in contents_structures
            ).most_common()
        ],
        "first_chunk_offset": stats(
            row["first_chunk_offset"]
            for row in contents_structures
            if row["first_chunk_offset"] is not None
        ),
        "first_chunk_type_counts": [
            {"type": value, "count": count}
            for value, count in Counter(
                row["first_chunk_type"] for row in contents_structures
            ).most_common()
        ],
        "chunk_reference_count": stats(
            row["chunk_reference_count"] for row in contents_structures
        ),
        "prechunk_table_start": stats(
            row["prechunk_table_start"]
            for row in contents_structures
            if row["prechunk_table_start"] is not None
        ),
        "prechunk_table_end": stats(
            row["prechunk_table_end"]
            for row in contents_structures
            if row["prechunk_table_end"] is not None
        ),
        "prechunk_table_child_count": stats(
            row["prechunk_table_child_count"] for row in contents_structures
        ),
        "prechunk_table_id_type_counts": [
            {"id": key[0], "type": key[1], "count": count}
            for key, count in Counter(
                (row["prechunk_table_id"], row["prechunk_table_type"])
                for row in contents_structures
            ).most_common()
        ],
        "prechunk_table_ends_at_first_chunk": sum(
            1 for row in contents_structures
            if row["prechunk_table_ends_at_first_chunk"]
        ),
        "prechunk_table_seq_1_to_n": sum(
            1 for row in contents_structures
            if row["prechunk_table_seq_1_to_n"]
        ),
        "universal_scaffold_exact_matches": sum(
            1 for row in contents_structures
            if row["scaffold_offset"] is not None
        ),
        "universal_scaffold_inside_prechunk_table": sum(
            1 for row in contents_structures
            if row["scaffold_inside_prechunk_table"]
        ),
        "scaffold_delta_from_table_start_counts": [
            {"delta": value, "count": count}
            for value, count in Counter(
                row["scaffold_delta_from_table_start"]
                for row in contents_structures
                if row["scaffold_delta_from_table_start"] is not None
            ).most_common()
        ],
        "scaffold_gap_to_first_chunk": stats(
            row["scaffold_gap_to_first_chunk"]
            for row in contents_structures
            if row["scaffold_gap_to_first_chunk"] is not None
        ),
    }

    report = {
        "schema": SCHEMA,
        "apk": str(apk_path),
        "template_count": n,
        "parsed_count": len(rows),
        "parse_errors": parse_errors,
        "categories": [
            {"category": a, "subcategory": b, "count": count}
            for (a, b), count in categories.most_common()
        ],
        "stream_path_count": len(presence),
        "ubiquitous_streams": ubiquitous,
        "variable_streams": variable,
        "stream_set_signature_count": len(stream_set_clusters),
        "largest_stream_set_clusters": [
            {"stream_set_sha256": sig, "count": count}
            for sig, count in stream_set_clusters.most_common(20)
        ],
        "duplicate_whole_files": duplicate_whole_files,
        "key_streams": key_streams,
        "seed_similarity": seed_report,
        "contents_0x2c_structure": contents_structure_report,
        "interpretation_boundary": (
            "Corpus frequency and byte similarity are physical evidence only; "
            "they do not prove semantic ownership of Publisher fields."
        ),
    }
    return report, rows, stream_rows


def write_csv(path: Path, rows: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({k for row in rows for k in row})
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, report: dict) -> None:
    lines = [
        "# Canyua Publisher 2013 template corpus",
        "",
        f"- templates: **{report['template_count']}**",
        f"- parsed OLE/CFB: **{report['parsed_count']}**",
        f"- distinct stream paths: **{report['stream_path_count']}**",
        f"- distinct stream-set signatures: **{report['stream_set_signature_count']}**",
        f"- exact duplicate PUB files: **{len(report['duplicate_whole_files'])} hash groups**",
        "",
        "## Streams present in every template",
        "",
    ]
    for item in report["ubiquitous_streams"]:
        lines.append(f"- `{item['path']}`")
    lines += ["", "## Key stream size / hash diversity", ""]
    for family, info in report["key_streams"].items():
        size = info["size"]
        lines.append(
            f"- **{family}**: count={size.get('count', 0)}, "
            f"min={size.get('min')}, median={size.get('median')}, "
            f"max={size.get('max')}, unique_hashes={info['unique_hashes']}"
        )
    lines += ["", "## Seed comparison", ""]
    for seed, info in report["seed_similarity"].items():
        best = info["best_common_prefix"][0] if info["best_common_prefix"] else None
        lines.append(
            f"- **{seed}**: seed_len={info['seed_len']}, "
            f"stream_present={info['templates_with_stream']}, "
            f"exact_matches={info['exact_matches']}, "
            f"best_prefix={best['common_prefix'] if best else None}, "
            f"best_suffix={info['best_common_suffix'][0]['common_suffix'] if info['best_common_suffix'] else None}, "
            f"best_64B_block_match={info['block_match']['best_templates'][0]['matched_pct'] if info['block_match']['best_templates'] else None}%"
        )
    structure = report["contents_0x2c_structure"]
    lines += [
        "",
        "## Contents 0x2C pre-chunk structure",
        "",
        f"- analyzed: **{structure['analyzed']}**",
        f"- pre-chunk table ends at first chunk: **{structure['prechunk_table_ends_at_first_chunk']}**",
        f"- pre-chunk table has sequential 1..N entry IDs: **{structure['prechunk_table_seq_1_to_n']}**",
        f"- exact 3712-byte scaffold matches: **{structure['universal_scaffold_exact_matches']}**",
        f"- scaffold is inside pre-chunk table: **{structure['universal_scaffold_inside_prechunk_table']}**",
        f"- scaffold delta from table start: **{structure['scaffold_delta_from_table_start_counts']}**",
        f"- table child-count stats: **{structure['prechunk_table_child_count']}**",
        "",
        "## Interpretation boundary",
        "",
        report["interpretation_boundary"],
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("base_apk", type=Path)
    p.add_argument("--out", type=Path, default=Path("work/canyua-template-corpus"))
    args = p.parse_args()

    report, templates, streams = analyze(args.base_apk)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_csv(args.out / "templates.csv", templates)
    write_csv(args.out / "streams.csv", streams)
    write_summary(args.out / "SUMMARY.md", report)

    print(json.dumps({
        "template_count": report["template_count"],
        "parsed_count": report["parsed_count"],
        "stream_path_count": report["stream_path_count"],
        "stream_set_signature_count": report["stream_set_signature_count"],
        "key_streams": {
            k: {
                "size": v["size"],
                "unique_hashes": v["unique_hashes"],
            }
            for k, v in report["key_streams"].items()
        },
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
