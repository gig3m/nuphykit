"""Hardware-free tests for nuphykit's pure logic.

    uv run --with hidapi python tests/test_pure.py

These cover the parts that can be wrong silently: address arithmetic, keycode and
slot resolution, and the flash frame builder (checked against real captured
frames from NuPhyIO).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nuphykit import bootloader, data, keymap, lighting  # noqa: E402

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
