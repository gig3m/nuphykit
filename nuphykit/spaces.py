"""The storage spaces, and the Mac/Win mode they are split by.

The board does NOT keep its settings in one place. Anything calling itself a
backup must cover all of them or say plainly that it does not (PROTOCOL §63).

    name       get   set   size     write granularity
    config     0xB2  0xB3  0x1C00   16-bit words only (a 1-byte write writes 2)
    func       0xE1  0xE2  4        single byte; one record PER Mac/Win MODE
    sleep      0xF3  0xF5  4        WHOLE RECORD ONLY
    appdefine  0xFB  0xFC  0x03BA   single byte; tail ALIASES Mac light + func
    light      0xD5  0xD6  17       single byte; one record PER Mac/Win MODE

Payload byte 3 - the "pad" byte - selects the mode for `func` and `light`
(§84). Equal to the active mode it touches the live copy; otherwise it goes
straight to the other mode's record in flash. So per-mode spaces are read and
written once per mode, and a snapshot holds `light@mac`, `light@win`,
`func@mac`, `func@win`.

The last 0x14 bytes of appdefine (from 0x3A6) are not app scratch: the firmware
bounds 0xFB/0xFC at 0x400, and that tail is the Mac light record and Mac func
bytes. Writes here stop short of it so they cannot clobber them.

Not covered, because no command reaches them: the Ctrl<->Caps swap flag
(`keymap_config`, §58/§84) and the radio link slots - BLE bonds and 2.4G
pairing (§84).
"""
from __future__ import annotations

from dataclasses import dataclass

from .device import Device

MAC, WIN = 0, 1
MODES = {"mac": MAC, "win": WIN}
APPDEFINE_ALIAS = 0x3A6   # appdefine[0x3A6:] aliases the Mac light + func records


@dataclass(frozen=True)
class Space:
    name: str
    get: int
    set: int
    size: int
    chunk: int
    whole_record: bool
    note: str = ""
    word: bool = False       # writes must be whole 16-bit words at even addresses
    per_mode: bool = False   # one record per Mac/Win mode, chosen by the pad byte


SPACES: dict[str, Space] = {
    "config": Space("config", 0xB2, 0xB3, 0x1C00, 0x38, False,
                    "keymap (8 banks x 0xDC), macro table+arena, SOCD/TapDance/TGL",
                    word=True),
    "func": Space("func", 0xE1, 0xE2, 4, 4, False,
                  "0 debounce x10 ms (1-3)  1 disableWin  2 disableAltF4  3 disableAltTab",
                  per_mode=True),
    "sleep": Space("sleep", 0xF3, 0xF5, 4, 4, True,
                   "0 autoSleep  1 level1 minutes  2 level2 minutes  3 early-sleep seconds"),
    "appdefine": Space("appdefine", 0xFB, 0xFC, 0x3BA, 0x38, False,
                       "app scratch; 0x70 version string, 0xA8 accessory 0=knob 1=button"),
    "light": Space("light", 0xD5, 0xD6, 17, 17, False,
                   "0 effect(1-20) 1 backlight% 2 speed 4 colourMode 6-8 RGB 10 sidelight",
                   per_mode=True),
}

FACTORY = {           # observed after a real factory reset (§59)
    "func": bytes([0x02, 0x00, 0x00, 0x00]),
    "sleep": bytes([0x01, 0x06, 0x18, 0x04]),
}


def active_mode(dev: Device) -> int:
    """0 = Mac, 1 = Windows: GetBase (0xA0) reply byte 0 (§84)."""
    b = dev.request(0xA0, [0x38, 0, 0, 0], want=1)
    if not b:
        raise ValueError("could not read the active Mac/Win mode")
    return b[0]


def _pad(dev: Device, s: Space, mode: int | None) -> int:
    if not s.per_mode:
        return 0
    return active_mode(dev) if mode is None else mode


def read(dev: Device, name: str, mode: int | None = None) -> bytes:
    """Read a space. Per-mode spaces default to the ACTIVE mode."""
    s = SPACES[name]
    pad = _pad(dev, s, mode)
    out = bytearray()
    for off in range(0, s.size, s.chunk):
        ln = min(s.chunk, s.size - off)
        got = dev.request(s.get, [ln, off & 0xFF, (off >> 8) & 0xFF, pad], want=ln)
        out += got if len(got) >= ln else bytes(ln)
    return bytes(out[:s.size])


def write(dev: Device, name: str, data: bytes, mode: int | None = None) -> None:
    """Write a space, honouring its granularity.

    `sleep` rejects partial writes - they are ack'd and silently discarded (§61),
    so it is always written whole. `appdefine` stops at APPDEFINE_ALIAS.
    """
    s = SPACES[name]
    if len(data) != s.size:
        raise ValueError(f"{name}: expected {s.size} bytes, got {len(data)}")
    pad = _pad(dev, s, mode)
    if s.whole_record:
        dev.send(s.set, [s.size, 0, 0, pad] + list(data), wait=0.3)
        return
    if name == "appdefine":
        data = data[:APPDEFINE_ALIAS]
    step = 48
    for off in range(0, len(data), step):
        chunk = data[off:off + step]
        dev.send(s.set,
                 [len(chunk), off & 0xFF, (off >> 8) & 0xFF, pad] + list(chunk),
                 wait=0.12)


def set_byte(dev: Device, name: str, index: int, value: int,
             mode: int | None = None) -> None:
    """Change one byte, read-modify-writing when the space demands it.

    `config` writes whole 16-bit words: a 1-byte `0xB3` write also overwrites the
    next byte with garbage, at even addresses as well as odd (§44). So the byte's
    word is read, patched and written back whole.
    """
    s = SPACES[name]
    if not 0 <= index < s.size:
        # 0xE2 is NOT bounds-checked by the firmware: past byte 3 it scribbles
        # over RAM (active mode) or the keymap in flash (inactive mode) - §84.
        raise ValueError(f"{name}: index {index} outside 0..{s.size - 1}")
    if name == "appdefine" and index >= APPDEFINE_ALIAS:
        raise ValueError(f"appdefine[0x{index:X}] aliases the Mac light/func "
                         "records; change those through `light`/`func`")
    pad = _pad(dev, s, mode)
    if s.word:
        a = index & ~1
        w = bytearray(dev.request(s.get, [2, a & 0xFF, (a >> 8) & 0xFF, 0], want=2))
        if len(w) != 2:
            raise ValueError(f"{name}: could not read word at 0x{a:04X}")
        w[index & 1] = value
        dev.send(s.set, [2, a & 0xFF, (a >> 8) & 0xFF, 0] + list(w), wait=0.25)
    elif s.whole_record:
        rec = bytearray(read(dev, name, pad))
        rec[index] = value
        write(dev, name, bytes(rec), pad)
    else:
        dev.send(s.set, [1, index & 0xFF, (index >> 8) & 0xFF, pad, value], wait=0.25)


def keys() -> list[tuple[str, str, int | None]]:
    """(snapshot key, space name, mode) for everything a snapshot holds."""
    out = []
    for n, s in SPACES.items():
        if s.per_mode:
            out += [(f"{n}@{m}", n, v) for m, v in MODES.items()]
        else:
            out.append((n, n, None))
    return out


def _owned(name: str, data: bytes) -> bytes:
    """The bytes a space is responsible for - appdefine minus its aliased tail."""
    return data[:APPDEFINE_ALIAS] if name == "appdefine" else data


def _legacy(snap: dict[str, str]) -> dict[str, str]:
    """Snapshots before §84 hold bare `light`/`func`, read with pad 0 = Mac."""
    snap = dict(snap)
    for n, s in SPACES.items():
        if s.per_mode and n in snap and f"{n}@mac" not in snap:
            snap[f"{n}@mac"] = snap.pop(n)
    return snap


def snapshot(dev: Device) -> dict[str, str]:
    snap = {k: read(dev, n, m).hex() for k, n, m in keys()}
    snap["_active_mode"] = ["mac", "win"][active_mode(dev)]
    return snap


def compare(dev: Device, snap: dict[str, str]) -> dict[str, int]:
    """Return {snapshot key: number of differing bytes} for keys the snapshot has."""
    snap = _legacy(snap)
    out = {}
    for k, n, m in keys():
        if k not in snap:
            continue
        live = _owned(n, read(dev, n, m))
        want = _owned(n, bytes.fromhex(snap[k]))
        out[k] = sum(1 for a, b in zip(live, want) if a != b) + abs(len(live) - len(want))
    return out


def restore(dev: Device, snap: dict[str, str]) -> list[str]:
    """Write back every key that differs from the board. Returns what was written.

    Unchanged keys are skipped - fewer flash writes, and an inactive mode's
    record is never rewritten needlessly. appdefine goes before light/func so
    the per-mode records have the last word over its aliasing tail.
    """
    snap = _legacy(snap)
    order = sorted(keys(), key=lambda t: SPACES[t[1]].per_mode)
    done = []
    for k, n, m in order:
        if k not in snap:
            continue
        want = bytes.fromhex(snap[k])
        if _owned(n, read(dev, n, m)) != _owned(n, want):
            write(dev, n, want, m)
            done.append(k)
    return done
