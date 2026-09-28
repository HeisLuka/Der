#!/usr/bin/env python3
"""Inspect a Canyua APK/XAPK candidate without executing it.

This is a narrow provenance/runtime-admission probe for the dynamic oracle.
It does not patch the package and does not bypass PairIP, licensing, signatures,
billing, or any other protection.

Supported inputs:
- a normal APK;
- an XAPK/APKS/ZIP containing one or more APK splits.

Optionally extracts installable APK members for a later emulator run.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = "der/canyua-package-inspection/v1"

NEEDLES = {
    "pairip": [
        b"com/pairip",
        b"com.pairip",
        b"licensecheck",
        b"LicenseActivity",
    ],
    "reader": [
        b"mspubCore",
        b"MSPUBDocument",
        b"libmspub",
        b"librevenge",
    ],
    "writer": [
        b"libpubBuilder",
        b"MSPUBBuilder",
        b"createPub",
    ],
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def is_direct_apk(path: Path) -> bool:
    if not zipfile.is_zipfile(path):
        return False
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
    return "AndroidManifest.xml" in names and "classes.dex" in names


def nested_apks(path: Path) -> list[tuple[str, bytes]]:
    if is_direct_apk(path):
        return [(path.name, path.read_bytes())]

    if not zipfile.is_zipfile(path):
        raise ValueError("candidate is not a ZIP/APK/XAPK")

    out: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as outer:
        for name in sorted(outer.namelist()):
            if name.lower().endswith(".apk") and not name.endswith("/"):
                out.append((name, outer.read(name)))
    if not out:
        raise ValueError("archive contains no APK members")
    return out


def inspect_apk(name: str, blob: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = z.namelist()
        abis = sorted({
            n.split("/")[1]
            for n in names
            if n.startswith("lib/") and n.count("/") >= 2
        })
        native = sorted(
            n for n in names
            if n.startswith("lib/") and n.endswith(".so")
        )
        scan = [
            n for n in names
            if n.endswith(".dex")
            or n == "AndroidManifest.xml"
            or n.endswith(".so")
        ]

        hits = {k: [] for k in NEEDLES}
        for member in scan:
            try:
                data = z.read(member).lower()
            except Exception:
                continue
            for group, patterns in NEEDLES.items():
                for pat in patterns:
                    if pat.lower() in data:
                        hits[group].append({
                            "file": member,
                            "needle": pat.decode("ascii", "replace"),
                        })

        return {
            "name": name,
            "bytes": len(blob),
            "sha256": sha256_bytes(blob),
            "abis": abis,
            "native_libraries": native,
            "marker_hits": hits,
        }


def inspect(path: Path, extract_dir: Optional[Path]) -> dict:
    members = nested_apks(path)
    split_reports = [inspect_apk(name, blob) for name, blob in members]

    pairip_hits = [
        {"apk": row["name"], **hit}
        for row in split_reports
        for hit in row["marker_hits"]["pairip"]
    ]
    reader_hits = [
        {"apk": row["name"], **hit}
        for row in split_reports
        for hit in row["marker_hits"]["reader"]
    ]
    writer_hits = [
        {"apk": row["name"], **hit}
        for row in split_reports
        for hit in row["marker_hits"]["writer"]
    ]

    all_abis = sorted({
        abi for row in split_reports for abi in row["abis"]
    })

    extracted = []
    if extract_dir is not None:
        extract_dir.mkdir(parents=True, exist_ok=True)
        for index, (name, blob) in enumerate(members):
            leaf = Path(name).name or f"split-{index}.apk"
            target = extract_dir / leaf
            if target.exists():
                target = extract_dir / f"{index:02d}-{leaf}"
            target.write_bytes(blob)
            extracted.append(str(target))

    return {
        "schema": SCHEMA,
        "candidate": str(path),
        "candidate_bytes": path.stat().st_size,
        "candidate_sha256": sha256_path(path),
        "container_kind": "apk" if is_direct_apk(path) else "split_archive",
        "apk_count": len(split_reports),
        "abis": all_abis,
        "pairip_present": bool(pairip_hits),
        "reader_markers_present": bool(reader_hits),
        "writer_markers_present": bool(writer_hits),
        "pairip_hits": pairip_hits,
        "reader_hits": reader_hits,
        "writer_hits": writer_hits,
        "splits": split_reports,
        "extracted_apks": extracted,
        "admission": (
            "eligible_for_normal_runtime_probe"
            if not pairip_hits and reader_hits and writer_hits
            else "not_eligible_for_writer_runtime_probe"
        ),
        "boundary": (
            "Static package inspection only. A positive writer marker does not "
            "grant entitlement to paid Save/Export features. Runtime automation "
            "must still respect purchase/license gates."
        ),
    }


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("candidate", type=Path)
    p.add_argument("--json", dest="json_path", type=Path)
    p.add_argument("--extract-apks", type=Path)
    p.add_argument("--require-eligible", action="store_true")
    return p.parse_args(argv)


def main() -> int:
    args = parse_args()
    report = inspect(args.candidate, args.extract_apks)
    text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.json_path:
        args.json_path.parent.mkdir(parents=True, exist_ok=True)
        args.json_path.write_text(text, encoding="utf-8")
    print(text, end="")
    if args.require_eligible and report["admission"] != "eligible_for_normal_runtime_probe":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
