"""nuphykit CLI.

    uv run --with hidapi python -m nuphykit show
    uv run --with hidapi python -m nuphykit backup <name>
    uv run --with hidapi python -m nuphykit verify <name>
    uv run --with hidapi python -m nuphykit restore <name>
    uv run --with hidapi python -m nuphykit key <slot> <keycode> [--layer N] [--both]
    uv run --with hidapi python -m nuphykit hyper-caps
    uv run --with hidapi python -m nuphykit light [--effect N] [--backlight N] ...
    uv run --with hidapi python -m nuphykit keycolor 255,0,0 W A S D --clear
    uv run --with hidapi python -m nuphykit cfg <space> <index> <value>
    uv run --with hidapi python -m nuphykit log [--raw] [--seconds N]
    uv run --with hidapi python -m nuphykit diag [--seconds N] [--out FILE] [--show-keys]
    uv run --with hidapi python -m nuphykit dongle-debug [on|off]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import data, diag, keymap, lighting, log, spaces
from .device import COMMANDS, Device, NuPhyError

# In a checkout, backups live in the repo's snapshots/; installed, in ./snapshots.
_REPO_SNAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "snapshots")
SNAP = _REPO_SNAP if os.path.isdir(_REPO_SNAP) else os.path.join(os.getcwd(), "snapshots")


def _path(name):
    os.makedirs(SNAP, exist_ok=True)
    return os.path.join(SNAP, f"kit_{name}.json")


def cmd_show(dev, a):
    active = spaces.active_mode(dev)
    print(f"  active mode: {['Mac', 'Windows'][active]}")
    for k, n, m in spaces.keys():
        s = spaces.SPACES[n]
        d = spaces.read(dev, n, m)
        if n == "config":
            import hashlib
            print(f"  {k:10} {len(d)} bytes  sha256={hashlib.sha256(d).hexdigest()[:16]}")
        elif n == "appdefine":
            acc = d[0xA8] if len(d) > 0xA8 else -1
            print(f"  {k:10} {len(d)} bytes  accessory={'button' if acc else 'knob'}")
        else:
            print(f"  {k:10} {' '.join(f'{x:02X}' for x in d)}")
        if n == "light":
            print(f"             {lighting.describe(d)}")
        if a.verbose and m != spaces.WIN:
            print(f"             {s.note}")
    print("\n  NOT captured by any of these: the Ctrl<->Caps swap flag and the "
          "radio link slots (BLE bonds, 2.4G pairing) - PROTOCOL 84.")


def cmd_backup(dev, a):
    json.dump(spaces.snapshot(dev), open(_path(a.name), "w"), indent=1)
    print(f"backed up all {len(spaces.SPACES)} spaces (light and func for both "
          f"Mac and Windows) -> {_path(a.name)}")


def cmd_verify(dev, a):
    snap = json.load(open(_path(a.name)))
    diffs = spaces.compare(dev, snap)
    for n, d in diffs.items():
        print(f"  {n:10} {'OK' if d == 0 else f'{d} bytes DIFFER'}")
    total = sum(diffs.values())
    print("all spaces match" if total == 0 else f"TOTAL {total} differing bytes")
    return 0 if total == 0 else 1


def cmd_restore(dev, a):
    snap = json.load(open(_path(a.name)))
    done = spaces.restore(dev, snap)
    print(f"restored {', '.join(done) if done else 'nothing - already identical'}; verifying...")
    return cmd_verify(dev, a)


def cmd_layout(dev, a):
    bank = keymap.read_bank(dev, a.layer)
    rows = {}
    for k in data.matrix():
        slot = k["addr"] // 2
        v = (bank[2 * slot] << 8) | bank[2 * slot + 1]
        rows.setdefault(k["row"], []).append((k["col"], k["legend"], v))
    print(f"  bank {a.layer} ({'Mac' if a.layer < 4 else 'Windows'} set)")
    for r in sorted(rows):
        cells = " ".join(f"{lg}={data.describe_keycode(v)}"
                         for _, lg, v in sorted(rows[r]))
        print(f"    r{r}: {cells}")
    knob = [(keymap.KNOB_CCW_SLOT, "knob-CCW"), (keymap.KNOB_CW_SLOT, "knob-CW")]
    print("    knob: " + "  ".join(
        f"{lbl}={data.describe_keycode((bank[2*s] << 8) | bank[2*s+1])}"
        for s, lbl in knob))


def cmd_key(dev, a):
    a.slot = data.resolve_slot(str(a.slot))
    kc = data.resolve_keycode(a.keycode)
    fn = keymap.set_key_both_banks if a.both else keymap.set_key
    fn(dev, a.slot, kc, a.layer, force=a.force)
    back = keymap.get_key(dev, a.slot, a.layer)
    print(f"slot {a.slot} layer {a.layer} <- 0x{kc:04X}; readback 0x{back:04X} "
          f"{'OK' if back == kc else 'MISMATCH'}")
    if kc in keymap.INERT:
        print(f"  NOTE: 0x{kc:04X} is {keymap.INERT[kc]} - it stores but does nothing")
    print("  readback proves STORAGE, not behaviour - press the key to confirm")


def cmd_hyper_caps(dev, a):
    if a.tap_esc:
        # Mod-tap works on this firmware (§22): tap = Esc, hold = Hyper.
        kc, what = keymap.mt(keymap.HYPER, 0x29), "tap Esc / hold Hyper"
    else:
        kc, what = keymap.HYPER, "Hyper"
    keymap.set_key_both_banks(dev, 54, kc)
    print(f"Caps Lock = {what} (0x{kc:04X}) in banks 0 and 4, "
          "so it survives the Mac/Win switch")


def cmd_light(dev, a):
    fields = {k: v for k, v in
              (("effect", a.effect), ("backlight", a.backlight),
               ("speed", a.speed), ("sidelight", a.sidelight))
              if v is not None}
    if a.rgb:
        fields["rgb"] = tuple(int(x, 0) for x in a.rgb.split(","))
    if not fields:
        print("  " + lighting.describe(lighting.get(dev, a.mode)))
        return
    print("  " + lighting.describe(lighting.modify(dev, a.mode, **fields)))


def cmd_keycolor(dev, a):
    """Light specific keys a colour via the hidden per-key mode (PROTOCOL 76-77)."""
    kl = data.key_led()
    r, g, b = (int(x, 0) for x in a.rgb.split(","))
    if a.clear:
        lighting.clear_keys(dev)
    colors = {}
    for key in a.keys:
        led = kl.get(key.upper())
        if led is None:
            led = int(key, 0)   # allow raw LED index
        colors[int(led)] = (r, g, b)
    lighting.enable_custom(dev)
    lighting.set_key_colors(dev, colors)
    print(f"lit {len(colors)} key(s) #{r:02X}{g:02X}{b:02X} via effect "
          f"{lighting.CUSTOM_EFFECT} (hidden per-key mode)")


def cmd_cfg(dev, a):
    spaces.set_byte(dev, a.space, a.index, int(a.value, 0), a.mode)
    print(f"  {a.space} -> "
          f"{' '.join(f'{x:02X}' for x in spaces.read(dev, a.space, a.mode)[:8])}")


def cmd_commands(dev, a):
    for c in sorted(COMMANDS):
        print(f"  0x{c:02X}  {COMMANDS[c]}")


def main(argv=None):
    p = argparse.ArgumentParser(prog="nuphykit", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("show").set_defaults(fn=cmd_show)
    sub.add_parser("commands").set_defaults(fn=cmd_commands)
    for nm, fn in (("backup", cmd_backup), ("verify", cmd_verify), ("restore", cmd_restore)):
        sp = sub.add_parser(nm)
        sp.add_argument("name")
        sp.set_defaults(fn=fn)

    sp = sub.add_parser("layout")
    sp.add_argument("--layer", type=int, default=0)
    sp.set_defaults(fn=cmd_layout)

    sp = sub.add_parser("key")
    sp.add_argument("slot", help="slot number, rRcC, or a physical legend e.g. CAPS")
    sp.add_argument("keycode", help="0x0F00, 4, or a name e.g. KC_A")
    sp.add_argument("--layer", type=int, default=0)
    sp.add_argument("--both", action="store_true",
                    help="write the Windows bank too (recommended)")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_key)

    sp = sub.add_parser("hyper-caps")
    sp.add_argument("--tap-esc", action="store_true",
                    help="tap for Esc, hold for Hyper (mod-tap) - e.g. for Vim")
    sp.set_defaults(fn=cmd_hyper_caps)

    sp = sub.add_parser("light")
    for f in ("effect", "backlight", "speed", "sidelight"):
        sp.add_argument(f"--{f}", type=int)
    sp.add_argument("--rgb", help="R,G,B (also switches to fixed colour)")
    sp.add_argument("--mode", type=lambda v: spaces.MODES[v], choices=[0, 1],
                    metavar="{mac,win}", help="which mode's record (default: active)")
    sp.set_defaults(fn=cmd_light)

    sp = sub.add_parser("keycolor")
    sp.add_argument("rgb", help="R,G,B e.g. 255,0,0")
    sp.add_argument("keys", nargs="+", help="key legends (CAPS W A S D) or LED indices")
    sp.add_argument("--clear", action="store_true", help="turn all other keys off first")
    sp.set_defaults(fn=cmd_keycolor)

    sp = sub.add_parser("cfg")
    sp.add_argument("space", choices=list(spaces.SPACES))
    sp.add_argument("index", type=int)
    sp.add_argument("value")
    sp.add_argument("--mode", type=lambda v: spaces.MODES[v], choices=[0, 1],
                    metavar="{mac,win}",
                    help="for func/light: which mode's record (default: active)")
    sp.set_defaults(fn=cmd_cfg)

    sp = sub.add_parser("log", help="stream the firmware debug log and state reports")
    sp.add_argument("--raw", action="store_true", help="hex frames, undecoded")
    sp.add_argument("--seconds", type=float, help="stop after N seconds")

    sp = sub.add_parser("diag", help="wireless timeline: key timing + link events + fw log")
    sp.add_argument("--seconds", type=float, help="stop after N seconds")
    sp.add_argument("--out", help="also append the timeline to this file")
    sp.add_argument("--show-keys", action="store_true",
                    help="print key codes in flagged events (hidden by default)")

    sp = sub.add_parser("dongle-debug", help="read/set the dongle's persistent debug-log flag")
    sp.add_argument("state", nargs="?", choices=["on", "off"])

    a = p.parse_args(argv)
    try:
        if a.cmd == "dongle-debug":
            # Talks to the DONGLE, not the keyboard. 0xFE persists one flag word
            # in the dongle's data flash; nothing else is written (§83).
            with Device(Device.find_dongle()) as dongle:
                if a.state:
                    dongle.send(0xFE, [0, 0, 0, 0, 1 if a.state == "on" else 0], wait=0.3)
                flag = dongle.request(0xFD, [0, 0, 0, 0], want=1)
                print(f"dongle debug log: {'on' if flag and flag[0] else 'off'}")
            return 0
        if a.cmd == "diag":
            out = open(a.out, "a") if a.out else None
            diag.Diag(a.show_keys, out).run(a.seconds)
            return 0
        if a.cmd == "log":
            # Plaintext reports: no handshake, so NuPhyIO's session survives.
            log.listen(a.raw, a.seconds)
            return 0
        with Device() as dev:
            return a.fn(dev, a) or 0
    except (NuPhyError, ValueError) as e:
        print(f"nuphykit: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
