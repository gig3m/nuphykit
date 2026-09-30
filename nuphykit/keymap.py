"""Keymap: addressing, layers, and the capabilities NuPhyIO hides.

Address formula (§19/§34, T2):

    addr16 = layer * 0xDC + 2 * (row * 18 + col)

8 banks of 110 slots; 101 are real keys. Banks 0-3 are the Mac set, 4-7 Windows.
The physical Mac/Win switch selects the base bank LIVE, with no replug (§20, T1),
so **every remap must be written to `layer` and `layer + 4`** or it vanishes when
the switch moves.

Entries are 16-BIT on the wire (§21). The app's 24-bit enum values are UI-level.

CRITICAL: the keymap stores any 16-bit value without validating it. Readback
proves storage, never behaviour. Whether the firmware *implements* a keycode
needs a physical keypress.
"""
from __future__ import annotations

from .device import Device

STRIDE = 18            # matrix columns
BANK_BYTES = 0xDC      # 220 bytes = 110 slots per bank
BANKS = 8
SLOTS = 110
KEYMAP_END = BANKS * BANK_BYTES   # 0x06E0

# The knob is a synthetic "row 6" - there is no sixth physical row (§56, T1).
KNOB_CCW_SLOT = 108
KNOB_CW_SLOT = 109
KNOB_PRESS_SLOT = 13   # the swappable module position's ordinary key

# Quantum keycodes (stock QMK values; this firmware is QMK-derived).
KC_TRNS = 0x0001
MO_BASE = 0x5220       # MO(n) = 0x5220 | n
TG_BASE = 0x5260       # TG(n) - layer LOCK; NuPhyIO never ships this (§22.1)
TT_BASE = 0x52C0       # degrades to momentary on this firmware
HYPER = 0x0F00         # ctrl+shift+alt+gui as a mod mask, no keycode

# NuPhy's own advanced-function keycodes.
KC_SOCD_BASE = 0x7F00
KC_TAPDANCE_BASE = 0x7F40
KC_TOGGLE_BASE = 0x7F80

# Refuse these without an explicit override.
DANGEROUS = {
    0x7E00: "BOOT - reboots into the bootloader when pressed",
    0x7E13: "RESET - resets the keyboard when pressed",
    # CORRECTED 2026-09-29 [T2]: 0x7000 was listed as inert. It is live QMK magic -
    # pressing it persistently swaps Ctrl<->Caps (eeprom word 0x004), invisible to
    # the keymap and to every backup; 0x7001 clears it (§57/§84).
    0x7000: "MAGIC swap Ctrl<->Caps - persists when pressed, no command reads it; "
            "0x7001 clears it",
}

# Verified inert on this firmware - they store but do nothing (§57, T1).
INERT = {
    0x5600: "swap-hands (not compiled in)",
    0x56F1: "swap-hands toggle (not compiled in)",
}


def addr(slot: int, layer: int = 0) -> int:
    """Byte address of a matrix slot in a given bank."""
    if not 0 <= slot < SLOTS:
        raise ValueError(f"slot {slot} out of range 0..{SLOTS - 1}")
    if not 0 <= layer < BANKS:
        raise ValueError(f"layer {layer} out of range 0..{BANKS - 1}")
    return layer * BANK_BYTES + 2 * slot


def slot_of(row: int, col: int) -> int:
    return row * STRIDE + col


def get_key(dev: Device, slot: int, layer: int = 0) -> int:
    a = addr(slot, layer)
    d = dev.request(0xB2, [2, a & 0xFF, (a >> 8) & 0xFF, 0], want=2)
    return (d[0] << 8) | d[1] if len(d) >= 2 else -1


def set_key(dev: Device, slot: int, keycode: int, layer: int = 0,
            force: bool = False) -> None:
    """Write one 16-bit keycode. Writes must be 16-bit aligned (HAZARD 2)."""
    if keycode > 0xFFFF:
        raise ValueError(
            f"0x{keycode:06X} exceeds 16 bits; the device would truncate it to "
            f"0x{keycode & 0xFFFF:04X}")
    if keycode in DANGEROUS and not force:
        raise ValueError(f"0x{keycode:04X} is {DANGEROUS[keycode]}; pass force=True")
    a = addr(slot, layer)
    dev.send(0xB3, [2, a & 0xFF, (a >> 8) & 0xFF, 0,
                    (keycode >> 8) & 0xFF, keycode & 0xFF], wait=0.22)


def set_key_both_banks(dev: Device, slot: int, keycode: int, layer: int = 0,
                       force: bool = False) -> None:
    """Write to the Mac bank AND its Windows counterpart.

    This is what you almost always want: the Mac/Win switch selects the base bank
    live, so a Mac-only remap silently disappears when the switch moves (§20).
    """
    base = layer % 4
    set_key(dev, slot, keycode, base, force)
    set_key(dev, slot, keycode, base + 4, force)


def read_bank(dev: Device, layer: int = 0) -> bytes:
    out = bytearray()
    start = layer * BANK_BYTES
    for off in range(start, start + BANK_BYTES, 0x38):
        ln = min(0x38, start + BANK_BYTES - off)
        out += dev.request(0xB2, [ln, off & 0xFF, (off >> 8) & 0xFF, 0], want=ln)
    return bytes(out[:BANK_BYTES])


def mo(n: int) -> int:
    """Momentary layer - hold to activate. What NuPhyIO ships."""
    return MO_BASE | n


def tg(n: int) -> int:
    """Toggle/LOCK a layer. Works on this board; the app just never offers it.

    The escape must exist on the destination layer or you are stuck there.
    """
    return TG_BASE | n


def mods(ctrl=False, shift=False, alt=False, gui=False, keycode=0x00) -> int:
    """Build a modifier-mask keycode. The whole 0x0100-0x1FFF range works (§22)."""
    m = (0x01 if ctrl else 0) | (0x02 if shift else 0) \
        | (0x04 if alt else 0) | (0x08 if gui else 0)
    return (m << 8) | (keycode & 0xFF)
