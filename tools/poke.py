"""Write one 16-bit value at a raw address. For probing regions that are not
keymap slots (knob tables, config blobs).

    uv run --with hidapi python tools/poke.py 0x06E0 0x0004

Writes are 16-bit aligned by construction. Verify afterwards with restore.py.
"""
import hid, os, sys, time

VID, PID = 0x19F5, 0x102D


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


def read16(h, k, addr):
    drain(h)
    h.write(b"\x00" + frame(0xB2, [2, addr & 0xFF, (addr >> 8) & 0xFF, 0], k))
    for _ in range(4):
        r = h.read(64, 80)
        if r and r[0] == 0xAA and r[1] == 0xB2:
            d = bytes((b ^ k) & 0xFF for b in r[4:10])[4:]
            return (d[0] << 8) | d[1]
    return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    if len(sys.argv) == 2:                       # read-only mode
        addr = int(sys.argv[1], 0)
        h = hid.device()
        h.open_path(dev())
        k = hs(h)
        print(f"0x{addr:04X}: 0x{read16(h, k, addr):04X}")
        h.close()
        return
    addr, val = int(sys.argv[1], 0), int(sys.argv[2], 0)
    if addr & 1:
        raise SystemExit(f"poke: 0x{addr:04X} is odd; unaligned writes corrupt the neighbour")
    if val > 0xFFFF:
        raise SystemExit(f"poke: 0x{val:X} exceeds 16 bits")

    h = hid.device()
    h.open_path(dev())
    k = hs(h)
    if k is None:
        raise SystemExit("poke: handshake failed")
    before = read16(h, k, addr)
    drain(h)
    h.write(b"\x00" + frame(0xB3, [2, addr & 0xFF, (addr >> 8) & 0xFF, 0,
                                   (val >> 8) & 0xFF, val & 0xFF], k))
    time.sleep(0.22)
    after = read16(h, k, addr)
    print(f"0x{addr:04X}: 0x{before:04X} -> 0x{after:04X}"
          f"{'' if after == val else '   *** WRITE DID NOT TAKE ***'}")
    h.close()


if __name__ == "__main__":
    main()
