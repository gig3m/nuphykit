"""Read / write the small named config spaces that live OUTSIDE the
0x0000-0x1BFF memory. restore.py does not cover these; a factory reset does.

    uv run --with hidapi python tools/cfg.py                    # read all
    uv run --with hidapi python tools/cfg.py sleep 1 9          # space idx value
    uv run --with hidapi python tools/cfg.py func 0 2

Spaces (PROTOCOL 60):

  func    0xE1 get / 0xE2 set   4 bytes
          0 Anti-Wobbliness  1=Low 2=Intermediate 3=High   (factory 2)
          1 Disable Win      0/1                           (factory 0)
          2 Disable Alt+F4   0/1                           (factory 0)
          3 Disable Alt+Tab  0/1                           (factory 0)

  sleep   0xF3 get / 0xF5 set   4 bytes
          0 Auto Sleep       0/1                           (factory 1)
          1 Level 1 Sleep    minutes                       (factory 6)
          2 Level 2 Sleep    minutes                       (factory 24)
          3 unknown                                        (factory 4)

  app     0xFB get / 0xFC set   AppDefine scratch, byte-addressed
          0xA8  Accessory Switch  0=Knob 1=Button

NOTE: every call here handshakes, which orphans NuPhyIO's session. Reload the
app (location.reload()) before expecting its writes to land again.
"""
import hid, os, sys, time

VID, PID = 0x19F5, 0x102D
SPACES = {                    # name: (get, set, default_len, default_addr)
    "func":  (0xE1, 0xE2, 4, 0),
    "sleep": (0xF3, 0xF5, 4, 0),
    "app":   (0xFB, 0xFC, 1, 0xA8),
}


def dev():
    d = hid.enumerate(VID, PID)
    return next(x["path"] for x in d if x.get("usage_page") == 1 and x.get("usage") == 0)


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


def hs(h):
    drain(h)
    p = bytearray(64)
    p[0], p[1], p[2] = 0x55, 0xEE, 0
    p[8:40] = os.urandom(32)
    p[3] = sum(p[4:64]) & 0xFF
    h.write(b"\x00" + bytes(p))
    for _ in range(6):
        r = h.read(64, 250)
        if r and r[0] == 0xAA and r[1] == 0xEE and r[4] == r[5] == r[6] == r[7]:
            return r[4]
    return None


def get(h, k, cmd, ln, addr):
    drain(h)
    h.write(b"\x00" + frame(cmd, [ln, addr & 0xFF, (addr >> 8) & 0xFF, 0], k))
    time.sleep(0.06)
    for _ in range(5):
        r = h.read(64, 150)
        if r and r[0] == 0xAA and r[1] == cmd:
            return bytes((b ^ k) & 0xFF for b in r[4:8 + ln])[4:]
    return None


def main():
    h = hid.device()
    h.open_path(dev())
    k = hs(h)
    if k is None:
        raise SystemExit("cfg: handshake failed")

    if len(sys.argv) >= 4:
        name, idx, val = sys.argv[1], int(sys.argv[2], 0), int(sys.argv[3], 0)
        if name not in SPACES:
            raise SystemExit(f"cfg: unknown space '{name}'; use {'/'.join(SPACES)}")
        g, s, ln, base = SPACES[name]
        drain(h)
        if name == "sleep":
            # 0xF5 ignores single-byte writes; it needs the whole record.
            # Read-modify-write. (0xE2 and 0xFC do accept single bytes.)
            rec = bytearray(get(h, k, g, ln, base) or bytes(ln))
            rec[idx] = val
            h.write(b"\x00" + frame(s, [ln, base & 0xFF, (base >> 8) & 0xFF, 0] + list(rec), k))
        else:
            addr = base + idx if name == "app" else idx
            h.write(b"\x00" + frame(s, [1, addr & 0xFF, (addr >> 8) & 0xFF, 0, val], k))
        time.sleep(0.3)
        print(f"wrote {name}[{idx}] = 0x{val:02X}")

    for name, (g, s, ln, base) in SPACES.items():
        d = get(h, k, g, ln, base)
        print(f"{name:6} {' '.join(f'{x:02X}' for x in d) if d else '(no reply)'}")
    h.close()


if __name__ == "__main__":
    main()
