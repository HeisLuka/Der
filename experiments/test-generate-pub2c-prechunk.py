#!/usr/bin/env python3
"""Metamorphic tests for generate-pub2c-prechunk.py.

These tests deliberately perturb independent inputs to prove that the
generator follows derived placement/pointer rules instead of replaying one
captured prefix.
"""
from __future__ import annotations

import hashlib
import importlib.util
import struct
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
GEN_PATH = HERE / "generate-pub2c-prechunk.py"
SPEC = importlib.util.spec_from_file_location("pub2c_prechunk", GEN_PATH)
assert SPEC and SPEC.loader
gen = importlib.util.module_from_spec(SPEC)
sys.modules["pub2c_prechunk"] = gen
SPEC.loader.exec_module(gen)


def inspect(prefix: bytes) -> dict:
    path_block_len = struct.unpack_from("<I", prefix, 0x5A)[0]
    path_end = 0x5E + path_block_len - 4
    table_start = path_end + 56
    return {
        "contents_len": struct.unpack_from("<I", prefix, 0x08)[0],
        "trailer": struct.unpack_from("<I", prefix, 0x1A)[0],
        "outer": struct.unpack_from("<I", prefix, 0x1E)[0],
        "major1": struct.unpack_from("<H", prefix, 0x22)[0],
        "major2": struct.unpack_from("<H", prefix, 0x24)[0],
        "path_end_minus4": struct.unpack_from("<I", prefix, 0x2C)[0],
        "mirror_len": struct.unpack_from("<I", prefix, 0x54)[0],
        "path_end": path_end,
        "trailer_mirror": struct.unpack_from("<I", prefix, path_end + 2)[0],
        "outer_mirror": struct.unpack_from("<I", prefix, path_end + 8)[0],
        "builds": tuple(
            struct.unpack_from("<I", prefix, path_end + off)[0]
            for off in (18, 24, 30, 36)
        ),
        "table_start": table_start,
        "table_hash": hashlib.sha256(prefix[table_start:]).hexdigest(),
    }


def main() -> int:
    base = gen.PrefixProfile(
        os_low16=0x000A,
        app_major=15,
        build0=5579,
        build1=5579,
        build2=5579,
        build3=5579,
        family_code=0x1A,
    )
    publisher_table_hash = hashlib.sha256(gen.build_table()).hexdigest()

    path_cases = ["A", "AB", "C:/x/a.pub", "C:/this/is/a/longer/path/document.pub"]
    for path in path_cases:
        prefix = gen.build_prefix(
            path=path,
            contents_len=9000,
            trailer_offset=7000,
            profile=base,
        )
        row = inspect(prefix)
        expected_path_end = 0x5E + len(path.encode("utf-16le")) + 2
        assert row["path_end"] == expected_path_end
        assert row["outer"] == expected_path_end + 40
        assert row["path_end_minus4"] == expected_path_end - 4
        assert row["table_start"] == expected_path_end + 56
        assert row["trailer_mirror"] == 7000
        assert row["outer_mirror"] == row["outer"]
        assert row["contents_len"] == row["mirror_len"] == 9000
        assert row["table_hash"] == publisher_table_hash

    perturbations = [
        ("contents_len", base, 12345, 7000),
        ("trailer", base, 9000, 8123),
        ("os", gen.PrefixProfile(0x0206, 15, 5579, 5579, 5579, 5579, 0x1A), 9000, 7000),
        ("major", gen.PrefixProfile(0x000A, 16, 5579, 5579, 5579, 5579, 0x1A), 9000, 7000),
        ("buildmix", gen.PrefixProfile(0x000A, 15, 4420, 5579, 4420, 5579, 0x1A), 9000, 7000),
        ("family", gen.PrefixProfile(0x000A, 15, 5579, 5579, 5579, 5579, 0x15), 9000, 7000),
    ]
    for _name, profile, contents_len, trailer_offset in perturbations:
        prefix = gen.build_prefix(
            path="C:/x/a.pub",
            contents_len=contents_len,
            trailer_offset=trailer_offset,
            profile=profile,
        )
        assert inspect(prefix)["table_hash"] == publisher_table_hash

    seed_profile = gen.PrefixProfile(
        0x0206, 12, 4518, 4518, 4518, 4518, 0x15, True
    )
    seed_prefix = gen.build_prefix(
        path="C:/x/a.pub",
        contents_len=9000,
        trailer_offset=7000,
        profile=seed_profile,
    )
    seed_hash = hashlib.sha256(gen.build_table(seed_entry139=True)).hexdigest()
    assert len(gen.build_table()) - len(gen.build_table(seed_entry139=True)) == 4
    assert inspect(seed_prefix)["table_hash"] == seed_hash

    print("PASS: 11 metamorphic cases")
    print("publisher_table_sha256", publisher_table_hash)
    print("seed_table_sha256", seed_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
