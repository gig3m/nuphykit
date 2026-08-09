"""Read the AppDefine store via 0xFB across offsets. Read-only."""
import hid,os,sys
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
h=hid.device(); h.open_path(dev()); k=hs(h)
SIZE=0x3BA
blob=bytearray()
for off in range(0,SIZE,0x30):
    ln=min(0x30,SIZE-off); drain(h)
    h.write(b"\x00"+frame(0xFB,[ln,off&0xFF,(off>>8)&0xFF,0],k))
    got=None
    for _ in range(4):
        r=h.read(64,90)
        if r and r[0]==0xAA and r[1]==0xFB:
            got=bytes((b^k)&0xFF for b in r[4:4+4+ln]); break
    if got is None: print(f"  off 0x{off:03X}: no reply"); blob+=bytes(ln); continue
    blob += got[4:4+ln]
h.close()
open("snapshots/appdefine.bin","wb").write(bytes(blob))
nz=sum(1 for x in blob if x)
print(f"AppDefine: {len(blob)} bytes, {nz} non-zero")
for r in range(0,min(len(blob),0xC0),16):
    print(f"  {r:04X}: {blob[r:r+16].hex(' ')}")
