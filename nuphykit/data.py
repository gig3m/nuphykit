"""Board data: the key matrix and the keycode table.

`matrix.json` legends are FIXED PHYSICAL labels — what is printed on the keycap.
They are deliberately not derived from live keycodes, which is what produced the
old bogus "F14/F15" entries (NuPhyIO's Key Bindings panel renders assigned
keycodes, while its Lighting panel renders physical legends).

`keycodes.json` is NuPhy's own table, extracted from webpack module 82206. Its
values are the app's 24-bit UI enum; the WIRE is 16-bit, so anything above
0xFFFF is a UI-level name and cannot be written directly.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@lru_cache(maxsize=1)
def matrix() -> list[dict]:
    with open(os.path.join(ROOT, "matrix.json")) as f:
        return json.load(f)["keys"]


@lru_cache(maxsize=1)
def by_legend() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for k in matrix():
        out.setdefault(k["legend"].upper(), k)
    return out


@lru_cache(maxsize=1)
def by_slot() -> dict[int, dict]:
    return {k["addr"] // 2: k for k in matrix()}


@lru_cache(maxsize=1)
def key_led() -> dict:
    """Physical legend -> LED index (row-major, 18/row). Verified rows 0-3."""
    try:
        return json.load(open(os.path.join(ROOT, "key_led.json")))["map"]
    except FileNotFoundError:
        return {k["legend"]: k["row"] * 18 + k["col"]
                for k in matrix()}


@lru_cache(maxsize=1)
def keycodes() -> dict[str, int]:
    try:
        with open(os.path.join(ROOT, "keycodes.json")) as f:
            raw = json.load(f)
    except FileNotFoundError:
        return {}
    out = {}
    items = raw.items() if isinstance(raw, dict) else []
    for name, v in items:
        try:
            out[name.upper()] = int(v, 0) if isinstance(v, str) else int(v)
        except (TypeError, ValueError):
            continue
    return out


@lru_cache(maxsize=1)
def keycode_names() -> dict[int, str]:
    """16-bit wire value -> shortest name. Entries above 0xFFFF are UI-only."""
    out: dict[int, str] = {}
    for n, v in keycodes().items():
        if v <= 0xFFFF and (v not in out or len(n) < len(out[v])):
            out[v] = n
    return out


def resolve_slot(spec: str) -> int:
    """Accept a slot number, 'rRcC', or a physical legend such as CAPS."""
    s = spec.strip()
    if s.isdigit():
        return int(s)
    low = s.lower()
    if low.startswith("r") and "c" in low:
        try:
            r, c = low[1:].split("c")
            return int(r) * 18 + int(c)
        except ValueError:
            pass
    k = by_legend().get(s.upper())
    if k is None:
        raise ValueError(f"unknown key {spec!r}; try a slot number, rRcC, or a legend")
    return k["addr"] // 2


def resolve_keycode(spec: str) -> int:
    """Accept 0x1234, a decimal, or a keycode name such as KC_A."""
    s = spec.strip()
    try:
        return int(s, 0)
    except ValueError:
        pass
    name = s.upper()
    for cand in (name, f"KC_{name}"):
        if cand in keycodes():
            v = keycodes()[cand]
            if v > 0xFFFF:
                raise ValueError(
                    f"{cand} = 0x{v:06X} is a UI-level enum value; the wire is "
                    f"16-bit and the device would truncate it to 0x{v & 0xFFFF:04X}")
            return v
    raise ValueError(f"unknown keycode {spec!r}")


def describe_keycode(v: int) -> str:
    from .keymap import MO_BASE, TG_BASE, TT_BASE, HYPER, KC_TRNS
    if v == KC_TRNS:
        return "TRNS"
    if v == HYPER:
        return "HYPER"
    if MO_BASE <= v <= MO_BASE + 15:
        return f"MO({v - MO_BASE})"
    if TG_BASE <= v <= TG_BASE + 15:
        return f"TG({v - TG_BASE})"
    if TT_BASE <= v <= TT_BASE + 15:
        return f"TT({v - TT_BASE})"
    n = keycode_names().get(v)
    if n:
        return n
    if 0x0100 <= v <= 0x1FFF:
        m = (v >> 8) & 0x1F
        parts = [x for b, x in ((1, "C"), (2, "S"), (4, "A"), (8, "G")) if m & b]
        return f"{'+'.join(parts) or 'mod'}({v & 0xFF:#04x})"
    return f"0x{v:04X}"
