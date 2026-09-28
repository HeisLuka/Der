#!/usr/bin/env python3
from __future__ import annotations
import argparse, importlib.util, io, sys, zipfile
from pathlib import Path
try:
    import olefile
except ImportError as exc:
    raise SystemExit("Missing dependency: python -m pip install olefile") from exc

TEMPLATE_PREFIX="assets/Publisher Templates/2013/BUILT-IN/"
HERE=Path(__file__).parent

def load(name,file):
    spec=importlib.util.spec_from_file_location(name,HERE/file)
    mod=importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod; spec.loader.exec_module(mod); return mod

pre=load("pub2c_prechunk","generate-pub2c-prechunk.py")
doc=load("pub2c_root_document","generate-pub2c-root-document.py")
base=doc.load_base()

def contents(blob):
    with olefile.OleFileIO(io.BytesIO(blob)) as ole: return ole.openstream(["Contents"]).read()

def validate(apk):
    total=0; failures=[]
    with zipfile.ZipFile(apk) as z:
        pubs=sorted(n for n in z.namelist() if n.startswith(TEMPLATE_PREFIX) and n.lower().endswith(".pub"))
        for name in pubs:
            c=contents(z.read(name))
            path,prof=pre.parse_params(c)
            prefix=pre.build_prefix(
                path=path,
                contents_len=len(c),
                trailer_offset=int.from_bytes(c[0x1A:0x1E],"little"),
                profile=prof,
            )
            off,raw,model,fields=doc.parse_model(base,c)
            generated=prefix+doc.build_document(model)
            expected=c[:off+len(raw)]
            if len(prefix)!=off or generated!=expected:
                lim=min(len(generated),len(expected))
                at=next((i for i in range(lim) if generated[i]!=expected[i]),lim)
                failures.append((name,len(prefix),off,len(generated),len(expected),at))
            total+=1
    print("validated",total)
    print("contiguous_generated_prefix_byte_identical",total-len(failures),"/",total)
    if failures:
        print("first_failure",failures[0]); raise SystemExit(1)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("base_apk",type=Path); a=ap.parse_args(); validate(a.base_apk)
if __name__=="__main__": main()
