# Canyua libpubBuilder static map — 2026-09-27

## Scope and boundary

Static interoperability/provenance analysis of the Android binary `libpubBuilder.so` shipped in `com.canyua.publisherexpert` 5.1.1.

This note records observable architecture, symbol taxonomy, stream layout and behavior. It does not reproduce proprietary implementation code.

Artifact:

- file: `libpubBuilder.so`
- ARM64 size: 1,232,024 bytes
- SHA-256: `faf1f1dd61a71deb589b966388755bff0c3939ea9a68ff43720ac2bcc6744359`
- Android target: 28
- toolchain marker: Android NDK r20b / clang 8 era
- stripped ELF, but substantial dynamic C++ symbols remain exported
- 2,750 defined dynamic symbols
- JNI exports:
  - `Java_com_canyua_publisherexpert_EditActivity_createPub`
  - `Java_com_canyua_publisherexpert_EditActivity_setRange`

## High-level conclusion

The library is a real native Microsoft Publisher writer/builder.

Its architecture is **template-seeded stream synthesis + explicit CFB/OLE assembly**, not a server conversion wrapper.

The Android `createPub` JNI path:

1. initializes `MSPUBBuilder`;
2. obtains four blank-document seed files;
3. passes seeds into Contents / Escher / Quill / Summary builders;
4. constructs document/page/component state;
5. ends the document;
6. calls `MSPUBBuilder::Build(..., BUILDTYPE=0xF)`;
7. builds all enabled Publisher stream families;
8. constructs a Compound File Binary container through a POLE-based helper;
9. finalizes the builder.

## Seed data embedded in the APK

The base APK contains a dedicated blank-page seed bundle:

`assets/Publisher Data/Publication Types/Blank Page Sizes/Standard/New Page Size/`

| Seed | Size | SHA-256 |
|---|---:|---|
| `Contents.dat` | 9,314 B | `e7dbebcd244daaf172df5c209939543bbf574083749b4866d2240edcd2f1a0de` |
| `EscherStm.dat` | 972 B | `bb5ea118ae3c30aff38c4dd5c635b6fbfd0c1f76ea196588b4b9a4aebaf7bfb5` |
| `QUILL_CONTENTS.dat` | 2,048 B | `b3b034e3c67eb970b40d5b683b4f06f67acda2f7c92a0bca3f527d093cbef7a6` |
| `SummaryInformation.dat` | 44,640 B | `c18cb860297f6facb1e6460ba6c0ed3880c061fe075e477f9b80d2896e9128a1` |

The JNI `createPub` routine has direct literal references to all four names and calls:

- `MSPUBBuilder::SetContentsTemplate`
- `MSPUBBuilder::SetEscherTemplate`
- `MSPUBBuilder::SetQuillTemplate`
- `MSPUBBuilder::SetSummaryTail`

This confirms template seeding rather than merely suggesting it from filenames.

## Builder public surface

Key `MSPUBBuilder` operations:

### Document/page lifecycle

- `Initialize`
- `BeginDocument`
- `EndDocument`
- `BeginPage`
- `EndPage`
- `BeginMasterPage`
- `EndMasterPage`
- `Finalize`

### Semantic content

- `PushComponent`
- `SetText`
- `PushParagraph`
- `PushSpan`
- `SetCellStyle`
- `SetImageInfo`
- `SetShapeVertex`
- `SetShapeArrowStyle`
- `SetWordArtBaseInfo`
- `ComponentStyle`

### Seed / persistence

- `SetContentsTemplate`
- `SetEscherTemplate`
- `SetQuillTemplate`
- `SetSummaryTail`
- `BuildStorageSteamNames`
- `Build`

## Build bitmask recovered

Disassembly of:

`MSPUBBuilder::Build(char const*, char const*, MSPUBBuilder::BUILDTYPE)`

shows the `BUILDTYPE` argument is tested as bit flags:

| Bit | Mask | Conditional build |
|---|---:|---|
| 0 | `0x1` | `MSPUB::Contents::Build` |
| 1 | `0x2` | `MSPUB::Escher::Build` |
| 2 | `0x4` | `MSPUB::Quill::Build` |
| 3 | `0x8` | `MSPUB::DocumentSummaryInformation::Build` and `MSPUB::SummaryInformation::Build` |

The Android `createPub` path calls `Build(..., 0xF)`, enabling all four families.

Some storage elements are built regardless of those bits, including CompObj / Envelope / Internal scaffolding.

## Compound File assembly

The binary embeds and uses POLE-style Compound File structures:

- `POLE::StorageIO`
- `POLE::DirTree`
- `POLE::AllocTable`

The final builder path invokes a helper equivalent to:

`poleHelperCreate(12, streamPaths, outputFile)`

Observed storage/stream names include:

- control-character-prefixed `CompObj`
- `Contents`
- control-character-prefixed `DocumentSummaryInformation`
- `Envelope`
- control-character-prefixed `Internal`
- `Escher`
- `EscherDelayStm`
- `EscherStm`
- `Quill`
- `QuillSub`
- `CONTENTS`
- control-character-prefixed `SummaryInformation`

This is a direct native CFB/PUB construction path rather than “export to some other format and rename”.

## Contents implementation

`MSPUB::Contents` exposes 81 dynamic symbols, including:

- `CreateContentChunk`
- `CreateChunkReference`
- `FillContentChunks`
- `FillDocumentChunk`
- `CalculateContentChunkOffset`
- `BuildChunkReference`
- `Fill4BChunk`
- `Fill4CChunk`
- `Fill8AChunk`
- `Fill61Buffer`
- `Fill65Buffer`
- `FillFontBuffer`
- `FillTableBuffer`
- `AddText`
- `AddImage`
- `AddShape`
- `AddTable`
- `AddWordArt`
- `AddBackground`
- `AddComponentInPageChunkContent`
- `AddBackgroundInPageChunkContent`

This maps strongly onto the Chaptera model of structured Contents records/chunks and cross-stream identity references.

A second `MSPUB::CONTENTS` implementation surface exposes 59 symbols and includes Quill-ish/content-model operations such as:

- `CreateBTEC`
- `CreateBTEP`
- `CreateFDPC`
- `CreateFDPP`
- `CreateMCLD`
- `CreateSTRS`
- `CreateTCD`
- `FillFONT`
- `FillPL`
- `FillSYID`
- `FillSTSH`-related structures observable in seed data

## Quill

`MSPUB::Quill` directly exposes:

- `SetTemplate`
- `SetText`
- `PushParagraph`
- `PushSpan`
- `Build`

The blank Quill seed contains markers such as `Quill96 Story Group Class`, `FONT`, `STSH`, `SYID`, and other familiar Quill structures.

## Escher

Separate classes exist for:

- `MSPUB::Escher`
- `MSPUB::EscherStm`
- `MSPUB::EscherDelayStm`

Relevant operations include:

- `BuildDg`
- `BuildBackgroundContainer`
- `BuildTableStyleContainer`
- `UnbuildDg`
- `Push`
- image placement/delay-stream indexing
- shape vertices and segment actions
- arrow styles/sizes
- WordArt base information

## Tables and structured objects

The writer is not text-only.

`MSPUB::Table` includes:

- row/column metrics;
- cell text and style;
- cell merge state;
- border index/colors/widths;
- split horizontal/vertical border information;
- table presets/types.

Other explicit object families:

- Text
- Image
- Shape
- WordArt
- Background
- Picture
- Component
- Table
- MergedCell

## Exact output generation remains open

The binary contains `Microsoft Publisher 3.0` and `Quill96 Story Group Class` strings, but those are not enough to label the emitted file as a specific modern Publisher release.

The APK separately bundles 252 actual `.pub` templates under:

`assets/Publisher Templates/2013/BUILT-IN/...`

This proves the application ships a Publisher 2013 template corpus, but it does **not by itself prove** the writer's native Save target generation.

The correct discriminator is dynamic:

1. create a minimal new document in the app;
2. save it as PUB;
3. fingerprint its stream/version/record profile;
4. reopen it in Microsoft Publisher and Chaptera;
5. perform controlled one-feature edits and binary-diff each output.

## Cross-check against the bundled Publisher 2013 corpus

The 252 bundled `.pub` templates were parsed as a separate corpus after this
static map was written. See:

`reports/canyua-publisher2013-template-corpus-map-2026-09-27.md`

The corpus materially sharpens two parts of the static model:

- all **252 / 252** templates expose one identical topology of **10 stream
  paths**; therefore the `poleHelperCreate(12, ...)` argument must not be
  described as “12 output streams”;
- the observed Quill data path is
  `/Quill/QuillSub/CONTENTS`, not the earlier shorthand
  `/Quill/CONTENTS`.

Most importantly, the seed relationship now has independent byte-level
evidence. The exact `Contents.dat[0x100:0xF80]` slice — **3712 bytes** —
occurs contiguously in the real `/Contents` stream of every one of the 252
templates, at document-dependent target offsets. Its SHA-256 is
`27ffd0f6f810d57b62c844c4bb37442ef6d3c4de8655bde5e65d780cb6f27441`.

Smaller exact reusable slices also occur in Escher and Quill. SummaryInformation
has high scattered 64-byte block overlap but only a 64-byte contiguous run, so
the static `SetSummaryTail` name is still not enough to claim a whole copied
tail.

This strengthens the model from “the writer accepts seed files” to “at least
one large seed-derived physical scaffold is independently observable across a
large real-PUB corpus”, while still leaving the exact current Canyua writer
policy to the dynamic oracle experiment.

## APK size: reader engine vs product baggage

Canyua's large APK should not be interpreted as the minimum size for a local mobile PUB reader.

Base APK contents include approximately:

- 530 bundled font files: **185.96 MiB raw / 106.26 MiB compressed**
- Publisher Templates: **59.60 MiB raw / 35.55 MiB compressed**
- manuals: **27.05 MiB raw / 23.66 MiB compressed**
- Publisher blank seed data: **1.12 MiB raw / 0.07 MiB compressed**

ARM64 native engines:

- `libmspubCore.so`: **35.01 MiB**
- `libpdfCore.so`: **4.59 MiB**
- `libpubBuilder.so`: **1.17 MiB**
- `libopenXmlCore.so`: **0.94 MiB**

A Chaptera read-only mobile viewer would not need the Canyua writer, OpenXML/PDF authoring engines, 252 PUB templates, 252 PDF previews, manuals or a huge bundled font corpus.

## Product/security implication

Canyua is direct evidence for both sides of the Chaptera mobile decision:

1. **Local PUB parsing on Android is practical.**
2. **Native binaries are inspectable.**

Even with stripped ELF files, exported symbols were enough to identify:

- libmspub/librevenge provenance;
- the local reader architecture;
- the existence and broad design of the writer;
- stream families;
- seed strategy;
- CFB construction;
- semantic object coverage.

Therefore Chaptera should assume its local engine architecture will be discoverable and make defensibility come from corpus coverage, fidelity, diagnostics, performance and accumulated edge-case behavior rather than secrecy.

## Next interoperability experiment

Highest-value next experiment:

`blank seed -> Canyua create/save -> Chaptera parse -> Publisher reopen -> controlled edit -> save -> stream/record diff`

This would answer the remaining questions static inspection cannot:

- actual emitted Publisher generation;
- exact template preservation policy;
- which streams are rebuilt vs copied;
- identity allocation policy;
- whether unknown records survive edits;
- native Save round-trip fidelity across text/image/shape/table/master-page cases.
