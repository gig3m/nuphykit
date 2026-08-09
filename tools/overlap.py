"""Is 0xB2's space a superset of the per-family spaces, or separate?"""
import hid,os
VID,PID=0x19F5,0x102D
def dev():
    d=hid.enumerate(VID,PID); return next(x["path"] for x in d if x.get("usage_page")==1 and x.get("usage")==0)
def frame(cmd,data,key):
    o=bytearray(64); o[0],o[1],o[2]=0x55,cmd,0
    e=[(b^key)&0xFF for b in data]; o[4:4+len(e)]=bytes(e); o[3]=sum(o[4:64])&0xFF; return bytes(o)
def drain(h):
    try:
        while True:
            if not h.read(64,1): break
    except OSError: pass
def hs(h):
    drain(h); p=bytearray(64); p[0],p[1],p[2]=0x55,0xEE,0
    p[8:40]=os.urandom(32); p[3]=sum(p[4:64])&0xFF; h.write(b"\x00"+bytes(p))
    for _ in range(6):
        r=h.read(64,250)
        if r and r[0]==0xAA and r[1]==0xEE and r[4]==r[5]==r[6]==r[7]: return r[4]
    return None
def rd(h,k,cmd,addr,ln=0x20):
    drain(h)
    h.write(b"\x00"+frame(cmd,[ln,addr&0xFF,(addr>>8)&0xFF,0],k))
    for _ in range(4):
        try: r=h.read(64,90)
        except OSError: return None
        if r and r[0]==0xAA and r[1]==cmd:
            return bytes((b^k)&0xFF for b in r[4:4+4+ln])[4:]
    return None
h=hid.device(); h.open_path(dev()); k=hs(h)
pairs=[("macro",0xC2,0x0000,0xB2,0x0700),
       ("socd", 0xB5,0x0000,0xB2,0x174C),
       ("tapdance",0xB8,0x0000,0xB2,0x1850),
       ("tgl",  0xBB,0x0000,0xB2,0x1A58)]
for name,fc,fa,gc,ga in pairs:
    a=rd(h,k,fc,fa); b=rd(h,k,gc,ga)
    if a is None or b is None: print(f"  {name}: read failed"); continue
    same = a==b
    print(f"  {name:9s} Get(0x{fc:02X})@0x{fa:04X} vs 0xB2@0x{ga:04X}: {'IDENTICAL' if same else 'DIFFERENT'}")
    if not same:
        print(f"      family: {a[:16].hex(' ')}")
        print(f"      0xB2  : {b[:16].hex(' ')}")
# and what does 0xB2 return past its own 0x6E0 boundary vs GetMacro's space
print()
for addr in (0x06E0,0x0700,0x0740):
    b=rd(h,k,0xB2,addr,0x10)
    print(f"  0xB2 @0x{addr:04X}: {b.hex(' ') if b else 'fail'}")
h.close()
