# CANYUA-WRITER-ORACLE-01 — controlled PUB writer experiment

## Goal

Use Canyua as an independent behavioral oracle for Microsoft Publisher writing.

The experiment is deliberately black-box. We compare documents produced by the
application and do not copy proprietary implementation code.

## Why this experiment exists

Static analysis already established that Canyua has a native writer that builds
Contents, Quill, Escher, EscherDelayStm and summary streams from template seeds.
Static symbols do not tell us which physical records change for one semantic
operation. Controlled before/after files can.

## Safety and provenance boundary

- Do not bypass PairIP, license checks, signatures or other access controls.
- Use either a legitimately runnable installed copy or a publicly distributed
  historical package that runs normally.
- Canyua behavior is evidence about Canyua. It becomes Publisher format evidence
  only after correlation with independent files/specification/Publisher.
- A changed byte range is not automatically a semantic field attribution.

## Experiment arms

All mutation arms must start from the same pinned source bytes.

1. **resave-control**
   - open the source;
   - make no semantic change;
   - save as PUB.
   - Purpose: measure writer normalization/noise.

2. **text-A-to-B**
   - change exactly one character in exactly one text object.

3. **text-B-to-A**
   - start from the result of arm 2 and restore the character.
   - Purpose: test whether physical bytes return or IDs/append-only state remain.

4. **move-shape-x**
   - move one shape horizontally by a known small amount only.

5. **font-size**
   - change one text run font size only.

6. **fill-color**
   - change one simple shape fill only.

7. **image-insert**
   - add one small pinned image only.

8. **repeat-save**
   - save an unchanged generated document twice.
   - Purpose: identify timestamps, IDs or other nondeterministic writer noise.

Later arms: table cell, merged cells, master page, background, WordArt.

## Capture per arm

Keep:

- exact source and output SHA-256;
- Canyua version/package source;
- device/emulator ABI;
- screenshot before/after if useful;
- semantic operation description;
- output PUB bytes;
- stream diff JSON from `diff-pub-cfb.py`.

Example:

```bash
python -m pip install olefile
python experiments/diff-pub-cfb.py \
  source.pub resave-control.pub \
  --json work/resave-control.diff.json

python experiments/diff-pub-cfb.py \
  source.pub text-A-to-B.pub \
  --json work/text-A-to-B.diff.json
```

## Interpretation order

Do not compare a mutation directly to the original first.

Use:

```text
source -> resave-control        = normalization baseline
source -> mutation              = normalization + mutation
resave-control -> mutation      = strongest first causal comparison
mutation A->B -> mutation B->A  = reversibility / allocation test
save #1 -> save #2              = nondeterminism test
```

The first high-value result is a matrix:

| operation | Contents | Quill/CONTENTS | EscherStm | EscherDelayStm | summary |
|---|---|---|---|---|---|
| resave-control | ? | ? | ? | ? | ? |
| text A→B | ? | ? | ? | ? | ? |
| move shape | ? | ? | ? | ? | ? |
| font size | ? | ? | ? | ? | ? |
| fill color | ? | ? | ? | ? | ? |
| insert image | ? | ? | ? | ? | ? |

## Gate for promoting a finding

A Canyua-derived mapping should only be promoted when:

1. the mutation arm differs from resave-control in a bounded/repeatable way;
2. repeated runs reproduce the relationship;
3. the affected stream/record is compatible with existing independent evidence;
4. the conclusion is worded no stronger than the evidence allows.

## Immediate next gate

The current 5.1.1 Play-distributed build installs and starts under x86_64
Android with ARM translation, but startup is intercepted by PairIP
LicenseActivity. That is not an ABI failure. Do not bypass it.

The practical route is therefore:

1. locate a legitimately public pre-PairIP Canyua build (3.1.10 is publicly
   indexed as an old release);
2. inspect its ABI and protection markers;
3. run it normally on the existing x86_64 + ARM-translation emulator;
4. execute resave-control first;
5. feed resulting PUB files into this diff harness.
