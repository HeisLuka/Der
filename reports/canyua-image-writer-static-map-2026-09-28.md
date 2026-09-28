# Canyua image writer static map — 2026-09-28

## Scope

Static control-flow analysis of Canyua 4.1.15
`lib/arm64-v8a/libpubBuilder.so`:

- size: 1,232,024 bytes;
- SHA-256:
  `0aff50700bd695794081cc3971f73389a6df6d76f0569876b85198e16b766ce6`.

The native writer payload is the same as tested Canyua 5.1.1 except for its
GNU Build ID, so the implementation map applies to both builds.

## Image creation path

The builder's generic component path is:

```text
MSPUBBuilder::PushComponent
    |
    v
MSPUB::Escher::Push
    |
    +--> EscherDelayStm::Push(picture_type, local_name, bytes)
    |       |
    |       +--> existing Picture by local-name -> AddRefCount -> reuse
    |       |
    |       +--> otherwise construct new Picture
    |               +--> index in delay-stream picture vector
    |               +--> computed physical delay-stream offset
    |
    v
MSPUB::EscherStm::Push(component=IMAGE, Picture*)
    |
    v
MSPUB::Image(Picture*)
    |
    v
MSPUBBuilder::PushComponent
    +--> copy MSBASEINFO / resolve component rectangle
    +--> Contents::PushComponent
            |
            +--> Contents::AddImage
            |
            +--> returned component ID
                    |
                    v
               Component::ID
```

## Picture admission and deduplication

`EscherDelayStm::Push(MSPICTURE, local_name, bytes)` accepts the observed
picture enum range 0..2. Values outside that range return null.

Before allocating a new picture it scans the existing picture vector and
compares the supplied UTF-16 local name against
`Picture::GetLocalName()`.

When the name matches:

- `Picture::AddRefCount()` is called;
- the existing Picture object is returned;
- no second Picture is appended to the delay-stream picture vector.

Therefore the tested Canyua writer has an explicit **local-name-based picture
deduplication policy**.

This is an implementation fact, not yet a Publisher rule.

## Delay-stream offset allocation

For a new Picture, the writer:

1. counts/scans all existing pictures;
2. calls `Picture::GetSize()` for each;
3. accumulates the previous picture sizes plus a fixed **0x19-byte per-picture
   framing increment**;
4. constructs a new `Picture(type, local_name, bytes, index)`;
5. stores the calculated value through
   `Picture::OffsetInEscherDelayStm()`;
6. appends the new Picture to the delay-stream picture vector.

Observed exported Picture surface:

- `GetIndexInEscherDelayStm()`;
- `GetLocalName()`;
- `GetPictureBufferInEscherStm()`;
- `GetPictureName()`;
- `GetPictureNameWithExt()`;
- `GetPictureNameWithOutExt()`;
- `GetPicutreCode()`;
- `GetSize()`;
- `GetType()`;
- `GetUUID()`;
- `OffsetInEscherDelayStm()`;
- `AddRefCount()`.

The strongest bounded conclusion is that Canyua maintains a typed Picture
object carrying both logical identity/name state and physical EscherDelayStm
placement state.

## Contents image path

`Contents::PushComponent` dispatches Image components to
`Contents::AddImage(image, current_page_seq)`.

The observed AddImage flow:

1. allocates a chunk reference;
2. links the component into current-page child content;
3. creates the primary image content chunk;
4. allocates/creates a second linked chunk;
5. writes component rectangle state;
6. obtains the shared Picture via
   `Image::GetPictureInEscherDelayStm()`;
7. obtains the picture filename including extension using
   `Picture::GetPictureNameWithExt()`;
8. builds additional Contents chunk content containing picture-derived state.

This gives a concrete three-layer image model:

```text
Picture bytes/name/type
      |
      v
EscherDelayStm physical asset
      |
      +--> shared Picture object
               |
               +--> Image component / Escher shape payload
               |
               +--> Contents image record + page-child relation
```

## Image component metadata

`MSPUBBuilder::SetImageInfo(image, MSIMAGEINFO*)` forwards image metadata
into the typed `Image::Info()` storage before final serialization.

The exact semantic layout of `MSIMAGEINFO` is not assigned here; the static
wrapper copies the first machine-word-sized payload into the Image info state.
Field meaning requires independent correlation.

## Escher projection

`Image` exposes two substantial physical-build paths:

- `Image::Build0BF0(bool)`;
- `Image::Build22F1(bool)`.

The generic `EscherStm::BuildDg` later consumes each non-background
Component's:

- generated 0BF0 data;
- generated 22F1 data;
- component rectangle;
- Contents-assigned `Component::ID`.

This means image geometry/object identity is not independent from the Contents
allocation step: the shared Component is assigned an ID by Contents before the
Escher drawing-group output is finalized.

## Chaptera discriminator value

The highest-value independent tests suggested by this map are:

1. **same-name / same-bytes vs same-name / different-bytes** image insertion:
   determine whether native Publisher deduplicates by content, logical resource
   identity or filename instead of assuming Canyua's local-name policy;
2. correlate a known Publisher image's Contents record with its EscherDelayStm
   index/offset and OfficeArt SPID identity;
3. test whether repeated image reuse increments one shared image resource or
   creates multiple native resources;
4. compare Chaptera's canonical asset identity with source picture names: do not
   make filename the canonical identity merely because Canyua does;
5. use the 0x19 per-picture framing increment only as a Canyua serializer
   hypothesis until confirmed against independent PUBs.

## Boundary

- No Save entitlement or access control was bypassed.
- Local-name dedupe and the 0x19 offset increment are **Canyua implementation
  facts**, not Publisher format laws.
- No semantic meaning is assigned to unknown `MSIMAGEINFO` fields.
- This map is useful because it identifies precise discriminators for Chaptera;
  it is not a source implementation to reproduce.
