"""Reboot the keyboard into its bootloader (IAP mode).

The keyboard STOPS working as a keyboard until it is reflashed. Power cycling
does not exit; only a reflash does. NuPhyIO recovers it automatically.

    uv run --with hidapi python tools/enter_iap.py
"""
import sys, os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nuphykit.device import Device            # noqa: E402
from nuphykit import bootloader as bl         # noqa: E402

if bl.in_bootloader():
    print("already in bootloader (PID 0x072D)")
    sys.exit(0)

with Device() as d:
    bl.enter(d)
print("in bootloader:", bl.in_bootloader())
