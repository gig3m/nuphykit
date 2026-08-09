"""Read / write the keyboard-function config space (0xE1 GetKeyboardFunc,
0xE2 SetKeyboardFunc). This space is SEPARATE from the 0x0000-0x1BFF config
memory -- restore.py does not cover it and a golden.bin restore will not undo
changes made here. A factory reset does.

    uv run --with hidapi python tools/kbfunc.py                 # read
    uv run --with hidapi python tools/kbfunc.py <index> <value> # write one byte

Payload shape is the uniform one: <len> <addr:16 LE> <pad> <data...>, matching
captured traffic (0xE2 01 00 00 00 <1|2|3>, 0xE2 01 01 00 00 <0|1>).

Known values, from the factory-reset differential (PROTOCOL 59):
    byte 0   0x02 at factory, was 0x08 before
    byte 1   0x00 at factory, was 0x08 while the Ctrl<->Caps swap was ACTIVE
"""
import hid, os, sys, time

VID, PID = 0x19F5, 0x102D
CMD_GET, CMD_SET = 0xE1, 0xE2


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


def read(h, k):
    drain(h)
    h.write(b"\x00" + frame(CMD_GET, [0x04, 0, 0, 0], k))
    time.sleep(0.06)
    for _ in range(5):
        r = h.read(64, 150)
        if r and r[0] == 0xAA and r[1] == CMD_GET:
            return bytes((b ^ k) & 0xFF for b in r[4:12])[4:8]
    return None


def main():
    h = hid.device()
    h.open_path(dev())
    k = hs(h)
    if k is None:
        raise SystemExit("kbfunc: handshake failed")

    before = read(h, k)
    print(f"read : {' '.join(f'{x:02X}' for x in before)}")

    if len(sys.argv) >= 3:
        idx, val = int(sys.argv[1], 0), int(sys.argv[2], 0)
        if not 0 <= idx <= 3 or not 0 <= val <= 0xFF:
            raise SystemExit("kbfunc: index 0-3, value 0-255")
        drain(h)
        h.write(b"\x00" + frame(CMD_SET, [0x01, idx, 0x00, 0x00, val], k))
        time.sleep(0.25)
        after = read(h, k)
        print(f"wrote: byte {idx} = 0x{val:02X}")
        print(f"read : {' '.join(f'{x:02X}' for x in after)}"
              f"{'' if after and after[idx] == val else '   *** WRITE DID NOT TAKE ***'}")
    h.close()


if __name__ == "__main__":
    main()
