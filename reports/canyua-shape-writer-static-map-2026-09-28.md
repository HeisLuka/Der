# Canyua shape writer static map — 2026-09-28

## Scope

Static interoperability analysis of the admitted pre-PairIP Canyua 4.1.15
`lib/arm64-v8a/libpubBuilder.so`.

Artifact:

- size: **1,232,024 bytes**
- SHA-256: `0aff50700bd695794081cc3971f73389a6df6d76f0569876b85198e16b766ce6`

The native writer payload is the same as the analyzed Canyua 5.1.1 writer
except for the 20-byte GNU Build ID, so the implementation map applies to both
tested releases.

This is competitor implementation evidence, not a Publisher semantic claim.

## Typed Shape object

The generic component constructor maps component type **4** to
`MSPUB::Shape`.

The exported builder API exposes:

- `MSPUBBuilder::SetShapeVertex(...)`
- `MSPUBBuilder::SetShapeArrowStyle(...)`

The Shape surface includes:

- `ShapeType()`
- `TypeValue()`
- `SetVertex(...)`
- `Vertex()` / `VertexCount()`
- `CalculateSegmentCount(...)`
- `FillSegment(...)`
- `Segment()`
- begin/end arrow style
- begin/end arrow size
- `Build0BF0(bool)`
- `Build22F1(bool)`

## Vertex coordinate normalization

`Shape::SetVertex(MSPOINT*, MSPOINTACTION*, count)` allocates an internal
array of two 32-bit coordinates per vertex.

For every input coordinate it performs the equivalent of:

```text
stored = trunc_toward_zero(input_float * 914400 / 72)
       = trunc_toward_zero(input_float * 12700)
```

Thus the Canyua Shape API receives point-space floating coordinates and stores
integer coordinates at **12,700 units per point**, i.e. the normal EMU-per-point
scale.

This is a concrete implementation fact and a useful independent cross-check
against Chaptera geometry units. It does not by itself prove how arbitrary
native Publisher Shape vertices are rounded in every producer path.

## Segment construction

The same `SetVertex` call receives an `MSPOINTACTION[]`.

It:

1. derives the serialized segment-command count with logic equivalent to the
   exported `CalculateSegmentCount`;
2. allocates a separate 16-bit segment buffer;
3. zero-initializes it;
4. fills it through `FillSegment`.

The action array therefore does not survive as the persisted representation.
Canyua translates its higher-level point actions into a compact 16-bit segment
command stream before Escher serialization.

The binary exposes several concrete command constants inside this translator,
but their Publisher semantic labels are intentionally not assigned here until
they are independently correlated.

## Contents side of a Shape

`Contents::PushComponent` dispatches component type 4 to
`Contents::AddShape(shape, current_page_seq)`.

The observed `AddShape` path:

1. reads `Shape::ShapeType()`;
2. selects one of two fixed chunk-reference/template profiles;
3. creates a chunk reference and patches a page-related reference with the
   current page sequence;
4. attaches the shape to the current page via
   `AddComponentInPageChunkContent`;
5. creates the primary Contents shape chunk;
6. patches two 32-bit fields in the selected Contents scaffold from
   `Component::Rect()`:
   - horizontal extent = right - left;
   - vertical extent = bottom - top;
7. returns the Contents component index/ID to the generic builder.

The two observed template profiles are selected for shape type
`0 / 0x14` versus other shape types. The template byte families and sizes
differ. Their exact Publisher semantic names are not assigned here.

Crucially, this observed Contents function does **not** read the Shape vertex
array, segment buffer, or arrow state.

## Escher side of a Shape

The large `Shape::Build0BF0(bool)` path directly consumes the private Shape
state populated by `SetVertex` and `SetShapeArrowStyle`.

### Vertex payload

The builder reads:

- vertex count from Shape offset corresponding to `VertexCount()`;
- vertex pointer corresponding to `Vertex()`.

It emits a complex-property payload whose body contains the exact internal
8-byte-per-vertex integer coordinate array.

### Segment payload

The builder also reads:

- derived segment-command count;
- segment buffer corresponding to `Segment()`.

It emits a separate complex-property payload whose body contains the
2-byte-per-command segment stream.

Therefore the tested Canyua implementation physically separates Shape vertices
and segment commands into distinct Escher complex-property payloads.

### Arrow properties

`SetShapeArrowStyle` writes four explicit Shape fields:

- begin arrow style;
- end arrow style;
- begin arrow size;
- end arrow size.

`Build0BF0` reads those fields and conditionally emits OfficeArt property IDs
in the contiguous **0x1D0–0x1D5** range.

The static relation is direct:

```text
builder arrow API
  -> Shape arrow fields
  -> Build0BF0
  -> OfficeArt/FOPT properties
```

Do not assign broader Publisher semantics to every property in that range from
Canyua alone; the useful point is that arrow metadata is clearly an
Escher/FOPT-side concern in this writer.

## Cross-stream shape model

The most defensible Canyua model is:

```text
Shape semantic input
    |
    +--> shape type
    |      |
    |      v
    |    Contents::AddShape
    |      +--> page-child relation
    |      +--> shape-class scaffold
    |      +--> outer width / height
    |      +--> returned component ID
    |
    +--> vertices in point-space
    |      |
    |      +--> x12700 -> integer EMU array
    |
    +--> point actions
    |      |
    |      +--> compact 16-bit segment command stream
    |
    +--> arrow styles/sizes
           |
           v
       Shape::Build0BF0 / Build22F1
           +--> vertex complex property
           +--> segment complex property
           +--> arrow FOPT properties
           +--> shared component/style/geometry state

Contents-assigned component ID
           |
           v
       final Escher drawing-group construction
```

## Why this matters for Chaptera

This gives a useful independent decomposition for the still-open structural
writer path.

The best discriminators are:

1. **Contents placement vs Escher path geometry** — verify on Publisher-created
   custom/freeform shapes that changing only path vertices leaves the Contents
   shape scaffold stable except for any independently required bookkeeping.
2. **point → EMU rounding** — compare Publisher-native vertex changes around
   fractional-point boundaries against Canyua's truncation-to-12700 behavior.
3. **vertex/segment independence** — test whether a topology-preserving
   coordinate-only mutation changes only the vertex complex property while a
   path-command mutation changes segment state.
4. **arrow isolation** — test begin/end style/size independently and compare the
   known Publisher FOPT deltas against the Canyua 0x1D0–0x1D5 lane.
5. **shape-class templates** — investigate why Canyua distinguishes shape type
   0/0x14 from other types before promoting any meaning for those two profiles.

## Boundary

- No Save entitlement, purchase state, PairIP, signature or access control was
  bypassed.
- The x12700 vertex conversion is a Canyua writer fact. It is consistent with
  EMU geometry but does not establish all Publisher producer rounding laws.
- Segment command constants remain unnamed until independently correlated.
- The Contents-vs-Escher split is a strong static implementation observation;
  any Publisher-format claim still requires native/corpus confirmation.
