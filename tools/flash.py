"""Flash a firmware image using the reconstructed protocol (PROTOCOL 67/68).

    uv run --with hidapi python tools/flash.py <image.bin>

The device must already be in bootloader mode (tools/enter_iap.py).

This writes firmware. A wrong image can leave the board unusable. The frame
sequence is verified byte-for-byte against a capture of NuPhyIO's own flash, but
this SENDER has its own risks: dropped or mis-paced frames would corrupt the
image. If the flash fails partway the board stays in the bootloader, which
NuPhyIO can recover.
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nuphykit import bootloader as bl        # noqa: E402

if len(sys.argv) < 2:
    raise SystemExit(__doc__)
img = open(sys.argv[1], "rb").read()
print(f"image: {sys.argv[1]}  {len(img)} bytes")

if not bl.in_bootloader():
    raise SystemExit("device is not in bootloader mode; run tools/enter_iap.py first")

frames = bl.build_frames(img)
print(f"frames: {len(frames)}")

h = bl.open_upgrader()
t0 = time.time()
sent = 0
try:
    for i, f in enumerate(frames):
        h.write(b"\x00" + f)
        sent += 1
        if i == 0:
            time.sleep(0.25)          # let the erase settle
        elif i % 512 == 0:
            time.sleep(0.004)         # gentle pacing
            print(f"  {i}/{len(frames)}", flush=True)
finally:
    try:
        h.close()
    except Exception:
        pass
print(f"sent {sent} frames in {time.time()-t0:.1f}s")
