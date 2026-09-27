#!/usr/bin/env python3
"""Classify the entry-139 profile of the Publisher 0x2C Contents pre-chunk table.

This is a narrow physical fingerprint probe. It does not claim semantic meaning
for entry 139 or its fields.

Profiles currently grounded by repository evidence:
- canyua_blank_seed_profile: Canyua 5.1.1 Contents.dat seed, 28-byte entry 139.
- publisher2013_template_profile: all 252 bundled Publisher 2013 templates,
  32-byte entry 139 with additional 0x06/0x08 and 0x07/0x08 zero blocks.

A Canyua-generated PUB is expected, but not yet dynamically proven, to retain
the blank-seed profile because the observed writer copies the pre-chunk region.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ANALYZER_PATH = HERE / "analyze-canyua-prechunk-table.py"
SEED_PATH = (
    "assets/Publisher Data/Publication Types/Blank Page Sizes/Standard/"
    "New Page Size/Contents.dat"
)
TEMPLATE_PREFIX = "assets/Publisher Templates/2013/BUILT-IN/"


def load_analyzer():
    spec = importlib.util.spec_from_file_location("canyua_prechunk_analyzer", ANALYZER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {ANALYZER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


A = load_analyzer()


def field_signature(contents: bytes) -> dict:
    table, entries = A.find_prechunk_table(contents)
    entry = entries[138]
    fields = []
    for field in A.children(contents, entry):
        value = None
        if field["data_length"] == 2:
            value = A.u16(contents, field["data_offset"])
        elif field["data_length"] == 4:
            value = A.u32(contents, field["data_offset"])
        fields.append({
            "id": field["id"],
            "type": field["type"],
            "value": value,
        })
    return {
        "table_start": table["start"],
        "entry_start": entry["start"],
        "entry_end": entry["end"],
        "entry_len": entry["end"] - entry["start"],
        "entry_sha256": A.sha256(contents[entry["start"]:entry["end"]]),
        "fields": fields,
    }


def key(fields: list[dict]) -> list[tuple[int, int, int | None]]:
    return [(f["id"], f["type"], f["value"]) for f in fields]


SEED_SIGNATURE = [
    (0x01, 0x18, 139),
    (0x03, 0x20, 65536020),
    (0x08, 0x08, None),
    (0x09, 0x10, 1),
    (0x0C, 0x20, 5),
]

PUBLISHER2013_SIGNATURE = [
    (0x01, 0x18, 139),
    (0x03, 0x20, 65536020),
    (0x06, 0x08, None),
    (0x07, 0x08, None),
    (0x08, 0x08, None),
    (0x09, 0x10, 1),
    (0x0C, 0x20, 5),
]


def classify(contents: bytes) -> dict:
    physical = field_signature(contents)
    signature = key(physical["fields"])

    if physical["entry_len"] == 28 and signature == SEED_SIGNATURE:
        profile = "canyua_blank_seed_profile"
    elif physical["entry_len"] == 32 and signature == PUBLISHER2013_SIGNATURE:
        profile = "publisher2013_template_profile"
    else:
        profile = "unknown"

    return {
        "schema": "der/canyua-contents-entry139-profile/v1",
        "profile": profile,
        **physical,
    }


def inspect_corpus(apk_path: Path) -> dict:
    with zipfile.ZipFile(apk_path) as apk:
        seed = classify(apk.read(SEED_PATH))
        template_paths = sorted(
            n for n in apk.namelist()
            if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub")
        )
        counts = Counter()
        unknown = []
        for path in template_paths:
            contents = A.extract_contents_from_pub(apk.read(path))
            result = classify(contents)
            counts[result["profile"]] += 1
            if result["profile"] == "unknown":
                unknown.append({
                    "path": path,
                    "entry_len": result["entry_len"],
                    "fields": result["fields"],
                })

    return {
        "schema": "der/canyua-contents-entry139-corpus-validation/v1",
        "seed": seed,
        "template_count": len(template_paths),
        "template_profiles": dict(sorted(counts.items())),
        "unknown_templates": unknown,
        "prediction": (
            "A newly emitted Canyua PUB is expected to carry "
            "canyua_blank_seed_profile because the observed Contents writer copies "
            "the pre-chunk seed region; dynamic output is still required to confirm."
        ),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    source = p.add_mutually_exclusive_group(required=True)
    source.add_argument("--pub", type=Path)
    source.add_argument("--contents", type=Path)
    source.add_argument("--apk-corpus", type=Path)
    p.add_argument("--json", dest="json_path", type=Path)
    p.add_argument("--assert-known-corpus", action="store_true")
    args = p.parse_args()

    if args.apk_corpus:
        result = inspect_corpus(args.apk_corpus)
        if args.assert_known_corpus:
            expected = {"publisher2013_template_profile": 252}
            if result["seed"]["profile"] != "canyua_blank_seed_profile":
                raise SystemExit(
                    f"unexpected seed profile: {result['seed']['profile']}"
                )
            if result["template_profiles"] != expected:
                raise SystemExit(
                    f"unexpected corpus profiles: {result['template_profiles']}"
                )
    elif args.contents:
        result = classify(args.contents.read_bytes())
    else:
        result = classify(A.extract_contents_from_pub(args.pub.read_bytes()))

    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
