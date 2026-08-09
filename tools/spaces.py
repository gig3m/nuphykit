"""Map each command family's own address space by reading it directly.
Read-only: uses only Get* opcodes."""
import hid,os,sys
VID,PID=0x19F5,0x102D
FAMILIES=[(0xB2,"GetUseKeys",0x6E0),(0xB1,"GetDefaultKeys",0x6E0),
          (0xB5,"GetSOCD",0x100),(0xB8,"GetTapDance",0x200),(0xBB,"GetTGL",0x100),
          (0xC2,"GetMacro",0x400),(0xD5,"GetLightState",0x40),
          (0xE1,"GetKeyboardFunc",0x40),(0xF3,"GetSleepInfo",0x40),
          (0xA0,"GetBase",0x40),(0xA1,"GetFirmwareInfo",0x40),(0xFD,"GetDebugEnable",0x20)]
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
os.makedirs("snapshots/spaces",exist_ok=True)
for cmd,name,size in FAMILIES:
    blob=bytearray(); fail=0
    for off in range(0,size,0x30):
        ln=min(0x30,size-off); drain(h)
        h.write(b"\x00"+frame(cmd,[ln,off&0xFF,(off>>8)&0xFF,0],k))
        got=None
        for _ in range(4):
            try: r=h.read(64,90)
            except OSError: break
            if r and r[0]==0xAA and r[1]==cmd:
                got=bytes((b^k)&0xFF for b in r[4:4+4+ln]); break
        if got is None: fail+=1; blob+=bytes(ln)
        else: blob+=got[4:4+ln]
    open(f"snapshots/spaces/{name}.bin","wb").write(bytes(blob))
    nz=sum(1 for x in blob if x not in (0x00,0xFF))
    # where does meaningful data end?
    last=max((i for i,x in enumerate(blob) if x not in (0x00,0xFF)), default=-1)
    print(f"  0x{cmd:02X} {name:18s} {len(blob):5d}B  meaningful={nz:4d}  last_data=0x{last+1:04X}  fails={fail}")
h.close()
