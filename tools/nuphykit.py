"""nuphykit — total-coverage backup / restore for the NuPhy Air100 V3.

The board keeps its settings in FIVE separate places. `restore.py` covers only
the first, so a "backup" that reads just the config memory silently loses the
other four. This tool covers all of them.

    uv run --with hidapi python tools/nuphykit.py show
    uv run --with hidapi python tools/nuphykit.py backup mybackup
    uv run --with hidapi python tools/nuphykit.py restore mybackup
    uv run --with hidapi python tools/nuphykit.py verify mybackup

Spaces (PROTOCOL 60-63):

  name      get   set   size     write granularity
  config    0xB2  0xB3  0x1C00   arbitrary, 16-bit aligned
  func      0xE1  0xE2  4        single byte OK
  sleep     0xF3  0xF5  4        WHOLE RECORD ONLY
  appdefine 0xFB  0xFC  0x03BA   single byte OK
  light     0xD5  0xD6  17       WHOLE RECORD ONLY

Not covered by anything here, because the device offers no way to read it:
the Ctrl<->Caps swap (PROTOCOL 58) is real, persistent, and unlocated.
"""
import hid, json, os, sys, time

VID, PID = 0x19F5, 0x102D

SPACES = {
    "config":    dict(get=0xB2, set=0xB3, size=0x1C00, chunk=0x38, whole=False),
    "func":      dict(get=0xE1, set=0xE2, size=4,      chunk=4,    whole=False),
    "sleep":     dict(get=0xF3, set=0xF5, size=4,      chunk=4,    whole=True),
    "appdefine": dict(get=0xFB, set=0xFC, size=0x3BA,  chunk=0x38, whole=False),
    "light":     dict(get=0xD5, set=0xD6, size=17,     chunk=17,   whole=True),
}


def dev():
    d = hid.enumerate(VID, PID)
    try:
        return next(x["path"] for x in d
                    if x.get("usage_page") == 1 and x.get("usage") == 0)
    except StopIteration:
        raise SystemExit("nuphykit: Air100 V3 raw-HID interface not found")


def frame(cmd, data, key):
    o = bytearray(64)
    o[0], o[1], o[2] = 0x55, cmd, 0
    e = [(b ^ key) & 0xFF for b in data]
    o[4:4 + len(e)] = bytes(e)
    o[3] = sum(o[4:64]) & 0xFF
    return bytes(o)


def drain(h):
    try:
        while True:
            if not h.read(64, 1):
                break
    except OSError:
        pass


def handshake(h):
    drain(h)
    p = bytearray(64)
    p[0], p[1], p[2] = 0x55, 0xEE, 0
    p[8:40] = os.urandom(32)          # minimum accepted is 21 bytes (AUDIT B1)
    p[3] = sum(p[4:64]) & 0xFF
    h.write(b"\x00" + bytes(p))
    for _ in range(6):
        r = h.read(64, 250)
        if r and r[0] == 0xAA and r[1] == 0xEE and r[4] == r[5] == r[6] == r[7]:
            return r[4]
    raise SystemExit("nuphykit: handshake rejected")


def read_space(h, k, name):
    s = SPACES[name]
    out = bytearray()
    for off in range(0, s["size"], s["chunk"]):
        ln = min(s["chunk"], s["size"] - off)
        drain(h)
        h.write(b"\x00" + frame(s["get"], [ln, off & 0xFF, (off >> 8) & 0xFF, 0], k))
        got = None
        for _ in range(5):
            r = h.read(64, 120)
            if r and r[0] == 0xAA and r[1] == s["get"]:
                got = bytes((b ^ k) & 0xFF for b in r[4:8 + ln])[4:]
                break
        out += got if got else bytes(ln)
    return bytes(out[:s["size"]])


def write_space(h, k, name, data):
    s = SPACES[name]
    if s["whole"]:
        drain(h)
        h.write(b"\x00" + frame(s["set"], [s["size"], 0, 0, 0] + list(data), k))
        time.sleep(0.3)
        return
    step = 48
    for off in range(0, len(data), step):
        chunk = data[off:off + step]
        drain(h)
        h.write(b"\x00" + frame(s["set"],
                [len(chunk), off & 0xFF, (off >> 8) & 0xFF, 0] + list(chunk), k))
        time.sleep(0.12)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    snaps = os.path.join(root, "snapshots")

    h = hid.device()
    h.open_path(dev())
    k = handshake(h)

    if cmd == "show":
        for name in SPACES:
            d = read_space(h, k, name)
            if name == "config":
                print(f"  {name:10} {len(d)} bytes  sha={__import__('hashlib').sha256(d).hexdigest()[:16]}")
            else:
                print(f"  {name:10} {' '.join(f'{x:02X}' for x in d[:24])}"
                      + (" ..." if len(d) > 24 else ""))
    elif cmd in ("backup", "verify", "restore"):
        if len(sys.argv) < 3:
            raise SystemExit("nuphykit: need a backup name")
        name = sys.argv[2]
        path = os.path.join(snaps, f"kit_{name}.json")
        if cmd == "backup":
            blob = {n: read_space(h, k, n).hex() for n in SPACES}
            json.dump(blob, open(path, "w"), indent=1)
            print(f"backed up all {len(SPACES)} spaces -> {path}")
            for n in SPACES:
                print(f"  {n:10} {len(blob[n])//2} bytes")
        else:
            blob = json.load(open(path))
            if cmd == "restore":
                for n in SPACES:
                    write_space(h, k, n, bytes.fromhex(blob[n]))
                    time.sleep(0.2)
                print("restored; verifying...")
            bad = 0
            for n in SPACES:
                live = read_space(h, k, n)
                want = bytes.fromhex(blob[n])
                diff = sum(1 for a, b in zip(live, want) if a != b)
                bad += diff
                print(f"  {n:10} {'OK' if diff == 0 else f'{diff} bytes DIFFER'}")
            print("all spaces match" if bad == 0 else f"TOTAL {bad} differing bytes")
    else:
        raise SystemExit(__doc__)
    h.close()


if __name__ == "__main__":
    main()
