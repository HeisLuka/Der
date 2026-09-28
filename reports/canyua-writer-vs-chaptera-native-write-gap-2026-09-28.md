# Canyua writer surface vs Chaptera native-write closure — 2026-09-28

## Scope

This is a **writer-surface crosswalk**, not a product-feature score.

For Canyua, the evidence below is exported native API / static implementation
surface from the admitted 4.1.15 `libpubBuilder.so`. The 4.1.15 writer is
byte-identical to the analyzed 5.1.1 writer except for its 20-byte ELF GNU
Build ID, and the four writer seeds are byte-identical across those releases.

For Chaptera, the right-hand side uses the current Notion capability/task
boundary: only native-PUB classes with independent acceptance evidence count as
closed. Chaptera-only Editor state and read/render support are not promoted to
native write.

## Crosswalk

| family | Canyua native writer evidence | Chaptera native-write state | gap / best discriminator |
|---|---|---|---|
| Whole PUB / CFB | `MSPUBBuilder::Build`, `BuildStorageSteamNames`, Contents/Quill/Escher/Summary builders, POLE-style final assembly | Whole-file materialization is closed only for operation-scoped source-aware replacement; no generic Save PUB | Canyua has a broad integrated builder surface; Chaptera intentionally remains operation-scoped |
| Document / Page | `BeginDocument`, `BeginPage`, `BeginMasterPage`, paired End* calls; Contents page/document construction | Existing page-order/rebind carrier authority is bounded; new native Page/object materialization is still separate | map Canyua page allocation/service-object policy; do not infer it from `BeginPage` alone |
| Story text | `SetText`, `PushParagraph`, `PushSpan`, Quill builder | **bounded native PASS** for ordinary Story text mutation + Publisher SaveAs/fresh reopen | Chaptera is already competitive on one narrow proven class; formatting breadth remains open |
| Paragraph/span formatting | explicit paragraph alignment + `MSFONT` span input | Chaptera-native authoring overlays exist/are growing, but broad Publisher-native formatting write is not closed | isolate Canyua paragraph/font serialization statically, then correlate only with entitled/natural outputs |
| Ordinary shape | `PushComponent`, `SetShapeVertex`, `SetShapeArrowStyle`; `Shape::Build0BF0/Build22F1`; segment/vertex/arrow logic | Chaptera can author source-neutral shapes, but synthetic native object create/delete remains behind structural-writer gates | **high-value gap**: object creation/allocation + Contents↔Escher cross-stream identity |
| Image | `SetImageInfo`; `Image::Build0BF0/Build22F1`; `Contents::AddImage`; EscherDelay picture path | strong read/recovery/render; no generic native image insert/replace writer claim | **high-value gap**: image allocation, delay-stream placement, object cross-references |
| Table | `Table::SetInfo`, `MergeCell`, `SetCellText`, `SetCellStyle`, row/column metrics, border/color/width accessors; Contents table buffers; Escher table-style containers | Chaptera has source-neutral table edit/structure/paint work, but broad native structural/style PUB write remains open | **highest static teardown value**: table writer is explicit and relatively self-contained |
| WordArt | `WordArt::SetBaseInfo`, `Build0BF0`, `Build22F1`; `Contents::AddWordArt`; Escher tracks WordArt count | no broad Chaptera WordArt authoring/native-write closure | useful independent serialization lineage for GeoText/WordArt |
| Background | `Contents::AddBackground`, `AddBackgroundInPageChunkContent`, `EscherStm::BuildBackgroundContainer` | no broad native background-authoring write closure | map background object/page ownership and Escher container shape |
| Master-page lifecycle | `BeginMasterPage` / `EndMasterPage`; page builder accepts master-related state | existing-page → existing-master authority is bounded; master create/duplicate/delete remains separate research | compare allocation/service graph, not just relation rewrite |

## Static symbol counts in the admitted 4.1.15 writer

Unique exported native methods/symbols observed for the main implementation
families include:

- `MSPUB::Contents`: ~81 dynamic function entries;
- `MSPUB::Table`: 30+ explicit methods, including merge, cell text/style,
  dimensions, borders and two physical-build variants;
- `MSPUB::Shape`: vertex, segment and arrow handling plus two build variants;
- `MSPUB::Image`: two build variants + EscherDelay linkage;
- `MSPUB::WordArt`: base-info setup + two build variants;
- `MSPUB::EscherStm`: component/image/WordArt inventory, DG construction,
  background and table-style container construction.

The important point is not the counts. The separation into typed object
builders shows that Canyua has a deliberate multi-family native serializer,
rather than a text-only patcher.

## What this changes

Canyua's strongest current technical advantage over Chaptera is **native writer
breadth**, not parser depth.

Chaptera should not copy Canyua's architecture. The useful leverage is to use
the binary as an independent implementation oracle to answer bounded questions
that are currently expensive for Chaptera:

1. table physical split: which state is emitted into Contents vs Escher;
2. shape creation: allocation + page-child + Escher SPID/container coupling;
3. image insertion: image object + delay-stream + Contents reference coupling;
4. WordArt: Contents/Escher object split and minimum required state;
5. master/page creation: service graph and identity allocation.

## Recommended static order while dynamic Save is entitlement-gated

1. **Table first.** The exported API is unusually rich and self-contained:
   `SetInfo / MergeCell / SetCellText / SetCellStyle`, Contents table buffers,
   and Escher table-style containers. This can yield a useful structural map
   without needing a generated output immediately.
2. **Image second.** Follow `SetImageInfo → AddImage → EscherStm →
   EscherDelayStm` and map identity/index propagation.
3. **Shape third.** Follow `PushComponent / SetShapeVertex /
   SetShapeArrowStyle` through Contents + Escher, focusing on allocator and
   cross-stream IDs rather than shape geometry already known independently.
4. **WordArt fourth.** Treat it as a separate object family and compare only
   against existing independent GeoText/WordArt evidence.
5. **Master/page creation last.** High leverage, but easiest place to overclaim
   service-object semantics from one implementation.

## Evidence boundary

- Exported symbols and disassembly prove implementation surface, not that every
  path is exposed or entitled in the UI.
- Canyua 4.1.15 Save-to-PUB is independently mapped through the Document
  Converter purchase gate. No purchase state is forged for this research.
- Static Canyua mappings remain competitor evidence until correlated with
  independent Publisher/Chaptera evidence.
- Chaptera native-write closure remains operation-specific; a broad Canyua
  method name does not downgrade or invalidate Chaptera's stronger provenance,
  preservation, recovery or semantic-model evidence.
