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
    lines += [
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
