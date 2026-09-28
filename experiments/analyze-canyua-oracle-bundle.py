#!/usr/bin/env python3
"""Aggregate controlled Canyua PUB writer arms into one machine-readable receipt.

The tool deliberately separates:
- writer normalization/noise: source -> no-op resave, repeated no-op save;
- semantic-correlated deltas: no-op control -> one-mutation output;
- reversibility/allocation: A -> B -> A or move -> restore.

It consumes existing physical CFB stream diff logic. It does not assign semantic
ownership to changed byte ranges and does not treat the entry-139 table variant
as a unique Canyua fingerprint.

Dependency for real PUB files:
    python -m pip install olefile

Expected bundle names (only source.pub is required):
    source.pub
    resave-control.pub
    resave-control-2.pub
    text-a-to-b.pub
    text-b-to-a.pub
    move-shape-x.pub
    move-shape-x-restore.pub
    font-size.pub
    fill-color.pub
    image-insert.pub
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

HERE = Path(__file__).resolve().parent
DIFF_PATH = HERE / "diff-pub-cfb.py"
PROFILE_PATH = HERE / "probe-canyua-contents-profile.py"

SCHEMA = "der/canyua-writer-oracle-bundle/v1"

ARMS = {
    "source": "source.pub",
    "resave_control": "resave-control.pub",
    "resave_control_2": "resave-control-2.pub",
    "text_a_to_b": "text-a-to-b.pub",
    "text_b_to_a": "text-b-to-a.pub",
    "move_shape_x": "move-shape-x.pub",
    "move_shape_x_restore": "move-shape-x-restore.pub",
    "font_size": "font-size.pub",
    "fill_color": "fill-color.pub",
    "image_insert": "image-insert.pub",
}

COMPARISONS = [
    ("normalization_baseline", "source", "resave_control"),
    ("repeat_save_noise", "resave_control", "resave_control_2"),
    ("text_semantic_delta", "resave_control", "text_a_to_b"),
    ("text_reversal", "text_a_to_b", "text_b_to_a"),
    ("shape_x_semantic_delta", "resave_control", "move_shape_x"),
    ("shape_x_reversal", "move_shape_x", "move_shape_x_restore"),
    ("font_size_semantic_delta", "resave_control", "font_size"),
    ("fill_color_semantic_delta", "resave_control", "fill_color"),
    ("image_insert_semantic_delta", "resave_control", "image_insert"),
]

FAMILY_ORDER = [
    "contents",
    "quill",
    "quill_legacy_or_simplified",
    "escher",
    "escher_delay",
    "summary_information",
    "document_summary_information",
]


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


D = load_module(DIFF_PATH, "der_pub_cfb_diff")


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def summarize_diff(report: dict) -> dict:
    family_rows: Dict[str, list[dict]] = {}
    for row in report["streams"]:
        family = row.get("family")
        if family is None:
            continue
        family_rows.setdefault(family, []).append(row)

    families = {}
    for family in FAMILY_ORDER:
        rows = family_rows.get(family, [])
        if not rows:
            families[family] = {
                "status": "absent",
                "paths": [],
            }
            continue
        changed = [r for r in rows if r["status"] != "unchanged"]
        families[family] = {
            "status": "changed" if changed else "unchanged",
            "paths": [
                {
                    "path": r["path"],
                    "status": r["status"],
                    "before_len": r["before"]["len"] if r["before"] else None,
                    "after_len": r["after"]["len"] if r["after"] else None,
                    "before_changed": r["before_changed"],
                    "after_changed": r["after_changed"],
                }
                for r in changed
            ],
        }

    return {
        "stream_summary": report["summary"],
        "families": families,
        "changed_key_families": [
            family
            for family in FAMILY_ORDER
            if families[family]["status"] == "changed"
        ],
    }


def safe_profile(path: Path) -> dict:
    """Classify only as a version/profile clue; never as producer identity."""
    try:
        P = load_module(PROFILE_PATH, "der_canyua_profile")
        contents = P.A.extract_contents_from_pub(path.read_bytes())
        result = P.classify(contents)
        return {
            "available": True,
            "profile": result["profile"],
            "entry_len": result["entry_len"],
            "entry_sha256": result["entry_sha256"],
            "interpretation": (
                "table_profile_only_not_unique_canyua_fingerprint"
            ),
        }
    except Exception as exc:
        return {
            "available": False,
            "error": repr(exc),
            "interpretation": (
                "profile unavailable or outside the narrow mature-0x2C probe"
            ),
        }


def analyze_bundle(bundle: Path) -> dict:
    paths = {
        arm: bundle / filename
        for arm, filename in ARMS.items()
        if (bundle / filename).is_file()
    }
    if "source" not in paths:
        raise SystemExit(f"missing required {bundle / ARMS['source']}")

    inputs = {
        arm: {
            "filename": path.name,
            "bytes": path.stat().st_size,
            "sha256": sha256_path(path),
            "contents_table_profile": safe_profile(path),
        }
        for arm, path in sorted(paths.items())
    }

    comparisons = {}
    matrix = {}
    for name, before_arm, after_arm in COMPARISONS:
        if before_arm not in paths or after_arm not in paths:
            comparisons[name] = {
                "status": "not_available",
                "before_arm": before_arm,
                "after_arm": after_arm,
            }
            continue

        before = D.load_ole_streams(paths[before_arm])
        after = D.load_ole_streams(paths[after_arm])
        physical = D.diff_maps(before, after)
        summary = summarize_diff(physical)
        comparisons[name] = {
            "status": "analyzed",
            "before_arm": before_arm,
            "after_arm": after_arm,
            **summary,
        }
        matrix[name] = {
            family: summary["families"][family]["status"]
            for family in FAMILY_ORDER
        }

    available_arms = sorted(paths)
    return {
        "schema": SCHEMA,
        "bundle": str(bundle),
        "available_arms": available_arms,
        "missing_optional_arms": sorted(set(ARMS) - set(paths)),
        "inputs": inputs,
        "comparisons": comparisons,
        "matrix": matrix,
        "interpretation_boundary": [
            "Physical stream changes do not by themselves prove semantic field ownership.",
            "Semantic-correlated evidence should be read against the no-op normalization baseline.",
            "Repeat-save differences are writer/session noise candidates until independently explained.",
            "A->B->A comparisons test convergence/reversibility but byte inequality does not automatically imply semantic failure.",
            "The 3902/3906 entry-139 variants are table/version profile evidence, not unique Canyua producer fingerprints.",
            "Canyua behavior becomes Publisher-format evidence only after independent correlation.",
        ],
    }


def markdown(report: dict) -> str:
    lines = [
        "# Canyua writer oracle bundle",
        "",
        f"- available arms: **{len(report['available_arms'])}**",
        f"- missing optional arms: **{len(report['missing_optional_arms'])}**",
        "",
        "## Physical stream-family matrix",
        "",
        "| comparison | Contents | Quill | Escher | EscherDelay | Summary | DocSummary |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, row in report["matrix"].items():
        lines.append(
            "| " + " | ".join([
                name,
                row["contents"],
                row["quill"],
                row["escher"],
                row["escher_delay"],
                row["summary_information"],
                row["document_summary_information"],
            ]) + " |"
        )

    lines += [
        "",
        "## Interpretation boundary",
        "",
    ]
    lines.extend(f"- {item}" for item in report["interpretation_boundary"])
    lines.append("")
    return "\n".join(lines)


def self_test() -> None:
    before = {
        "/Contents": b"same",
        "/Quill/QuillSub/CONTENTS": b"abc",
        "/Escher/EscherStm": b"shape",
    }
    after = {
        "/Contents": b"same",
        "/Quill/QuillSub/CONTENTS": b"abd",
        "/Escher/EscherStm": b"shape",
    }
    report = D.diff_maps(before, after)
    summary = summarize_diff(report)
    assert summary["families"]["contents"]["status"] == "unchanged"
    assert summary["families"]["quill"]["status"] == "changed"
    assert summary["families"]["escher"]["status"] == "unchanged"
    assert summary["changed_key_families"] == ["quill"]
    print("OK")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", type=Path)
    p.add_argument("--json", dest="json_path", type=Path)
    p.add_argument("--markdown", dest="markdown_path", type=Path)
    p.add_argument("--self-test", action="store_true")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.bundle is None:
        raise SystemExit("--bundle is required unless --self-test is used")

    report = analyze_bundle(args.bundle)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(text, encoding="utf-8")
    if args.markdown_path:
        args.markdown_path.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_path.write_text(markdown(report), encoding="utf-8")

    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
