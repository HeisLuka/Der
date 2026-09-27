# Canyua Publisher 2013 template corpus map — 2026-09-27

## Scope

Cross-corpus physical analysis of the 252 Microsoft Publisher `.pub` templates
bundled by Canyua under:

`assets/Publisher Templates/2013/BUILT-IN/`

The source package is the already preserved Canyua 5.1.1 package artifact used
by the Android competitor teardown.

Analysis implementation:

- `experiments/analyze-canyua-template-corpus.py`
- workflow: `.github/workflows/canyua-template-corpus.yml`
- final evidence run: GitHub Actions run `36306742403`
- artifact: `canyua-publisher-template-corpus-analysis`, id `10927491863`

This is physical/corpus evidence. It does not by itself assign semantic meaning
to unknown Publisher fields.

## Corpus integrity

All 252 bundled `.pub` files parse as OLE/CFB.

Observed:

- templates: **252**
- parsed: **252 / 252**
- exact duplicate PUB files: **0**
- distinct stream paths across the corpus: **10**
- distinct stream-set signatures: **1**

Therefore every tested template has the same logical stream topology.

## Exact stream topology

The following 10 stream paths occur in **252 / 252** templates:

```text
/\x01CompObj
/\x03Internal
/\x05DocumentSummaryInformation
/\x05SummaryInformation
/Contents
/Envelope
/Escher/EscherDelayStm
/Escher/EscherStm
/Quill/QuillSub/\x01CompObj
/Quill/QuillSub/CONTENTS
```

Important correction to earlier shorthand: the observed Quill data stream in
this corpus is:

`/Quill/QuillSub/CONTENTS`

not `/Quill/CONTENTS`.

The static `poleHelperCreate(12, ...)` observation must **not** be interpreted
as evidence that the final PUB contains 12 streams. The controlled corpus shows
10 stream paths; the internal builder count and the CFB stream count are
different facts.

## Stream diversity

| Family | Count | Min bytes | Median bytes | Max bytes | Unique hashes |
|---|---:|---:|---:|---:|---:|
| Contents | 252 | 11,080 | 15,269 | 47,086 | 252 |
| Quill/QuillSub/CONTENTS | 252 | 6,144 | 15,872 | 57,344 | 252 |
| EscherStm | 252 | 4,408 | 20,055 | 148,894 | 251 |
| EscherDelayStm | 252 | 0 | 1,059.5 | 188,613 | 124 |
| SummaryInformation | 252 | 33,548 | 50,900 | 50,900 | 252 |
| DocumentSummaryInformation | 252 | 152 | 152 | 152 | 2 |

Two particularly useful invariants:

1. `Contents` and Quill are unique in every template despite the identical
   stream topology.
2. `DocumentSummaryInformation` is nearly invariant: **251 / 252** templates
   share one exact 152-byte stream hash.

`EscherDelayStm` is much less diverse than the main Escher stream: only 124
unique hashes for 252 files, including repeated clusters and 11 empty streams.

## Seed-to-real-stream comparison

The APK's blank-document seed bundle contains:

| Seed | Bytes | Expected real stream |
|---|---:|---|
| `Contents.dat` | 9,314 | `/Contents` |
| `QUILL_CONTENTS.dat` | 2,048 | `/Quill/QuillSub/CONTENTS` |
| `EscherStm.dat` | 972 | `/Escher/EscherStm` |
| `SummaryInformation.dat` | 44,640 | `/\x05SummaryInformation` |

No full seed is byte-identical to a complete corresponding stream in any of the
252 templates. Whole-stream equality is therefore the wrong model.

### Contents: strong reusable scaffold

This is the strongest result.

For **all 252 / 252** templates, the exact seed slice:

```text
Contents.dat
seed offset: 0x100
length:      0xE80 = 3712 bytes
end:         0xF80
SHA-256:     27ffd0f6f810d57b62c844c4bb37442ef6d3c4de8655bde5e65d780cb6f27441
```

appears as one **contiguous exact-byte run** inside the real `/Contents`
stream.

The target offset varies by document. Common observed actual starts include
`0x150` (18 files), `0x142` (15), `0x162` (14), `0x152` (13) and
`0x15E` (13), among many others.

This means the stable bytes are not merely in a fixed absolute location. A
variable-sized prefix precedes a reusable 3712-byte physical scaffold.

A 64-byte block scan gives:

- minimum seed-block hit rate: **65.52%**
- median: **71.03%**
- maximum: **72.41%**
- longest same-delta exact run: **3712 bytes in every template**

The contiguous-run result is much stronger than the percentage alone.

### Escher: small universal structural slice

For **252 / 252** templates, the longest same-delta seed run is exactly:

```text
EscherStm.dat
seed offset: 0x300
length:      0x80 = 128 bytes
SHA-256:     a92a58689d9b53733367516274b3395f8993551794200f2acfe8e9c210225635
```

The target offset varies substantially by document.

The bytes sit inside ordinary OfficeArt/Escher record structure, including
record headers in the `0xF002 / 0xF003 / 0xF004` family. This is compatible
with a small reusable OfficeArt scaffold, but the result is much weaker than
the Contents finding.

The 64-byte block hit rate is exactly **20%** for all 252 templates.

### Quill: partial reusable regions, not one universal long scaffold

Quill shows two dominant seed anchors for each template's longest exact run:

- seed offset `0x100`: **173 / 252**
- seed offset `0x240`: **79 / 252**

Longest exact same-delta run:

- minimum: 64 bytes
- median: 64 bytes
- maximum: **384 bytes**

64-byte seed-block hit rate:

- minimum: **18.75%**
- median: **21.88%**
- maximum: **40.62%**

The strongest 384-byte run starts at `QUILL_CONTENTS.dat + 0x240`.

This supports partial Quill template reuse, but not a claim that most Quill
bytes are copied unchanged.

### SummaryInformation: high scattered overlap, weak contiguous evidence

A naive 64-byte block scan finds a high overlap:

- minimum: **76.61%**
- median: **81.64%**
- maximum: **81.78%**

However the longest same-delta exact run is only **64 bytes** in every
template. It is always:

```text
seed start:   0x140
actual start: 0x102
delta:        -62
length:       64
```

Therefore the high block-hit percentage must not be interpreted as “~80% of
SummaryInformation.dat is copied as one tail”. Repeated/common blocks can
inflate relocation-insensitive matching.

This matters because static analysis found a method named
`SetSummaryTail`. The method name plus scattered corpus overlap is suggestive,
but the exact writer policy still requires dynamic Canyua output.

## Contents 0x2C: universal pre-chunk table

A structural pass over the same 252 `/Contents` streams sharpens the
3712-byte scaffold result considerably.

Using the public libmspub physical block framing rules for the 0x2C family,
every analyzed file has the same high-level relationship:

```text
Contents header / prelude
        |
        +-- id=0x03, type=0x90 variable container
        |      |
        |      +-- 143 x type=0x88 GeneralContainer entries
        |             internal id=0x01/type=0x18 values: 1..143
        |
        +-- container end == first referenced content-chunk offset
               |
               v
          generated/document chunks
               |
               v
          trailer / chunk-reference directory
```

Corpus invariants:

- analyzable as this 0x2C structure: **252 / 252**;
- final pre-chunk block is the table above: **252 / 252**;
- that table ends exactly at the first content chunk: **252 / 252**;
- child count is exactly **143** in every file;
- the child containers use the sequential inner index `1..143` with no
  gaps: **252 / 252**;
- the universal 3712-byte scaffold is inside this table: **252 / 252**;
- its start is always exactly **14 bytes after the table start**.

The seed therefore has:

```text
table start:     0x00F2
scaffold start:  0x0100
delta:           0x000E
scaffold end:    0x0F80
table end:       0x1030
first chunk:     0x1030
```

The target absolute offsets move between real templates, but these internal
relationships do not.

The 143 entries are highly regular. In the seed, each one is a
`type=0x88` container and its `id=0x01/type=0x18` value is the exact
1-based entry number. Other recurring physical fields use only a small number
of schemas and values. This is strong evidence for a fixed indexed preset /
default table, but **the semantic name of the table remains unassigned** until
independent evidence identifies what those 143 entries represent.

### Writer-side consequence

Static disassembly of `libpubBuilder.so` independently shows why this table
survives.

`MSPUB::Contents::BeginDocument` reads the seed trailer directory and keeps
the first referenced `CHUNK_OFFSET`. For the bundled blank seed that offset
is `0x1030`.

`MSPUB::Contents::Build` copies the template bytes up to that first-chunk
boundary, performs targeted early-header patching through `BuildHead`, then
seeks to the first-chunk offset and emits rebuilt content chunks and a rebuilt
chunk-reference/trailer area.

The observed `BuildHead` writes are in the early header, before the universal
table scaffold. Therefore the `0x100:0xF80` scaffold is not merely
byte-similar to writer output: in this writer profile it lies in the explicit
template-copy region and outside the observed patch coordinates.

This is the strongest current evidence for **template-seeded Contents
construction**.

## Entry-level variability: the table is fully corpus-invariant

A dedicated per-entry pass over all 143 table entries across all 252 templates
produced a stronger result than the earlier 3712-byte window.

Evidence workflow:

- `.github/workflows/canyua-prechunk-table.yml`
- analyzer: `experiments/analyze-canyua-prechunk-table.py`
- successful run: `36307392333`
- artifact: `canyua-contents-prechunk-variability` / `10927352588`

Result:

- **143 / 143 entries are byte-invariant across all 252 Publisher templates**;
- **142 / 143 entries are also byte-identical to the Canyua blank
  `Contents.dat` seed**;
- the only seed-vs-corpus difference is **entry 139**;
- there are **zero document-dependent entry variants** in this table.

Exact seed-identical entry ranges:

```text
1-138
140-143
```

### Entry 139: the only seed-profile difference

The seed entry is 28 bytes. The corresponding entry in all 252 Publisher 2013
templates is 32 bytes.

Fields shared by both forms:

```text
id=0x01 type=0x18 value=139
id=0x03 type=0x20 value=65536020
id=0x08 type=0x08
id=0x09 type=0x10 value=1
id=0x0C type=0x20 value=5
```

The Publisher-template corpus form contains two additional zero-length blocks
before `id=0x08`:

```text
id=0x06 type=0x08
id=0x07 type=0x08
```

So the physical difference is exactly four bytes of block headers:

```text
seed profile:
  01/18, 03/20,         08/08, 09/10, 0C/20

252-template profile:
  01/18, 03/20, 06/08, 07/08, 08/08, 09/10, 0C/20
```

No semantic meaning is assigned to the two flags yet.

### Independent Publisher corpus cross-check

The entry-139 discriminator was checked against a second, unrelated public
Publisher corpus from GemeindebriefDruckerei rather than relying only on files
bundled inside Canyua.

Evidence:

- workflow: `.github/workflows/canyua-entry139-independent-corpus.yml`
- successful run: `36307630024`
- artifact: `canyua-entry139-independent-corpus` / `10927962184`
- samples: A001-A007 and A014 public Microsoft Publisher templates;
- source PUB bytes were used transiently by CI and were **not** retained in the
  evidence artifact.

Result:

```text
independent samples: 8
publisher2013_template_profile: 8 / 8
canyua_blank_seed_profile:      0 / 8
unknown:                        0 / 8
```

All eight independent files have the same 32-byte entry-139 form and exact
entry hash observed in the 252 Canyua-bundled Publisher templates:

`0331ff885069ee3401aa0aca44409483fcdc3c4a9f3a8beab0b776b0c72aa9ae`

This does not prove that the 28-byte seed form is globally unique to Canyua,
but it materially weakens the alternative explanation that it is simply a
common Publisher 2010+ document variant.

### Consequence for the Canyua writer fingerprint

The static writer path copies the pre-content-chunk seed region and the
observed `BuildHead` patches are confined to the early header, not entry 139.
Therefore the current evidence predicts that a PUB newly emitted by this
Canyua writer should retain the **28-byte seed form of entry 139**, while every
one of the 252 bundled Publisher 2013 templates carries the **32-byte form**.

This is a **candidate behavioral fingerprint**, not yet a dynamic fact. It
becomes confirmed only when a legitimately produced Canyua output is captured
and inspected.

The useful point is that the dynamic test no longer needs to begin with a
whole-file diff: entry 139 gives a precise first discriminator to check.

## What this changes in the writer model

Before this corpus pass, template seeding was established from the writer API
and JNI call graph:

```text
SetContentsTemplate
SetEscherTemplate
SetQuillTemplate
SetSummaryTail
    -> Build(..., 0xF)
```

The corpus now adds independent byte-level evidence:

```text
seed files
   |
   +-- Contents.dat
   |      exact 3712-byte scaffold survives in 252/252 real templates
   |
   +-- QUILL_CONTENTS.dat
   |      smaller partial exact regions survive
   |
   +-- EscherStm.dat
   |      128-byte structural slice survives in 252/252
   |
   +-- SummaryInformation.dat
          many scattered blocks match, but no long contiguous run
```

The best current model is therefore not “copy a blank PUB and patch a few
bytes”, and not “generate every stream from zero”.

It is closer to:

```text
stable physical scaffold(s)
        +
document-specific generated prefixes / records / payloads
        +
relocated or rewritten stream regions
        +
CFB assembly
        =
output PUB
```

The exact partition differs by stream family.

## High-value next experiments

1. **Decode `Contents.dat[0x100:0xF80]` structurally**
   - identify record/chunk boundaries inside the universal 3712-byte scaffold;
   - map which fields are invariant and which references point outside it.

2. **Controlled dynamic writer oracle**
   - resave-control first;
   - then one semantic mutation per arm;
   - compare against resave-control with `experiments/diff-pub-cfb.py`.

3. **Generated blank output vs seed bundle**
   - this remains the cleanest way to distinguish copied scaffolding from
     builder-generated equivalents.

4. **Cross-version corpus comparison**
   - compare Publisher 98/2000/2002/2003/current files with the same physical
     scaffold fingerprints;
   - do not assume the Publisher 2013 template result is universal.

## Claim boundary

Confirmed for the 252 bundled Publisher 2013 templates:

- identical 10-stream topology;
- exact observed Quill path;
- the 3712-byte Contents seed scaffold survives in all 252;
- the 128-byte Escher slice survives in all 252;
- smaller Quill seed regions survive;
- Summary has high scattered overlap but only a 64-byte contiguous run.

Not confirmed yet:

- that Canyua's current writer emits exactly this 2013 profile;
- that Microsoft Publisher itself uses these seed files;
- semantic meaning of the universal Contents slice;
- whether Canyua copies the slice or independently regenerates byte-identical
  structures from the seed-backed builder state.
