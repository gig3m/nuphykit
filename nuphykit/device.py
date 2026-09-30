"""Transport, session and framing for the NuPhy Air100 V3.

Everything here is verified against hardware. See PROTOCOL.md for the evidence
tier behind each claim; section numbers are cited inline.
"""
from __future__ import annotations

import os
import sys
import time

# The hidapi wheel's default backend on Linux is libusb, which reports every
# interface as usage 0/0 (so the raw interface can't be told apart) and needs
# access to /dev/bus/usb. Its hidraw backend reports usages and opens the
# /dev/hidraw nodes a udev uaccess rule grants to the desktop user.
if sys.platform.startswith("linux"):
    import hidraw as hid
else:
    import hid

VID = 0x19F5
PID_APP = 0x102D          # application firmware
PID_UPGRADER = 0x072D     # bootloader ("Air100 V3 Upgrader")
PID_DONGLE = 0x2620       # 2.4G receiver - its own firmware, forwards nothing (§83)

FLAG_CMD = 0x55           # host -> device
FLAG_REPLY = 0xAA         # device -> host
REPORT_LEN = 64           # confirmed from the firmware's own HID descriptor (§65)

# NuPhy's own command names, recovered from webpack module 40877 export S4.
COMMANDS = {
    0x2F: "GetDongelName", 0xA0: "GetBase", 0xA1: "GetFirmwareInfo",
    0xB1: "GetDefaultKeys", 0xB2: "GetUseKeys", 0xB3: "SetUseKeys",
    0xB4: "RestoreUseLayers", 0xB5: "GetSOCD", 0xB6: "SetSOCD", 0xB7: "ResetSOCD",
    0xB8: "GetTapDance", 0xB9: "SetTapDance", 0xBA: "ResetTapDance",
    0xBB: "GetTGL", 0xBC: "SetTGL", 0xBD: "ResetTGL",
    0xC1: "SetKeyUpload", 0xC2: "GetMacro", 0xC3: "SetMacro",
    0xD1: "GetLightCount", 0xD2: "GetKeyLightColor", 0xD5: "GetLightState",
    0xD6: "SetLightState", 0xE1: "GetKeyboardFunc", 0xE2: "SetKeyboardFunc",
    0xE3: "SetDebounceTime", 0xE4: "TestDelayTime", 0xE5: "SetTouchBarConfig",
    0xE6: "GetTouchBarConfig", 0xEE: "SetSecretKey", 0xEF: "SetIapMode",
    0xF1: "RestoreFactory", 0xF3: "GetSleepInfo", 0xF5: "SetSleepCfg",
    0xFA: "GetAppDefineSize", 0xFB: "GetAppDefine", 0xFC: "SetAppDefine",
    0xFD: "GetDebugEnable", 0xFE: "SetDebugLog",
}

# Commands that change or destroy state. The CLI refuses these without --force.
DESTRUCTIVE = {
    0xEF: "SetIapMode - reboots into the bootloader; the keyboard stops working "
          "as a keyboard until reflashed (recoverable via NuPhyIO)",
    0xF1: "RestoreFactory - wipes ALL FIVE config spaces",
    0xB4: "RestoreUseLayers - restores layer defaults",
    0xB7: "ResetSOCD", 0xBA: "ResetTapDance", 0xBD: "ResetTGL",
}


class NuPhyError(RuntimeError):
    pass


class Device:
    """One raw-HID session with the keyboard.

    Every instance performs its own 0xEE handshake. That mints a new session key
    and ORPHANS any session NuPhyIO currently holds, so the app's subsequent
    writes are ack'd and silently discarded until it is reloaded (§60). Reads are
    unaffected in both directions.
    """

    def __init__(self, path: bytes | None = None):
        self.h = hid.device()
        self.h.open_path(path or self._find())
        self.key = self._handshake()

    @staticmethod
    def _find() -> bytes:
        for d in hid.enumerate(VID, PID_APP):
            # The raw interface is usage_page 0x01 / usage 0x00 - NOT the
            # keyboard collection. Confirmed from the firmware descriptor (§65).
            if d.get("usage_page") == 0x01 and d.get("usage") == 0x00:
                return d["path"]
        if hid.enumerate(VID, PID_UPGRADER):
            raise NuPhyError(
                "keyboard is in BOOTLOADER mode (PID 0x072D). Recover it by "
                "opening NuPhyIO, which detects and reflashes automatically."
            )
        raise NuPhyError("Air100 V3 not found (is it plugged in?)")

    @staticmethod
    def find_dongle() -> bytes:
        """The DONGLE's raw interface. Same frame format, but every command is
        answered by the dongle itself - nothing reaches the keyboard (§83)."""
        for d in hid.enumerate(VID, PID_DONGLE):
            if d.get("usage_page") == 0x01 and d.get("usage") == 0x00:
                return d["path"]
        raise NuPhyError("Air100 V3 dongle not found")

    # -- framing ---------------------------------------------------------
    def frame(self, cmd: int, payload: list[int]) -> bytes:
        """[0]=0x55 [1]=cmd [2]=0 [3]=checksum [4..]=payload XOR session key."""
        o = bytearray(REPORT_LEN)
        o[0], o[1], o[2] = FLAG_CMD, cmd, 0x00
        enc = [(b ^ self.key) & 0xFF for b in payload]
        o[4:4 + len(enc)] = bytes(enc)
        o[3] = sum(o[4:REPORT_LEN]) & 0xFF
        return bytes(o)

    def _drain(self):
        try:
            while self.h.read(REPORT_LEN, 1):
                pass
        except OSError:
            pass

    def _handshake(self) -> int:
        """0xEE: >=21 random bytes at offset 8; reply bytes 4-7 are all the key.

        An all-zero challenge is refused even at full length, so the content
        matters, not just the length (AUDIT B1).
        """
        self._drain()
        p = bytearray(REPORT_LEN)
        p[0], p[1], p[2] = FLAG_CMD, 0xEE, 0x00
        p[8:40] = os.urandom(32)
        p[3] = sum(p[4:REPORT_LEN]) & 0xFF
        self.h.write(b"\x00" + bytes(p))
        for _ in range(6):
            r = self.h.read(REPORT_LEN, 250)
            if r and r[0] == FLAG_REPLY and r[1] == 0xEE and r[4] == r[5] == r[6] == r[7]:
                return r[4]
        raise NuPhyError("handshake rejected by device")

    def request(self, cmd: int, payload: list[int], want: int = 0,
                wait: float = 0.06, tries: int = 5) -> bytes:
        """Send a command; return `want` decoded payload bytes (header stripped)."""
        self._drain()
        self.h.write(b"\x00" + self.frame(cmd, payload))
        if wait:
            time.sleep(wait)
        for _ in range(tries):
            r = self.h.read(REPORT_LEN, 150)
            if r and r[0] == FLAG_REPLY and r[1] == cmd:
                dec = bytes((b ^ self.key) & 0xFF for b in r[4:8 + want])
                return dec[4:]
        return b""

    def send(self, cmd: int, payload: list[int], wait: float = 0.15) -> None:
        """Fire-and-forget write.

        NOTE: the device ACKS writes it discards - an ack proves nothing (§3).
        Always verify by reading back, which is what the higher layers do.
        """
        self._drain()
        self.h.write(b"\x00" + self.frame(cmd, payload))
        time.sleep(wait)

    def close(self):
        try:
            self.h.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
