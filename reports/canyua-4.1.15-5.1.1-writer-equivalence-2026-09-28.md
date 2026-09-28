# Canyua 4.1.15 ↔ 5.1.1 writer equivalence — 2026-09-28

## Result

The native PUB writer carried by the admitted pre-PairIP Canyua 4.1.15 build is
machine-code/data equivalent to the writer in the retained Canyua 5.1.1 build,
apart from the ELF GNU Build ID note.

This materially upgrades the dynamic-oracle plan: 4.1.15 can be used as the
normally runnable historical runtime candidate while the existing 5.1.1
`libpubBuilder.so` static map remains directly applicable to the writer code.

## Compared artifacts

### Canyua 4.1.15

- admitted XAPK SHA-256:
  `693d5d322e46a0d68fa630d226a9a4a6aedb9382f4bc9bda8acd590c577522f1`
- package source: APKPure via `apkeep`, admitted by
  `experiments/inspect-canyua-package.py`
- writer:
  - path: `lib/arm64-v8a/libpubBuilder.so`
  - size: **1,232,024 bytes**
  - SHA-256:
    `0aff50700bd695794081cc3971f73389a6df6d76f0569876b85198e16b766ce6`
  - GNU Build ID:
    `fc13c4a3da68a40a9608bd1b1e27d5348fad0e77`

### Canyua 5.1.1

- retained Play-distributed package artifact from workflow run `36275409853`
- writer:
  - path: `lib/arm64-v8a/libpubBuilder.so`
  - size: **1,232,024 bytes**
  - SHA-256:
    `faf1f1dd61a71deb589b966388755bff0c3939ea9a68ff43720ac2bcc6744359`
  - GNU Build ID:
    `14e05a34311363b1361e2b69634d9f13eadceed8`

## Binary comparison

- file length: identical;
- unique defined dynamic symbol names: **2452 / 2452**;
- defined dynamic symbol set difference: **empty in both directions**;
- raw defined dynamic symbol table: **identical**;
- byte differences across the full 1,232,024-byte ELF: **20 bytes total**;
- first differing byte: zero-based offset **528**;
- differences occupy exactly the 20-byte GNU Build ID payload;
- bytes after that Build ID payload are identical through EOF.

Therefore the observed hash difference is explained by the ELF Build ID note,
not by a different writer implementation.

Representative exported API present in both builds includes:

- `MSPUBBuilder::Initialize`
- `MSPUBBuilder::BeginDocument`
- `MSPUBBuilder::BeginPage`
- `MSPUBBuilder::BeginMasterPage`
- `MSPUBBuilder::PushComponent`
- `MSPUBBuilder::SetText`
- `MSPUBBuilder::PushParagraph`
- `MSPUBBuilder::PushSpan`
- `MSPUBBuilder::SetCellStyle`
- `MSPUBBuilder::SetImageInfo`
- `MSPUBBuilder::SetShapeVertex`
- `MSPUBBuilder::SetShapeArrowStyle`
- `MSPUBBuilder::SetWordArtBaseInfo`
- `MSPUBBuilder::BuildStorageSteamNames`
- `MSPUBBuilder::Build`
- `MSPUBBuilder::Finalize`
- `Java_com_canyua_publisherexpert_EditActivity_createPub`
- `Java_com_canyua_publisherexpert_EditActivity_setRange`

## Seed equivalence

The four blank-document inputs used by the writer are also byte-identical
between 4.1.15 and 5.1.1.

| seed | SHA-256 in 4.1.15 and 5.1.1 |
|---|---|
| `Contents.dat` | `e7dbebcd244daaf172df5c209939543bbf574083749b4866d2240edcd2f1a0de` |
| `EscherStm.dat` | `bb5ea118ae3c30aff38c4dd5c635b6fbfd0c1f76ea196588b4b9a4aebaf7bfb5` |
| `QUILL_CONTENTS.dat` | `b3b034e3c67eb970b40d5b683b4f06f67acda2f7c92a0bca3f527d093cbef7a6` |
| `SummaryInformation.dat` | `c18cb860297f6facb1e6460ba6c0ed3880c061fe075e477f9b80d2896e9128a1` |

## Interpretation

For the tested ARM64 writer artifact and its four seed inputs, there is no
writer-code or seed-data drift between Canyua 4.1.15 and 5.1.1.

This does **not** prove the Java/UI purchase flow is identical across versions.
The dynamic oracle must still respect whatever entitlement gates 4.1.15 exposes.

It does mean that if 4.1.15 legitimately reaches `createPub`, the existing
5.1.1 native-writer reverse map is evidence about the exact native writer code
being invoked, not merely a similar later implementation.

## Boundary

- No PairIP, purchase, signature or license mechanism was bypassed.
- Comparison is between legitimately obtained package artifacts already admitted
  into the research pipeline.
- Writer behavior becomes Publisher-format evidence only after controlled output
  is correlated with independent Microsoft Publisher / Chaptera evidence.
