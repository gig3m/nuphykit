"""Capture EVERY readable piece of device state into one named snapshot, so a
single UI change can be diffed across the whole device instead of one window.

    uv run --with hidapi python tools/fullstate.py before
    # ... flip exactly ONE option in NuPhyIO, then quit the app ...
    uv run --with hidapi python tools/fullstate.py after
    python3 tools/statediff.py before after

Captures:
  * the config region 0x0000-0x1BFF via 0xB2 (the memory restore.py covers)
  * every read-only Get command in opcodes.json (18 of them)

Only Get* opcodes are sent. Nothing here writes. 0xEF SetIapMode (bootloader
entry) and every Set/Reset/Restore are deliberately excluded -- see HANDOFF
HAZARD 1, never sweep opcodes.

0xD2 GetKeyLightColor is captured but marked VOLATILE: it returns the live
rendered LED frame, which changes continuously under any animated effect, so it
would otherwise dominate every diff.
"""
import hid, json, os, sys, time

VID, PID = 0x19F5, 0x102D
REGION_END = 0x1C00
VOLATILE = {"0xD2"}          # live LED frame - changes on its own


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


def read_region(h, k, end):
    out = bytearray()
    for off in range(0, end, 0x38):
        ln = min(0x38, end - off)
        drain(h)
        h.write(b"\x00" + frame(0xB2, [ln, off & 0xFF, (off >> 8) & 0xFF, 0], k))
        got = None
        for _ in range(4):
            r = h.read(64, 80)
            if r and r[0] == 0xAA and r[1] == 0xB2:
                got = bytes((b ^ k) & 0xFF for b in r[4:4 + 4 + ln])[4:]
                break
        out += got if got else bytes(ln)
    return bytes(out)


def poll(h, k, cmd, ln=0x38):
    drain(h)
    h.write(b"\x00" + frame(cmd, [ln, 0, 0, 0], k))
    time.sleep(0.05)
    for _ in range(5):
        r = h.read(64, 150)
        if r and r[0] == 0xAA and r[1] == cmd:
            # Padding is RAW 0x00, which XOR-decodes to the session key - and the
            # key is fresh every session, so decoding first makes every reply
            # look changed. Trim on the raw bytes, then decode.
            raw = bytes(r[4:64])
            end = len(raw)
            while end > 0 and raw[end - 1] == 0x00:
                end -= 1
            body = bytes((b ^ k) & 0xFF for b in raw[:end])[4:]
            return body.hex()
    return None


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    name = sys.argv[1]
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmds = json.load(open(os.path.join(root, "opcodes.json")))["commands"]
    gets = {c: n for c, n in cmds.items() if n.lower().startswith("get")}

    h = hid.device()
    h.open_path(dev())
    k = hs(h)
    if k is None:
        raise SystemExit("fullstate: handshake failed (is NuPhyIO holding the device?)")

    region = read_region(h, k, REGION_END)
    state = {"name": name, "region_sha": None, "gets": {}, "volatile": sorted(VOLATILE)}
    import hashlib
    state["region_sha"] = hashlib.sha256(region).hexdigest()

    for c in sorted(gets, key=lambda x: int(x, 16)):
        if c == "0xB2":
            continue                      # captured as the region above
        state["gets"][c] = {"name": gets[c].split("[")[0].strip(),
                            "data": poll(h, k, int(c, 16))}
        time.sleep(0.04)
    h.close()

    snap = os.path.join(root, "snapshots")
    open(os.path.join(snap, f"state_{name}.bin"), "wb").write(region)
    json.dump(state, open(os.path.join(snap, f"state_{name}.json"), "w"), indent=1)

    ok = sum(1 for v in state["gets"].values() if v["data"])
    print(f"captured '{name}': region {len(region)} bytes, "
          f"{ok}/{len(state['gets'])} Get commands replied")
    for c, v in state["gets"].items():
        if not v["data"]:
            print(f"  no reply: {c} {v['name']}")


if __name__ == "__main__":
    main()
