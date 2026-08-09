"""Watch the USB tree for devices appearing/disappearing.

    python3 tools/usbwatch.py [seconds]

Used to catch a bootloader/ISP device that may only appear briefly. Polls the
full USB tree (not just HID), because WCH's ROM ISP is a vendor-class device and
would be invisible to hidapi.

Flags:
  VID 0x19F5  NuPhy       (0x102D app, 0x072D NuPhy's own IAP bootloader)
  VID 0x4348  WCH ISP     <- the unerasable ROM bootloader we are hunting
  VID 0x1A86  WCH/QinHeng <- ditto
"""
import re
import subprocess
import sys
import time

INTERESTING = {0x19F5: "NuPhy", 0x4348: "WCH ISP", 0x1A86: "WCH/QinHeng"}


def snapshot():
    out = subprocess.run(["ioreg", "-p", "IOUSB", "-w0", "-l"],
                         capture_output=True, text=True).stdout
    vids = [int(x) for x in re.findall(r'"idVendor" = (\d+)', out)]
    pids = [int(x) for x in re.findall(r'"idProduct" = (\d+)', out)]
    return sorted(zip(vids, pids))


def label(v, p):
    tag = INTERESTING.get(v)
    return f"VID 0x{v:04X} PID 0x{p:04X}" + (f"  <<< {tag}" if tag else "")


def main():
    dur = float(sys.argv[1]) if len(sys.argv) > 1 else 60
    prev = snapshot()
    print(f"watching for {dur:.0f}s — {len(prev)} USB devices at start")
    for v, p in prev:
        if v in INTERESTING:
            print(f"  present: {label(v, p)}")
    print("  ... unplug / replug now ...", flush=True)
    t0 = time.time()
    found_wch = False
    while time.time() - t0 < dur:
        time.sleep(0.4)
        cur = snapshot()
        if cur == prev:
            continue
        gone = [d for d in prev if d not in cur]
        new = [d for d in cur if d not in prev]
        ts = time.time() - t0
        for d in gone:
            if d[0] in INTERESTING:
                print(f"  [{ts:5.1f}s] REMOVED  {label(*d)}", flush=True)
        for d in new:
            if d[0] in INTERESTING:
                print(f"  [{ts:5.1f}s] ADDED    {label(*d)}", flush=True)
            if d[0] in (0x4348, 0x1A86):
                found_wch = True
                print("  *** WCH ROM ISP DETECTED ***", flush=True)
        prev = cur
    print("done. WCH ISP seen:" , found_wch)


if __name__ == "__main__":
    main()
