import hid,os,time
from collections import Counter
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
golden=open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"snapshots","golden.bin"),"rb").read(); END=len(golden)
h=hid.device(); h.open_path(dev()); k=hs(h)
live=bytearray()
for off in range(0,END,0x38):
    ln=min(0x38,END-off); drain(h)
    h.write(b"\x00"+frame(0xB2,[ln,off&0xFF,(off>>8)&0xFF,0],k))
    got=None
    for _ in range(4):
        r=h.read(64,80)
        if r and r[0]==0xAA and r[1]==0xB2:
            got=bytes((b^k)&0xFF for b in r[4:4+4+ln])[4:]; break
    live += got if got else bytes(ln)
h.close()
open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"snapshots","postflash.bin"),"wb").write(bytes(live))
def region(a):
    if a < 0x06E0: return 'keymap (8 banks)'
    if a < 0x0740: return 'macro offset table'
    if a < 0x1700: return 'macro data'
    if a < 0x174C: return 'knob region'
    if a < 0x1850: return 'SOCD table'
    if a < 0x1A58: return 'TapDance table'
    if a < 0x1C00: return 'Toggle table +'
    return 'above 0x1C00'
diff=[i for i in range(END) if live[i]!=golden[i]]
print("total differences:", len(diff))
print(Counter(region(a) for a in diff))
km=[a for a in diff if a<0x06E0]
print("\nkeymap differences:", len(km))
for a in km[:12]:
    idx=(a%0xDC)//2; layer=a//0xDC
    print(f"  0x{a:04X} layer{layer} idx{idx}: live 0x{live[a]:02X} golden 0x{golden[a]:02X}")
