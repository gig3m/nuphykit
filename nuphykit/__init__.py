"""nuphykit — an open-source toolkit for the NuPhy Air100 V3.

NuPhy's V3 boards are QMK-derived but the VIA endpoint is gone, so no VIA JSON
will ever work. This package speaks their proprietary raw-HID protocol instead,
and covers things NuPhyIO does not expose: Hyper and arbitrary modifier combos,
layer LOCKING (TG), and backup/restore of ALL FIVE storage spaces rather than
just the keymap.

Everything here is derived from hardware experiments recorded in PROTOCOL.md,
with evidence tiers in AUDIT.md. Claims that are inference rather than
observation are marked as such in the source.
"""
from .device import Device, NuPhyError, COMMANDS, VID, PID_APP, PID_UPGRADER
from . import spaces, keymap, lighting, bootloader

__version__ = "0.1.0"
__all__ = ["Device", "NuPhyError", "COMMANDS", "VID", "PID_APP", "PID_UPGRADER",
           "spaces", "keymap", "lighting", "bootloader"]
