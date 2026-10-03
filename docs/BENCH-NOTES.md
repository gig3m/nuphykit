# NuPhy Air100 V3 — maintainer bench notes

**Read this first.** Then `AUDIT.md` (evidence discipline), then `PROTOCOL.md`
(the spec). Goal: understand the board completely enough to ship an open-source
configurator that fixes what NuPhy left out.

## Board state right now

As of the **2026-09-29 re-verification** (Linux host, cable mode):

- **Stock firmware** 1.0.6.6 — USB serial `NuPhy Keybord 0720`. The modified
  `0721` image (§69) is no longer on the board.
- Application firmware, PID `0x102D`, four USB interfaces. hidapi lists them as
  6 entries on Linux and 7 on macOS, which also reports the mouse collection's
  nested Pointer usage (PROTOCOL §70) — same device, different enumeration
- **The keymap is the owner's current Linux setup, not `golden.bin`.**
  `golden.bin` was built when a Mac was the owner's desktop (Caps = plain
  Hyper). Now the host is Linux and Caps must give **Esc for Neovim**: Caps =
  `MT(HYPR, KC_ESC)` `0x2F29` in banks 0 and 4 — **tap Esc, hold Hyper** (T1,
  2026-09-29). Bottom-right modifiers and the macro arena are also the owner's.
  Current full backup: `snapshots/kit_20260929-bothmodes.json` (both Mac/Win
  records). Lighting is changed with Fn keys, so `light@mac` drift is normal.
  **Do not run `tools/restore.py --fix`** — it would revert all of that to golden.
- `snapshots/factory.bin` is still the true factory image (`GetDefaultKeys`
  matches it byte for byte, T2); `golden.bin` = factory + **4 bytes** (Hyper on
  Caps in banks 0 *and* 4) — the old Mac-desktop layout, now history.
  `golden_pre_reset_contaminated.bin` — **never restore it**, it carries
  opcode-sweep damage (PROTOCOL §59).
- The firmware Ctrl/Caps swap (HAZARD 9) was **cleared by the factory reset** of
  2026-08-08

Verify at any time:

```
cd ~/Projects/nuphy-re && uv run --with hidapi python -m nuphykit verify 20260929-bothmodes
```

The 2026-09-29 pass re-ran every read-only claim, reversible write tests on bank
7, and T1 keypresses captured as raw HID reports from `/dev/hidraw*` (below any
host remapper). Corrections it forced are made in place and dated.

## Layout

```
PROTOCOL.md              the spec, 3200+ lines, claims tagged by evidence tier
SWEEP.md                 UI option sweep procedure + checklist (Kyle's plan)
AUDIT.md                 evidence rules + what is NOT proven  <- governs PROTOCOL.md
docs/BENCH-NOTES.md      this file
keycodes.json            519 keycodes, name -> value
matrix.json              101 keys: index, row, col, addr, fixed physical legend
enum_to_wire.json        app 24-bit enum -> 16-bit wire, + the 3 translation rules
keypos_to_matrix.json    app keyPos -> matrix index
keytest.html             keystroke capture page (see below)
samples/                 MACRO-1-export.json — NuPhy's own macro interchange format
snapshots/golden.bin     8 KB config image — HISTORY now (see Board state);
                         current full backups: snapshots/kit_20260929-*.json
snapshots/drive_main.js  the web app bundle (2.2 MB) — NOT in the repo (NuPhy's
                         code; gitignored); fetch your own from drive.nuphy.io
tools/                   scan / restore / diff / probe scripts
~/.local/bin/nuphy       the OLD CLI — superseded by `nuphykit` (installed
                         command, or `python -m nuphykit` from a checkout)
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
2. **Config writes must be whole 16-bit words.** A length-1 `0xB3` write always
   writes two bytes — the second is garbage — at **even addresses too**, not just
   odd (re-tested 2026-09-29). `nuphykit cfg config` now read-modify-writes the
   aligned word. `0xE2`/`0xFC`/`0xD6` take genuine single-byte writes.
3. **Never hold a capture only in page memory.** The app reloads when the device
   re-enumerates; that lost a 20,092-frame firmware-flash capture. Persist
   incrementally (localStorage chunks or a local HTTP sink).
4. **Bootloader is not exited by power cycling.** Only a reflash recovers it —
   NuPhyIO's update flow (automatic, no physical intervention) or
   `tools/flash.py` (used for §69; not yet rehearsed on Linux).
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
   switch. **On macOS, run this before any keypress test** (on Linux, read
   `/dev/hidraw*` instead — below):

   ```
   hidutil property --get "UserKeyMapping"          # expect (null)
   defaults read com.raycast.macos raycast_hyperKey_state
   ps aux | grep -iE 'karabiner|hyperkey|bettertouch|keyboardmaestro|kanata'
   ```

   **CORRECTED 2026-09-29:** there is no timing tell. Raw HID capture shows the
   keyboard's own `0x0F00` sends all four mod bits in **one report** — the
   "staggered keydowns" seen in the browser were macOS splitting that report into
   per-modifier events. Staggered-vs-atomic cannot tell keyboard from host [T1].
   The reliable method is to read the reports below the OS: on Linux,
   `/dev/hidraw*` (user-readable via the seat ACL); in cable mode the keys arrive
   on the NuPhy's own nodes, in 2.4G mode on the **dongle's** (PID `0x2620`).
   Prefer plain-letter probes — no remapper targets `KC_M`.
9. **The board can apply a firmware Ctrl<->Caps swap that the keymap does not
   show** (PROTOCOL §58). While active, a key storing `KC_LCTRL` emits
   **CapsLock** and one storing `KC_CAPS` emits **Control**. Not macOS, not
   Raycast, not NuPhyIO, not the config region — it lives in the keyboard-function
   space. **Cleared by a factory reset**, but its storage is **NOT** the
   keyboard-function space — all four reconstructions of the pre-reset `0xE1`
   bytes failed to reproduce it (§59), and `GetBase` was unchanged across the
   reset. ~~Location still unknown.~~ **Located 2026-09-29 [T2]:** QMK
   `keymap_config` bit 0 at eeprom word `0x004` (DF `0x5004`), set by the
   `0x7000` magic keycode — almost certainly pressed in the §57 test. `0x7001`
   clears it. Never use Ctrl or Caps as a test probe.
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
sending anything. `0xEF SetIapMode` = bootloader entry (do not send). The
firmware also accepts hidden `0xD8`/`0xC4`/`0xF4`; `0xE3`/`0xE5`/`0xE6` are no-op
acks, and `0xE4` types Enter (PROTOCOL §76, §84).

```
transport   HID usage_page 0x01 / usage 0x00, 64-byte reports, report ID 0
frame       [0]=0x55 cmd / 0xAA reply   [1]=opcode   [2]=0x00
            [3]=checksum = sum(bytes[4..63]) & 0xFF
            [4..]=payload, each byte XOR the session key
payload     <length> <addr:16 LE> <pad> <data...>           (uniform!)
            pad = 0x00, except 0xD5/D6/E1/E2: 0 = Mac, 1 = Win record (§84)
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
            window. CORRECTED 2026-09-29 [T2]: not "volatile" - light/func/sleep
            are stored in QMK eeprom outside it (§84); Base and FirmwareInfo
            are computed. Read via their own commands.
notes       0xD2 GetKeyLightColor is a READ of live LED state (357B = 119x3);
            0xD8 is the hidden per-key-colour SET (PROTOCOL 76); 0xD2 is the read.
            Advanced-function slots: the table field is a BYTE OFFSET (slot*size),
            while the bound keycode uses the slot number (0x7F40|slot).
            Reset commands exist: 0xB7 SOCD, 0xBA TapDance, 0xBD TGL.
```

**There are FIVE storage spaces, and `restore.py` covers only the first:**

```
config memory 0x0000-0x1BFF  0xB2/0xB3   keymap, macros, SOCD/TapDance/TGL
keyboard func 4 bytes x2     0xE1/0xE2   debounce x10ms, disable Win/AltF4/AltTab   [PER MODE]
sleep cfg     4 bytes        0xF3/0xF5   auto-sleep, L1/L2 min, early-sleep s  [whole record; 6 stored, §79]
appdefine     0x03BA bytes   0xFB/0xFC   app scratch; 0xA8 = knob/button
lighting      17 bytes x2    0xD5/0xD6   effect, brightness, speed, RGB   [PER MODE]
```

**`func` and lighting are stored per Mac/Win mode**, selected by payload byte 3
(0 = Mac, 1 = Win; PROTOCOL §84). `nuphykit backup` saves both modes as
`light@mac`/`light@win`/`func@mac`/`func@win` whichever way the switch is set.
Old snapshots' bare `light`/`func` are Mac. Not reachable by any command: the
Ctrl/Caps swap flag and the radio link slots (BLE bonds, 2.4G pairing).

**`nuphykit` covers all five at once** — `show` / `backup` / `verify` /
`restore` (`python -m nuphykit ...`). Use it, not `restore.py`, for anything
calling itself a backup. ~~`tools/nuphykit.py`, `tools/cfg.py`, `tools/light.py`~~
are the pre-§84 single-mode versions (pad 0 = Mac only) — history; use
`nuphykit cfg` / `nuphykit light`.
A factory reset clears **all** of them (and the BLE bonds, but not the 2.4G
pairing — §84). The Ctrl/Caps swap (§58) is captured by **none** of them.

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
`layer+4`** or it vanishes when the switch moves. ~~Caps=Hyper currently exists only
in bank 0.~~ (Caps is now `MT(HYPR, KC_ESC)` in banks 0 and 4 — see Board state.)

**Knob (T1):** the top-right position is a swappable module — keycap (ships as
Delete) or rotary knob, hot-swappable with a **0-byte** config diff. Rotate left =
matrix slot 108, rotate right = slot 109 (the synthetic `r6c0`/`r6c1`), press =
slot 13, the position's ordinary key. All three are plain keymap entries, so a
configurator needs no special knob path. The knob can be seated **upside down**;
the firmware signals that by flashing the top-row LEDs instead of acting.

~~The one real firmware gap: anything needing tap-vs-hold timing.~~
**CORRECTED 2026-09-29 [T1]:** QMK mod-tap **works** — `MT(Ctrl, X)` = `0x211B`
emitted `x` on tap and held Ctrl (no `x`) on a 2 s hold, captured as raw HID.
So tap-Escape/hold-Hyper **is** reachable: `MT(HYPR, KC_ESC)` = `0x2F29` —
confirmed T1 on Caps (tap Esc, hold Hyper, Hyper+M).
`TT(n)` degrading to momentary and Tap Dance long-press firing discretely are
the earlier observations and were not re-tested (the firmware *does* contain a
hold path for Tap Dance — PROTOCOL §79).

## KNOCKLIST — needs Kyle

Physical or judgement calls I cannot do alone:

1. ~~Flip the Mac/Win switch~~ — **DONE, resolved T1 2026-08-08.** The switch
   selects the base bank live (Mac→0, Win→4), writes nothing to config memory.
   See PROTOCOL §20.
2. ~~Do `0x5600` / `0x7000` actually work?~~ — **DONE, resolved T1 2026-08-08.**
   Swap-hands (`0x5600`/`0x56F1`) inert. **CORRECTED 2026-09-29:** `0x7000` is
   NOT inert — it persistently sets QMK's Ctrl<->Caps swap, the probable cause
   of HAZARD 9. PROTOCOL §57/§84.
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
   the knob ~~and is now unexplained~~ — it is erased/unallocated (§59). See
   PROTOCOL §56.
7. ~~Per-key RGB: probably answered — `0xD2` is read-only with no Set counterpart.~~
   **CORRECTED 2026-09-29 [T1]:** per-key RGB works via the hidden `0xD8` under
   hidden effect >= 21 (`nuphykit keycolor`); NuPhyIO just never exposes it.
   PROTOCOL §76-§78.

## Use the keystroke capture page for all T1 tests

On Linux, prefer raw reports from `/dev/hidraw*` (HAZARD 8) — below every host
remapper. The browser page is the macOS method:

```
cd ~/Projects/nuphy-re && python3 -m http.server 8777 --bind 127.0.0.1
# then http://127.0.0.1:8777/keytest.html
```

Logs keydown **and keyup with hold durations** — that distinction is what
separates a modifier being *held* from being *fired*, and it is how the Tap Dance
question got settled. Raw array in `window.__log`.

## Where we left off — wireless repeat investigation (2026-09-29)

**The problem:** on 2.4G the Air100 V3 sometimes repeats a key (`rrrr...`) and
drops the connection, including mid-sentence. Widely reported publicly.

**Board and host state at close:**
- Stock fw 1.0.6.6; Caps = `MT(HYPR, KC_ESC)` `0x2F29` both banks; Mac lighting
  changed by the owner via Fn keys. Current backup: `kit_20260929-bothmodes`.
- 2.4G re-paired and working (§82). **Dongle debug log left ON**
  (`nuphykit dongle-debug off` to undo; one persisted flag, harmless).
- Dongle sits alone on a CPU root port (bus 3) — the only place it has been
  reliable on this machine. Host USB autosuspend is off for both devices.
- Hyprland `repeat_delay` = 250 ms, so any key-up late by >250 ms repeats.

**What is established:**
- Mechanism class — lost/late key-up + host autorepeat — is well supported
  (full-state reports; dongle releases ~1 s after silence; keyboard keep-alives
  every ~600 ms mask that timer; a 3.5 s hold was delivered intact, T1).
- Two clean `diag` baselines (1,500 presses): no faults, -59..-65 dBm, low retry %.
  **No incident has been captured yet.**

**First live capture (2026-10-03, T1 for the log):** during a fade (RSSI -70 →
-78 dBm, retry rate 45 %) the keyboard logged `rend index 7821, channel 36 type 0
over 50 times` + `loss a key 10, 0` — **a key report dropped after 50 retries** —
then hopped 36 → 26 (the dongle followed). No stuck key that time, so it was not
a key-up. Signal was weaker than on 09-29 (-70..-78 vs -60); two hops in 30 min.
`diag` now runs as a user service: `systemctl --user status nuphy-diag`, log in
`~/nuphy-diag.txt` with wall-clock times.

**Live hypotheses** (PROTOCOL §83-§84):
1. ~~USB bandwidth contention at the dongle~~ — **explains a different symptom
   (owner, 2026-09-30):** on a shared bus the dongle *flatly doesn't work or stops
   working* — not intermittent. Consistent with its 6 interrupt endpoints at 1 ms
   (a large periodic reservation behind a hub's TT) being refused or starved, and
   its queue flushing. **It latches** (owner): once throughput fails it stays
   dead, not recovering when the bus frees up — so a dongle firmware bug on top
   of the bandwidth demand: its USB IN path (retry → `equal > max` → `over send
   remove`, dongle `0x236A`-`0x23BE`) apparently never re-arms. Worth tracing if
   anyone patches the dongle. Workaround: dongle on its own root port. **Not the cause of the
   intermittent mid-sentence repeats.** (A dongle patch to a longer `bInterval`
   could make it tolerate shared buses — optional.)
2. Radio fade → keyboard drops a key-up after 50 retries (`loss a key`), never
   re-sent; keep-alives hold the stuck key until the next keypress. (~40 %, T2 only)
3. Full RF disconnect/reconnect (`rf has disconnect`), keys typed meanwhile lost.
4. Switch chatter (29 ms re-press seen once; debounce is `func[0]` x 10 ms = 20 ms).

**Next steps, in order:**
1. **Radio stress test (provokes #2/#3 on demand):** dongle on its root port,
   cable in for the keyboard log, `python -m nuphykit diag --out ~/nuphy-diag.txt`,
   then degrade the link while typing — hand over the dongle, loose foil, or
   distance. `RADIO … loss a key` + a key stuck until the next press confirms #2;
   `rf has disconnect` points at #3.
2. Otherwise run `diag` wherever it fails in daily use and read the `RADIO` lines.
3. Only after an incident names the cause: firmware patch work — rehearse a stock
   reflash on Linux first (`nuphykit/bootloader.py`), then patch. Candidates:
   keyboard re-sends full state after a dropped report (#2); dongle release
   timer byte `0x62ED` (`0x64`→`0x20`) only helps #3.
4. Loose ends: verify `0x7001` clears the swap (§84); `0xD6` inactive-mode write
   (static only); sleep bytes 4-5.

## Next work, in order

1. ~~Config blobs `0x0900`/`0x0E00`/`0x1100`/`0x1400`~~ — RESOLVED, unallocated
   macro arena holding stale flash (PROTOCOL §55.1).
2. ~~What is `0x1700`–`0x174B`?~~ — **RESOLVED 2026-08-08**: erased/unallocated,
   reads `0xFFFF` after a factory reset. The vol codes were residue (§59).
3. Characterise `0xFB`/`0xE1`/`0xF3`/`0xD5`/`0xC1`/`0xA0`/`0xFA` **individually
   and deliberately** — never by sweeping.
4. ~~Firmware binary acquisition (knocklist 4).~~ — DONE (§64, §67-§69).
5. Only then start the configurator.
