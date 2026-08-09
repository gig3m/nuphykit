import hid, os, time, sys
VID,PID=0x19F5,0x102D
def dev():
    d=hid.enumerate(VID,PID)
    return next(x["path"] for x in d if x.get("usage_page")==1 and x.get("usage")==0)
h=hid.device(); h.open_path(dev())
def drain():
    try:
        while True:
            if not h.read(64,1): break
    except OSError: pass
def frame(cmd,data,key):
    o=bytearray(64); o[0],o[1],o[2]=0x55,cmd,0
    e=[(b^key)&0xFF for b in data]; o[4:4+len(e)]=bytes(e)
    o[3]=sum(o[4:64])&0xFF; return bytes(o)
drain()
p=bytearray(64); p[0],p[1],p[2]=0x55,0xEE,0
p[8:64]=os.urandom(56); p[3]=sum(p[4:64])&0xFF
h.write(b"\x00"+bytes(p)); key=None
for _ in range(8):
    r=h.read(64,300)
    if r and r[0]==0xAA and r[1]==0xEE and r[4]==r[5]==r[6]==r[7]: key=r[4]; break
for c,d in ((0xFA,[0x0A,0,0,0]),(0xFB,[0x38,0,0,0]),(0xFB,[0x38,0x38,0,0]),(0xA0,[0x08,0,0,0])):
    h.write(b"\x00"+frame(c,d,key)); time.sleep(0.03); drain()
END=int(sys.argv[1],0); BLK=0x38
blob=bytearray(); fails=[]
off=0
while off<END:
    ln=min(BLK,END-off); drain()
    h.write(b"\x00"+frame(0xB2,[ln,off&0xFF,(off>>8)&0xFF,0],key))
    got=None
    for _ in range(4):
        r=h.read(64,60)
        if r and r[0]==0xAA and r[1]==0xB2:
            got=bytes((b^key)&0xFF for b in r[4:4+4+ln]); break
    if got is None:
        fails.append(off); blob+=bytes(ln)
    else:
        blob+=got[4:4+ln]
    off+=ln
h.close()
open("scan.bin","wb").write(blob)
print("read",len(blob),"bytes; failed blocks:",len(fails), fails[:6])

