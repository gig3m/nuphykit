"""Lighting: 0xD5 GetLightState / 0xD6 SetLightState, 17 bytes (PROTOCOL §62).

Byte map, established by reading before/after each single UI change:

    0   effect index, 1-based in UI order
    1   back-light brightness %      (00 = "Back Light off"; it is NOT a flag)
    2   speed / gear
    6-8 custom RGB, stored PRE-SCALED by brightness
    4   colour mode: 01 = cycling, 00 = fixed custom colour
    10  side-light brightness        (00 = "Side Light off"; also not a flag)

0xD6 accepts partial writes (§62). One record per Mac/Win mode: `mode` picks
it through the pad byte, defaulting to the active mode (§84).

There is no per-key colour control: 0xD2 GetKeyLightColor is a READ of the
rendered LED frame (357 bytes = 119 LEDs x 3) with no Set counterpart (§54), and
the app polls it to animate its own preview.
"""
from __future__ import annotations

from . import spaces
from .device import Device

LIGHT_LEN = 17
LED_COUNT = 119            # confirmed by GetLightCount (0xD1) = 0x77
LED_FRAME = LED_COUNT * 3  # 357

EFFECTS = [
    None, "Ray", "Stair", "Static", "Breath", "Flower", "Wave", "Ripple",
    "Spout", "Galaxy", "Rotation", "Ripple2", "Point", "Grid", "Time", "Rain",
    "Ribbon", "Gaming", "Identify", "Windmill", "Diagonal",
]  # index 0 unused; the UI really does list "Ripple" twice

EFFECT = 0
BACKLIGHT = 1
SPEED = 2
COLOUR_MODE = 4
RGB_R, RGB_G, RGB_B = 6, 7, 8
SIDELIGHT = 10


def get(dev: Device, mode: int | None = None) -> bytes:
    return spaces.read(dev, "light", mode)


def set(dev: Device, state: bytes, mode: int | None = None) -> None:
    if len(state) != LIGHT_LEN:
        raise ValueError(f"lighting state must be {LIGHT_LEN} bytes")
    spaces.write(dev, "light", state, mode)


def modify(dev: Device, mode: int | None = None, **fields) -> bytes:
    """Read-modify-write named fields. Returns the new state.

    e.g. modify(dev, effect=6, backlight=50, sidelight=60)
    """
    names = {"effect": EFFECT, "backlight": BACKLIGHT, "speed": SPEED,
             "colour_mode": COLOUR_MODE, "sidelight": SIDELIGHT}
    rec = bytearray(get(dev, mode))
    if len(rec) != LIGHT_LEN:
        raise RuntimeError("could not read lighting state")
    for k, v in fields.items():
        if k == "rgb":
            r, g, b = v
            rec[RGB_R], rec[RGB_G], rec[RGB_B] = r & 0xFF, g & 0xFF, b & 0xFF
            rec[COLOUR_MODE] = 0x00          # fixed colour, not cycling
        elif k in names:
            rec[names[k]] = v & 0xFF
        else:
            raise ValueError(f"unknown lighting field {k!r}")
    set(dev, bytes(rec), mode)
    return bytes(rec)


def describe(state: bytes) -> str:
    if len(state) < LIGHT_LEN:
        return "(unreadable)"
    eff = state[EFFECT]
    name = EFFECTS[eff] if 0 < eff < len(EFFECTS) else f"?{eff}"
    mode = "cycling" if state[COLOUR_MODE] else "fixed"
    return (f"effect {eff} ({name})  backlight {state[BACKLIGHT]}%  "
            f"speed {state[SPEED]}  colour {mode} "
            f"#{state[RGB_R]:02X}{state[RGB_G]:02X}{state[RGB_B]:02X}  "
            f"sidelight {state[SIDELIGHT]}")


def read_led_frame(dev: Device) -> bytes:
    """Read the live rendered LED frame (357 bytes, RGB per LED).

    This is what the app polls to animate its on-screen preview. It is READ-ONLY:
    there is no SetKeyLightColor in the command set, so per-key colour cannot be
    driven this way.
    """
    out = bytearray()
    while len(out) < LED_FRAME:
        off = len(out)
        ln = min(0x36, LED_FRAME - off)
        out += dev.request(0xD2, [ln, off & 0xFF, (off >> 8) & 0xFF, 0], want=ln)
    return bytes(out[:LED_FRAME])


# --- Per-key custom colour (hidden, PROTOCOL 76-77) --------------------------
# opcode 0xD8 writes a per-LED RGB table; it renders only under a hidden effect
# index (>= 21) that the app never selects. Record = (index, R, G, B).
CUSTOM_EFFECT = 21
SET_KEY_COLOR = 0xD8


def enable_custom(dev: Device) -> None:
    """Switch to the hidden per-key custom-colour effect so 0xD8 renders."""
    st = bytearray(get(dev))
    st[EFFECT] = CUSTOM_EFFECT
    st[COLOUR_MODE] = 0
    set(dev, bytes(st))


def set_key_colors(dev: Device, colors: dict) -> None:
    """colors: {led_index: (r, g, b)}. LEDs not listed are left unchanged.

    Auto-splits into 14-LED frames. Requires enable_custom() (or effect >= 21)
    to be visible.
    """
    recs = [(i, r, g, b) for i, (r, g, b) in colors.items()]
    for i in range(0, len(recs), 14):
        data = []
        for idx, r, g, b in recs[i:i + 14]:
            data += [idx & 0xFF, r & 0xFF, g & 0xFF, b & 0xFF]
        dev.send(SET_KEY_COLOR, [len(data), 0, 0, 0] + data, wait=0.08)


def clear_keys(dev: Device) -> None:
    set_key_colors(dev, {i: (0, 0, 0) for i in range(LED_COUNT)})
