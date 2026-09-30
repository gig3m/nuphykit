"""Live stream of the keyboard's unsolicited reports - debug log included.

The firmware pushes frames on the raw interface without being asked (§82):

    0xFE  LogUpload         its printf debug log - radio, pairing, BLE, RSSI
    0xA2  ModeStateChange   active layer; fires on Fn, TG(n) and the Mac/Win switch
    0xD7  LightStateChange  the 17-byte lighting record of the mode just entered

These are PLAINTEXT - not XORed with a session key - so listening needs no
handshake and does not orphan NuPhyIO's session.
"""
from __future__ import annotations

import time

from .device import Device, REPORT_LEN, hid

LOG_UPLOAD = 0xFE
MODE_STATE = 0xA2
LIGHT_STATE = 0xD7


def decode(r: bytes, pending: list[str]) -> str | None:
    """Turn one report into a line, or None while a multi-part log is incomplete.

    A log frame is `fe <parts> <index> <text...>`; long messages span several
    frames sharing `parts`, sent in index order, padded with spaces.
    """
    if r[0] == 0xAA:
        # A reply to some other client's command - every reader of the raw
        # interface sees every report. Not ours to print.
        return None
    if r[0] == LOG_UPLOAD:
        parts, index = r[1], r[2]
        pending.append(bytes(r[3:]).split(b"\0")[0].decode("latin1"))
        if index + 1 < parts:
            return None
        text = "".join(pending).rstrip()
        pending.clear()
        return text
    if r[0] == MODE_STATE:
        return f"[mode] layer {r[1]}  {bytes(r[:4]).hex(' ')}"
    if r[0] == LIGHT_STATE:
        return f"[light] {bytes(r[1:18]).hex(' ')}"
    return f"[0x{r[0]:02X}] {bytes(r[:16]).hex(' ')}"


def listen(raw: bool = False, duration: float | None = None) -> None:
    h = hid.device()
    h.open_path(Device._find())
    t0, pending = time.time(), []
    try:
        while duration is None or time.time() - t0 < duration:
            r = h.read(REPORT_LEN, 250)
            if not r:
                continue
            if raw:
                print(f"{time.time() - t0:9.3f}  {bytes(r).hex(' ')}", flush=True)
                continue
            line = decode(bytes(r), pending)
            if line is not None:
                print(f"{time.time() - t0:9.3f}  {line}", flush=True)
    finally:
        h.close()
