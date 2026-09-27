#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import struct
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("generate-pub2c-prechunk.py")
SPEC = importlib.util.spec_from_file_location("pub2c_prechunk", MODULE_PATH)
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)

EXPECTED_TABLE_SHA256 = "d21025e0e5324f0cf1312bff15d11ce7afa2e699ac5869e093a550b9e445fc81"


def path_end(path: str) -> int:
    return 0x5E + len(path.encode("utf-16le")) + 2


def table_start(path: str) -> int:
    return path_end(path) + 40 + 16


def split_entries(table: bytes) -> list[bytes]:
    assert table[:2] == bytes((0x03, 0x90))
    total = struct.unpack_from("<I", table, 2)[0]
    assert total == len(table) - 2
    rows: list[bytes] = []
    pos = 6
    while pos < len(table):
        assert table[pos : pos + 2] == bytes((0x00, 0x88))
        row_size = struct.unpack_from("<I", table, pos + 2)[0] + 2
        rows.append(table[pos : pos + row_size])
        pos += row_size
    assert pos == len(table)
    return rows


def build(
    *,
    path: str = r"C:\x.pub",
    contents_len: int = 10000,
    trailer_offset: int = 9000,
    os_low16: int = 0x0A00,
    app_major: int = 16,
    builds: tuple[int, int, int, int] = (1, 2, 3, 4),
    family_code: int = 0x1A,
    seed_entry139: bool = False,
) -> bytes:
    profile = m.PrefixProfile(
        os_low16=os_low16,
        app_major=app_major,
        build0=builds[0],
        build1=builds[1],
        build2=builds[2],
        build3=builds[3],
        family_code=family_code,
        seed_entry139=seed_entry139,
    )
    return m.build_prefix(
        path=path,
        contents_len=contents_len,
        trailer_offset=trailer_offset,
        profile=profile,
    )


def blank_ranges(data: bytes, ranges: list[tuple[int, int]]) -> bytes:
    out = bytearray(data)
    for start, end in ranges:
        out[start:end] = b"\x00" * (end - start)
    return bytes(out)


class PrechunkMetamorphicTests(unittest.TestCase):
    def test_fixed_table_shape_and_hash(self) -> None:
        table = m.build_table()
        self.assertEqual(len(table), 3906)
        self.assertEqual(hashlib.sha256(table).hexdigest(), EXPECTED_TABLE_SHA256)
        rows = split_entries(table)
        self.assertEqual(len(rows), 143)
        for i, row in enumerate(rows, 1):
            self.assertEqual(struct.unpack_from("<H", row, 8)[0], i)

    def test_canyua_seed_variant_is_only_entry_139(self) -> None:
        normal = split_entries(m.build_table())
        seed = split_entries(m.build_table(seed_entry139=True))
        self.assertEqual(len(normal), 143)
        self.assertEqual(len(seed), 143)
        changed = [i + 1 for i, (a, b) in enumerate(zip(normal, seed)) if a != b]
        self.assertEqual(changed, [139])
        self.assertEqual(len(normal[138]) - len(seed[138]), 4)
        self.assertEqual(len(m.build_table(seed_entry139=True)), 3902)

    def test_path_length_moves_structure_but_not_table(self) -> None:
        short_path = r"C:\a.pub"
        long_path = r"C:\nested\folder\much-longer-name.pub"
        a = build(path=short_path)
        b = build(path=long_path)
        tsa, tsb = table_start(short_path), table_start(long_path)

        self.assertEqual(a[tsa:], b[tsb:])
        self.assertEqual(struct.unpack_from("<I", a, 0x1E)[0], path_end(short_path) + 40)
        self.assertEqual(struct.unpack_from("<I", b, 0x1E)[0], path_end(long_path) + 40)
        self.assertEqual(struct.unpack_from("<I", a, 0x2C)[0], path_end(short_path) - 4)
        self.assertEqual(struct.unpack_from("<I", b, 0x2C)[0], path_end(long_path) - 4)
        self.assertEqual(len(b) - len(a), len(long_path.encode("utf-16le")) - len(short_path.encode("utf-16le")))

    def test_contents_len_has_exactly_two_storage_sites(self) -> None:
        a = build(contents_len=10000)
        b = build(contents_len=12345)
        self.assertNotEqual(a, b)
        self.assertEqual(
            blank_ranges(a, [(0x08, 0x0C), (0x54, 0x58)]),
            blank_ranges(b, [(0x08, 0x0C), (0x54, 0x58)]),
        )
        self.assertEqual(struct.unpack_from("<I", b, 0x08)[0], 12345)
        self.assertEqual(struct.unpack_from("<I", b, 0x54)[0], 12345)

    def test_trailer_offset_has_exactly_two_storage_sites(self) -> None:
        p = r"C:\x.pub"
        pe = path_end(p)
        a = build(path=p, trailer_offset=9000)
        b = build(path=p, trailer_offset=9999)
        self.assertEqual(
            blank_ranges(a, [(0x1A, 0x1E), (pe + 2, pe + 6)]),
            blank_ranges(b, [(0x1A, 0x1E), (pe + 2, pe + 6)]),
        )
        self.assertEqual(struct.unpack_from("<I", b, 0x1A)[0], 9999)
        self.assertEqual(struct.unpack_from("<I", b, pe + 2)[0], 9999)

    def test_each_build_provenance_word_is_local(self) -> None:
        p = r"C:\x.pub"
        pe = path_end(p)
        base = build(path=p, builds=(1, 2, 3, 4))
        sites = [pe + 18, pe + 24, pe + 30, pe + 36]
        for idx, site in enumerate(sites):
            vals = [1, 2, 3, 4]
            vals[idx] = 0x11223344 + idx
            mutated = build(path=p, builds=tuple(vals))
            self.assertEqual(
                blank_ranges(base, [(site, site + 4)]),
                blank_ranges(mutated, [(site, site + 4)]),
            )
            self.assertEqual(struct.unpack_from("<I", mutated, site)[0], vals[idx])

    def test_family_code_never_changes_fixed_table(self) -> None:
        p = r"C:\x.pub"
        a = build(path=p, family_code=0x1A)
        b = build(path=p, family_code=0x1B)
        ts = table_start(p)
        self.assertEqual(a[ts:], b[ts:])
        self.assertNotEqual(a[:ts], b[:ts])

    def test_layout_invariants_over_deterministic_matrix(self) -> None:
        paths = [
            r"C:\x.pub",
            r"D:\folder\blank.pub",
            r"C:\очень-длинный-путь\пример.pub",
            r"Z:\資料\publisher.pub",
        ]
        lengths = [4224, 9390, 10000, 65535, 100000]
        trailers = [0, 1, 4096, 8191, 9000]
        majors = [11, 14, 16]

        cases = 0
        for i in range(36):
            p = paths[i % len(paths)]
            clen = lengths[(i * 3) % len(lengths)]
            trailer = trailers[(i * 2) % len(trailers)]
            major = majors[i % len(majors)]
            family = 0x1A + (i % 2)
            builds = (0x1000 + i, 0x2000 + i, 0x3000 + i, 0x4000 + i)
            data = build(
                path=p,
                contents_len=clen,
                trailer_offset=trailer,
                app_major=major,
                builds=builds,
                family_code=family,
            )

            pe = path_end(p)
            outer = pe + 40
            ts = outer + 16
            encoded = p.encode("utf-16le") + b"\x00\x00"

            self.assertEqual(data[:2], struct.pack("<H", 0xACE8))
            self.assertEqual(data[2], 0x2C)
            self.assertEqual(struct.unpack_from("<I", data, 0x08)[0], clen)
            self.assertEqual(struct.unpack_from("<I", data, 0x1A)[0], trailer)
            self.assertEqual(struct.unpack_from("<I", data, 0x1E)[0], outer)
            self.assertEqual(struct.unpack_from("<H", data, 0x22)[0], major)
            self.assertEqual(struct.unpack_from("<H", data, 0x24)[0], major)
            self.assertEqual(struct.unpack_from("<I", data, 0x2C)[0], pe - 4)
            self.assertEqual(data[0x5E:pe], encoded)
            self.assertEqual(struct.unpack_from("<I", data, pe + 8)[0], outer)
            self.assertEqual(struct.unpack_from("<I", data, outer)[0], len(m.build_table()) + 16)
            self.assertEqual(struct.unpack_from("<I", data, outer + 6)[0], 143)
            self.assertEqual(data[ts:], m.build_table())
            self.assertEqual(len(data), ts + 3906)
            cases += 1

        self.assertEqual(cases, 36)


if __name__ == "__main__":
    unittest.main(verbosity=2)
