# Android Microsoft Publisher competitor teardown — 2026-09-27

## Scope

Static analysis of Android apps that open or convert Microsoft Publisher `.pub` files.

Targets:

| App | Package | Observed model |
|---|---|---|
| Publisher: for MS Office | `com.canyua.publisherexpert` | **Local parser + local editor/writer** |
| PUB File Viewer and Converter | `com.vdprime.pubviewerandconverter` | **Server conversion -> local PDF preview** |
| PUB to PDF Converter | `smartapps38.convert.publisher.topdf.pubtopdf` | **Server conversion** |
| PUB to PDF Converter | `com.daemon.publishertopdfconverter` | **Server conversion** |

Method: APK/XAPK download through GitHub Actions, split selection, JADX static inspection, native library inventory, ELF symbol/string inspection. This is static evidence only; it does not replace behavioral testing on a device/emulator.

## 1. Canyua Publisher — the important result

Package inspected:

- package: `com.canyua.publisherexpert`
- versionCode: `242`
- versionName: `5.1.1`
- base APK: ~181.96 MB
- ARM64 split: ~43.84 MB

### Native architecture

ARM64 split contains:

| Library | Size | Exported symbols | Role |
|---|---:|---:|---|
| `libmspubCore.so` | 36,713,696 B | 6,258 | PUB reader/parser + drawing bridge |
| `libpubBuilder.so` | 1,232,024 B | 2,750 | PUB writer/builder |
| `libopenXmlCore.so` | 986,144 B | 2,195 | Word/PowerPoint OpenXML export |
| `libpdfCore.so` | 4,814,648 B | 8,760 | PDF export/edit support |

Hashes:

- `libmspubCore.so`: `d41acfe29013e5d2a400db85e47fcd31bd910f79aec9e0b8f368f9c6869aa60b`
- `libopenXmlCore.so`: `28f4ec4125585aca599feacc9cbf99b33061c473da1d28ebff101500219ff749`
- `libpdfCore.so`: `cfeefecdb4858deda230a4155dae3cf0ee187feea0d3301501408ac251c98e5d`
- `libpubBuilder.so`: `faf1f1dd61a71deb589b966388755bff0c3939ea9a68ff43720ac2bcc6744359`

All four were built for Android 28 using NDK r20b and are stripped.

### Reader provenance

`libmspubCore.so` unmistakably embeds the LibreOffice/libmspub family:

- `libmspub::MSPUBDocument::isSupported`
- `libmspub::MSPUBDocument::parse`
- large `libmspub::MSPUBCollector` surface
- `librevenge::RVNGInputStream`
- `librevenge::RVNGDrawingInterface`
- `librevenge::RVNGPropertyList`
- `librevenge::RVNGString`

JNI surface includes:

- `Java_com_canyua_publisherexpert_MainActivity_pubCoreInit`
- `Java_com_canyua_publisherexpert_MainActivity_pubCoreParse`
- `Java_com_canyua_publisherexpert_MainActivity_pubCoreUninit`
- `Java_com_canyua_publisherexpert_MainActivity_convertEmfInSvg`
- `Java_com_canyua_publisherexpert_EditActivity_parseSvg`

The Java UI contains a source-neutral-ish application model with classes such as:

- `MspubPage`
- `MspubParagraph`
- `MspubSpan`
- `MspubUtil`
- multiple custom `CSObject` / text / image / fill / border classes

Interpretation: `libmspub` is used as the low-level Publisher parser, while a custom `DrawingGenerator` bridge converts librevenge callbacks into Canyua's editable/renderable model.

### Writer — likely proprietary and much more interesting

`libpubBuilder.so` does not look like public libmspub. It exposes a substantial independent writer model:

- `MSPUBBuilder::Initialize`
- `MSPUBBuilder::BeginDocument`
- `MSPUBBuilder::EndDocument`
- `MSPUBBuilder::BeginPage`
- `MSPUBBuilder::EndPage`
- `MSPUBBuilder::BeginMasterPage`
- `MSPUBBuilder::SetText`
- `MSPUBBuilder::PushParagraph`
- `MSPUBBuilder::PushSpan`
- `MSPUBBuilder::PushComponent`
- `MSPUBBuilder::SetCellStyle`
- `MSPUBBuilder::SetImageInfo`
- `MSPUBBuilder::SetShapeVertex`
- `MSPUBBuilder::SetShapeArrowStyle`
- `MSPUBBuilder::SetWordArtBaseInfo`
- `MSPUBBuilder::BuildStorageSteamNames`
- `MSPUBBuilder::Build`
- `MSPUBBuilder::Finalize`

Writer internals explicitly expose Publisher storage families:

- `MSPUB::Contents`
- `MSPUB::Quill`
- `MSPUB::Escher`
- `MSPUB::EscherStm`
- `MSPUB::EscherDelayStm`
- `DocumentSummaryInformation`
- `CompObj`
- `Envelope`
- `Internal`

Representative writer operations include:

- `Fill4BChunk`
- `Fill4CChunk`
- `Fill8AChunk`
- `Fill61Buffer`
- `Fill65Buffer`
- `BuildChunkReference`
- `CalculateContentChunkOffset`
- `AddComponentInPageChunkContent`
- `AddBackgroundInPageChunkContent`
- `BuildDg`
- `BuildBackgroundContainer`
- `BuildTableStyleContainer`

JNI confirms Android can create PUB locally:

- `Java_com_canyua_publisherexpert_EditActivity_createPub`
- `Java_com_canyua_publisherexpert_EditActivity_setRange`

This is the highest-value competitor artifact found so far. Treat it as a black-box/provenance/interoperability oracle, not source to copy.

### Other export engines

`libopenXmlCore.so` exposes `OpenXmlBuilder` and contains explicit WordprocessingML / PresentationML / DrawingML package construction.

`libpdfCore.so` embeds PoDoFo and exposes:

- `EditActivity_beginPdf`
- `EditActivity_endPdf`
- `EditActivity_deletePage`

### Locality

The app declares `INTERNET`, but the actual PUB reader/writer libraries have no dependency on a network stack. The native parser depends only on Android/system libraries and zlib. Static evidence therefore strongly supports genuine on-device PUB parsing/writing.

## 2. VD Prime — server conversion + PDFium

Package: `com.vdprime.pubviewerandconverter`.

Findings:

- OkHttp / Retrofit API client
- upload / convert / completion models
- server conversion routes
- `PUBFileActivity` -> conversion -> `PDFPreviewActivity`
- local preview uses `com.github.barteksc.pdfviewer.PDFView`
- native split carries PDFium/FreeType/PNG libraries
- no libmspub / LibreOffice / local PUB parser fingerprints

Architecture:

`.pub -> upload -> server conversion -> PDF -> Android PDFView/PDFium`

## 3. SmartApps38 — server conversion through PDFCandy/123apps infrastructure

Package: `smartapps38.convert.publisher.topdf.pubtopdf`.

Findings:

- no native PUB libraries
- Basic4Android/B4X style application
- explicit `upload_multipart`
- OkHttp
- `https://pdfcandy.com/getConfig`
- dynamic `endpoint`, `upload_endpoint`, `upload_endpoint_key`
- uploads the selected file with authorization header
- receives conversion endpoint/session metadata and downloads result
- references `s60.123apps.com`

Architecture is server-side conversion, not local PUB parsing.

## 4. OnlineConverting — server conversion

Package: `com.daemon.publishertopdfconverter`.

Findings:

- no native PUB libraries
- INTERNET / network permissions
- OkHttp
- `online-converting.com`, `www1.online-converting.com`, `www2.online-converting.com`
- resource string `android_doc2pdf2.php`
- strings: `Uploading file`, `Connection to the server is broken`, `server_error`, `no_internet`

Architecture is unambiguously server-side conversion.

## Product implication for Chaptera Mobile Reader

The competitor landscape is not homogeneous.

Three apps examined so far avoid a local Publisher implementation and convert remotely.

Canyua proves the opposite architecture is viable on Android:

`PUB bytes -> local libmspub parser -> local editable model -> local render/export -> optional custom PUB writer`

This validates several design choices for Chaptera:

1. A fully local Android PUB reader is technically practical.
2. A public libmspub-derived parser can be embedded in Android successfully.
3. The hard differentiator is not merely "can parse PUB"; Canyua already does that.
4. Differentiation must come from broader compatibility, fidelity, diagnostics, robustness, performance, UX, privacy and corpus-driven edge-case coverage.
5. A local native engine is reverse-engineerable in practice. Canyua's parser provenance and writer architecture are visible from exported symbols even though the binaries are stripped.
6. The Canyua writer is a valuable external oracle because it exposes a second implementation of native PUB synthesis.

## Next reverse-engineering targets

Priority order:

1. **Canyua `libpubBuilder.so`**
   - classify writer API by stream family
   - map writer operations to Chaptera Contents/Quill/Escher knowledge
   - identify template-seeding behavior
   - determine supported generation/version target
   - use only as behavioral/provenance evidence

2. **Canyua libmspub revision fingerprint**
   - narrow likely upstream libmspub revision from exported symbol set / behavior
   - identify custom patches around `DrawingGenerator`

3. **Dynamic interoperability test**
   - use simple controlled PUB fixtures
   - open/edit/save in Canyua
   - binary-diff original vs saved file
   - reopen saved output in Microsoft Publisher / Chaptera
   - map changed streams and records

4. **Offline verification**
   - airplane-mode device/emulator test
   - verify open/edit/save path never requires network
