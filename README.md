# nuphykit — open-source tooling for the NuPhy Air100 V3

NuPhy's Air100 V3 borrows QMK's *keycode numbering* but is **not QMK** — it's
custom firmware on a WCH CH58x, with the VIA endpoint absent. So no VIA JSON will
ever make `usevia.app` talk to it. NuPhy shipped a proprietary raw-HID protocol
and a so-so configurator instead.

This repo is a full reverse-engineering of that protocol, a toolkit that does
what NuPhyIO won't, and a documented map of the firmware down to the flash
protocol — enough to build custom firmware.

## What this gives you that NuPhyIO doesn't

- **Hyper on Caps Lock** — and any modifier combination. The whole `0x0100`–`0x1FFF`
  range works; NuPhyIO never offers it.
- **Per-key RGB** — NuPhy built it (`0xD8` + a hidden lighting mode) and never
  exposed it. `nuphykit keycolor 255,0,0 W A S D` lights those keys red.
- **Layer *locking*** — `TG(n)`. The board isn't momentary-only; NuPhy just never
  ships a toggle keycode. Layer chaining works 3 deep.
- **Backup/restore of everything.** The board keeps settings in **five separate
  places**; tools that read only the keymap silently lose the other four.
  `light` and `func` are kept **per Mac/Win mode**; `backup` saves both,
  whichever way the switch is set.
- **Writes to both Mac and Windows banks**, so a remap survives the physical
  Mac/Win switch (which selects the base bank *live*).

## Install

No install. Requires `hidapi`, pulled on demand with [uv](https://docs.astral.sh/uv/):

```bash
uv run --with hidapi python -m nuphykit show
```

On Linux the `hidraw` backend (bundled with `hidapi`) is used automatically;
the default libusb backend can't see HID usage pages, so it can't find the
raw interface. The CLI talks over the USB cable; it works with the board in
2.4G mode too (keystrokes then arrive via the dongle). Configuring through the
dongle alone is untested.

Quit NuPhyIO isn't required, but note that any CLI command orphans the app's
session until you reload it (see Hazards).

## Usage

```bash
python -m nuphykit show                     # all five spaces + lighting
python -m nuphykit backup mybackup          # everything
python -m nuphykit verify mybackup
python -m nuphykit restore mybackup

python -m nuphykit layout                   # decode the whole keymap with legends
python -m nuphykit hyper-caps               # Caps = Hyper, both banks
python -m nuphykit key CAPS KC_A --both     # by legend + keycode name
python -m nuphykit key r3c0 0x0F00 --both   # or by row/col, or raw slot number
python -m nuphykit light --effect 6 --backlight 50
python -m nuphykit keycolor 255,0,0 W A S D --clear   # PER-KEY colour
python -m nuphykit cfg func 1 1             # disable Win key
python -m nuphykit commands                 # NuPhy's own command names
python -m nuphykit log                      # live firmware debug log: radio, pairing, RSSI
```

## The five storage spaces

| space | get/set | size | granularity |
|-------|---------|------|-------------|
| `config` | `0xB2`/`0xB3` | `0x1C00` | whole 16-bit words (a 1-byte write writes 2) |
| `func` | `0xE1`/`0xE2` | 4 **per Mac/Win mode** | single byte (never past byte 3) |
| `sleep` | `0xF3`/`0xF5` | 4 (6 internally) | **whole record only** |
| `appdefine` | `0xFB`/`0xFC` | `0x03BA` | single byte; last `0x14` alias Mac `light`/`func` |
| `light` | `0xD5`/`0xD6` | 17 **per Mac/Win mode** | single byte |

Payload byte 3 picks the mode for `func`/`light` (PROTOCOL §84).

A factory reset clears all five. A **firmware flash preserves all five.**

## What was recovered from the firmware

All from static analysis of the (freely downloadable) firmware image — no
teardown:

- **Command dispatch table** — 42 commands, incl. 3 the app never sends
  (`0xD8` per-key RGB, `0xC4` macro-maintenance, `0xF4` RAM-only auto-sleep toggle).
- **Matrix pin map** — `matrix_pins.json` (rows `PB16/17/18/20/21/22`, 18 cols).
- **LED driver** — 2× AW20216S-class over SPI; per-LED channel map in
  `led_map.json`.
- **Flash protocol** — reimplemented and verified byte-for-byte vs NuPhyIO
  (`nuphykit/bootloader.py`).
- **CORRECTED 2026-09-29 [T2]:** `PA5`/`PA6` are the knob's rotary-encoder
  lines (QMK encoder table at `0x3FC84`), not the Mac/Win switch, which is still
  unlocated. The tap-dance code *does* have a hold path (register on timeout,
  unregister on key-up; 100 ms floor on the timing field), so the tap-hold
  limitation is not explained by the firmware code (PROTOCOL §73, §79).
- `0xE3`/`0xE5`/`0xE6` (debounce, touch-bar) are no-op acks in 1.0.6.6 — 38
  functional handlers plus the `0xEE` handshake (§76).

## Custom firmware — proven possible, recoverable on-device

The bootloader does **no image validation**. A one-byte edit to NuPhy's own
1.0.6.6 image, flashed with the code here, boots and reports the change over USB
(the serial string). All five config spaces survived byte-identical.

Recovery is buildable-in: because nothing validates the image and you flash the
whole app partition, keeping the stock USB + `0xEF` recovery code intact in every
build means `0xEF`-reflash always works — **no devboard needed for disciplined
development.** Only a build that fails to even enumerate USB needs WCH ROM ISP
(a BOOT pad inside the case). See `PROTOCOL.md` §67–§69, §81.

VIA specifically is reachable by **replacing** the firmware with the community
CH58x QMK port (`rgoulter/qmk_port_ch5xx`, which supports VIA) — the matrix pins
and LED map here are most of that board definition. ZMK is ruled out (Zephyr has
no CH58x support). See `PROTOCOL.md` §70–§71.

## Known gaps — read these

- **The Ctrl↔Caps swap** is QMK's `keymap_config` flag, almost certainly set by
  pressing `0x7000` during testing (PROTOCOL §57/§84). No command reads it; bind
  `0x7001` and press it once to clear it.
- **Readback proves storage, never behaviour.** The keymap stores any 16-bit
  value without validating it; `0x5600`/`0x56F1` store and do nothing. (`0x7000`
  looked inert too — it wasn't; see above.)
- **CH582 vs CH583 is unconfirmed** — the `0x82` in `GetBase` is a hardcoded
  constant, not a chip-ID read. Needs eyes on the PCB (§80).
- **Nothing has been compiled from source**; modifying firmware *code* (vs the
  descriptor byte) is untested.

## Hazards

1. **Never sweep opcodes.** A "benign" payload is a valid write, and `0xEF`
   enters the bootloader.
2. **Config writes must be whole 16-bit words** — a 1-byte write clobbers the
   next byte, at even addresses too.
3. **Never hold a capture only in page memory** — the page reloads when the
   device re-enumerates.
4. **Power cycling does not exit the bootloader**; only a reflash does (NuPhyIO
   recovers it automatically).
5. **Any CLI command orphans NuPhyIO's session** — its writes are ack'd and
   discarded until you reload the app.
6. **Host-side remappers corrupt results.** Raycast's Hyper Key on Caps Lock
   silently inverted a test result for four rounds. On Linux, read keypresses
   from `/dev/hidraw*` instead — below every remapper (the dongle's nodes in
   2.4G mode).

## Tests

```bash
uv run --with hidapi python tests/test_pure.py
```

Hardware-free. Covers address arithmetic, slot/keycode resolution, the lighting
byte map, and the flash frame builder checked against **real captured frames**.

## Documents

| file | contents |
|------|----------|
| `HANDOFF.md` | read first: board state, hazards, protocol on a page |
| `PROTOCOL.md` | the spec, every claim tagged by evidence tier |
| `AUDIT.md` | evidence rules and what is **not** proven |
| `SWEEP.md` | the UI-option sweep and its results |
| `firmware/README.md` | how to obtain the firmware (not included here) |

Claims are tagged **T1** (physical behaviour observed), **T2** (readback through a
different channel), **T3** (device ack — never counts), **T4** (inference).
Several confident claims turned out wrong mid-project; the audit records which and
why, and the corrections are made in place. That evidence discipline is the point
as much as the results.

## Firmware & legal

The firmware binary and NuPhy's web-app bundle are **not** in this repo — they're
NuPhy's copyrighted work and aren't ours to redistribute. The firmware is
published by NuPhy over a public API; `firmware/README.md` shows how to fetch and
verify your own copy. Everything derived from it here (pin maps, channel maps,
the command table, the protocol) is factual information extracted for
interoperability.

This is independent reverse-engineering for interoperability and repair. It is
not affiliated with or endorsed by NuPhy. Flashing custom firmware or writing
undocumented commands can brick a keyboard; there is no warranty (see `LICENSE`).

## License

[MIT](LICENSE) — free to use, modify, and distribute.

## Status

Reverse engineering is essentially complete for the application protocol, and the
firmware is mapped down to the flash protocol. This is not a polished product —
it is a correct one, with its gaps written down.
