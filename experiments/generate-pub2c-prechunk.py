#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, struct, zipfile
from dataclasses import dataclass
from pathlib import Path

# Neutral physical entry patterns for the fixed mature-0x2C 143-entry table.
# Pattern tuple: (field03_u32|None, presence_fields, field09_u16|None, field0C_u32|None)
PATTERNS = [
(65536000,(6,8),1,1),(65536000,(8,),1,2),(65536000,(8,),None,3),(65536000,(8,),4,3),
(65536000,(6,7,8),1,4),(65536000,(8,11),1,5),(None,(),None,None),(65536000,(6,7,8),1,5),
(65536000,(8,),1,5),(65536000,(8,),3,5),(65536000,(),None,5),(65536000,(11,),None,5),
(65536000,(8,),4,5),(65536000,(8,),2,5),(65536000,(6,8,10),2,5),(65536000,(8,),None,5),
(65536000,(),4,5),(65536000,(6,8,11),3,0xFFFFFFFF),(65536000,(6,8),2,5),(65536000,(8,10),2,5),
(65536000,(6,8),1,5),(65536015,(8,),4,5),(65536017,(8,),1,5),(65536017,(6,8),1,0xFFFFFFFF),
(65536017,(8,),1,0xFFFFFFFF),(65536020,(8,),4,5),(65536020,(6,7,8),1,5),(65536020,(8,),1,5),
(65536001,(6,8),1,5),(65536001,(8,),1,5),
]
PATTERN_IDS = [
0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1,1,1,1,1,1,1,1,1,
1,1,1,1,1,1,1,2,3,2,2,2,2,2,2,2,2,2,2,2,2,2,2,4,
4,4,4,4,4,4,4,4,4,4,4,4,4,4,4,5,6,6,7,7,8,9,10,11,
12,9,9,8,12,8,13,6,6,6,14,15,16,9,12,15,7,17,15,8,9,9,12,12,
18,6,8,6,13,12,12,12,15,12,12,9,9,6,6,18,19,19,19,12,18,15,12,12,
12,12,12,12,12,20,7,13,7,12,21,22,23,23,24,24,23,25,26,27,28,29,25,
]
assert len(PATTERN_IDS) == 143


def f0(fid:int, typ:int)->bytes: return bytes((fid,typ))
def f16(fid:int, typ:int, v:int)->bytes: return bytes((fid,typ))+struct.pack('<H',v)
def f32(fid:int, typ:int, v:int)->bytes: return bytes((fid,typ))+struct.pack('<I',v)

def build_entry(seq:int, pattern_id:int, *, seed_entry139:bool=False)->bytes:
    v03,pres,v09,v0c=PATTERNS[pattern_id]
    # Canyua seed differs only at entry 139 by omitting 06/08 and 07/08.
    if seed_entry139 and seq == 139:
        pres=tuple(x for x in pres if x not in (6,7))
    body=bytearray()
    body += f16(0x01,0x18,seq)
    if v03 is not None: body += f32(0x03,0x20,v03)
    for fid in (0x06,0x07,0x08):
        if fid in pres: body += f0(fid,0x08)
    if v09 is not None: body += f16(0x09,0x10,v09)
    if 0x0A in pres: body += f0(0x0A,0x08)
    if 0x0B in pres: body += f0(0x0B,0x08)
    if v0c is not None: body += f32(0x0C,0x20,v0c)
    return bytes((0x00,0x88)) + struct.pack('<I',len(body)+4) + body

def build_table(*, seed_entry139:bool=False)->bytes:
    body=b''.join(build_entry(i+1,pid,seed_entry139=seed_entry139) for i,pid in enumerate(PATTERN_IDS))
    return bytes((0x03,0x90)) + struct.pack('<I',len(body)+4) + body

@dataclass(frozen=True)
class PrefixProfile:
    os_low16:int
    app_major:int
    build0:int
    build1:int
    build2:int
    build3:int
    family_code:int=0x1A
    seed_entry139:bool=False


def build_prefix(*, path:str, contents_len:int, trailer_offset:int, profile:PrefixProfile)->bytes:
    path_raw=path.encode('utf-16le')+b'\x00\x00'
    path_end=0x5E+len(path_raw)
    outer_start=path_end+40

    p=bytearray()
    p += struct.pack('<HBBHHI',0xACE8,0x2C,0x00,0x03E8,profile.os_low16,contents_len)
    p += struct.pack('<I',0x01000000 | profile.family_code)
    p += b'\x00'*10
    p += struct.pack('<IIHHIH',trailer_offset,outer_start,profile.app_major,profile.app_major,0,0)
    p += struct.pack('<I',path_end-4)
    assert len(p)==0x30

    p += f16(0x01,0x18,0xACE8)
    p += f32(0x02,0x68,0x00000100)
    for fid in (0x03,0x04,0x05,0x07): p += f32(fid,0x20,0x03E80000 | profile.family_code)
    p += f32(0x08,0x20,contents_len)
    p += bytes((0x09,0xC0)) + struct.pack('<I',len(path_raw)+4) + path_raw
    assert len(p)==path_end

    p += f32(0x0A,0xB8,trailer_offset)
    p += f32(0x0B,0xB8,outer_start)
    p += f16(0x0C,0x18,1)
    p += f32(0x0D,0x20,profile.build0)
    p += f32(0x0E,0x20,profile.build1)
    p += f32(0x0F,0x20,profile.build2)
    p += f32(0x10,0x20,profile.build3)
    assert len(p)==outer_start

    table=build_table(seed_entry139=profile.seed_entry139)
    p += struct.pack('<I',len(table)+16)
    p += f32(0x01,0x20,143)
    p += f32(0x02,0x20,0x03E80000 | profile.family_code)
    p += table
    return bytes(p)

# Minimal CFB reader for validation-only corpus replay.
def contents_from_pub(b:bytes)->bytes:
    assert b[:8]==bytes.fromhex('d0cf11e0a1b11ae1')
    ss=1<<struct.unpack_from('<H',b,0x1e)[0]
    nf=struct.unpack_from('<I',b,0x2c)[0]
    dif=list(struct.unpack_from('<109I',b,0x4c))
    fs=[x for x in dif if x<0xfffffffa][:nf]
    def sec(s): return b[(s+1)*ss:(s+2)*ss]
    fat=[]
    for s in fs: fat.extend(struct.unpack('<%dI'%(ss//4), sec(s)))
    def chain(s):
        out=[]; seen=set()
        while s<0xfffffffa:
            if s in seen: raise ValueError('FAT loop')
            seen.add(s);out.append(s);s=fat[s]
        return out
    dd=b''.join(sec(s) for s in chain(struct.unpack_from('<I',b,0x30)[0]))
    for off in range(0,len(dd),128):
        e=dd[off:off+128]
        if len(e)<128: break
        nl=struct.unpack_from('<H',e,64)[0]
        if nl>=2 and e[:nl-2].decode('utf-16le','replace')=='Contents':
            st=struct.unpack_from('<I',e,116)[0]; sz=struct.unpack_from('<Q',e,120)[0]
            return b''.join(sec(s) for s in chain(st))[:sz]
    raise ValueError('Contents missing')

def parse_params(c:bytes):
    plen=struct.unpack_from('<I',c,0x5A)[0]
    raw=c[0x5E:0x5E+plen-4]
    assert raw[-2:]==b'\0\0'
    path=raw[:-2].decode('utf-16le')
    pe=0x5E+len(raw)
    return path, PrefixProfile(
        os_low16=struct.unpack_from('<H',c,0x06)[0],
        app_major=struct.unpack_from('<H',c,0x22)[0],
        build0=struct.unpack_from('<I',c,pe+18)[0],
        build1=struct.unpack_from('<I',c,pe+24)[0],
        build2=struct.unpack_from('<I',c,pe+30)[0],
        build3=struct.unpack_from('<I',c,pe+36)[0],
        family_code=struct.unpack_from('<I',c,pe+52)[0] & 0xFF,
        seed_entry139=False,
    )

def validate_apk(apk:Path)->int:
    pref='assets/Publisher Templates/2013/BUILT-IN/'
    checked=0
    with zipfile.ZipFile(apk) as z:
        names=sorted(n for n in z.namelist() if n.startswith(pref) and n.lower().endswith('.pub'))
        for n in names:
            c=contents_from_pub(z.read(n))
            path,prof=parse_params(c)
            got=build_prefix(path=path,contents_len=len(c),trailer_offset=struct.unpack_from('<I',c,0x1A)[0],profile=prof)
            if got != c[:len(got)]:
                lim=min(len(got),len(c)); at=next((i for i in range(lim) if got[i]!=c[i]),lim)
                raise AssertionError(f'{n}: prefix mismatch at 0x{at:X}')
            checked+=1
    print(f'validated {checked}/{checked} Publisher 2013 templates: generated prefix byte-identical')
    print('table_len',len(build_table()),'table_sha256',hashlib.sha256(build_table()).hexdigest())
    return checked

def validate_seed(seed:Path)->None:
    c=seed.read_bytes()
    plen=struct.unpack_from('<I',c,0x5A)[0];raw=c[0x5E:0x5E+plen-4];path=raw[:-2].decode('utf-16le'); pe=0x5E+len(raw)
    prof=PrefixProfile(
      os_low16=struct.unpack_from('<H',c,6)[0],app_major=struct.unpack_from('<H',c,0x22)[0],
      build0=struct.unpack_from('<I',c,pe+18)[0],build1=struct.unpack_from('<I',c,pe+24)[0],
      build2=struct.unpack_from('<I',c,pe+30)[0],build3=struct.unpack_from('<I',c,pe+36)[0],
      family_code=struct.unpack_from('<I',c,pe+52)[0] & 0xFF,seed_entry139=True)
    got=build_prefix(path=path,contents_len=len(c),trailer_offset=struct.unpack_from('<I',c,0x1A)[0],profile=prof)
    if got != c[:len(got)]:
      lim=min(len(got),len(c));at=next((i for i in range(lim) if got[i]!=c[i]),lim)
      raise AssertionError(f'seed prefix mismatch at 0x{at:X}')
    print('validated Canyua Contents.dat seed: generated prefix byte-identical')
    print('seed_table_len',len(build_table(seed_entry139=True)),'seed_table_sha256',hashlib.sha256(build_table(seed_entry139=True)).hexdigest())

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--apk',type=Path);ap.add_argument('--seed',type=Path)
    a=ap.parse_args()
    if a.apk: validate_apk(a.apk)
    if a.seed: validate_seed(a.seed)
