"""Hardware-free tests for nuphykit's pure logic.

    uv run --with hidapi python tests/test_pure.py

These cover the parts that can be wrong silently: address arithmetic, keycode and
slot resolution, and the flash frame builder (checked against real captured
frames from NuPhyIO).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nuphykit import bootloader, data, diag, keymap, lighting, log, spaces  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FW = os.path.join(ROOT, "firmware", "Air100v3_US_v1.0.6.6_20260723.bin")

fails = []


def check(name, got, want):
    if got != want:
        fails.append(f"{name}: got {got!r}, want {want!r}")
        print(f"  FAIL {name}: got {got!r}, want {want!r}")
    else:
        print(f"  ok   {name}")


print("address arithmetic (PROTOCOL 19/34)")
check("slot 0 layer 0", keymap.addr(0, 0), 0x0000)
check("caps slot 54 layer 0", keymap.addr(54, 0), 0x006C)
check("caps slot 54 layer 4", keymap.addr(54, 4), 0x03DC)
check("slot 33 layer 0", keymap.addr(33, 0), 0x0042)
check("last slot 109 layer 7", keymap.addr(109, 7), 7 * 0xDC + 218)
check("keymap end", keymap.BANKS * keymap.BANK_BYTES, 0x06E0)
check("slot_of(3,0)", keymap.slot_of(3, 0), 54)
check("slot_of(5,9)", keymap.slot_of(5, 9), 99)

print("\nlayer keycode helpers")
check("MO(1)", keymap.mo(1), 0x5221)
check("MO(5)", keymap.mo(5), 0x5225)
check("TG(2)", keymap.tg(2), 0x5262)
check("hyper mask", keymap.mods(True, True, True, True), 0x0F00)
check("ctrl+c", keymap.mods(ctrl=True, keycode=0x06), 0x0106)

print("\nslot / keycode resolution")
check("legend CAPS", data.resolve_slot("CAPS"), 54)
check("legend lowercase", data.resolve_slot("caps"), 54)
check("rRcC form", data.resolve_slot("r3c0"), 54)
check("numeric", data.resolve_slot("33"), 33)
check("KC_A", data.resolve_keycode("KC_A"), 0x0004)
check("bare a", data.resolve_keycode("a"), 0x0004)
check("hex", data.resolve_keycode("0x0F00"), 0x0F00)

print("\nkeycode description")
check("describe A", data.describe_keycode(0x0004), "KC_A")
check("describe hyper", data.describe_keycode(0x0F00), "HYPER")
check("describe MO(1)", data.describe_keycode(0x5221), "MO(1)")
check("describe TRNS", data.describe_keycode(0x0001), "TRNS")

print("\nphysical legends must NOT be keycode names (the old F14/F15 bug)")
legends = {k["legend"] for k in data.matrix()}
for bad in ("F14", "F15", "MEDIA_PREV", "VOL_UP", "VOL_DOWN", "r5c9"):
    check(f"{bad} absent from legends", bad in legends, False)
for good in ("F1", "F12", "CAPS", "FN", "KNOB_CW", "KNOB_CCW"):
    check(f"{good} present", good in legends, True)

print("\nconfig byte writes are whole aligned words (PROTOCOL 44)")


class FakeDev:
    def __init__(self, mem):
        self.mem, self.sent = bytearray(mem), []

    def request(self, cmd, p, want=0, **kw):
        a = p[1] | p[2] << 8
        return bytes(self.mem[a:a + p[0]])

    def send(self, cmd, p, **kw):
        self.sent.append(p)


for idx, want in ((0x6C, [2, 0x6C, 0, 0, 0x2A, 0x39]), (0x6D, [2, 0x6C, 0, 0, 0x00, 0x2A])):
    fd = FakeDev(bytes(0x6C) + bytes([0x00, 0x39]))
    spaces.set_byte(fd, "config", idx, 0x2A)
    check(f"config set_byte 0x{idx:02X}", fd.sent, [want])
fd = FakeDev(bytes(4))
spaces.set_byte(fd, "func", 1, 1)
check("func set_byte stays 1 byte", fd.sent, [[1, 1, 0, 0, 1]])

fd = FakeDev(bytes(4))
spaces.set_byte(fd, "func", 1, 1, mode=spaces.WIN)
check("func set_byte win uses pad 1", fd.sent, [[1, 1, 0, 1, 1]])
for name, idx in (("func", 4), ("appdefine", 0x3A6), ("appdefine", 0x3B9)):
    try:
        spaces.set_byte(FakeDev(bytes(0x400)), name, idx, 0)
        check(f"{name}[0x{idx:X}] refused", "written", "ValueError")
    except ValueError:
        check(f"{name}[0x{idx:X}] refused", "ValueError", "ValueError")
check("legacy snapshot keys", sorted(spaces._legacy({"light": "00", "func": "01", "sleep": "02"})),
      ["func@mac", "light@mac", "sleep"])
check("snapshot keys", [k for k, _, _ in spaces.keys()],
      ["config", "func@mac", "func@win", "sleep", "appdefine", "light@mac", "light@win"])
check("appdefine tail not owned", len(spaces._owned("appdefine", bytes(0x3BA))), 0x3A6)
fd = FakeDev(bytes(0x400))
spaces.write(fd, "appdefine", bytes(0x3BA))
check("appdefine write stops at alias",
      max(p[1] | p[2] << 8 for p in fd.sent) + fd.sent[-1][0], 0x3A6)

print("\nunsolicited report decoding (PROTOCOL 82)")


def frame(*head, text=b""):
    return bytes(head) + text + b" " * (64 - len(head) - len(text))


pend = []
check("log single", log.decode(frame(0xFE, 1, 0, text=b"rf has connected \n"), pend),
      "rf has connected")
# A non-final part fills all 61 text bytes; the next part continues mid-word.
part1 = b"=" * 11 + b"keyboard want to pair, channel 34, addr 1207380725"
check("log part 1 waits", log.decode(bytes([0xFE, 2, 0]) + part1, pend), None)
check("log part 2 joins", log.decode(frame(0xFE, 2, 1, text=b" ======\n"), pend),
      part1.decode() + " ======")
check("replies to other clients ignored", log.decode(frame(0xAA, 0xB2, 0), pend), None)
check("mode report", log.decode(frame(0xA2, 4, 1), pend), "[mode] layer 4  a2 04 01 20")

print("\nwireless diag flagging")


def run_keys(events, delay=250):
    d = diag.Diag.__new__(diag.Diag)
    d.show_keys, d.out, d.delay, d.t0 = False, None, delay, 0.0
    d.down, d.last_up, d.flagged, d.stats = {}, {}, set(), {}
    kinds = []
    d.emit = lambda kind, msg, t=None: kinds.append(kind)
    for t, code, v in events:
        d.on_key("2.4g", code, v, t)
    return kinds, d.stats.get("2.4g", {})


K_R, K_E, K_SHIFT = 19, 18, 42
check("normal typing unflagged",
      run_keys([(0, K_R, 1), (0.08, K_R, 0), (0.2, K_E, 1), (0.27, K_E, 0)])[0], [])
check("late key-up flagged once",
      run_keys([(0, K_R, 1), (0.5, K_E, 1), (0.55, K_E, 0), (0.7, K_E, 1),
                (0.75, K_E, 0), (0.9, K_R, 0)])[0], ["LATE-UP", "LONG"])
check("held shift is not flagged",
      run_keys([(0, K_SHIFT, 1), (0.6, K_E, 1), (0.65, K_E, 0), (0.9, K_SHIFT, 0)])[0], [])
check("chatter flagged",
      run_keys([(0, K_E, 1), (0.05, K_E, 0), (0.07, K_E, 1), (0.12, K_E, 0)])[0], ["CHATTER"])

d = diag.Diag.__new__(diag.Diag)
d.stats, d.pending, kinds = {}, {"fw": []}, []
d.emit = lambda kind, msg, t=None: kinds.append(kind)


class OneShot:
    def __init__(self, frames):
        self.frames = list(frames)

    def read(self, n):
        return self.frames.pop(0) if self.frames else []


d.raws = {"fw": OneShot([frame(0xFE, 1, 0, text=b"loss a key 0, 21\n"),
                         frame(0xFE, 1, 0, text=b"====chan 2, rate 0, rssi -60, ack 1 ===\n")])}
d.read_raw("fw")
check("radio fault flagged", (kinds, d.stats), (["RADIO", "fw"], {"fw": {"dropped_report": 1}}))

print("\nlighting byte map")
st = bytes([0x06, 0x32, 0x02, 0x00, 0x01, 0x00, 0x00, 0x05, 0x80,
            0x04, 0x3C, 0x02, 0x01, 0x00, 0xFF, 0x00, 0x00])
check("effect index", st[lighting.EFFECT], 6)
check("effect name", lighting.EFFECTS[st[lighting.EFFECT]], "Wave")
check("backlight", st[lighting.BACKLIGHT], 50)
check("sidelight", st[lighting.SIDELIGHT], 60)
check("led frame size", lighting.LED_FRAME, 357)

if os.path.exists(FW):
    print("\nflash frame builder vs captured NuPhyIO frames (PROTOCOL 67/68)")
    img = open(FW, "rb").read()
    fr = bootloader.build_frames(img)
    check("frame count", len(fr), 10046)
    cap = {
        1: "81 07 00 00 00 00",
        2: "80 38 00 00 00 00 6f 20 00 30",
        3: "80 38 38 00 00 00",
        10045: "82 18 58 4a 04 00 02 00 00 00",
        10046: "83 02 00 00 00 00",
    }
    for n, exp in cap.items():
        got = " ".join(f"{x:02x}" for x in fr[n - 1][:len(exp.split())])
        check(f"frame n={n}", got, exp)
    check("last block is short", fr[10045 - 1][1], 0x18)
else:
    print("\n(firmware image absent - skipping flash frame tests)")

print()
if fails:
    print(f"{len(fails)} FAILURES")
    for f in fails:
        print("  " + f)
    sys.exit(1)
print("all tests passed")
