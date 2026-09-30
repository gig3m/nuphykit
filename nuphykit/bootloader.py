"""Bootloader / IAP (PROTOCOL §67).

Entering the bootloader is captured and verified. **Writing firmware from this
module is NOT.** See the warning on `flash()`.

Entry:      0xEF SetIapMode, payload 02 00 00 00, from a normal session.
Enumerates: VID 0x19F5 / PID 0x072D, usage_page 0xFF00, "Air100 V3 Upgrader".

It is NOT a stock WCH ISP device - the VID stays NuPhy's, so `wchisp` and
friends will not talk to it. The protocol is its own, but trivial:

    81 07 00 00 00 00                     begin / erase
    80 38 <addr:32 LE> <56 data bytes>    write
    82 38 <addr:32 LE> <56 data bytes>    verify

No 0x55 header, no checksum byte, no session, no XOR - unlike application mode.
Addresses run from 0, stepping 0x38, covering the whole image.

Recovery: open NuPhyIO. It detects upgrade mode by itself, downloads the image
and reflashes with no physical intervention. A flash PRESERVES all five config
spaces (verified byte-identical before/after).
"""
from __future__ import annotations

import time

from .device import Device, hid, NuPhyError, VID, PID_UPGRADER

CMD_BEGIN = 0x81      # frame: 81 07 00 00 00 00 ...   (0x07 is a constant, not a length)
CMD_WRITE = 0x80      # frame: 80 <len> <addr:32 LE> <data>
CMD_VERIFY = 0x82     # frame: 82 <len> <addr:32 LE> <data>   same data, second pass
CMD_FINALIZE = 0x83   # frame: 83 02 00 00 00 00 ...  -> device reboots into the app
BLOCK = 0x38          # 56 data bytes per frame; the LAST block is short (24 for 1.0.6.6)


def in_bootloader() -> bool:
    return bool(hid.enumerate(VID, PID_UPGRADER))


def enter(dev: Device) -> None:
    """Reboot into the bootloader.

    The keyboard STOPS BEING A KEYBOARD until it is reflashed. Power cycling does
    not exit (HAZARD 4) - only a reflash does. Make sure another input device is
    available before calling this.
    """
    try:
        dev.send(0xEF, [0x02, 0x00, 0x00, 0x00], wait=0.3)
    except OSError:
        pass          # the device drops off the bus mid-write; expected
    for _ in range(30):
        if in_bootloader():
            return
        time.sleep(0.2)
    raise NuPhyError("device did not re-enumerate as the Upgrader")


def open_upgrader():
    for d in hid.enumerate(VID, PID_UPGRADER):
        h = hid.device()
        h.open_path(d["path"])
        return h
    raise NuPhyError("Upgrader (PID 0x072D) not present")


def _frame(cmd: int, arg: int, addr: int = 0, data: bytes = b"") -> bytes:
    """cmd, arg(=len for data frames), 32-bit LE address, then the payload.

    Verified byte-identical against NuPhyIO's captured frames.
    """
    o = bytearray(64)
    o[0], o[1] = cmd, arg
    o[2] = addr & 0xFF
    o[3] = (addr >> 8) & 0xFF
    o[4] = (addr >> 16) & 0xFF
    o[5] = (addr >> 24) & 0xFF
    o[6:6 + len(data)] = data
    return bytes(o)


def build_frames(image: bytes) -> list[bytes]:
    """The exact frame sequence NuPhyIO sends, as verified by capture.

    Pure function - builds the frames without touching hardware, so it can be
    checked against a capture before anything is written.
    """
    out = [_frame(CMD_BEGIN, 0x07)]
    for phase in (CMD_WRITE, CMD_VERIFY):
        for off in range(0, len(image), BLOCK):
            chunk = image[off:off + BLOCK]
            out.append(_frame(phase, len(chunk), off, chunk))
    out.append(_frame(CMD_FINALIZE, 0x02))
    return out


def flash(image: bytes, confirm: str = "") -> None:
    """Write a firmware image. **UNTESTED - THIS CAN BRICK THE BOARD.**

    The frame layout below is reconstructed from a captured NuPhyIO flash and is
    believed correct, but this code path has never been executed. It is also
    unknown whether the bootloader validates the image at all (signature, CRC,
    magic) - only NuPhy's own image has ever been sent.

    If a bad image is accepted, NuPhyIO's recovery flow may or may not be able to
    put things right. Requires confirm="I understand this may brick the board".
    """
    if confirm != "I understand this may brick the board":
        raise NuPhyError(
            "flash() is untested and potentially destructive; pass the explicit "
            "confirm string if you really mean it")
    h = open_upgrader()
    try:
        frames = build_frames(image)
        for i, f in enumerate(frames):
            h.write(b"\x00" + f)
            if i == 0:
                time.sleep(0.2)      # let the erase settle
    finally:
        try:
            h.close()
        except Exception:
            pass
