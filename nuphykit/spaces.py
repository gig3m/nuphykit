"""The five storage spaces.

The board does NOT keep its settings in one place. Anything calling itself a
backup must cover all five or say plainly that it does not (PROTOCOL §63).

    name       get   set   size     write granularity
    config     0xB2  0xB3  0x1C00   16-bit words only (a 1-byte write writes 2)
    func       0xE1  0xE2  4        single byte
    sleep      0xF3  0xF5  4        WHOLE RECORD ONLY
    appdefine  0xFB  0xFC  0x03BA   single byte
    light      0xD5  0xD6  17       single byte; one record PER Mac/Win MODE

Not covered, because the device exposes no way to read it: the firmware-level
Ctrl<->Caps swap (§58) is real and persistent, and is invisible to all of these.

Only partly covered: lighting is stored per Mac/Win mode, and `0xD5`/`0xD6` see
only the mode the switch is in now (§62). Back up once in each switch position.
"""
from __future__ import annotations

from dataclasses import dataclass

from .device import Device


@dataclass(frozen=True)
class Space:
    name: str
    get: int
    set: int
    size: int
    chunk: int
    whole_record: bool
    note: str = ""
    word: bool = False    # writes must be whole 16-bit words at even addresses


SPACES: dict[str, Space] = {
    "config": Space("config", 0xB2, 0xB3, 0x1C00, 0x38, False,
                    "keymap (8 banks x 0xDC), macro table+arena, SOCD/TapDance/TGL",
                    word=True),
    "func": Space("func", 0xE1, 0xE2, 4, 4, False,
                  "0 anti-wobble(1-3)  1 disableWin  2 disableAltF4  3 disableAltTab"),
    "sleep": Space("sleep", 0xF3, 0xF5, 4, 4, True,
                   "0 autoSleep  1 level1 minutes  2 level2 minutes  3 unknown"),
    "appdefine": Space("appdefine", 0xFB, 0xFC, 0x3BA, 0x38, False,
                       "app scratch; 0x70 version string, 0xA8 accessory 0=knob 1=button"),
    "light": Space("light", 0xD5, 0xD6, 17, 17, False,
                   "0 effect(1-20) 1 backlight% 2 speed 4 colourMode 6-8 RGB 10 sidelight; "
                   "active Mac/Win mode only"),
}

FACTORY = {           # observed after a real factory reset (§59)
    "func": bytes([0x02, 0x00, 0x00, 0x00]),
    "sleep": bytes([0x01, 0x06, 0x18, 0x04]),
}


def read(dev: Device, name: str) -> bytes:
    s = SPACES[name]
    out = bytearray()
    for off in range(0, s.size, s.chunk):
        ln = min(s.chunk, s.size - off)
        got = dev.request(s.get, [ln, off & 0xFF, (off >> 8) & 0xFF, 0], want=ln)
        out += got if len(got) >= ln else bytes(ln)
    return bytes(out[:s.size])


def write(dev: Device, name: str, data: bytes) -> None:
    """Write a space, honouring its granularity.

    `sleep` rejects partial writes - they are ack'd and silently discarded (§61),
    so it is always written whole.
    """
    s = SPACES[name]
    if len(data) != s.size:
        raise ValueError(f"{name}: expected {s.size} bytes, got {len(data)}")
    if s.whole_record:
        dev.send(s.set, [s.size, 0, 0, 0] + list(data), wait=0.3)
        return
    step = 48
    for off in range(0, len(data), step):
        chunk = data[off:off + step]
        dev.send(s.set,
                 [len(chunk), off & 0xFF, (off >> 8) & 0xFF, 0] + list(chunk),
                 wait=0.12)


def set_byte(dev: Device, name: str, index: int, value: int) -> None:
    """Change one byte, read-modify-writing when the space demands it.

    `config` writes whole 16-bit words: a 1-byte `0xB3` write also overwrites the
    next byte with garbage, at even addresses as well as odd (§44). So the byte's
    word is read, patched and written back whole.
    """
    s = SPACES[name]
    if s.word:
        a = index & ~1
        w = bytearray(dev.request(s.get, [2, a & 0xFF, (a >> 8) & 0xFF, 0], want=2))
        if len(w) != 2:
            raise ValueError(f"{name}: could not read word at 0x{a:04X}")
        w[index & 1] = value
        dev.send(s.set, [2, a & 0xFF, (a >> 8) & 0xFF, 0] + list(w), wait=0.25)
    elif s.whole_record:
        rec = bytearray(read(dev, name))
        rec[index] = value
        write(dev, name, bytes(rec))
    else:
        dev.send(s.set, [1, index & 0xFF, (index >> 8) & 0xFF, 0, value], wait=0.25)


def snapshot(dev: Device) -> dict[str, str]:
    return {n: read(dev, n).hex() for n in SPACES}


def compare(dev: Device, snap: dict[str, str]) -> dict[str, int]:
    """Return {space: number of differing bytes}."""
    out = {}
    for n in SPACES:
        live = read(dev, n)
        want = bytes.fromhex(snap[n])
        out[n] = sum(1 for a, b in zip(live, want) if a != b) + abs(len(live) - len(want))
    return out
