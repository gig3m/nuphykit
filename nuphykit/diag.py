"""Wireless diagnostics: one timeline of key timing, link events and the firmware log.

The usual "rrrrr" is a LOST OR LATE KEY-UP: the host sees a key go down, the up
arrives late, and the compositor's autorepeat fills the gap. Chatter (duplicate
down/up pairs) is a different fault. This separates them and lines each one up
against what the keyboard's radio reported at the time (§82).

Sources, all read-only:
  evdev      every NuPhy input node - dongle (2.4G), Bluetooth, cable. Nodes
             appearing/vanishing are logged as link events.
  fw         the keyboard's raw interface over the cable, if plugged in - its
             firmware debug log (0xFE) and state reports. No handshake.
  dongle     the dongle's own debug log, if enabled (`nuphykit dongle-debug on`):
             queue flushes and channel hops on the receiver side (§83).

Key identities are hidden unless --show-keys: the tool needs timing, not text.
"""
from __future__ import annotations

import glob
import os
import select
import struct
import subprocess
import time

from . import log
from .device import Device, NuPhyError, REPORT_LEN, hid

EVENT = struct.Struct("llHHi")      # struct input_event on 64-bit Linux
EV_KEY = 1
MODIFIERS = {29, 42, 54, 56, 97, 100, 125, 126, 58}   # ctrl shift alt meta caps
CHATTER_MS = 40                     # re-press this soon after release = chatter
RESCAN_S = 1.0

# Firmware log lines that mark a radio fault (PROTOCOL §84 ranked causes).
RADIO_FAULTS = {
    "loss a key": "dropped_report",     # a report - maybe a key-up - given up on
    "over 50 times": "retry_exhausted",
    "disconnect": "rf_disconnect",
    "prepare hop": "hop",
    "do hop": "hop",
    "jump to channel": "hop",           # dongle side
    "over send remove": "dongle_flush",
    "queue is full": "queue_flush",
    "Full, clear the queue": "queue_flush",
    "kbd shuld sleep": "host_suspend_sleep",
}


def repeat_delay_ms() -> int:
    """The compositor's autorepeat delay - a key-up later than this repeats."""
    try:
        out = subprocess.run(["hyprctl", "getoption", "input:repeat_delay"],
                             capture_output=True, text=True, timeout=2).stdout
        return int(out.split("int:")[1].split()[0])
    except Exception:
        return 600


def _nodes() -> dict[str, str]:
    """{/dev/input/eventN: label} for every NuPhy keyboard-ish input node."""
    out = {}
    for e in glob.glob("/sys/class/input/event*"):
        try:
            name = open(f"{e}/device/name").read().strip()
            bus = open(f"{e}/device/id/bustype").read().strip()
        except OSError:
            continue
        if "Air100" not in name and "NuPhy" not in name:
            continue
        if any(x in name for x in ("Mouse", "System Control", "Consumer Control")):
            continue
        link = "bt" if bus == "0005" else ("2.4g" if "Dongle" in name else "cable")
        out[f"/dev/input/{os.path.basename(e)}"] = link
    return out


class Diag:
    def __init__(self, show_keys=False, out=None):
        self.show_keys = show_keys
        self.out = out
        self.delay = repeat_delay_ms()
        self.t0 = time.time()
        self.fds: dict[int, tuple[str, str]] = {}   # fd -> (path, link)
        self.raws: dict[str, object] = {}          # "fw"/"dongle" -> hid handle
        self.pending: dict[str, list[str]] = {"fw": [], "dongle": []}
        self.down: dict[tuple[str, int], float] = {}
        self.last_up: dict[tuple[str, int], float] = {}
        self.flagged: set[tuple[str, int]] = set()   # late-up already reported
        self.started = False
        self.stats: dict[str, dict[str, int]] = {}

    # -- output ----------------------------------------------------------
    def emit(self, kind: str, msg: str, t: float | None = None):
        t = time.time() if t is None else t
        clock = time.strftime("%H:%M:%S", time.localtime(t))
        line = f"{clock} {t - self.t0:9.3f}  {kind:7} {msg}"
        print(line, flush=True)
        if self.out:
            self.out.write(line + "\n")
            self.out.flush()

    def key(self, code: int) -> str:
        if self.show_keys:
            return f"key {code}"
        return "modifier" if code in MODIFIERS else "key"

    def count(self, link: str, what: str):
        s = self.stats.setdefault(link, {})
        s[what] = s.get(what, 0) + 1

    # -- sources ---------------------------------------------------------
    def rescan(self):
        now = _nodes()
        have = {p for p, _ in self.fds.values()}
        appeared = set()
        for path, link in now.items():
            if path in have:
                continue
            try:
                fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            except OSError as e:
                self.emit("warn", f"cannot open {path}: {e}")
                continue
            self.fds[fd] = (path, link)
            if self.started:
                self.emit("link", f"{link} input node appeared ({path})")
                if link not in appeared:     # one device brings several nodes
                    appeared.add(link)
                    self.count(link, "reconnects")
        for src, find, what in (("fw", Device._find, "keyboard firmware log (cable)"),
                                ("dongle", Device.find_dongle, "dongle log")):
            if src in self.raws:
                continue
            try:
                h = hid.device()
                h.open_path(find())
                h.set_nonblocking(1)
                self.raws[src] = h
                self.emit("link", f"listening: {what}")
            except (NuPhyError, OSError):
                pass

    def drop(self, fd: int):
        path, link = self.fds.pop(fd)
        os.close(fd)
        self.emit("link", f"{link} input node VANISHED ({path}) - disconnect")
        self.count(link, "disconnects")
        for k in [k for k in self.down if k[0] == link]:
            self.emit("STUCK", f"{link} {self.key(k[1])} was down at disconnect")
            del self.down[k]
            self.flagged.discard(k)

    def on_key(self, link: str, code: int, value: int, t: float):
        k = (link, code)
        if value == 1:
            prev_up = self.last_up.get(k)
            if prev_up is not None and (t - prev_up) * 1000 < CHATTER_MS:
                self.emit("CHATTER", f"{link} {self.key(code)} re-pressed "
                          f"{(t - prev_up) * 1000:.0f} ms after release", t)
                self.count(link, "chatter")
            # A new press while another non-modifier key has been held past the
            # repeat delay is the signature of a lost key-up: nobody types a
            # second letter while deliberately holding the first.
            for (l2, c2), t2 in self.down.items():
                if l2 == link and c2 != code and c2 not in MODIFIERS \
                        and code not in MODIFIERS and (t - t2) * 1000 > self.delay \
                        and (l2, c2) not in self.flagged:
                    self.flagged.add((l2, c2))
                    self.emit("LATE-UP", f"{link} {self.key(c2)} still down "
                              f"{(t - t2) * 1000:.0f} ms when the next key was "
                              f"pressed (repeat delay {self.delay} ms)", t)
                    self.count(link, "late_up")
            self.down[k] = t
            self.count(link, "presses")
        elif value == 0:
            t_down = self.down.pop(k, None)
            self.last_up[k] = t
            self.flagged.discard(k)
            if t_down is not None and code not in MODIFIERS:
                held = (t - t_down) * 1000
                if held > self.delay:
                    self.emit("LONG", f"{link} {self.key(code)} held {held:.0f} ms "
                              f"(> {self.delay} ms: host would autorepeat)", t)
                    self.count(link, "long_holds")

    def read_evdev(self, fd: int):
        path, link = self.fds[fd]
        try:
            data = os.read(fd, EVENT.size * 64)
        except BlockingIOError:
            return
        except OSError:
            self.drop(fd)
            return
        for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
            sec, usec, typ, code, value = EVENT.unpack_from(data, i)
            if typ == EV_KEY:
                self.on_key(link, code, value, sec + usec / 1e6)

    def read_raw(self, src: str):
        try:
            while True:
                r = self.raws[src].read(REPORT_LEN)
                if not r:
                    return
                line = log.decode(bytes(r), self.pending[src])
                if line is None:
                    continue
                fault = next((v for k, v in RADIO_FAULTS.items() if k in line), None)
                if fault:
                    self.emit("RADIO", f"[{src}] {line}")
                    self.count(src, fault)
                else:
                    self.emit(src, line)
        except OSError:
            del self.raws[src]
            self.emit("link", f"{src} raw interface lost")

    # -- main loop -------------------------------------------------------
    def run(self, duration: float | None = None):
        self.rescan()
        self.started = True
        links = sorted({l for _, l in self.fds.values()}) or ["none"]
        self.emit("start", f"watching {', '.join(links)}; repeat delay {self.delay} ms; "
                  f"keys {'SHOWN' if self.show_keys else 'hidden'}")
        next_scan = time.time() + RESCAN_S
        try:
            while duration is None or time.time() - self.t0 < duration:
                r, _, _ = select.select(list(self.fds), [], [], 0.05)
                for fd in r:
                    if fd in self.fds:
                        self.read_evdev(fd)
                for src in list(self.raws):
                    self.read_raw(src)
                if time.time() >= next_scan:
                    self.rescan()
                    next_scan = time.time() + RESCAN_S
        except KeyboardInterrupt:
            pass
        finally:
            self.summary()
            for fd in list(self.fds):
                os.close(fd)
            for h in self.raws.values():
                h.close()

    def summary(self):
        self.emit("summary", "per link: " + ("; ".join(
            f"{l}: " + ", ".join(f"{k}={v}" for k, v in sorted(s.items()))
            for l, s in sorted(self.stats.items())) or "no key activity"))
