# Canyua table writer static map — 2026-09-28

## Scope

Static control-flow analysis of the admitted pre-PairIP Canyua 4.1.15
`libpubBuilder.so`.

Artifact identity:

- `lib/arm64-v8a/libpubBuilder.so`
- size: 1,232,024 bytes
- SHA-256:
  `0aff50700bd695794081cc3971f73389a6df6d76f0569876b85198e16b766ce6`

The 4.1.15 writer is byte-identical to the previously mapped 5.1.1 writer
except for the 20-byte GNU Build ID, so this map applies to both tested
releases.

This is competitor implementation evidence. It does not establish Publisher
semantics by itself.

## Typed component switch

`MSPUBBuilder::PushComponent(...)` first calls `MSPUB::Escher::Push(...)`.

`MSPUB::EscherStm::Push` has an explicit six-way component switch. The
constructors make the enum mapping observable:

| component value | constructed type | object allocation |
|---:|---|---:|
| 0 | `MSPUB::Background` | 0xD8 bytes |
| 1 | `MSPUB::Text` | 0xD8 bytes |
| 2 | `MSPUB::Table` | 0x138 bytes |
| 3 | `MSPUB::Image` | 0xE0 bytes |
| 4 | `MSPUB::Shape` | 0x108 bytes |
| 5 | `MSPUB::WordArt` | 0x170 bytes |

For a table, `EscherStm::Push`:

1. constructs `MSPUB::Table`;
2. copies the supplied `MSTABLEINFO` fields into
   `Table::SetInfo(...)`;
3. reads the merge-count from the table-info structure;
4. iterates fixed-size merge descriptors and calls
   `Table::MergeCell(row1, col1, row2, col2)` for each one;
5. stores the resulting Table as the shared Component object.

This proves merge topology is part of the typed table model before either
Contents or Escher final serialization.

## Shared Component → Contents identity path

After `Escher::Push` returns a Component, `MSPUBBuilder::PushComponent`:

1. copies `MSBASEINFO` into the Component;
2. derives/fills its rectangle using the current paper information;
3. calls `MSPUB::Contents::PushComponent(component)`;
4. writes the integer returned by Contents into `Component::ID()`.

Therefore the Escher-side object is created first, then receives the
Contents-side returned identity/index. This is a direct cross-stream coupling
point in the Canyua writer.

`Contents::PushComponent` dispatches on `Component::GetType()`:

- 0 → `Contents::AddBackground`;
- 1 → `Contents::AddText`;
- 2 → `Contents::AddTable`;
- 3 → `Contents::AddImage`;
- 4 → `Contents::AddShape`.

The observed function has no type-5 WordArt branch. A separate exported
`Contents::AddWordArt` implementation exists, but a full static disassembly
search found no direct call to it. Do **not** infer a complete WordArt
Contents path from symbol presence alone.

This is a useful correction to the earlier broad writer-surface interpretation:
WordArt is definitely represented in Escher, but its Contents integration is
not yet statically proven on this build.

## Table creation in Contents

`Contents::AddTable(table, current_page_seq)` is not a one-record write.

Observed steps include:

1. allocate a primary chunk reference and patch a page-related reference with
   the current page sequence;
2. attach the new component into current-page child content;
3. create the primary table content chunk;
4. create a second chunk reference/content chunk linked to the first;
5. build a table-level buffer sized from `row + column`;
6. call `FillTableChuckContent(table, ...)`;
7. build a child/cell buffer sized from `GetCellCount()`;
8. call `FillTableChildChuckContent(table, ...)`;
9. retain the Table pointer in an internal table collection.

Two useful physical sizing laws are visible directly in the writer:

- table-level temporary framing grows by **0x12 bytes per row/column
  descriptor**;
- table-child framing grows by **0x42 bytes per cell**, plus fixed framing.

These are implementation-level physical facts for this Canyua writer. They are
not yet promoted as Publisher format laws.

## What the Contents table layer consumes

`FillTableChuckContent` reads at least:

- `Table::Row()`;
- `Table::Column()`;
- `Component::Rect()`;
- `Table::ColumnWidth()`;
- `Table::RowHeight()`;
- `Table::TableType()`.

`FillTableChildChuckContent` iterates cell state using:

- `Table::GetCellCount()`;
- `Table::GetCellInfo(...)`.

This separates the observed Canyua table persistence into a table-level
geometry/metrics block and a cell-level child topology block.

## Quill coupling for table text

The overloaded builder call

`MSPUBBuilder::SetText(table, cell_index, text, length, sync_quill)`

does the following:

1. `Table::SetCellText(cell_index, text, length)`;
2. if `sync_quill == false`, stop;
3. otherwise obtain total flattened `Table::TextLength()`;
4. allocate a UTF-16 buffer for the whole table;
5. `Table::GetText(buffer)`;
6. call `MSPUB::Quill::SetText(table, buffer, total_length)`.

So Quill is not updated with one independent cell string. The Table object
maintains cell-local text state, then exposes a flattened aggregate text view
which is handed to Quill.

The table-specific `MSPUBBuilder::PushParagraph(table, cell_index, range,
alignment)` similarly:

1. asks `Table::GetCellTextPosition(cell_index)`;
2. resolves a zero range length to that cell's
   `GetCellTextLength(cell_index)`;
3. offsets the requested range by the cell's position in the flattened table
   text;
4. forwards the adjusted range to
   `Quill::PushParagraph(table, adjusted_range, alignment, false)`.

This is strong static evidence for a two-level table-text model:

`cell-local logical text → flattened table text coordinates → Quill formatting`.

## Escher table-style layer

The same `MSPUB::Table` object is later consumed by
`EscherStm::BuildTableStyleContainer`.

Observed inputs include:

- `Table::Presets()`;
- `Table::Row()` / `Column()`;
- horizontal/vertical split-border queries;
- `Table::GetCellStyle(index)`;
- `Table::GetBorderIndex(index)`;
- `Table::LineColors()`;
- `Table::LineWidths()`;
- `Component::ID()`.

The final table-style container therefore consumes the Contents-assigned
Component ID. This closes the direction of one important cross-stream edge:

`Contents AddTable → returned ID → Component::ID → Escher table-style records`.

## Working Canyua table model

The most defensible static model is:

```text
MSTABLEINFO
   |
   v
EscherStm::Push
   |
   +--> Table::SetInfo
   +--> Table::MergeCell*
   |
   v
shared MSPUB::Table object
   |
   +--> Contents::AddTable
   |      +--> page child/reference
   |      +--> table-level metrics/topology chunk
   |      +--> cell child/topology chunk
   |      +--> returns table/component ID
   |
   +--> Component::ID = Contents return
   |
   +--> SetCellText / SetCellStyle
   |      |
   |      +--> flattened aggregate text --> Quill::SetText
   |      +--> cell-relative paragraph range --> flattened Quill range
   |
   +--> EscherStm::BuildTableStyleContainer
          +--> presets
          +--> cell styles
          +--> borders / colors / widths
          +--> split-border topology
          +--> Contents-assigned Component ID
```

This is substantially more specific than “Canyua supports tables”.

## Chaptera discriminator value

This static map suggests several concrete comparisons against the existing
Chaptera table evidence:

1. test whether Chaptera's current table-cell text model naturally maps onto
   the same **cell-local → flattened Story coordinate** split, without copying
   Canyua's implementation;
2. correlate known Publisher Contents table chunks with Canyua's separate
   table-level vs child/cell builders;
3. correlate known Publisher table paint/border evidence with the Escher
   table-style container rather than assuming all style lives in Contents;
4. inspect the Component ID bridge against Chaptera's existing identity
   namespaces instead of treating it as a universal object ID;
5. keep merge topology independent from border splitting: Canyua initializes
   merges in the Table model before later style-container construction.

## Boundary

- No Canyua Save entitlement was bypassed.
- No proprietary source code is available or reproduced.
- Function names, call edges and binary behavior are static interoperability
  evidence.
- The observed 0x12/0x42 sizing laws belong to this Canyua implementation until
  independently correlated with real Publisher files.
- No Canyua-derived field meaning should be promoted over existing Publisher
  native/corpus evidence.
