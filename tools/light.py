"""Read the lighting state (0xD5 GetLightState, 17 bytes).

    uv run --with hidapi python tools/light.py            # read once
    uv run --with hidapi python tools/light.py <label>    # read and append to a log

Used to map UI controls to bytes: read, change ONE control in NuPhyIO, read again.
Byte meanings established so far (PROTOCOL 62).
"""
import hid, os, sys, time

VID, PID = 0x19F5, 0x102D
LEN = 0x11
NAMES = {0: "effect", 1: "brightness", 2: "speed"}


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


def main():
    h = hid.device()
    h.open_path(dev())
    k = hs(h)
    drain(h)
    h.write(b"\x00" + frame(0xD5, [LEN, 0, 0, 0], k))
    time.sleep(0.06)
    for _ in range(5):
        r = h.read(64, 150)
        if r and r[0] == 0xAA and r[1] == 0xD5:
            d = bytes((b ^ k) & 0xFF for b in r[4:4 + 4 + LEN])[4:]
            line = " ".join(f"{x:02X}" for x in d)
            label = sys.argv[1] if len(sys.argv) > 1 else "read"
            print(f"{label:24} {line}")
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(root, "snapshots", "lightlog.txt"), "a") as f:
                f.write(f"{label}\t{line}\n")
            break
    h.close()


if __name__ == "__main__":
    main()
