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
fancy=load("pub2c_fancyborders","generate-pub2c-fancyborders.py")
page263=load("pub2c_page263","generate-pub2c-page263.py")
web=load("pub2c_page_web","generate-pub2c-page-web-companions.py")
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
            refs=fancy.directory_refs(c)
            ba_ref=next(r for r in refs if r["seq"]==261 and r["type"]==0x46 and r["parent"]==256)
            ba_len=int.from_bytes(c[ba_ref["off"]:ba_ref["off"]+4],"little")
            ba_raw=c[ba_ref["off"]:ba_ref["off"]+ba_len]
            ba_defs=fancy.parse_fancy_borders(ba_raw)
            ba_generated=fancy.build_fancy_borders(ba_defs)
            mm_ref=next(r for r in refs if r["seq"]==262 and r["type"]==0x54 and r["parent"]==256)
            mm_len=int.from_bytes(c[mm_ref["off"]:mm_ref["off"]+4],"little")
            if mm_len != 4:
                raise AssertionError(f"{name}: MailMergeData not empty: {mm_len}")
            p_ref=next(r for r in refs if r["seq"]==263 and r["type"]==0x43 and r["parent"]==256)
            p_len=int.from_bytes(c[p_ref["off"]:p_ref["off"]+4],"little")
            p_raw=c[p_ref["off"]:p_ref["off"]+p_len]
            p_generated=page263.build_page(page263.parse_page(p_raw))
            w_ref=next(r for r in refs if r["seq"]==264 and r["type"]==0x60 and r["parent"]==263)
            w_len=int.from_bytes(c[w_ref["off"]:w_ref["off"]+4],"little")
            f_ref=next(r for r in refs if r["seq"]==265 and r["type"]==0x77 and r["parent"]==263)
            f_len=int.from_bytes(c[f_ref["off"]:f_ref["off"]+4],"little")
            w_generated=web.build_web_page_info(web.WebPageInfo())
            f_generated=web.build_form_properties(web.FormProperties())
            generated=prefix+doc.build_document(model)+b"\x04\x00\x00\x00"+b"\x04\x00\x00\x00"+ba_generated+b"\x04\x00\x00\x00"+p_generated+w_generated+f_generated
            expected=c[:f_ref["off"]+f_len]
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
