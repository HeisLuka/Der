#!/usr/bin/env python3
"""
Physical CFB/OLE stream diff for controlled Microsoft Publisher experiments.

This tool intentionally makes no semantic claims about Publisher records. It
compares stream bytes so that a controlled writer experiment can later be
mapped onto Contents / Quill / Escher with separate format evidence.

Dependency for real PUB files:
    python -m pip install olefile

Self-test:
    python experiments/diff-pub-cfb.py --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SCHEMA = "der/pub-cfb-stream-diff/v1"

KEY_STREAMS = {
    "/Contents": "contents",
    "/Quill/QuillSub/CONTENTS": "quill",
    "/Quill/CONTENTS": "quill_legacy_or_simplified",
    "/Escher/EscherStm": "escher",
    "/Escher/EscherDelayStm": "escher_delay",
    "/\x05SummaryInformation": "summary_information",
    "/\x05DocumentSummaryInformation": "document_summary_information",
}


@dataclass(frozen=True)
class Span:
    start: int
    end: int

    @property
    def length(self) -> int:
        return self.end - self.start


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def stream_family(path: str) -> Optional[str]:
    if path in KEY_STREAMS:
        return KEY_STREAMS[path]
    if path.endswith("/CONTENTS") and "/Quill" in path:
        return "quill"
    if path.endswith("/EscherStm"):
        return "escher"
    if path.endswith("/EscherDelayStm"):
        return "escher_delay"
    return None


def common_prefix_len(left: bytes, right: bytes) -> int:
    limit = min(len(left), len(right))
    i = 0
    while i < limit and left[i] == right[i]:
        i += 1
    return i


def common_suffix_len(left: bytes, right: bytes, prefix: int) -> int:
    limit = min(len(left), len(right)) - prefix
    i = 0
    while i < limit and left[len(left) - 1 - i] == right[len(right) - 1 - i]:
        i += 1
    return i


def differing_runs(left: bytes, right: bytes, max_runs: int = 64) -> Tuple[List[Span], bool]:
    """
    Return positional mismatch runs inside the overlapping region.

    Insertions/deletions can shift later bytes, so these runs are descriptive
    only. The prefix/suffix envelope remains the safer first localization.
    """
    limit = min(len(left), len(right))
    runs: List[Span] = []
    start: Optional[int] = None

    for i in range(limit):
        differs = left[i] != right[i]
        if differs and start is None:
            start = i
        elif not differs and start is not None:
            runs.append(Span(start, i))
            start = None
            if len(runs) >= max_runs:
                return runs, True

    if start is not None:
        runs.append(Span(start, limit))

    if len(left) != len(right) and len(runs) < max_runs:
        runs.append(Span(limit, max(len(left), len(right))))

    truncated = len(runs) > max_runs
    return runs[:max_runs], truncated


def snapshot(data: bytes) -> dict:
    return {"len": len(data), "sha256": sha256(data)}


def diff_one(path: str, before: Optional[bytes], after: Optional[bytes]) -> dict:
    family = stream_family(path)

    if before is None:
        return {
            "path": path,
            "family": family,
            "status": "added",
            "before": None,
            "after": snapshot(after or b""),
            "common_prefix_len": 0,
            "common_suffix_len": 0,
            "before_changed": None,
            "after_changed": {"start": 0, "end": len(after or b""), "len": len(after or b"")},
            "mismatch_runs": [],
            "mismatch_runs_truncated": False,
        }

    if after is None:
        return {
            "path": path,
            "family": family,
            "status": "removed",
            "before": snapshot(before),
            "after": None,
            "common_prefix_len": 0,
            "common_suffix_len": 0,
            "before_changed": {"start": 0, "end": len(before), "len": len(before)},
            "after_changed": None,
            "mismatch_runs": [],
            "mismatch_runs_truncated": False,
        }

    if before == after:
        return {
            "path": path,
            "family": family,
            "status": "unchanged",
            "before": snapshot(before),
            "after": snapshot(after),
            "common_prefix_len": len(before),
            "common_suffix_len": 0,
            "before_changed": None,
            "after_changed": None,
            "mismatch_runs": [],
            "mismatch_runs_truncated": False,
        }

    prefix = common_prefix_len(before, after)
    suffix = common_suffix_len(before, after, prefix)
    before_end = len(before) - suffix
    after_end = len(after) - suffix
    runs, runs_truncated = differing_runs(before, after)

    return {
        "path": path,
        "family": family,
        "status": "changed",
        "before": snapshot(before),
        "after": snapshot(after),
        "common_prefix_len": prefix,
        "common_suffix_len": suffix,
        "before_changed": {
            "start": prefix,
            "end": before_end,
            "len": before_end - prefix,
        },
        "after_changed": {
            "start": prefix,
            "end": after_end,
            "len": after_end - prefix,
        },
        "mismatch_runs": [
            {"start": run.start, "end": run.end, "len": run.length}
            for run in runs
        ],
        "mismatch_runs_truncated": runs_truncated,
    }


def diff_maps(before: Dict[str, bytes], after: Dict[str, bytes]) -> dict:
    streams = [
        diff_one(path, before.get(path), after.get(path))
        for path in sorted(set(before) | set(after))
    ]

    summary = {"added": 0, "removed": 0, "changed": 0, "unchanged": 0}
    for row in streams:
        summary[row["status"]] += 1

    key_changes = [
        {
            "path": row["path"],
            "family": row["family"],
            "status": row["status"],
            "before_len": row["before"]["len"] if row["before"] else None,
            "after_len": row["after"]["len"] if row["after"] else None,
            "before_changed": row["before_changed"],
            "after_changed": row["after_changed"],
        }
        for row in streams
        if row["family"] is not None and row["status"] != "unchanged"
    ]

    return {
        "schema": SCHEMA,
        "interpretation": "physical_stream_diff_only",
        "warning": (
            "Changed bytes are evidence of physical writer behavior, not proof "
            "of Publisher semantic field ownership."
        ),
        "summary": summary,
        "key_stream_changes": key_changes,
        "streams": streams,
    }


def load_ole_streams(path: Path) -> Dict[str, bytes]:
    try:
        import olefile  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "Missing dependency 'olefile'. Install with: python -m pip install olefile"
        ) from exc

    if not olefile.isOleFile(str(path)):
        raise SystemExit(f"Not a CFB/OLE file: {path}")

    streams: Dict[str, bytes] = {}
    with olefile.OleFileIO(str(path)) as ole:
        for parts in ole.listdir(streams=True, storages=False):
            logical = "/" + "/".join(parts)
            streams[logical] = ole.openstream(parts).read()
    return streams


def print_text(report: dict, include_unchanged: bool) -> None:
    s = report["summary"]
    print(
        f"streams: changed={s['changed']} added={s['added']} "
        f"removed={s['removed']} unchanged={s['unchanged']}"
    )

    if report["key_stream_changes"]:
        print("\nkey Publisher streams:")
        for row in report["key_stream_changes"]:
            print(
                f"  {row['status']:9} {row['family']:28} {row['path']} "
                f"{row['before_len']} -> {row['after_len']}"
            )

    print("\nstream diff:")
    for row in report["streams"]:
        if row["status"] == "unchanged" and not include_unchanged:
            continue
        before_len = row["before"]["len"] if row["before"] else "-"
        after_len = row["after"]["len"] if row["after"] else "-"
        envelope = ""
        if row["status"] == "changed":
            b = row["before_changed"]
            a = row["after_changed"]
            envelope = (
                f" before[{b['start']}:{b['end']}]"
                f" after[{a['start']}:{a['end']}]"
                f" prefix={row['common_prefix_len']}"
                f" suffix={row['common_suffix_len']}"
            )
        print(
            f"  {row['status']:9} {before_len!s:>8} -> {after_len!s:<8} "
            f"{row['path']}{envelope}"
        )


def self_test() -> None:
    before = {
        "/Contents": b"abcDEFghi",
        "/Quill/QuillSub/CONTENTS": b"same",
        "/Old": b"gone",
    }
    after = {
        "/Contents": b"abcXYZghi",
        "/Quill/CONTENTS": b"same",
        "/New": b"new",
    }
    report = diff_maps(before, after)
    assert report["summary"] == {
        "added": 1,
        "removed": 1,
        "changed": 1,
        "unchanged": 1,
    }

    contents = next(row for row in report["streams"] if row["path"] == "/Contents")
    assert contents["common_prefix_len"] == 3
    assert contents["common_suffix_len"] == 3
    assert contents["before_changed"] == {"start": 3, "end": 6, "len": 3}
    assert contents["after_changed"] == {"start": 3, "end": 6, "len": 3}
    assert contents["family"] == "contents"

    insertion = diff_one("/Quill/QuillSub/CONTENTS", b"abcghi", b"abcXYZghi")
    assert insertion["before_changed"] == {"start": 3, "end": 3, "len": 0}
    assert insertion["after_changed"] == {"start": 3, "end": 6, "len": 3}
    print("OK")


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Physical CFB/OLE stream diff for controlled PUB writer experiments."
    )
    parser.add_argument("before", nargs="?", type=Path)
    parser.add_argument("after", nargs="?", type=Path)
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument("--include-unchanged", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0

    if args.before is None or args.after is None:
        raise SystemExit("before.pub and after.pub are required unless --self-test is used")

    before = load_ole_streams(args.before)
    after = load_ole_streams(args.after)
    report = diff_maps(before, after)

    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")

    print_text(report, args.include_unchanged)
    return 0


if __name__ == "__main__":
    sys.exit(main())
