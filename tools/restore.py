"""Diff live device state against golden.bin and write back any differences.
Uses the bulk-write capability (0xB3 with a length field) so a full repair is a
handful of packets."""
import hid,os,time,sys
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
def readall(h,k,end):
    out=bytearray()
    for off in range(0,end,0x38):
        ln=min(0x38,end-off); drain(h)
        h.write(b"\x00"+frame(0xB2,[ln,off&0xFF,(off>>8)&0xFF,0],k))
        got=None
        for _ in range(4):
            r=h.read(64,80)
            if r and r[0]==0xAA and r[1]==0xB2:
                got=bytes((b^k)&0xFF for b in r[4:4+4+ln])[4:]; break
        out += got if got else bytes(ln)
    return bytes(out)
golden=open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),"snapshots","golden.bin"),"rb").read()
END=len(golden)
h=hid.device(); h.open_path(dev()); k=hs(h)
live=readall(h,k,END)
diff=[i for i in range(END) if live[i]!=golden[i]]
print(f"differences: {len(diff)}")
if diff and "--fix" in sys.argv:
    runs=[]; s=diff[0]; p=diff[0]
    for x in diff[1:]:
        if x>p+1: runs.append((s,p)); s=x
        p=x
    runs.append((s,p))
    for s,e in runs:
        a = s & ~1               # align down to a 16-bit word
        n = (e - a + 1 + 1) & ~1 # round length up to even
        while n>0:
            chunk=min(n,48)
            drain(h)
            h.write(b"\x00"+frame(0xB3,[chunk,a&0xFF,(a>>8)&0xFF,0]+list(golden[a:a+chunk]),k))
            time.sleep(0.12); a+=chunk; n-=chunk
        print(f"  repaired 0x{s:04X}-0x{e:04X}")
    live=readall(h,k,END)
    rem=[i for i in range(END) if live[i]!=golden[i]]
    print(f"after repair: {len(rem)} differences")
elif diff:
    for i in diff[:20]: print(f"  0x{i:04X}: live 0x{live[i]:02X} golden 0x{golden[i]:02X}")
h.close()

