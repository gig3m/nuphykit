# NuPhy Air100 V3 — reverse engineering handoff

**Read this first.** Then `AUDIT.md` (evidence discipline), then `PROTOCOL.md`
(the spec). Goal: understand the board completely enough to ship an open-source
configurator that fixes what NuPhy left out.

## Board state right now

- **Running MODIFIED firmware** (`firmware/Air100v3_MODIFIED_serial0721.bin`):
  NuPhy 1.0.6.6 with one byte changed at `0x42650`, so it reports USB serial
  `NuPhy Keybord 0721` instead of `0720`. Typing confirmed normal. This proves
  the bootloader does not validate images (§69). Reflash
  `Air100v3_US_v1.0.6.6_20260723.bin` to return to stock.
- Application firmware, PID `0x102D`, all six HID interfaces present
- **Factory reset applied 2026-08-08.** `snapshots/factory.bin` is the true
  factory image; `golden.bin` = factory + **4 bytes** (Hyper on Caps in banks 0
  *and* 4). `golden_pre_reset_contaminated.bin` is history — **never restore it**,
  it carries opcode-sweep damage (PROTOCOL §59).
- **Verified 0 differences** vs `snapshots/golden.bin`
- Caps Lock = `0x0F00` (Hyper), now in **both** base banks so the Mac/Win switch
  cannot take it away. This is **keyboard-native** Hyper; Raycast's Hyper Key was
  disabled 2026-08-08 after it was found contaminating tests (HAZARD 8)
- The firmware Ctrl/Caps swap (HAZARD 9) was **cleared by the factory reset**

Verify at any time:

```
cd ~/projects/nuphy-re && uv run --with hidapi python tools/restore.py
# add --fix to repair any drift back to golden
```

## Layout

```
PROTOCOL.md              the spec, 1400+ lines, claims tagged by evidence tier
SWEEP.md                 UI option sweep procedure + checklist (Kyle's plan)
AUDIT.md                 evidence rules + what is NOT proven  <- governs PROTOCOL.md
HANDOFF.md               this file
keycodes.json            519 keycodes, name -> value
matrix.json              101 keys: index, row, col, addr, fixed physical legend
enum_to_wire.json        app 24-bit enum -> 16-bit wire, + the 3 translation rules
keypos_to_matrix.json    app keyPos -> matrix index
keytest.html             keystroke capture page (see below)
samples/                 MACRO-1-export.json — NuPhy's own macro interchange format
snapshots/golden.bin     8 KB full device image, the restore reference
snapshots/drive_main.js  the web app bundle (2.2 MB) for static analysis
tools/                   scan / restore / diff / probe scripts
~/.local/bin/nuphy       the CLI
```

Stale, kept only as history: `keypos.json`, `keymap_dump.json`, `keymap_bulk.bin`
— built from the **wrong** address formula. Use `matrix.json`.

## Evidence rules — follow these

Four confident claims turned out wrong (address formula, keycode width, layer
count, slot indexing) because of four repeated mistakes. `AUDIT.md` has the full
treatment. Short version:

| tier | meaning | reportable as proven? |
|------|---------|----------------------|
| T1 | physical behaviour a human observed | yes |
| T2 | readback via a **different channel** than the write | yes |
| T3 | device ack | **no** — it acks writes it discards |
| T4 | inference or reading NuPhy's source | **no** |

1. No rule from fewer than **3 samples spanning the extremes** of its domain.
2. Every rule needs a **falsifying test that was actually run**.
3. Never promote across tiers.
4. Never present a closed list of unknowns. Split *named* from *unprobed*.
5. **A correction edits the original claim** — appending a truer section later is
   how `PROTOCOL.md` ended up with two wrong CONFIRMED sections for 3 sessions.
6. **Pick a probe outside the domain you are testing.** Testing the
   modifier-swapping Mac/Win switch *with modifier keycodes* produced a flat
   contradiction and cost four rounds. Plain letters settled it in one.
7. **Restate the physical control state in every instruction** ("switch on Win,
   do not flip it, press X"). Assumed state is how the above contradiction
   survived.

Critical corollary discovered late: **the keymap stores any 16-bit value without
validation.** Readback therefore proves storage, never behaviour. Anything about
whether the firmware *implements* a keycode needs T1.

## HAZARDS — all learned the hard way

1. **Never sweep opcodes.** A "benign" 4-byte payload `[0x02,0x00,0x00,0x00]` is
   a *valid write command* — sweeping sent `0xB3` = "write 2 bytes at address 0"
   and corrupted ESC. And some opcode in `0x40`–`0xFF` **enters the bootloader**.
2. **Writes must be 16-bit aligned.** A length-1 write at an odd address corrupts
   the neighbouring byte.
3. **Never hold a capture only in page memory.** The app reloads when the device
   re-enumerates; that lost a 20,092-frame firmware-flash capture. Persist
   incrementally (localStorage chunks or a local HTTP sink).
4. **Bootloader is not exited by power cycling.** Only NuPhyIO's update flow
   recovers it — which does work, fully, no physical intervention.
5. **CORRECTED 2026-08-08:** "Quit NuPhyIO before using the CLI" was **wrong** —
   CLI reads work fine while the app is connected. The real hazard is the
   reverse: **every CLI command handshakes (`0xEE`), which mints a new session key
   and orphans the app's session.** The app handshakes only at connect, never per
   write, so after any CLI command its writes are ack'd and silently discarded
   until you reload it. Poll *after* the app writes, never between (PROTOCOL §60).
   NuPhyIO does **not** revert your writes (tested).
7. **NuPhyIO's web app frequently hangs at "Loading..." with the device open and
   sends no HID frames.** The device is fine — the CLI works throughout. Cache
   clears, reloads and idle periods do not fix it; a firmware flash did once.
   This blocks all UI-differential experiments (PROTOCOL sec 48).
6. `0x7E00` (BOOT) and `0x7E13` (RESET) are bootloader/reset keycodes; `nuphy`
   refuses them without `--force`.
8. **HOST-SIDE REMAPPERS CONTAMINATE EVERY T1 TEST.** Raycast's Hyper Key was
   enabled on `keyCode 57` (Caps Lock) and silently rewrote Caps Lock to Hyper at
   the OS level. That inverted a T1 result and cost four rounds on the Mac/Win
   switch. **Run this before any keypress test:**

   ```
   hidutil property --get "UserKeyMapping"          # expect (null)
   defaults read com.raycast.macos raycast_hyperKey_state
   ps aux | grep -iE 'karabiner|hyperkey|bettertouch|keyboardmaestro|kanata'
   ```

   Tell: the keyboard's own `0x0F00` sets four mod bits across successive HID
   reports, so keydowns arrive **staggered** and build up. A software remapper
   injects all four in **one atomic event**. Staggered = keyboard, atomic = host.
   Prefer plain-letter probes — no remapper targets `KC_M`.
9. **The board can apply a firmware Ctrl<->Caps swap that the keymap does not
   show** (PROTOCOL §58). While active, a key storing `KC_LCTRL` emits
   **CapsLock** and one storing `KC_CAPS` emits **Control**. Not macOS, not
   Raycast, not NuPhyIO, not the config region — it lives in the keyboard-function
   space. **Cleared by a factory reset**, but its storage is **NOT** the
   keyboard-function space — all four reconstructions of the pre-reset `0xE1`
   bytes failed to reproduce it (§59), and `GetBase` was unchanged across the
   reset. Location still unknown. Never use Ctrl or Caps as a test probe.
11. **`navigate` to the same URL including its `#hash` does NOT reload the page** —
   same-document navigation, the JS context survives. Use `location.reload()`.
   A wrong conclusion was drawn from this in session 9.
12. **NuPhyIO's Mode Settings UI reflects the device only at load time.** It does
   not poll. A stale toggle is not evidence about device state.
10. **Establish baselines from a known-clean device**, not from the earliest
   snapshot to hand — `golden.bin` was contaminated for five sessions because the
   first snapshot was taken *after* the opcode-sweep damage (AUDIT B9).

## The protocol in one page

**`opcodes.json` has all 39 commands with NuPhy's own names** — read it before
sending anything. `0xEF SetIapMode` = bootloader entry (do not send).

```
transport   HID usage_page 0x01 / usage 0x00, 64-byte reports, report ID 0
frame       [0]=0x55 cmd / 0xAA reply   [1]=opcode   [2]=0x00
            [3]=checksum = sum(bytes[4..63]) & 0xFF
            [4..]=payload, each byte XOR the session key
payload     <length> <addr:16 LE> <pad 0x00> <data...>      (uniform!)
session     0xEE handshake: bytes 4-7 zero, >=21 random bytes at 8+.
            Reply bytes 4-7 all equal the session key. NO init commands needed.
addressing  addr16 = layer*0xDC + 2*(row*18 + col)
            8 layers: 0-3 Mac, 4-7 Windows. 110 matrix slots, 101 real keys.
keycodes    16-BIT on the wire. The app's 24-bit enum values are UI-level.
read        0xB2 <len> <addr> — bulk, reflects writes. 0xB1 returns FACTORY matrix.
write       0xB3 — arbitrary length, so a whole layer is ~5 packets
region      0x0000-0x1BFF readable AND writable; above that ignores writes
spaces      0xB2 is a GENERAL read over one flat config memory. The family Get*
            commands are windows into the SAME memory at fixed bases:
              0x0000 keymap (8 banks x 0xDC, ends exactly 0x06E0)
              0x0700 macro offset table (32 x 16-bit LE, rel. to 0x0700)
              0x0740 macro event arena -> 0x16FF; append-only, currently 16B used
              0x174C SOCD (8B records)  0x1850 TapDance (8B)  0x1A58 TGL (2B)
            GetLightState/KeyboardFunc/SleepInfo/Base/FirmwareInfo are NOT in this
            memory - volatile/computed state, read via their own commands.
notes       0xD2 GetKeyLightColor is a READ of live LED state (357B = 119x3);
            0xD8 is the hidden per-key-colour SET (PROTOCOL 76); 0xD2 is the read.
            Advanced-function slots: the table field is a BYTE OFFSET (slot*size),
            while the bound keycode uses the slot number (0x7F40|slot).
            Reset commands exist: 0xB7 SOCD, 0xBA TapDance, 0xBD TGL.
```

**There are FIVE storage spaces, and `restore.py` covers only the first:**

```
config memory 0x0000-0x1BFF  0xB2/0xB3   keymap, macros, SOCD/TapDance/TGL
keyboard func 4 bytes        0xE1/0xE2   wobbliness, disable Win/AltF4/AltTab
sleep cfg     4 bytes        0xF3/0xF5   auto-sleep, level-1/2 minutes   [whole record]
appdefine     0x03BA bytes   0xFB/0xFC   app scratch; 0xA8 = knob/button
lighting      17 bytes       0xD5/0xD6   effect, brightness, speed, RGB   [whole record]
```

**`tools/nuphykit.py` covers all five at once** — `show` / `backup` / `verify` /
`restore`. Use it, not `restore.py`, for anything calling itself a backup.
`tools/cfg.py` reads/writes the small spaces; `tools/light.py` reads lighting.
A factory reset clears **all** of them. The Ctrl/Caps swap (§58) is captured by
**none** of them.

**Custom firmware recovery (PROTOCOL 81):** NuPhy's IAP bootloader uses a
persistent DataFlash flag (0x55) and does NO image validation. So on-device
recovery via 0xEF works for any image that still enumerates USB and handles 0xEF.
Keep the stock frame parser (0x14168), dispatch table (0x42108), 0xEF handler
(0x12BF2) and USB code unchanged in every custom build and reflash always works -
no devboard needed. Only a build that fails to enumerate needs ROM ISP (BOOT pad,
case open).

**Firmware:** `firmware/` holds the verified 1.0.6.6 image, `strings.txt` and
`fwtool.py` (capstone RV32 analysis, no toolchain install needed). See §64-§65.

Region map, table bases, macro/TapDance/Toggle/SOCD record layouts, and the
lighting and mode-settings commands are all in `PROTOCOL.md` §33–§46 and §60–§63.

## Capabilities NuPhyIO hides (all T1-verified)

- **Hyper** `0x0F00`, and **any** modifier combo — the whole `0x0100`–`0x1FFF` range
- **`TG(n)` layer locking** — the board is *not* momentary-only; NuPhy just never
  ships a toggle. The escape must exist on the destination layer.
- **Layer chaining 3 deep** (L0 → L2 → L3)
- 8 layers, two mode sets, 101 addressable keys each

**Mac/Win switch (T1):** selects the base bank live — Mac→bank 0, Win→bank 4 — and
writes nothing to config memory. So **every remap must be written to `layer` and
`layer+4`** or it vanishes when the switch moves. Caps=Hyper currently exists only
in bank 0.

**Knob (T1):** the top-right position is a swappable module — keycap (ships as
Delete) or rotary knob, hot-swappable with a **0-byte** config diff. Rotate left =
matrix slot 108, rotate right = slot 109 (the synthetic `r6c0`/`r6c1`), press =
slot 13, the position's ordinary key. All three are plain keymap entries, so a
configurator needs no special knob path. The knob can be seated **upside down**;
the firmware signals that by flashing the top-row LEDs instead of acting.

The one real firmware gap: **anything needing tap-vs-hold timing.** `TT(n)`
degrades to momentary, QMK mod-tap discards the tap, and NuPhy's Tap Dance
long-press **fires discretely rather than holding** — so tap-Escape/hold-Hyper on
one key is unreachable.

## KNOCKLIST — needs Kyle

Physical or judgement calls I cannot do alone:

1. ~~Flip the Mac/Win switch~~ — **DONE, resolved T1 2026-08-08.** The switch
   selects the base bank live (Mac→0, Win→4), writes nothing to config memory.
   See PROTOCOL §20.
2. ~~Do `0x5600` / `0x7000` actually work?~~ — **DONE, resolved T1 2026-08-08.**
   Both inert. `0x5600`, `0x56F1` (swap-hands toggle) and `0x7000` all do nothing.
   PROTOCOL §57.
3. ~~Do DKS / RS / HT do anything?~~ — **DONE 2026-08-08.** Not constructible:
   this model's keycode table has zero `0x90`-`0x95` entries; those tags belong
   to the hall-effect line. Nothing to bind. PROTOCOL §57.
4. ~~Firmware~~ — **DONE 2026-08-08.** Binary in hand (§64) *and* the flash
   protocol captured (§67): `0xEF` payload `02 00 00 00` enters the bootloader;
   the Upgrader is NuPhy's own raw-HID bootloader (NOT WCH ISP — VID stays
   `0x19F5`); protocol is plaintext `80 38 <addr32> <56B>` write + `82` verify,
   no session/XOR. A flash **preserves** all five config spaces. Recovery via
   NuPhyIO is automatic. Old note:
   **The firmware BINARY is in hand (PROTOCOL §64).** Downloaded
   from NuPhy's public API and verified against their published sha256; no
   bootloader entry needed. It is **unencrypted RISC-V** for a **WCH CH58x**,
   built with riscv-none-elf-gcc 12.2.0. `firmware/` holds the zip, the .bin and
   `strings.txt`. What is STILL missing is the **flash protocol** — but the next
   step is not a capture, it is checking whether the Upgrader (PID `0x072D`) is
   just WCH's standard IAP bootloader, which open tooling already speaks.
   Old note follows:
   **Confirm a re-captured firmware flash.** Deliberate bootloader entry is now
   possible (bind `0x7E00`, press it). Worth redoing with persistent capture to
   recover the flash protocol — and it also yields the **firmware binary**, the
   single most valuable artefact for the custom-firmware question.
5. **Import Macros** — needs a file picker interaction.
6. ~~Turn the knob~~ — **DONE, resolved T1 2026-08-08.** Rotation = matrix slots
   108/109; press = matrix slot 13. `0x06E0` is an alias window, `0x1700` is NOT
   the knob and is now unexplained. See PROTOCOL §56.
7. Per-key RGB: probably answered — `0xD2` is read-only with no Set counterpart.
   Worth one confirmation that NuPhyIO cannot set a single key's colour.

## Use the keystroke capture page for all T1 tests

```
cd ~/projects/nuphy-re && python3 -m http.server 8777 --bind 127.0.0.1
# then http://127.0.0.1:8777/keytest.html
```

Logs keydown **and keyup with hold durations** — that distinction is what
separates a modifier being *held* from being *fired*, and it is how the Tap Dance
question got settled. Raw array in `window.__log`.

## Next work, in order

1. ~~Config blobs `0x0900`/`0x0E00`/`0x1100`/`0x1400`~~ — RESOLVED, unallocated
   macro arena holding stale flash (PROTOCOL §55.1).
2. ~~What is `0x1700`–`0x174B`?~~ — **RESOLVED 2026-08-08**: erased/unallocated,
   reads `0xFFFF` after a factory reset. The vol codes were residue (§59).
3. Characterise `0xFB`/`0xE1`/`0xF3`/`0xD5`/`0xC1`/`0xA0`/`0xFA` **individually
   and deliberately** — never by sweeping.
4. Firmware binary acquisition (knocklist 4).
5. Only then start the configurator.
