"""Query ONLY the read-only GET commands named in opcodes.json.
Deliberately excludes every Set*/Reset*/Restore* and 0xEF SetIapMode."""
import hid,os,time
VID,PID=0x19F5,0x102D
GETS=[(0x2F,"GetDongelName"),(0xA0,"GetBase"),(0xA1,"GetFirmwareInfo"),
      (0xB5,"GetSOCD"),(0xB8,"GetTapDance"),(0xBB,"GetTGL"),(0xC2,"GetMacro"),
      (0xD1,"GetLightCount"),(0xD5,"GetLightState"),(0xE1,"GetKeyboardFunc"),
      (0xE6,"GetTouchBarConfig"),(0xF3,"GetSleepInfo"),
      (0xFA,"GetAppDefineSize"),(0xFB,"GetAppDefine"),(0xFD,"GetDebugEnable")]
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
print("session key 0x%02X\n" % k)
for cmd,name in GETS:
    drain(h)
    h.write(b"\x00"+frame(cmd,[0x20,0x00,0x00,0x00],k))
    got=None
    for _ in range(4):
        try: r=h.read(64,90)
        except OSError: break
        if r and r[0]==0xAA and r[1]==cmd: got=bytes((b^k)&0xFF for b in r[4:40]); break
    if got is None:
        print(f"  0x{cmd:02X} {name:20s} no reply")
    else:
        hdr=got[:4].hex(' '); data=got[4:28]
        txt=''.join(chr(c) if 32<=c<127 else '.' for c in data)
        print(f"  0x{cmd:02X} {name:20s} hdr={hdr} | {data.hex(' ')} | {txt}")
h.close()
