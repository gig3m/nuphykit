# NuPhy Air100 V3 — raw HID protocol

Reverse-engineered from `drive.nuphy.io` and `/Applications/NuPhyIO.app` (the
desktop app is Electron wrapping the same React build, and exposes no HID IPC of
its own — both use WebHID in the renderer, so this covers both).

Target: NuPhy Air100 V3, USB `VID 0x19F5 / PID 0x102D`, model id `0x17`.

Claims are tagged **[CONFIRMED]** (observed on the wire or verified by device
behaviour), **[SOURCED]** (read from NuPhy's code, not exercised), or
**[HYPOTHESIS]**.

## 0. Why VIA cannot work — CORRECTED (see §70)

> **This section was misleading.** It said "V3 is QMK-derived but the VIA endpoint
> is gone", which implies QMK with VIA switched off. **It is not QMK at all.**
> The firmware contains **zero** QMK/ChibiOS/VIA markers and is built on WCH's
> CH58x SDK. NuPhy reused QMK's *keycode numbering*, nothing more. Full evidence
> in §70.

Basic keycodes are stock QMK/HID (`KC_A=0x04`, `KC_ESC=0x29`, `KC_CAPS=0x39`) and
`MO(1)` is `0x5221`, matching upstream exactly — but that is a shared numbering
convention, not shared code. No VIA JSON will ever make `usevia.app` talk to this
board. **[CONFIRMED]**

QMK's mod-tap is not compiled in: writing `MT(MOD_HYPR, KC_ESC)` (`0x2F29`)
applies the modifiers and silently discards the tap half. NuPhy shipped their own
"Tap Dance" instead. **[CONFIRMED]**

## 1. Transport

HID interface `usage_page=0x01, usage=0x00` (interface 3 on macOS). 64-byte
output reports on report ID 0 — `hidapi` callers prepend the report-ID byte and
write 65. **[CONFIRMED]**

## 2. Frame

```
byte 0     0x55 = write/command,  0xAA = response
byte 1     command
byte 2     0x00
byte 3     checksum = sum(bytes[4..63]) & 0xFF
byte 4+    payload, each byte XOR the session key
```

The checksum formula comes from NuPhy's own `calculateChecksum` in the demo
virtual device (webpack module `65843`) and validated against every packet
captured. **[CONFIRMED]**

That module's `parse()` also documents a `len`/`addr` layout at bytes 4–7 with
data at byte 8. **That is the hall-effect family, not this board.** The Air100 V3
puts payload directly at byte 4. **[CONFIRMED]**

## 3. Session — this is the part that gates writes

**Reads work with no session at all** (key `0x00`, i.e. plaintext). **Writes are
silently discarded without one** — the device still returns a perfect `0xAA` ack
echoing your payload, which makes failures look like address bugs. **[CONFIRMED]**

### 3.1 Handshake

```
OUT  55 EE 00 <cs>  00 00 00 00  <56 random bytes filling 8..63>
IN   AA EE 00 <cs>  KK KK KK KK  <56 bytes from the device>
```

Bytes 4–7 of the request are zero; the device returns them encrypted with the
session key, so **all four are the key**. Read `response[4]`. **[CONFIRMED]**

If the device echoes your packet back byte-for-byte, it rejected the handshake —
that happens if the 56-byte challenge is short. An 8-byte challenge is rejected.
**[CONFIRMED]**

The key is fresh per session — `0xC9`, `0xA1`, `0x90`, `0xC5`, `0x92`, `0xF1`,
`0x8A`, `0x43` observed. It is bound to the connection: closing the app ends the
session even though the key value still decodes reads correctly.

### 3.2 Init

Four commands follow the handshake before writes are accepted:

```
0xFA   0A 00 00 00
0xFB   38 00 00 00
0xFB   38 38 00 00
0xA0   08 00 00 00
```

All four are acked. **[CONFIRMED]** Their individual meanings are unknown, and
which of them actually unlocks writing has not been isolated. **[HYPOTHESIS]**

## 4. Commands

| opcode | direction | meaning | session? |
|--------|-----------|---------|----------|
| `0xEE` | out | handshake / key exchange | establishes it |
| `0xFA` `0xFB` `0xA0` | out | post-handshake init | — |
| `0xB2` | out | select address | no |
| `0xB1` | out | read **default** matrix at selected address | no |
| `0xB3` | out | write keycode | **yes** |

`0xB2` echoes any key you send it, so it cannot be used to discover the session
key. `0xB1` can — probe keys 0..255 and the correct one returns a plausible
keycode — but the handshake is the proper route. **[CONFIRMED]**

### 4.1 Set keycode

```
0xB2   02 <addr> 00 00                        select
0xB3   02 <addr> <keycode, 4 bytes BIG endian>  write
```

Verified writes: `0x0004`→types a, `0x0005`→types b, `0x5221`→`MO(1)`,
`0x0F00`→**Hyper**. **[CONFIRMED]**

The leading `02` is constant in every capture and replayed verbatim; meaning
unknown. **[HYPOTHESIS]** a sub-command or record-type selector.

### 4.2 Read caveat

`0xB1` returns the **factory default** matrix, not the active user keymap, so it
does **not** reflect writes. This burned an hour: Caps read back `0x39` while
physically producing Hyper. NuPhy's HE enum has both `GetDefaultKeyMatrix` and
`GetUseKeyMatrix`, so an active-matrix opcode exists but is not identified here.
**Verify writes by typing.** **[CONFIRMED]**

### 4.3 HE-family enum, for reference **[SOURCED]**

Module `99726`, export `EG` — the hall-effect boards' command set, *not* this
board's:

```
QuickCommStart=0x01 QuickCommEnd=0x02 GetInfo=0x03 GetBase=0x04 GetFunc=0x05
SetFunc=0x06 GetDefaultKeyMatrix=0x07 GetUseKeyMatrix=0x08 SetUseKeyMatrix=0x09
GetLedDefine=0x0A SetLedDefine=0x0B GetMacro=0x0C SetMacro=0x0D
GetGamepad=0x10 SetGamepad=0x11 GetKeyRTInfo=0xA0 SetKeyRTInfo=0xA1
GetDKSInfo=0xA2 SetDKSInfo=0xA3 GetMtKeyInfo=0xA4 SetMtKeyInfo=0xA5
GetTglKeyInfo=0xA6 SetTglKeyInfo=0xA7 StartCalibration=0xA8 EndCalibration=0xA9
GetCalibrationInfo=0xAA LedSyncDownload=0xDD LedSyncUpload=0xDE
RestoreFactorySettings=0xEE GetAppDefine=0xF1 SetAppDefine=0xF2
```

Report types (module `97822`, `E$`): `WriteCommand=0x55 ReadCommand=0xAA
CalibrationStatusReport=0xA0 StateChangeReport=0xA1 KeyboardReset=0xA2
KeyboardFuncCfgReport=0xA3 DongleConnectionReport=0xFA`

## 5. Addressing — SUPERSEDED, see sec 19 and 34

> **This section was wrong.** It claimed `addr = 2 * denseIndex`, tagged
> CONFIRMED on the strength of four adjacent keys in one row. It fails on the
> lower rows. The correct formula is in sec 19/34:
>
> ```
> addr16 = layer * 0xDC + 2 * (row * 18 + col)
> ```
>
> `keypos.json` and `keymap_dump.json` were built from the wrong formula and are
> retained only as historical artefacts. Use `matrix.json`.

## 6. Keycodes

519 keycodes in `keycodes.json`, extracted at runtime from webpack module
`82206` export `A`. 267 basic (`<=0xFF`, stock HID) and the rest extended, up to
24 bits **in the app's enum**. NOTE: the *wire* is 16-bit — see sec 21. The
24-bit values below are UI-level names, not writable values. The high byte is a type tag, per enum `RU` (module `99726`):

```
Keyboard=0x10  MouseKey=0x20  MouseWheel=0x21  MouseMove=0x22  MouseXY=0x23
Consumer=0x30  System=0x40    Exe=0x50  Web=0x60  Macro=0x70  KeyboardWheel=0x80
DKS=0x90  TGL=0x91  MT=0x92  RS=0x93  SOCD=0x94  HT=0x95
GKey=0xE0  Function=0xF0  Gamepad=0xF1
```

`KC_VOL_UP=0x30E900` is Consumer, `KC_G1=0xE00000` is macro G-key 1. Layer
keycodes are computed, not enumerated; `MO(n) = 0x5220 | n`.

**Hazardous:** `KC_FN_BOOT=0xF00700` and `KC_FN_RESET=0xF00800` bind bootloader
entry / reset to a key. `nuphy` refuses both without `--force`.

## 7. Persistence

- Writes go **straight to flash**. There is no commit opcode. **[CONFIRMED]**
- **Unplug/replug preserves** remaps. **[CONFIRMED]**
- **A device reset wipes them** back to factory. **[CONFIRMED]**
- **NuPhyIO does NOT revert out-of-band writes.** Tested in session 3: dump,
  full app connect cycle, dump again - byte-identical. The earlier claim was
  wrong; those failures were the missing session handshake (sec 3). You still
  need to quit it, because it holds the device session. **[CONFIRMED]**

## 8. Firmware / bricking risk

From the desktop app's cached manifest
(`NuPhyIO.app/Contents/Resources/app/build/resStatic/keyboard`): **[SOURCED]**

```json
{"productType": "app",  "productId": "0x102d", "deviceName": "Air100 V3"}
{"productType": "boot", "productId": "0x072D", "deviceName": "Air100 V3 Upgrader"}
```

The bootloader is a **separate USB device** with its own PID (same `0x10xx` →
`0x07xx` pattern for the ISO/JIS variants). That is the recoverable design: bad
application firmware should still enumerate as the Upgrader. Combined with
`KC_FN_BOOT` as a software entry route, a bad flash looks recoverable rather
than fatal — though this has not been tested and should not be taken as a
guarantee.

Flashing happens in the renderer over WebHID; `preload.js` exposes only theme,
window and `electron-updater` IPC, and `electron-updater` updates the *app*, not
the keyboard. No firmware is published for the Air100 V3
(`lastFirmwareVersion: null`), so there is no image to inspect and **whether
images are signed remains unknown**.

Device-role enum (module `44437`, `Xt`): `keyboard=0x1 upgrader=0x2 dongle=0x4`.

## 9. Still open

1. **Tap Dance / advanced-function wire format.** `RU` names the types (DKS, TGL,
   MT = Tap Dance, RS, SOCD, HT) and a bound key should carry a keycode with high
   byte `0x92`. The editor emitted no HID write on Confirm or key-bind, so it
   batches to a save gesture not yet located. This is what's needed for
   tap=Escape / hold=Hyper in firmware.
2. **Active-matrix read opcode** (§4.2).
3. **Which init command unlocks writes** (§3.2).
4. **The `02` payload prefix** (§4.1).
5. **Firmware image signing** (§8).

## 10. Method notes

The base64 string-array obfuscator was never defeated and did not need to be.
The app is a webpack build exposing `window.webpackChunkNuPhyIO`; push a probe
chunk to get `__webpack_require__`, then enums come out fully resolved:

```js
let req; window.webpackChunkNuPhyIO.push([['probe'], {}, r => { req = r }])
req('82206').A     // keycodes
req('99726').EG    // HE command enum
req('99726').RU    // keycode type namespace
req('44437').ui    // models (Air100V3 = 0x17)
req('97822').E$    // report types
```

`req.m` holds 1251 module factories readable via `Function.prototype.toString`
**without instantiating them** — important, since requiring an unloaded module
could fire side effects on a connected keyboard.

Per-key data (`keyPos`, `label`, `keyCode`, `layer`, `MtDelay`) is on the React
`keyObj` prop of each rendered key — no clicking required.

To capture the connect handshake the order must be **unplug → arm the hook →
plug in**. The page reloads on device disconnect, so arming first and then
replugging loses the hook.

---

# Part 2 — Features (captured session 2)

All **[CONFIRMED]** by driving NuPhyIO and capturing the wire, unless noted.

## 11. Corrected payload for 0xB3

```
02 <addr> <layer> <keycode, 24-bit big-endian>
```

The third byte is the **layer**, not keycode padding. It read `00` throughout
Part 1 only because all of that work was on layer 0. Verified by writing on FN1:
`02 4a 01 00 00 05`.

Keycodes are **24-bit** (max observed `0xF193FF`), not 32. The Part 1 CLI was
accidentally correct on layer 0 because `kc >> 24` is always 0 there.

Layer switching in the UI emits no HID traffic — the app bulk-reads every layer
at connect and switches views client-side.

## 12. CORRECTION — key addressing

**`addr = 2 * denseIndex` is wrong.** It held only for the top rows, which is all
Part 1 tested. The real structure is a matrix with **row stride 18**:

```
addr = 2 * (row * 18 + col)
```

| key | row | col | index | addr |
|-----|-----|-----|-------|------|
| F14 | 0 | 1 | 1 | `0x02` |
| F15 | 0 | 2 | 2 | `0x04` |
| CAPS | 3 | 0 | 54 | `0x6C` |
| A / S / D | 3 | 1/2/3 | 55/56/57 | `0x6E`/`0x70`/`0x72` |
| ← | 5 | 11 | 101 | `0xCA` |
| → | 5 | 13 | 103 | `0xCE` |

`col` is **not** position-in-row: wide keys (a 6u spacebar, 1.75u caps) consume
several matrix columns, and the numpad occupies fixed high columns. So `col` is
not derivable from the layout `x` value and must be captured per key.

**Consequence:** `keypos.json` `predictedAddr` and `keymap_dump.json` are wrong
below the top rows. Caps Lock (`0x6C`) is in the verified region.

## 13. Advanced functions

Creation flow — this is what blocked three earlier attempts: create the advanced
key, **then select a physical key on the rendered keyboard** (that enables
Confirm), *then* Confirm. Confirming without a key selected emits nothing.

Each writes its definition, then a normal `0xB3` binds a magic keycode:

| feature | opcode | definition payload | bound keycode |
|---------|--------|--------------------|---------------|
| SOCD | `0xB6` | `08 <idx> 00 00 <key1:16> 01 01 <key2:16> 00 <prio>` | `0x7F00` / `0x7F01` |
| Tap Dance | `0xB9` | `08 <idx> 00 00 <tap:16> <double:16> <hold:16> <holdms:16>` | `0x7F40` |
| Toggle Key | `0xBC` | `02 <idx> 00 00 <keycode:16>` | `0x7F80` |
| Macro | `0xC3` | block upload (below) | `0x77xx` |

Tap Dance verified: tap=`KC_ESC`, double=`KC_A`, hold=`KC_B`, `00 AA` = 170 ms,
matching the UI's Hold Time field exactly.

`keyObj` carries per-key slots for all six types — `MT`, `DKS`, `SOCD`, `RS`,
`HT`, `TGL`, `TD`, `Macro` — so the firmware models more than the UI exposes
(`DKS`, `RS`, `HT` have no editor).

## 14. Macros

```
0xC1  01 <idx> 00 00 01      start recording
0xC1  01 <idx> 00 00 00      stop recording
0xC3  <len> <offset:16 LE> <data...>    block upload (80 bytes observed)
```

Each event is **4 bytes**:

```
<delay_ms: 16-bit LE> <flags: 8> <keycode: 8>
```

Verified against the UI event list:

```
01 00 40 e0   →   1 ms  press  KC_LEFT_CTRL     (UI: CTRL,  1 ms)
02 00 40 e2   →   2 ms  press  KC_LEFT_ALT      (UI: OPT,   2 ms)
07 00 40 e1   →   7 ms  press  KC_LEFT_SHIFT    (UI: SHIFT, 7 ms)
4c 03 c0 e3   → 844 ms  0xC0   KC_LEFT_GUI      (UI: CMD, 844 ms)
```

`0x034C` = 844. Flags `0x40` = press; `0xC0` appears on the final event only —
likely a terminator bit, since the UI showed all four as "Press Down".
**[HYPOTHESIS]**

Note a macro cannot replicate Hyper: it fires a *sequence*, it cannot hold four
modifiers while another key is pressed. That is what `0x0F00` is for.

## 15. Lighting

```
0xD6  09 00 00 00 <effect> <brightness> <speed> 00 <flag> 00 <R> <G> <B>
0xD6  01 01 00 00 <brightness>
0xD2  <len> <offset:16 LE> <RGB bytes...>
```

`0xD2` is a **live per-LED frame stream**: 357 bytes per frame (119 LEDs x 3),
chunked as 6x54 + 33. It runs continuously while the Lighting panel is open —
4,864 frames captured in about a minute — so it is a preview stream, with `0xD6`
holding the persisted config.

Colour bytes verified: `4e 00 ff` and `fc 16 16` matched the picker exactly.

## 16. Mode settings

```
0xE2  01 00 00 00 <1|2|3>    anti-wobbliness / debounce level (Low/Med/High)
0xE2  01 01 00 00 <0|1>      Disable Win
```

The "Mode Settings" tab is *not* the M1/M2/M3 profile switch — it is Disable
Win / Alt+F4 / Alt+Tab plus debounce. M1/M2/M3 profile switching was not
captured. **[OPEN]**

## 17. Additional opcodes

| opcode | meaning |
|--------|---------|
| `0xB4` | `01 00 00 00 00` — restore factory defaults |
| `0xB2` sub `0x38` | **bulk read**, `38 <offset:16 LE> 00`, 56-byte blocks |
| `0xC1` | macro record start/stop |
| `0xFB` sub `0x01` | query (`01 a8 00 00` on panel open) |
| `0xE1` `0xF3` `0xD5` | queries fired when Mode Settings opens |

So `0xB2` has two modes: sub `0x02` selects a single address, sub `0x38` bulk
reads a block. The connect-time keymap slurp uses the latter.

## 18. Still open after Part 2

1. **Key address table** — §12, needs per-key capture or decoding the bulk-read
   block layout (which would give the whole matrix in 4 packets).
2. **M1/M2/M3 profile switching.**
3. **DKS / RS / HT** — modelled in `keyObj` but with no UI to drive.
4. **Active-matrix read opcode** — `0xB1` still returns the factory matrix.
5. Which init command unlocks writes; the `02` payload prefix.

---

# Part 3 — Address space, layers, capability limits (session 3)

## 19. CORRECTION — the address is flat 16-bit, there is no layer field

```
addr16 = layer * 0xDC + 2 * (row * STRIDE + col)      STRIDE = 18
```

Little endian at payload bytes 1..2:

```
0xB3   02 <addr_lo> <addr_hi> 00 <keycode:16 BE>
```

Part 2 described byte 2 as a "layer" field. It is the **address high byte**. The
app's layer-1 write to `A` was `02 4a 01 00 00 05` = `0x014A` = `0xDC + 2*55`,
i.e. bank 1, entry 55. **[CONFIRMED]**

Diagnosed by a failed experiment: writing "layer 1, addr 0x6E" produced `0x016E`,
which is entry 73 (`Z`) rather than entry 55 (`A`).

## 20. Eight layers, not four — and modes are just base layers

Eight consecutive 220-byte (`0xDC`) banks, `0x0000`..`0x06DF`:

| banks | base | content |
|-------|------|---------|
| 0–3 | `0x0000` | **M1 Mac** set, layers 0–3 |
| 4–7 | `0x0370` | **M2 Windows** set, layers 4–7 |
| — | `~0x0700` | macro storage (the `40 00 50 00...` region seen in `0xC3`) |

The physical Mac/Win switch **selects the base bank, live, with no replug**; it is
not a separate namespace. Mac → bank 0, Windows → bank 4. **[T1 — CONFIRMED]**

Method: write a *different plain letter* to the same slot in bank 0 and bank 4,
then flip the switch and press that one key. The switch is the only variable.

| slot | bank 0 | bank 4 | Mac | Win |
|------|--------|--------|-----|-----|
| 33 (numpad `/`) | `a` | `z` | `a` | `z` (twice, non-adjacent) |
| 54 (Caps) | `b` | `y` | `b` | `y` |
| 54 (Caps) | `HYPR` `0x0F00` | `y` | Hyper | `y` |

Steps 1 and 3 of the slot-33 run were the same switch position and agreed, which
rules out a RAM-cache-reload explanation — the switch selects, it does not merely
trigger a reload. Config memory is **byte-identical** across a flip (full-image
diff, 0 differences), so the switch writes nothing; it is a pure runtime selector.

**Re-confirmed 2026-09-29 [T1]** from raw HID reports on Linux: slot 69 (`KP_5`)
= `q` in bank 0 / `z` in bank 4 gave `q`, `z`, `q` across Mac→Win→Mac. Each flip
also pushes two unsolicited frames on the raw interface: `0xA2 ModeStateChange`
(`a2 04 01` entering Win, `a2 00 00` back to Mac) and `0xD7 LightStateChange`
carrying a **different lighting record per mode** — see §62. `0xA2` also fires
on `TG(n)` with the active layer (`a2 02` / `a2 00`), so it is a live layer
indicator a host tool can listen for.

Earlier phrasing cited Fn holding `MO(1)` in bank 0 and `MO(5)` in bank 4. That
is true (T2) but it only shows the banks *contain* a Mac and a Windows map — it
never showed the switch is what selects them. It was tagged CONFIRMED for three
sessions on that inference alone.

> **Probe-choice hazard, and a worse one underneath it.** The first two attempts
> used *modifiers* — Caps=Hyper, and the LALT/LGUI pair at slots 91/92 that the
> switch itself edits — and produced a flat contradiction. But the root cause was
> not the probe choice: **a host-side remapper was rewriting the result.**
> Raycast's Hyper Key feature was enabled on `keyCode 57` (`0x39` = Caps Lock).
> On Win the board correctly served bank 4, whose Caps holds the literal Caps Lock
> scancode, and **macOS converted it to Hyper before the browser saw it.**
> The bank model was correct from the first test.
>
> Two lessons: never pick a discriminator in the same domain as the mechanism
> under test (plain letters settled this in one round), and **verify the host is
> not transforming input before trusting any keypress observation.**
>
> The tell was visible all along: the keyboard's own `0x0F00` sets four modifier
> bits across successive HID reports, so keydowns arrive **staggered** ~5 ms
> apart and build up (`ctrl` → `ctrl+shift` → ...). A software remapper injects
> all four in a **single atomic event**. Staggered = keyboard. Atomic = host.

Practical consequence: a remap applied in Mac mode does **not** exist in Windows
mode. Write it to `layer + 4` as well. Concretely, Caps=Hyper in bank 0 reverts to
factory CapsLock the moment the switch moves to Win.

The app calls these "Onboard Configuration / Modes Saved on the Keyboard"
(M1 Mac, M2 Windows) in its My Configuration panel.

## 21. CORRECTION — keymap entries are 16-bit

Each matrix entry is **2 bytes**. The app's enum carries 24-bit values for media
and system keys, but those are UI-level; the device stores QMK's **basic 8-bit**
aliases:

```
0xA5 SYSTEM_POWER  0xA8 MUTE  0xA9 VOL_UP  0xAA VOL_DOWN
0xAB NEXT  0xAC PREV  0xAD STOP  0xAE PLAY_PAUSE
```

Anything above `0xFFFF` truncates. `KC_FN_SWITCH_LAYER` (`0xF0FE00`) therefore
cannot be written at all — it becomes `0xFE00`, which the firmware ignores.
**[CONFIRMED]**

## 22. Quantum keycode support — what works

The app's own range table matches **QMK's standard quantum layout** exactly
(`0x0100` mods, `0x2000` mod-tap, `0x4000` layer-tap, `0x5200`–`0x52DF` layer
block, `0x7E00` QK_KB, `0x7F00` QK_USER). NuPhy put their function keys in QK_KB
(`0x7Exx`), advanced keys in QK_USER (`0x7Fxx`), macros at `0x77xx`.

| keycode | value | result |
|---------|-------|--------|
| mods, any combination | `0x0100`–`0x1FFF` | **works** — `LCTL(KC_C)` verified |
| `HYPR` | `0x0F00` | **works** |
| `MO(n)` | `0x5220` | **works** (factory Fn) |
| `TG(n)` | `0x5260` | **works — toggles and holds** |
| `TT(n)` | `0x52C0` | degrades to momentary |
| `MT(mod,kc)` | `0x2000` | ~~mods applied, tap half discarded~~ **works — tap and hold** (CORRECTED 2026-09-29, T1) |

~~**The pattern: everything works except anything needing tap-vs-hold timing.**~~
**CORRECTED 2026-09-29 [T1]:** mod-tap works. `MT(Ctrl, X)` = `0x211B` on `KP_7`,
captured as raw HID reports: a tap emitted `x` (press+release in one burst on key
release); a 2 s hold emitted Ctrl alone for the whole hold, no `x`. So tap-vs-hold
timing *is* implemented for mod-tap. `MT(HYPR, KC_ESC)` = `0x2F29` on Caps gives
**tap = Esc, hold = Hyper, hold+`M` = Hyper+M** — confirmed the same way [T1]. `TT(n)` was not re-tested.
Also re-confirmed T1 in the same pass: `HYPR`, `LSFT(KC_A)` = `0x0204`, `TG(2)`
with its escape, and `0x5600` (no report at all).

### 22.1 Layer locking works — the trap is the escape key

`TG(n)` genuinely locks. The reason the board feels momentary-only is that NuPhy
ships `MO(1)` on Fn and puts **no toggle anywhere**, and a toggled layer needs the
toggle key to also exist on the destination layer or there is no way back:

```
nuphy set r0c2 'TG(1)'                 # tap to lock
nuphy --layer 1 set r0c2 'TG(1)'       # the escape - REQUIRED
```

## 23. DKS / RS / HT are impossible on this board

Not a UI gate — a hardware one. The shared V3 definition has
`switchTypeList: []`, `precisionOptionsA: []`, `precisionOptionsB: []` and
`isMachineAxis: true`. Air60HE by contrast has `defaultPrecision: 0.01` with
0.1 / 0.02 / 0.01 mm options.

DKS (actions at travel depths), RS (rapid trigger) and HT need **analog travel
sensing**. The Air100 V3 has mechanical switches. The `keyObj` slots exist because
the app shares one data model across the whole product line. **[SOURCED]**

## 24. Hardware detail

The Air100 V3 definition includes `mountings: [LeftRightSlider]` and
`especialKeys: [SquareKnob]` with volume down / mute / volume up — the board has a
knob and a slider, whose actions appear at matrix indices 108/109
(`0x00AA` / `0x00A9` = vol down / vol up, matrix row 6).

## 25. Revised open list

1. Whether NuPhyIO actually reverts out-of-band writes on connect. Earlier
   sessions assumed so, but the failures were later explained by the missing
   session handshake. Hyper has since survived several app launches.
   **Probably false — needs a clean test.**
2. Quantum blocks `0x5600` (swap-hands) and `0x7000` (magic) — present in the
   range table, never observed in use, untested.
3. Macro storage layout at `0x0700+`.
4. Which init command unlocks writes; the `02` payload prefix.

---

# Part 4 — Macros, inventory, enum/wire translation (session 4)

## 26. Macro import/export — a documented interchange format

The Macro Recording panel's per-macro `...` menu has **Import Macros** and
**Export Macros**. Export produces `MACRO <n>.json`:

```json
{
  "used": false, "label": "MACRO 1", "keyCode": 0,
  "bottomKeyType": 7, "value": 0,
  "bindKeys": [ {"id":4,"label":"","layer":0,"isEmpty":true,"loop":1,"isActive":true}, ... ],
  "info": {
    "macroId": 0,
    "actions": [
      {"delayMs":1,  "keyAction":1,"isEnd":false,"keyCode":224,"id":1,"editArr":[],"lightIndex":1,"keyLabel":"CTRL"},
      {"delayMs":844,"keyAction":1,"isEnd":true, "keyCode":227,"id":4,"editArr":[],"lightIndex":4,"keyLabel":"CMD"}
    ]
  }
}
```

**This validates the wire format exactly.** JSON -> wire:

```
flags = (keyAction << 6) | (isEnd ? 0x80 : 0)
event = <delayMs: 16-bit LE> <flags> <keyCode>
```

Round-trip verified byte-for-byte against the captured `0xC3` upload:

```
{"delayMs":1,  "keyAction":1,"isEnd":false,"keyCode":224}  ->  01 00 40 e0
{"delayMs":844,"keyAction":1,"isEnd":true, "keyCode":227}  ->  4c 03 c0 e3      (0x034C = 844)
```

So `isEnd` is the `0x80` bit — previously a **[HYPOTHESIS]**, now **[CONFIRMED]**.

New fields: `bindKeys` carries up to 3 bind slots each with a **`loop`** count, so
macros can repeat. `lightIndex` is per-action. `bottomKeyType: 7` presumably
identifies the record as a macro.

Sample in `samples/MACRO-1-export.json`. A configurator can read and write
NuPhy's own macro files directly.

## 27. Full picker inventory — 301 entries

Harvested from the app's picker via the React `keyObj` prop:

| category | count |
|---|---|
| Basic | 140 |
| Media | 66 |
| RGB | 23 |
| Special | 40 |
| **Macro** | **32** |

Photoshop / Illustrator / Figma shortcuts occupy `0x7E28`–`0x7E3A` and are
16-bit, therefore directly writable today. RGB entries are 24-bit enum values
(`0xF02E00` `RGB_MODE-` … `0xF01600` `SIDE MODE`) and need translation (§28).

## 28. enum -> wire translation

The app's picker uses **24-bit semantic enum values**; the wire is **16-bit**.
Pairing the app's `keyObj.keyCode` against a wire dump, position by position,
yields the mapping. **87 of 99** factory keycodes need no translation at all.

Three families:

```
identity   most keys: enum == wire
consumer   type 0x30 -> QMK basic 8-bit aliases
             0x30B600 -> 0x00AC   0x30CD00 -> 0x00AE   0x30B500 -> 0x00AB
             0x30E200 -> 0x00A8   0x30EA00 -> 0x00AA   0x30E900 -> 0x00A9
NuPhy fn   arbitrary assignments into QK_KB 0x7Exx
             0x309F02 MISSION_CONTROL -> 0x7E06
             0xF05100 SEARCH          -> 0x7E07
             0x30CF00 SIRI            -> 0x7E08
             0x409B00 DND             -> 0x7E16
layer      KC_FN{n} 0xF0FF0n -> MO(n) 0x5220|n     (0xF0FF01 -> 0x5221 confirmed)
```

`enum_to_wire.json` holds these. **[CONFIRMED]**

### 28.1 Method, and what is still missing

The alignment works because the app renders 99 keys and the matrix has 101
non-empty slots — the 2 extras being indices 108/109, the **knob** (this was an
assumption when written; **confirmed T1 in §56** — they are the knob's CCW and CW
actions), which the app
draws separately as `especialKeys`. Excluding those, the sequences pair 1:1 in
visual order. `keypos_to_matrix.json` records that mapping (the app's `keyPos` is
its own 0..100 numbering, *not* the matrix index).

Still missing: translations for RGB and most Special entries, since those do not
appear in the factory keymap and so have nothing to pair against. Getting them
requires binding each picker item and capturing the `0xB3` value — and **synthetic
clicks do not reach React**, so it needs real UI clicks (~2 per item, ~130 total).
That is mechanical but unautomatable through the current tooling.

## 29. Note on the app's FN 0..3 selector

The app's layer selector does not map straightforwardly onto the eight wire
banks — a snapshot taken with "FN 1" selected did not match wire bank 1. Whatever
the app is presenting there is filtered or remapped. **[OPEN]**

## 30. The remaining gap, and the method that will close it

Unresolved: wire codes for RGB and most Special picker entries. Concretely, these
appear in the factory keymaps but have **no name** in the extracted enum:

```
0x7E02 0x7E03 0x7E04 0x7E05 0x7E06 0x7E07 0x7E08
0x7E0D 0x7E0E 0x7E0F 0x7E10 0x7E11 0x7E12 0x7E13 0x7E14
0x7E16 0x7E18 0x7E19 0x7E57
```

(Four were recovered by pairing layer 0 against the app: `0x7E06` MISSION_CONTROL,
`0x7E07` SEARCH, `0x7E08` SIRI, `0x7E16` DND. `keycodes.json` already names
`0x7E0B`–`0x7E56`, 50 entries.)

**The method that works** — and it avoids the ~130 UI clicks otherwise required:

1. Record the current value of N scratch matrix slots.
2. Write the unknown wire codes into those slots on **layer 0** (the layer the app
   renders by default — this sidesteps the FN selector entirely).
3. Load NuPhyIO and read `keyObj.label` off each rendered key. The app names any
   keycode it recognises, so this yields wire -> label in one pass.
4. Write the recorded originals back.

`/tmp/probe_plan.json` + `probe.py` in the scratchpad implement steps 1/2/4; the
staging and restore were both verified against a full-matrix diff (0 differences).

**Why it did not complete:** after many session handshakes, NuPhyIO stopped
loading the device keymap and began rendering its built-in default template
(`F1 = 0x3A`) rather than live values (`F14 = 0x69`). The device itself stayed
healthy throughout — CLI reads and writes continued to work and verified
byte-for-byte. This looks like app-side state, most likely cleared by a keyboard
replug, which needs physical access. **[BLOCKED - needs a replug, then rerun the
4 steps above]**

## 31. Also still open

- The app's FN 0..3 selector does not correspond to wire banks 1..3 in any way
  established here (sec 29).
- Quantum blocks `0x5600` (swap-hands) and `0x7000` (magic): present in the app's
  range table, never observed in use, untested.
- Macro storage layout at `0x0700+` (the `40 00 50 00 ...` region).
- The `02` payload prefix, and which of the four init commands actually unlocks
  writes.

## 32. RESOLVED — the 19 unnamed wire codes

Closed by writing unknown codes into scratch slots and reading NuPhy's own
rendering. Note the app's `keyObj` fiber props go stale; the reliable read is the
**rendered DOM** (`<use xlink:href="#iconName">` or text), not React state.

| wire | meaning | picker enum |
|------|---------|-------------|
| `0x7E00` | **BOOT — enters bootloader** | — |
| `0x7E01` | unused / blank | — |
| `0x7E02` | LINK 2.4G | — |
| `0x7E03` `0x7E04` `0x7E05` | LINK Bluetooth 1 / 2 / 3 | — |
| `0x7E0D` | side light brightness up | `0xF01000` |
| `0x7E0E` | side light brightness down | `0xF01100` |
| `0x7E0F` | side light mode | `0xF01600` |
| `0x7E10` | side light colour | `0xF01500` |
| `0x7E11` | side light speed up | `0xF01300` |
| `0x7E12` | side light speed down | `0xF01200` |
| `0x7E13` | **RESET (keyboard reset)** | — |
| `0x7E14` | SLEEP | — |
| `0x7E18` | backlight off | `0xF03500` |
| `0x7E19` | RGB test | `0xF03100` |
| `0x7E57` | WIN report reverse | — |

Matched via SVG icon id: the RGB picker and the rendered keyboard share
`lightKeys_keyIconNN` sprites, so pairing icon ids maps picker enum -> wire.

**Two new hazards**: `0x7E00` (bootloader) and `0x7E13` (reset) join
`KC_FN_BOOT`/`KC_FN_RESET`; `nuphy` refuses all four without `--force`.

`keycodes.json` is now 519 entries. The wire-code inventory for this board is
complete for everything observed in the factory keymaps and the RGB picker.

---

# Part 5 — Full address space map (session 5)

Method: snapshot the whole readable space, make exactly one change, rescan, diff.
This locates each feature's storage unambiguously. Scanner: `scan.py`.

## 33. Readable extent

Bulk read (`0xB2` sub-`0x38`) succeeds cleanly from `0x0000` to at least
`0x2000` — 8192 bytes, zero failed blocks. Everything from `0x1C00` up is
zeros. **[CONFIRMED]**

## 34. Region map

| range | contents |
|-------|----------|
| `0x0000`–`0x06DF` | **keymap**, 8 banks x 0xDC (Mac 0-3, Windows 4-7) |
| `0x0700`–`0x073F` | **macro offset table**, 32 entries x 2 bytes |
| `0x0740`–        | **macro event data** |
| `0x1700`–`0x174B` | **UNALLOCATED / erased** — reads `0xFFFF` throughout after a factory reset. The vol up/down codes once seen here were residue, not structure (§59). Earlier called "knob / rotary actions" from content alone; falsified in §56 |
| `0x174C`–        | **SOCD table**, 8-byte records |
| `0x1850`–        | **Tap Dance table**, 8-byte records |
| `0x1A58`–        | **Toggle Key table**, 2-byte records |
| `0x1C00`–`0x1FFF` | zeros |

Unwritten table space reads as `0xFF` (erased flash).

## 35. Macro storage

```
0x0700  40 00  50 00 x31        32-entry table of START OFFSETS (16-bit LE),
                                 relative to 0x0700, one per macro slot
0x0740  01 00 40 e0 ...          macro 1 events, at +0x40 exactly as entry 0 says
```

Entry 0 = `0x0040`; unused entries all read `0x0050`, i.e. they point at the next
free position. Event encoding is per §14. **[CONFIRMED]**

## 36. Advanced-function tables

| feature | opcode | table base | record | record layout |
|---------|--------|-----------|--------|---------------|
| SOCD | `0xB6` | `0x174C` | 8 bytes | `<key1:16> 01 01 <key2:16> 00 <prio>` |
| Tap Dance | `0xB9` | `0x1850` | 8 bytes | `<tap:16> <double:16> <hold:16> <holdms:16>` |
| Toggle Key | `0xBC` | `0x1A58` | 2 bytes | `<keycode:16>` |

**IMPORTANT — the second payload byte is a BYTE OFFSET, not a slot index.**
Proven by writing offsets 0, 3, 7, 16 and 32 and observing writes at `0x1850`,
`0x1853`, `0x1857`, `0x1860`, `0x1870` — a 1:1 byte stride. The app uses
`offset = slot * recordSize`. The *bound keycode*, by contrast, uses the slot
number (`0x7F40 | slot`). Conflating the two silently corrupts neighbouring
records. `nuphy tapdance --slot N` now sends `N*8` and binds `0x7F40|N`.
**[CONFIRMED]**

Verification: slot 4 wrote `00 21 00 22 00 23 02 58` at `0x1870` = keys 4/5/6
with a 600 ms hold, matching the request exactly.

## 37. Still unknown after Part 5

1. Quantum blocks `0x5600` (swap-hands) and `0x7000` (magic) - in the app's range
   table, never observed in use, untested on device.
2. Config blobs at `0x0900`, `0x0E00`, `0x1100` - small structured records, not
   yet correlated to any UI control.
3. Per-key RGB persistence: `0xD2` is a live preview stream; whether custom
   per-key colours are stored (and where) is unestablished.
4. Import Macros - the reverse of §26, never exercised.
5. Firmware update protocol against the Upgrader device (PID `0x072D`).
6. The `02` payload prefix on `0xB1`/`0xB2`/`0xB3`, and which of the four init
   commands actually gates writes.

---

# Part 6 — Audit corrections (session 6)

See `AUDIT.md` for the full evidence re-classification. Corrections that change
what an implementer should do:

## 38. The handshake challenge — measured, not guessed

Minimum length is **21 bytes**; content must not be all-zero. Swept 0..32 plus
48/55/56 and a zero-filled 56:

```
 0            -> key 0x00 (degenerate, not a real session)
 1..20        -> REJECTED
21..56        -> accepted
56 all-zero   -> REJECTED
```

Part 3 said "56 random bytes" — that was one working sample and one failing one,
generalised. `nuphy` now sends 32. **[CONFIRMED, T2]**

## 39. The init commands are NOT required

`0xFA` / `0xFB` / `0xFB` / `0xA0` are what NuPhyIO sends after the handshake.
Tested with none, one, and all four; a write landed and read back correctly in
every case. **The handshake alone authorises writes.** Previous sections implied
these were part of the session setup; they are not. **[CONFIRMED, T2]**

## 40. Address space extent

The device replies to bulk reads at every 16-bit offset tested up to `0xFF00`.
Data exists only in `0x0000`-`0x1BFF`; everything above reads as zeros. Part 5's
"readable to 0x2000" described where scanning stopped, not a boundary.
**[CONFIRMED, T2]**

## 41. Claims demoted, not yet re-tested

Carried forward from `AUDIT.md` §B and §C — these are **not** established:

- ~~the physical Mac/Win switch selecting the base layer (inferred, never
  flipped)~~ — **RESOLVED T1, see §20.** The switch selects the base bank live,
  Mac→0 / Win→4, proven with plain-letter discriminators in both directions.
- DKS/RS/HT being impossible (source inference, never sent to the device)
- the enum->wire table (positional alignment is inference; pairs unverified)
- ~~`0x1700` being knob actions (named from content, no differential test)~~ —
  **FALSIFIED**, §56. The knob is matrix slots 108/109; `0x1700` is unexplained.
- "no commit opcode exists" (restate: none is required)

And twelve subsystems in `AUDIT.md` §C have never been probed at all.

---

# Part 7 — Protocol unification, and a bootloader incident (session 7)

## 42. The first payload byte is a LENGTH field

This unifies every command. Payload format is:

```
<length> <addr:16 LE> <pad 0x00> <data ...>
```

Swept the byte on `0xB3` from 0x00..0x07: `0x00` performs no write, `0x01`-`0x07`
all write. It matches every previously observed command:

| command | length byte | data |
|---------|-------------|------|
| `0xB2` bulk read | `0x38` | 56 bytes returned |
| `0xB3` set key | `0x02` | 2-byte keycode |
| `0xB9` Tap Dance | `0x08` | 8-byte record |
| `0xBC` Toggle | `0x02` | 2-byte record |
| `0xB6` SOCD | `0x08` | 8-byte record |

Earlier parts called this an unexplained "02 prefix". **[CONFIRMED, T2]**

## 43. Bulk writes work

`0xB3` accepts arbitrary lengths, not just 2. Verified writing **12 bytes = 6
keycodes in a single packet**, read back correct, then restored:

```
before  00 1f 00 20 00 21 00 22 00 23 00 24
write   len=12 addr=40  -> 00 04 00 05 00 06 00 07 00 08 00 09
after   00 04 00 05 00 06 00 07 00 08 00 09
```

A full 220-byte layer is ~5 packets instead of 110. **[CONFIRMED, T2]**

## 44. Writes are 16-bit word aligned — HAZARD

A length-1 write ~~at an **odd** address~~ corrupts the adjacent byte. Observed while
repairing state: single-byte writes at 0x0029, 0x002B ... left 0xF9 in the
neighbouring high bytes. Re-running the repair with addresses aligned down to
even and lengths rounded up to even produced **0 differences**.

**CORRECTED 2026-09-29 [T2]:** it is not about odd addresses. A length-1 `0xB3`
write **always writes two bytes**, the second being garbage (`0xC1` in the test):
`len=1` at even `0x0644` gave `2a c1`, at odd `0x0645` gave `00 2a c1` — the
following byte clobbered both times. `nuphykit.spaces.set_byte` now
read-modify-writes the aligned word. `0xE2`, `0xFC` and `0xD6` take genuine
single-byte writes (neighbours verified unchanged).

**Always write at even addresses with even lengths.** **[CONFIRMED, T2]**

## 45. Writable region == populated region

Write-then-readback across every known region: keymap (both mode sets), macro
table, SOCD/TapDance/Toggle tables, `0x1700`, and the config blobs at `0x0900`,
`0x0E00`, `0x1100` are all **writable**. `0x1C00` and `0x2000` silently ignore
writes. So `0x0000`-`0x1BFF` is the read/write window. **[CONFIRMED, T2]**

## 46. The keymap does NOT validate keycodes — methodological note

`0x5600` (swap-hands), `0x7000` (magic), `0x9000`/`0x9200`/`0x9300`/`0x9500`
(DKS/MT/RS/HT types), `0xF101`, `0x7700` and even `0xFFFF` all store and read
back unchanged.

**Therefore readback proves storage, never behaviour.** Whether the firmware
*implements* any of those keycodes cannot be established without physical
observation. All such claims stay **T4**. This retires the idea that the quantum
blocks could be resolved by writing and reading.

## 47. INCIDENT — opcode sweep triggered bootloader entry

Sweeping opcodes `0x00`-`0xFF` with a benign 4-byte payload (skipping the known
`0xEE` handshake and `0xB4` factory-reset), the device stopped responding and
re-enumerated as:

```
VID 0x19F5  PID 0x072D  usage_page 0xFF00  usage 0x01  "Air100 V3 Upgrader"
```

**An opcode in `0x40`-`0xFF` causes bootloader entry.** A prior sweep of
`0x00`-`0x3F` completed with the device alive, which brackets the culprit but
does not identify it. It did not return to application firmware after 60s, so
there is no short DFU timeout.

Side effect: this **confirms by observation** what section 8 previously inferred
from the manifest — the bootloader is a real, separately enumerated USB device.
Recovery is expected to be a power cycle (unplug/replug).

**Do not sweep opcodes on a device you cannot physically reach.** The bootloader
protocol is not documented in the app bundle in any form found so far, so there
is no known software path back to the application firmware.

## 48. NuPhyIO's web app is unreliable — the device is not

Repeatedly, `drive.nuphy.io` renders its shell, reports the HID device as
`opened`, and then sits at "Loading..." forever **without sending a single HID
frame**. Established by elimination:

- device healthy: the CLI completes a handshake (session key obtained) and a full
  bulk read **while the app is stuck** — T2
- not a stale local cache: `localStorage` (incl. `device_cache_*`), sessionStorage,
  IndexedDB, caches and service workers all cleared, no change
- not API failure: `keyBoardList` / `dongleList` / `rfList` / firmware-version
  calls all return 200 with data
- not device state left by the CLI: an idle period plus a hard `location.reload()`
  does not fix it, yet the CLI works throughout
- not my probe writes: reverting to factory values changed nothing

**[CONFIRMED, T2]** the fault is app-side. A firmware flash cleared it once; a
plain replug did not.

Consequence for the configurator: it must not depend on NuPhyIO for anything, and
**UI-differential experiments are unreliable** — the method that cracked the
storage tables (change one control, rescan, diff) is blocked whenever the app is
in this state. Prefer direct write/readback differentials, which never depend on it.

## 49. Config blobs at 0x0900 / 0x0E00 / 0x1100 / 0x1400 — partial

Contents look keymap-like but **byte-shifted** relative to the main banks. At
`0x1401` the pairs read `00 01` (= `KC_TRANSPARENT`), `0x142E` holds `52 25`
(= `MO(5)`), and `4a 00 4e 00 4d 00` (= HOME/PGDN/END) appears — matching the
odd "FN 1" view the app rendered in session 4. A repeated 24-byte pattern
(`00 20 00 40 00 30 00 40 50 77 ...`) occurs at `0x0900`, `0x0E58` and `0x1122`.

**[HYPOTHESIS]** these are secondary/derived keymap copies, possibly the app's
"Recommended Configuration" staging or a factory-default backup. Confirming needs
a UI differential, which is blocked by sec 48. **[OPEN]**

---

# Part 8 — The authoritative command enum (session 8)

## 50. Complete named opcode list — recovered

Webpack module `40877`, export `S4`, extracted at runtime. **This is NuPhy's own
naming.** Full table in `opcodes.json` (39 commands). The critical entries:

```
0xEE SetSecretKey        <- THE HANDSHAKE. Confirms the session-key model by name.
0xEF SetIapMode          <- BOOTLOADER ENTRY. This is the opcode my sweep hit.
0xB1 GetDefaultKeys      <- confirms by name that 0xB1 returns the FACTORY matrix
0xB2 GetUseKeys / 0xB3 SetUseKeys      "Use" = the active keymap
0xB4 RestoreUseLayers    (layer defaults) vs 0xF1 RestoreFactory (everything)
0xB5/0xB6/0xB7  Get/Set/Reset SOCD
0xB8/0xB9/0xBA  Get/Set/Reset TapDance
0xBB/0xBC/0xBD  Get/Set/Reset TGL
0xC1 SetKeyUpload  0xC2 GetMacro  0xC3 SetMacro
0xD1 GetLightCount  0xD2 GetKeyLightColor  0xD5/0xD6 Get/SetLightState
0xE1/0xE2 Get/SetKeyboardFunc   0xE3 SetDebounceTime   0xE4 TestDelayTime
0xE5/0xE6 Set/GetTouchBarConfig
0xF3 GetSleepInfo  0xF5 SetSleepCfg
0xFA GetAppDefineSize  0xFB GetAppDefine  0xFC SetAppDefine
0xA0 GetBase  0xA1 GetFirmwareInfo  0x2F GetDongelName
0xFD GetDebugEnable  0xFE SetDebugLog
```

Report/event types (module `40877`, `P3`): `ModeStateChange=0xA2`,
`KeyUpload=0xC1`, `LightStateChange=0xD7`, `KeyboardReset=0xF2`,
`SleepCfgChange=0xF4`, `LogUpload=0xFE`.

Keycode range prefixes (`Ih`): `Macro=0x77`, `ADVANCED=0x7F` — confirms the
prefixes observed empirically in Part 2. **[SOURCED]**

### 50.1 Corrections this forces

- **`0xD2` is `GetKeyLightColor`, not a "live LED frame stream".** Part 5 described
  the repeated `0xD2` traffic as a preview stream; by NuPhy's own name it is a
  per-key colour **read**. The repetition was polling, not streaming. Part 5's
  interpretation is withdrawn. **[SOURCED]**
- **`0xB4` is `RestoreUseLayers`, not a full factory reset.** `0xF1
  RestoreFactory` is the real one. Part 5 called `0xB4` "restore factory
  defaults"; it restores *layers*.
- **Reset commands exist for every advanced function** (`0xB7`/`0xBA`/`0xBD`).
  Part 5 said no delete command was known — wrong; they were simply unqueried.

## 51. GET command results — read-only, verified

All GETs queried with `len=0x20, addr=0`. **`0xEF` and every Set/Reset/Restore
were deliberately excluded.**

| cmd | name | reply | reading |
|-----|------|-------|---------|
| `0xA1` | GetFirmwareInfo | `06 00 01 aa 06 00` | version data |
| `0xD1` | **GetLightCount** | `77` | **119 LEDs** |
| `0xFA` | GetAppDefineSize | `03 ba` | **954 bytes** |
| `0xD5` | GetLightState | `08 08 02 00 00 00 08 00 14 04 3c 02 01 00 ff 00 00` | effect/brightness/speed/colour |
| `0xE1` | GetKeyboardFunc | `08 08 00 00` | mode settings |
| `0xF3` | GetSleepInfo | `00 06 19 04` | sleep config |
| `0xA0` | GetBase | `00 08 04 06 12 82` | base info |
| `0xB5` | GetSOCD | `00 50 01 01 00 4f 00 01` | matches the 8-byte record layout |
| `0xBB` | GetTGL | `00 06 ff ff ... 00 39` | matches the 2-byte record layout |
| `0xC2` | GetMacro | `40 00 50 00 50 00 ...` | **the 32-entry offset table** |
| `0xB8` | GetTapDance | 8-byte records | matches |
| `0xE6` | GetTouchBarConfig | empty | this board likely has no touch bar |
| `0x2F` | GetDongelName | `01 ff ff...` | ~~no dongle attached~~ **CORRECTED 2026-09-29:** identical with a dongle paired and connected — meaning unknown |

**`GetLightCount` = 119 independently confirms the LED count** previously *inferred*
from a 357-byte frame being 119x3. That inference is now **[CONFIRMED, T2]**.

`GetSOCD` / `GetTGL` / `GetMacro` returning exactly the record layouts found by
differential scanning is independent corroboration of Part 5 §35-36 through a
second channel.

## 52. AppDefine — likely the unidentified config blobs

`GetAppDefineSize` reports **954 bytes (0x03BA)**. The unexplained regions sit at
`0x0900`-`0x1BFF`. **[HYPOTHESIS]** the `0xFB`/`0xFC` AppDefine store is what
occupies them; `0xFB` at addr 0 returned zeros, so the addressing base for
AppDefine is not yet known. Testable with `0xFB` reads across offsets — safe,
read-only, and does **not** require NuPhyIO.

## 53. 0xB2 is a general memory read; Get* commands are WINDOWS into it
### (this section was wrong on first writing - corrected below)

Decisive test: search the `0xB2` address space (`0x0000`-`0x1FFF`) for the exact
bytes each GET returned.

```
GetSOCD  (0xB5) bytes -> found at 0x174C   (matches the mapped SOCD table)
GetMacro (0xC2) bytes -> found at 0x0700   (matches the macro offset table)
GetLightState, GetKeyboardFunc, GetSleepInfo, GetBase, GetFirmwareInfo
                       -> NOT PRESENT anywhere in 0x0000-0x1FFF
```

**First reading (WRONG):** "each command family has its own address space".

**Corrected model**, established by reading the same data both ways:

```
GetMacro   (0xC2) @0x0000  ==  0xB2 @0x0700   IDENTICAL
GetSOCD    (0xB5) @0x0000  ==  0xB2 @0x174C   IDENTICAL
GetTapDance(0xB8) @0x0000  ==  0xB2 @0x1850   IDENTICAL
GetTGL     (0xBB) @0x0000  ==  0xB2 @0x1A58   IDENTICAL
```

`0xB2` is a **general read over one flat config memory** (`0x0000`-`0x1BFF`), and
the family `Get*` commands are **convenience windows** into that same memory at
fixed bases. Both routes return byte-identical data. **[CONFIRMED, T2]**

Separately, `GetUseKeys`/`GetDefaultKeys` report meaningful data ending at exactly
**`0x06E0`** = 8 banks x `0xDC`, confirming the keymap extent from a second
direction. **[CONFIRMED, T2]**

The configs that are genuinely **not** in this memory — `GetLightState`,
`GetKeyboardFunc`, `GetSleepInfo`, `GetBase`, `GetFirmwareInfo` — are therefore
volatile or computed state rather than stored config, since their bytes appear
nowhere in `0x0000`-`0x1FFF`. **[CONFIRMED, T2]** for the absence;
**[HYPOTHESIS]** for "volatile rather than stored elsewhere".

### 53.1 Table bases, consolidated

```
0x0000  keymap, 8 banks x 0xDC          (GetUseKeys / SetUseKeys)
0x06E0  ALIAS window onto the per-bank knob slots, NOT a table (sec 56)
0x0700  macro offset table, 32 entries  (GetMacro / SetMacro)
0x0740  macro event data                 meaningful through ~0x09A1
0x174C  SOCD records, 8 bytes each      (GetSOCD / SetSOCD / ResetSOCD)
0x1850  TapDance records, 8 bytes each  (GetTapDance / SetTapDance / ResetTapDance)
0x1A58  TGL records, 2 bytes each       (GetTGL / SetTGL / ResetTGL)
```

**Knob location — RESOLVED. [T1]** See §56.

## 54. 0xD2 is a LIVE READ of rendered LED state — Part 5 was wrong

`GetKeyLightColor` returns exactly **357 bytes = 119 LEDs x 3 (RGB)**, matching
`GetLightCount`=119. The values are a live gradient (`7800ff`, `7000ed`, `6700db`
...) consistent with the active effect and colour.

**CORRECTION (see §76): there is no `SetKeyLightColor` in the APP's enum — but the
firmware has one at hidden opcode `0xD8`.** The hypothesis below ("no per-key set
exists") is **FALSIFIED**: it was absent from NuPhy's webpack enum, not from the
firmware. Per-key colour IS settable. The rest of this section (the read
direction) stands.

Part 5 described the repeated `0xD2` traffic as the app *streaming* a preview to
the keyboard. It is the opposite: the app **polls the keyboard for its rendered
LED state** to animate the on-screen keyboard. That is why it repeated
continuously while the Lighting panel was open (4,864 frames/minute), and why the
"frame" size matched the LED count.

Consequence for the read direction: `0xD2` is the app polling rendered LED state.
**[CONFIRMED, T2].** The former hypothesis that per-key colour cannot be set is
**withdrawn** — `0xD8` sets it (§76).

## 55. Four hypotheses FALSIFIED for the 0x0900-0x16FF regions

Recorded because negative results are results, and each was tempting:

| hypothesis | test | outcome |
|---|---|---|
| copies of keymap banks | slide against all 8 banks, all shifts | max **60%**, mostly coincidental zero-matching — **no** |
| 685-byte repeating records | autocorrelation 8..1400 over the region | no peak at 685; only small even periods (2-byte alignment) — **no** |
| the AppDefine store | read `0xFB`, 954 bytes | AppDefine is app scratch: offset 0x70 holds ASCII `1786189909506,2.2.6` (timestamp + NuPhyIO version) — **no** |
| macro event data (4-byte records) | parse at all 4 shifts vs the known-good macro | known macro parses **100%** clean; these score 65-77% with inconsistent shifts and implausible values (27392 ms delays, flags 0x00/0x0F not 0x40/0xC0) — **no** |

Also discarded: a "valid keycode density" test, because including all 8192
modifier combos made almost any 16-bit value count as valid. Not usable evidence.

### 55.1 RESOLVED — it is unused macro arena holding stale flash

The macro offset table decodes cleanly and settles this:

```
0x0700  32 entries, 16-bit LE, relative to 0x0700
        entry 0  = 0x0040  -> macro slot 0's events live at 0x0740
        entries 1-31 = 0x0050  -> the "next free byte" marker
0x0740  macro 0: 1ms/0xE0, 2ms/0xE2, 7ms/0xE1, 844ms/0xE3 END   (16 bytes)
```

Macro 0 occupies `0x0740`-`0x074F`. Every empty slot points at `0x0050`, i.e. the
next free byte — so the arena is **append-only and currently 16 bytes used**.
The arena runs to `0x16FF` (where the knob/SOCD structures begin), giving
4032 bytes for 32 macros.

**Therefore `0x0750`-`0x16FF` is unallocated arena containing uninitialised flash
residue — not a structure at all.** This explains every one of the four
falsifications above: stale bytes are not keymap copies, have no record period,
are not AppDefine, and do not parse as valid macro events. The keycode-shaped
values seen in it (`MO(5)`, HOME/PGDN/END) are residue from earlier recordings or
factory test data.

**[CONFIRMED, T2]** for the table semantics and the used extent;
**[HYPOTHESIS]** that the residue is specifically prior-recording leftovers rather
than some other artefact — but its being *unallocated* follows directly from the
offset table.

Practical consequence for a configurator: **do not interpret anything between the
last allocated macro and `0x16FF`.** Compute the used extent from the offset
table.

## 56. The knob — RESOLVED [T1]

The Air100 V3's top-right position takes a **swappable module**: either an ordinary
keycap (ships as Delete) or a rotary knob. Both were tested on the same board.

### What the knob reads

| function | storage | factory value |
|----------|---------|---------------|
| rotate **left** (CCW) | matrix **slot 108** (`bank*0xDC + 0xD8`) | `0x00AA` VOL_DOWN |
| rotate **right** (CW) | matrix **slot 109** (`bank*0xDC + 0xDA`) | `0x00A9` VOL_UP |
| **press** | matrix **slot 13** (`bank*0xDC + 0x1A`) | `0x004C` DEL |

Method: five distinct letters written to the five candidate addresses at once,
then one click left, one click right, one press. Result `c` / `f` / `g` — slot
108, slot 109, slot 13. No ambiguity and no second round needed.

Slots 108/109 are the "synthetic row 6" (`r6c0`, `r6c1`) — there is no sixth
physical row. They are ordinary keymap entries in every respect: per-bank, 16-bit,
writable with the same `0xB3` path as any key. **A configurator needs no special
knob support beyond exposing those two slots.**

### Press is not stored separately

Press maps to the matrix slot the module position already owns. That is why
swapping the key module for the knob produces a **0-byte diff** across the whole
config image (full 7168-byte before/after comparison, hot-swapped with no
unplug and no re-enumeration). Rotation is the only function needing its own
storage. **[T2]**

### `0x06E0`-`0x06FF` is an ALIAS, not a table

Writing either address changes both, in both directions:

```
0x06E0 <-> 0x00D8   (bank 0 CCW)      0x06E0 + 4*bank      <-> bank*0xDC + 0xD8
0x06E4 <-> 0x01B4   (bank 1 CCW)      0x06E0 + 4*bank + 2  <-> bank*0xDC + 0xDA
0x06FC <-> 0x06DC   (bank 7 CCW)
0x06FE <-> 0x06DE   (bank 7 CW)
```

Verified bidirectionally at banks 0, 1 and 7. The "16-entry table" counted in
Part 5 is 8 banks x 2 directions seen through a mirror window. **[T2]**

**Correction:** this section originally explained the odd `0x0306` at `0x06EC` as
"simply bank 3's CCW slot". **It was corruption**, not factory data — a factory
reset on 2026-08-08 restored that slot to `0x00AA` (VOL_DOWN) like every other
bank. It was residue from the early opcode-sweep incident (§47), sitting in the
old `golden.bin`. See §59.

Consequence: `restore.py` repairs `0x00D9` and `0x06E1` as separate runs when they
are one byte. Harmless, but any tool computing a checksum or a byte budget over
`0x0000`-`0x06FF` **double-counts the knob slots**.

### `0x1700` is NOT the knob — reopened

Part 5 named `0x1700`-`0x174B` "knob / rotary actions" from content alone
(`00 a9 00 aa` pairs). Letters planted at `0x1700` and `0x1702` produced nothing
on rotation. Its 7 entries of volume codes are unexplained. **[OPEN]** — and a
reminder that naming a region from its content is how it sat wrong for 5 sessions.

### Orientation indicator

The knob can be seated upside down. The firmware detects this and signals it by
changing the **top-row LEDs** on rotation instead of acting on the turn. This cost
one full test round — the probe letters appeared not to work when the real cause
was an unseated module. **[T1]**

## 57. Quantum blocks `0x5600` / `0x7000` — stored, unimplemented [T1]

Both were known to *store* in the keymap (§46), but storage never proved
behaviour. Now tested on hardware.

| bound value | meaning in QMK | pressed on device |
|-------------|----------------|-------------------|
| `0x5600` | `QK_SWAP_HANDS` base | nothing |
| `0x56F1` | swap-hands **toggle** | nothing; `asdf` typed normally after |
| `0x7000` | `MAGIC_SWAP_CONTROL_CAPS_LOCK` | ~~nothing; Caps and LCtrl unchanged~~ **CORRECTED 2026-09-29 — see below** |

Swap-hands was tested with the toggle variant specifically, because the base
code alone would be a no-op even on firmware that supports it. Typing `asdf`
before and after produced identical output, so the hand-swap matrix is absent.
~~**Both blocks are inert. A configurator must not offer them.**~~

**CORRECTED 2026-09-29 [T2, not re-tested live]:** only swap-hands is inert.
`0x7000` is live QMK magic: `process_magic` (`0x08B8C`) sets bit 0 of
`keymap_config` and **persists it immediately** to eeprom word `0x004`
(data flash `0x5004`). The press "did nothing" visibly because the swap only
shows on the *next* Ctrl or Caps press — and this is almost certainly the
origin of the §58 Ctrl<->Caps swap found right afterwards. `0x7001` unswaps,
`0x7002` toggles; `0x7003`/`0x7004` and `0x7020`-`0x7022` drive the caps->ctrl
and Esc<->Caps bits of the same word. See §84.

Scope limit: `0x7000` was exercised only for the control/caps-lock swap
semantic. Other `0x70xx` magic codes were not tried, and this says nothing about
them. Sweeping them is **not** worth the bootloader risk (§47, HAZARD 1).

### DKS / RS / MT / HT are not constructible on this model

AUDIT §C7 asked for a `0x9x`-type keycode to be bound and pressed. **The test
cannot be built**: this model's keycode table (webpack `82206`, 517 entries) has
high-byte distribution `0x00, 0x20, 0x21, 0x30, 0x40, 0xE0, 0xF0, 0xF1` and
**zero** entries tagged `0x90`–`0x95`. Those tags come from enum `RU` in module
`99726`, the **hall-effect** product line. There is no DKS/RS/MT/HT keycode in
this board's vocabulary to write.

This upgrades AUDIT B5 from "inference from `isMachineAxis: true`" to a
structural fact about the shipped keycode table — while leaving genuinely
untested the question of whether the *firmware* would honour such a code if one
were synthesised. Not worth pursuing: the board has mechanical switches and the
features need analog travel.

The board's actual advanced functions are SOCD / Tap Dance / TGL at `0x7Fxx`,
all mapped in §36.

### Incidental confirmation

Planting `m`/`n`/`o` in slots 90/91/92 and pressing the bottom-left three keys
returned `m n o`, confirming **T1** that those slots are LCtrl / LAlt / LCmd.
The bottom row of `matrix.json` had never been exercised before.

## 58. Firmware-level Ctrl <-> Caps swap, invisible to the keymap [T1]

The board applies a **KC_CAPS <-> KC_LCTRL exchange on output**, after the keymap
lookup. It is bidirectional and was verified with two independent keys:

| slot | stored value | emitted |
|------|--------------|---------|
| 90 (`r5c0`, Ctrl position) | `0x00E0` KC_LCTRL | **CapsLock** |
| 33 (numpad `/`) | `0x0039` KC_CAPS | **ControlLeft** |

Ruled out, each by direct check:

- **Not the keymap.** Slot 90 reads `0x00E0`, and planting a letter there types
  that letter — the keymap reaches the key normally.
- **Not NuPhyIO.** The app displays that key as Ctrl, matching storage. It has no
  Ctrl/Caps setting at all (all 81 `caps` hits in the bundle are layout geometry).
- **Not the config region.** `golden.bin` restores to 0 differences while the swap
  stays active, so the flag is **outside `0x0000`-`0x1BFF`**.
- **Not macOS.** `hidutil` `UserKeyMapping` is `(null)` on all three interfaces of
  both enumerated PIDs (`0x102D` and `0xD030`), and there is no
  `com.apple.keyboard.modifiermapping.*` key anywhere in ByHost preferences.
- **Not Raycast.** Its Hyper Key was disabled before these two tests.

`GetKeyboardFunc` (`0xE1`) returns exactly **4 bytes, `08 08 00 00`**, and ignores
the offset field — the same 4 bytes come back at offsets 0/4/8/16. Whether the
swap flag is one of them is **unknown**: there is no baseline to diff against,
and the flag was already set when the space was first read. The app's parser is
webpack module `505` (`KeyboardFunc`), not yet extracted — that needs the web app
loaded, which is blocked by §48.

**Why this matters more than the feature itself:** it breaks the assumption that
the keymap determines behaviour. Storage, app readback and firmware output can all
disagree. Any T1 test involving Ctrl or Caps on this board is unreliable until the
swap state is known, and a configurator that shows the stored keycode will lie to
the user for exactly these two keys.

Workaround while the flag is set (located 2026-09-29, §84 — `0x7001` clears it): **invert them in the keymap.** Writing
`KC_CAPS` to the Ctrl position yields a working Control key, and vice versa.

**[OPEN]** how the swap is toggled. Not exposed by NuPhyIO, so presumably an `Fn`
combo. Once a toggle is known, one before/after read of `0xE1` locates the flag.


## 59. Factory reset — a true baseline, and what it exposed [T1/T2]

Kyle applied a full factory reset on 2026-08-08 after the Ctrl/Caps swap (§58)
made the board unusable. The swap cleared, and the reset provided the first
uncontaminated baseline plus three differentials that were otherwise unreachable.

### `golden.bin` had been contaminated for the whole project

The pre-reset image differed from true factory in **666 bytes**, only 2 of which
were intentional:

| region | bytes | what |
|--------|-------|------|
| macro arena `0x0740`-`0x16FF` | 548 | stale flash residue (§55.1), now erased |
| `0x1700`-`0x174B` | 72 | residue, now erased |
| macro offset table | 32 | stale entries, now reset |
| keymap | 12 | see below |
| knob alias window | 2 | mirror of a corrupted keymap slot |

The 6 differing keymap entries:

```
bank0 slot  54 CAPS       factory 0x0039  golden 0x0F00   <- intentional (Hyper)
bank3 slot  60 H          factory 0x7E53  golden 0x0001
bank3 slot 108 VOL_DOWN   factory 0x00AA  golden 0x0306   <- corruption
bank5 slot  14 HOME       factory 0x0001  golden 0x2B2D   <- corruption
bank5 slot  15 END        factory 0x0001  golden 0xCDCD   <- corruption
bank5 slot  16 PAGE_UP    factory 0x0001  golden 0xCDCD   <- corruption
```

`0xCDCD` and `0x2B2D` are unmistakably damage from the opcode-sweep incident
(§47). **Every "verified 0 differences" check in this project was measured
against a partly corrupt reference.** No conclusion depended on those bytes —
they sit in banks 3 and 5, which no test touched — but the reference was wrong
and the `0x0306` anomaly was written up in §56 as though it were real data.

Baselines now:

```
snapshots/factory.bin                       true factory, post-reset
snapshots/golden.bin                        factory + Hyper on Caps in banks 0 AND 4 (4 bytes)
snapshots/golden_pre_reset_contaminated.bin kept as history only - do NOT restore from it
```

### `0x1700`-`0x174B` is unallocated — RESOLVED

Post-reset the entire region reads **`0xFFFF`** (erased flash). The volume codes
previously found there were residue, exactly like the macro arena. It was named
"knob / rotary actions" from content in Part 5, falsified as the knob in §56, and
is now closed properly: **there is no structure there.** **[T2]**

### The keyboard-function flag — located to one byte

`GetKeyboardFunc` (`0xE1`) across the reset:

```
before (Ctrl/Caps swap ACTIVE):   08 08 00 00
after  (swap cleared, T1)     :   02 00 00 00
```

Byte 1 went `0x08` -> `0x00` and byte 0 `0x08` -> `0x02`.

**Both candidates were then tested directly and BOTH FAILED.** With user consent,
`0xE2` was used to reconstruct each state from the clean factory baseline, each
followed by pressing the Ctrl-position key and a key bound to `KC_CAPS`:

| function space | Ctrl position emits | `KC_CAPS` key emits | swap? |
|----------------|---------------------|---------------------|-------|
| `02 00 00 00` (factory) | ControlLeft | CapsLock | no |
| `02 08 00 00` | ControlLeft | CapsLock | **no** |
| `08 00 00 00` | ControlLeft | CapsLock | **no** |
| `08 08 00 00` (exact pre-reset) | ControlLeft | CapsLock | **no** |

Every write was confirmed by readback. **The Ctrl<->Caps swap is NOT stored in the
keyboard-function space.** The `0xE1` change across the reset was *correlation* —
a factory reset clears many things at once — and the causal reading was wrong.

`GetBase` (`0xA0`) was **identical** before and after the reset
(`00 08 04 06 12 82`), so it is not there either.

**[OPEN]** where the swap lives. The productive next step is not more byte
guessing: it is learning **how the swap is toggled** (not exposed by NuPhyIO, so
presumably an `Fn` combo). One toggle gives a full-device before/after diff
across every readable space at once, instead of a 4-byte window.

> **Probe note:** `KC_CAPS` is a poor probe on macOS. Caps Lock is an OS-level
> toggle, so the browser sees only partial key events — on first press just the
> keyup. Use an ordinary letter wherever the test allows.

## 60. Mode Settings fully mapped — and the app/CLI session conflict [T2]

Done by instrumenting **WebHID in the live app** (`HIDDevice.prototype.sendReport`
wrapped from the page context) while driving the UI, then corroborating each value
against a CLI readback and the re-rendered UI. This is far stronger than
snapshot-diffing: it shows the exact frame the app sends.

### The app's session key was `0x08`

Frames captured while toggling, with the checksum confirming the encoded bytes:

```
Disable Win   off  55 E2 00 2A | 09 09 08 08 08     decoded: 01 01 00 00 | 00
Disable AltF4 off  55 E2 00 2B | 09 10 08 08 08     decoded: 01 02 00 00 | 00
Disable AltTab off 55 E2 00 2C | 09 11 08 08 08     decoded: 01 03 00 00 | 00
Disable Win   ON   55 E2 00 2B | 09 09 08 08 09     decoded: 01 01 00 00 | 01
```

Payload is the uniform `<len> <addr16 LE> <pad> <data>`. The last frame was a
**prediction made before clicking** and matched byte for byte.

### The map

`0xE1 GetKeyboardFunc` / `0xE2 SetKeyboardFunc` address a **4-byte** space:

| index | setting | domain | factory |
|-------|---------|--------|---------|
| 0 | Anti-Wobbliness Level | `1` Low, `2` Intermediate, `3` High | `2` |
| 1 | Disable Win | `0` / `1` | `0` |
| 2 | Disable Alt+F4 | `0` / `1` | `0` |
| 3 | Disable Alt+Tab | `0` / `1` | `0` |

Verified in both directions: every value was written from the CLI, then the app
was **reloaded** and its UI re-rendered the matching state — including all three
anti-wobbliness levels, i.e. 3 samples spanning the extremes. `0xE1` is a true
readback of `0xE2`.

### *** The app and the CLI fight over the session ***

`0xE1` appeared **not** to reflect the app's writes, which nearly produced a
second false conclusion. The cause:

**Every CLI command issues its own `0xEE` handshake, which mints a new session key
and orphans the app's session. The app handshakes only once, at connect — it does
NOT re-handshake per write (confirmed: no `0xEE` precedes any `0xE2` frame). Its
subsequent writes are ack'd and silently discarded (§3).**

Consequences for any UI-differential work:

1. **CLI reads while the app is connected are fine** — this corrects the
   long-standing "quit NuPhyIO first" hazard, which came from one early
   observation and was wrong.
2. **But after any CLI command, the app must be reloaded before its writes will
   land again.** Poll *after* the app has written, never between.
3. A configurator sharing a device with NuPhyIO must expect the same conflict.

### Methodology traps hit in this session

- **`navigate` to the same URL including its `#hash` does not reload the page.**
  It is a same-document navigation; the JS context survives (proven — an earlier
  prototype patch was still installed). A conclusion that "the app shows cached
  state" was drawn from that non-reload and was **wrong**. Use `location.reload()`.
- The app's Mode Settings UI reflects device state **only at load time**. It does
  not poll. A stale UI is not evidence about the device.

### Unexplained

The **first** Mode Settings interaction wrote 14 bytes at `0x0F44`-`0x0F51`
(`0F 07 07 07 07 07 07 07 07 07 07 07 07 07`) inside the macro arena, and no
later toggle changed them again — including toggling the same option back. Not a
setting store, since the value does not track the setting. **[OPEN]**

## 61. The Settings (gear) panel — mapped, and a THIRD config space [T2]

Driven through the live UI with WebHID instrumented, each value then confirmed by
CLI write -> app reload -> UI re-render.

### Sleep space — `0xF3 GetSleepInfo` / `0xF5 SetSleepCfg`, 4 bytes

| index | setting | factory |
|-------|---------|---------|
| 0 | Auto Sleep | `01` (on) |
| 1 | Level 1 Sleep, **minutes** | `06` |
| 2 | Level 2 Sleep, **minutes** | `18` = 24 |
| 3 | unknown | `04` |

Confirmed bidirectionally: writing index 1 = `0x09` from the CLI made the app
render "Level 1 Sleep: 9 minute" after a reload.

> **`0xF5` requires the WHOLE 4-byte record.** A single-byte write
> (`len=1, addr=1, value`) is ack'd and silently discarded — `0xE2` accepts
> single-byte writes, `0xF5` does not. Read-modify-write instead. `tools/cfg.py`
> does this automatically. This is the same ack-then-discard trap as §3, in a
> different guise: **the ack proves nothing.**

### AppDefine — `0xFB GetAppDefine` / `0xFC SetAppDefine`, byte-addressed

A **third** config space, separate from the keymap and from the two 4-byte
spaces. `GetAppDefineSize` (`0xFA`) returns `03 BA`.

| offset | setting | values |
|--------|---------|--------|
| `0xA8` | **Accessory Switch** | `00` Knob, `01` Button |

Captured frame when selecting "Button": `0xFC` decoded `01 A8 00 00 | 01`. The
app also *reads* exactly that byte on panel open (`0xFB` with `01 A8 00 00`).

### App-only settings — no device traffic at all

**Keyboard Layout** (US-ANSI-Mac, UK-ISO-Mac, DE/FR/SE/JPN x Mac/WIN — 12 options)
sends **zero HID frames**. It only selects which legends the on-screen keyboard
draws; the device stores nothing. Same for Switch Language and Switch Theme.

A configurator must not present layout as a device setting.

### Device facts read off this panel

```
Device version   1.0.6.6
Firmware update  Air100 V3 1.0.6.6, released 23 July 2026
Connection       2.4G USB
```

### Two traps hit while doing this

1. **Changing Keyboard Layout reloads the whole app**, destroying an in-page
   capture log — precisely BENCH-NOTES HAZARD 3 (never hold a capture only in page
   memory), walked into anyway. Fix: have the `sendReport` hook append to
   `localStorage` on every frame.
2. **The app's Auto Sleep write was silently discarded** because CLI calls made
   earlier had already orphaned its session (§60). The UI showed the toggle off
   while the device still read `01`. After the app reloaded and got a fresh
   session, its writes landed again. **Never interleave CLI calls with UI changes
   you expect to persist.**

## 62. Lighting — `0xD5` / `0xD6`, 17 bytes [T2]

Mapped by reading `0xD5 GetLightState` before and after each single UI change.

| byte | meaning | observed |
|------|---------|----------|
| 0 | **effect index, 1-based in UI order** | Ray=`01`, Static=`03`, Wave=`06` |
| 1 | **back-light brightness %** | `32`=50, `58`=88; **`00` = Back Light OFF** |
| 2 | **speed / gear** | `02` default; changed with the slider |
| 7-8 | 16-bit value that tracks brightness | `0580` at 50%, `08E0` at 88% — a computed PWM/current limit, not directly set |
| 10 | **side-light brightness** | `3C`=60 default; **`00` = Side Light OFF** |
| 3-6, 9, 11-16 | unchanged by every control exercised | — |

"Back Light off" and "Side Light off" are **not flags** — the app writes brightness
`0`. A configurator should model them as brightness, not booleans.

Effect list in UI order (1-based): Ray, Stair, Static, Breath, Flower, Wave,
Ripple, Spout, Galaxy, Rotation, Ripple, Point, Grid, Time, Rain, Ribbon, Gaming,
Identify, Windmill, Diagonal. (Two entries are both labelled "Ripple".)

### ~~`0xD6 SetLightState` needs the whole 17-byte record~~ — CORRECTED

Restoring the original state in one write produced an **exact** readback match:

```
0xD6  <len=0x11> <addr=0x0000> <pad>  06 32 02 00 01 00 00 05 80 04 3C 02 01 00 FF 00 00
```

~~Same rule as `0xF5` (§61): these record-oriented Sets do not accept partial
writes.~~ **CORRECTED 2026-09-29 [T2]:** that was inferred from `0xF5`, never
tested. `0xD6` **does** apply partial writes: `len=1, addr=1` set backlight
`0x32`→`0x3C`, and `len=1, addr=2` set speed `04`→`01`, each with every other
byte unchanged. (`0xF5` does discard partial writes — re-confirmed.)

**The record is per Mac/Win mode [T1].** Flipping the switch pushes `0xD7
LightStateChange` with a different record (on this board: Mac
`06 32 04 00 01 00 00 05 80 01 01 02 00 00 ff 6d 1e`, Win
`06 32 02 00 01 00 00 05 80 04 3c 02 01 00 ff 00 00`), and `0xD5` returns the
active mode's. A backup made in one switch position does not contain the other
mode's lighting. ~~Whether `0xD6` can address the inactive mode is unprobed.~~
**RESOLVED 2026-09-29:** payload byte 3 selects the mode — `0xD5` with `pad=1`
reads the Windows record [T2, live]; `0xD6` with a non-active pad writes the
inactive record in flash [T2 static]. It also means `0xD5`/`0xD6` with `pad=0`
**address Mac, not "the active mode"**: in Windows mode they reach Mac's stored
record. See §84.

### `0xD2` confirms §54 from the app side

While the Lighting panel is open the app polls `0xD2 GetKeyLightColor`
continuously, reading **357 bytes in 7 chunks** (`0x36`x5, then `0x37`, then
`0x20`, at offsets 0/0x36/0x6C/0xA2/0xD8/0x10F/0x145). 357 = 119 LEDs x 3.
It is a read of rendered LED state to animate the on-screen preview — exactly as
§54 concluded, now corroborated from the app's own traffic.

### Instrumentation note

Capturing app traffic must **filter `0xD2` at capture time**. The poll runs
continuously and floods any ring buffer, evicting the frames of interest.

### Legends: `matrix.json` corrected

The Lighting Effects panel renders **physical keycap legends**, while Key
Bindings renders **assigned keycodes**. That is the origin of the bogus "F14/F15"
legends: they were the Mac-mode media *keycodes* (`0x0069`/`0x006A`), not labels.
Kyle flagged this long ago ("those keys are obviously f1 and f2").

Corrected idx 1-12 to **F1..F12** (previously F14, F15, ..., MEDIA_PREV,
PLAY_PAUSE, MEDIA_NEXT, MUTE, VOL_DOWN, VOL_UP). Keycodes are unchanged; only the
physical labels were wrong.

### Correction: the "2.4G USB" label

§61 recorded the connection as "2.4G USB" from the settings panel. **The board is
connected by a USB cable.** That string is a single mode label in NuPhyIO covering
its receiver/wired path; it is not evidence of a 2.4GHz link.

## 63. UI sweep complete — the four storage spaces

Every NuPhyIO control has now been traced to its storage (or shown to have none).
The board has **four** distinct spaces, not one:

```
1. CONFIG MEMORY   0x0000-0x1BFF   0xB2 read / 0xB3 write
     keymap (8 banks x 0xDC), macro offset table + arena,
     SOCD / TapDance / TGL tables.   restore.py covers ONLY this.
2. KEYBOARD FUNC   4 bytes         0xE1 get / 0xE2 set   (single-byte writes OK)
     0 anti-wobbliness  1 disable-Win  2 disable-Alt+F4  3 disable-Alt+Tab
3. SLEEP CFG       4 bytes         0xF3 get / 0xF5 set   (WHOLE RECORD ONLY)
     0 auto-sleep  1 level-1 minutes  2 level-2 minutes  3 unknown (04)
4. APPDEFINE       0x03BA bytes    0xFB get / 0xFC set   (single-byte writes OK)
     0x70 app version string  0xA8 accessory switch (0 knob / 1 button)
   plus LIGHTING   17 bytes        0xD5 get / 0xD6 set   (WHOLE RECORD ONLY)
```

**A factory reset clears all of them; `restore.py --fix` restores only #1.** Any
configurator claiming to back up "the keyboard" must cover all five, or say so.

### Controls with NO device storage

| control | reality |
|---------|---------|
| Keyboard Layout (12 options) | app-only; sends zero HID frames |
| Switch Language / Switch Theme | app-only |
| "Back Light off" / "Side Light off" | not flags — brightness written as `0` |

### Not present on this model

- **Slider / TouchBar.** `0xE6 GetTouchBarConfig` never replies. The Air100 V3
  model definition lists `especialKeys: [SquareKnob]` only — no `LeftRightSlider`.
  The opcode exists in the shared enum for other boards. **Not a gap.**
- **Polling rate.** No such control in any panel for this model.
- **Per-key colour.** No UI control, and `0xD2` has no Set counterpart (§54).

### The app's model corroborates the knob mapping (§56)

Air100 V3 defines its knob as three actions with app keyPos indices:

```
especialKeys:[{type:SquareKnob, data:[
  {i18:"RemapPage.ReduceVolume",    index:13},
  {i18:"RemapPage.Mute",            index:14},
  {i18:"RemapPage.AmplifyTheVolume",index:15}]}]
```

`keypos_to_matrix.json` maps **keyPos 14 -> matrix slot 13** — and keyPos 14 is
*Mute*, the **press** action. That is exactly the T1 result in §56 (press = slot
13, the module position's ordinary key), reached independently from NuPhy's own
source. keyPos 13 and 15 have no matrix entry in that alignment, consistent with
rotation living in the synthetic row 6 (slots 108/109).

### Still unresolved after the sweep

1. **The Ctrl/Caps swap (§58).** No UI control touches it. Not in any of the four
   spaces as far as the sweep reached.
2. `sleep` index 3 (factory `04`) — present, purpose unknown.
3. Lighting byte 2 speed scale — the byte is identified, the gear mapping is not.
4. The 14 bytes written once at `0x0F44` on first Mode Settings use (§60).

## 64. FIRMWARE OBTAINED — and it is unencrypted RISC-V [T2]

**The firmware binary was acquired with zero risk to the device — no bootloader
entry, no flash capture.** NuPhy publishes it over a plain public API.

### How to get it

```
GET https://drive.nuphy.io/prod-api/api/nuphyIo/keyBoardList
GET https://drive.nuphy.io/prod-api/api/nuphyIo/getLastFirmwareVersionsByType
        ?businessId=<board id>&type=1
```

For Air100 V3 (`businessId=1996757112579686401`):

```json
"versionNumber":   "1.0.6.6",
"firstListTime":   "2026-07-23 18:11:33",
"firmwareFileUrl": "https://cdn.nuphy.io/image/2026/07/23/3d75c08cec8e4409952ceb3c2ffdce94.zip",
"sha256":          "41ad76952c35e57d75abfd8c3bf5d7206c45dc79a66fa131d6a960af271d42c6",
"isFallback": "Y",  "e2Prom": "N",  "forcedUpdate": "N"
```

The zip holds one file, `Air100v3_US_v1.0.6.6_20260723.bin`, **281,200 bytes**.
The published `sha256` is of the **inner .bin**, not the zip — verified, exact
match. Stored at `firmware/`.

`isFallback: Y` means NuPhy's own metadata marks this image as roll-back-able.

### It is NOT encrypted

Initial entropy (7.116 b/B), absence of an ARM vector table and lack of long
strings suggested encryption. **That was wrong**, and three independent tests
settled it:

| test | result |
|------|--------|
| chi-square vs uniform | **724,363** (encrypted/random would be ~255) |
| repeating-XOR key sweep, L=2..256 | no key — per-class entropy stays ~6.7-7.0 |
| string table at `0x3FFEC`+ | plaintext, entropy drops to **5.376** in that region |

The high entropy is simply dense compiled code. Plaintext strings include:

```
dynamic_keycode: %x, raw_keycode: %x
Keymap ID out of range: %d
Unknown priority level: 0x%02X
more tap hold
Air100 V3
```

### Architecture: RISC-V on a WCH CH58x

```
CH58x_BLE_LIB_V2.0
/Host/home/yyyy/Work/riscv-none-elf-gcc-12.2.0-1/linux-x64/sources/
        newlib-4.2.0.20211231/newlib/libc/stdlib/rand.c
```

- **MCU: WCH CH58x** (CH582/CH583) — a RISC-V "Qingke" BLE SoC, **not ARM**.
  This is why the ARM Thumb BL-pair density was only 0.37% (real Thumb: 2-5%)
  and no Cortex-M vector table exists at any offset.
- **Toolchain: `riscv-none-elf-gcc` 12.2.0** with newlib 4.2.0 — the xPack
  RISC-V bare-metal toolchain, freely available.
- Corroborated by the opcode histogram: low-2-bits `11` at **41%**, the RV32
  32-bit-instruction marker, against 25% for random data.

### Why this matters for the custom-firmware question

Kyle asked in session 1 whether custom firmware was feasible. The evidence now:

1. The image is **unencrypted**, so it can be disassembled with stock
   `riscv-none-elf-objdump` / Ghidra (RISC-V support is mature).
2. The MCU is a **documented, publicly purchasable WCH part** with a vendor SDK,
   BLE stack and an open toolchain — not a locked-down proprietary core.
3. **Strong lead on flashing:** CH58x parts ship a factory IAP bootloader, and
   WCH's ISP protocol has open tooling (`wchisp`). The "NuPhy Device Upgrader"
   (PID `0x072D`) may simply be that standard bootloader — which would mean the
   flash protocol needs no capture at all. **Untested.**

Caveats, stated plainly: none of this has been exercised. Nothing has been
disassembled, no build has been produced, and the bootloader has not been probed
since the accidental entry in §47. Feasibility looks good; it is not demonstrated.

### Other things the strings reveal

The board runs BLE **and** 2.4 GHz RF as well as wired: channel hopping, pairing,
RSSI, `switch to rf 24`, `switch to BLE channel %d`, `dongle %d, mac %s`,
`actory_test` (factory test). None of that is exposed on this wired unit.

**No `caps`/`ctrl`/`swap`/`lock` string exists anywhere in the binary** — so the
Ctrl/Caps swap (§58) is not a named debug feature. (Located 2026-09-29: it is
QMK's `keymap_config`, whose magic handler prints nothing — §84.)

## 65. Firmware static analysis [T2/T4]

Tooling: `firmware/fwtool.py` (capstone RV32IMAC via `uv run --with capstone`).
No RISC-V toolchain is installed system-wide and none is needed.

### Architecture, confirmed

- First word is `0x3000206F` = **`j 0x2300`**, a RISC-V reset jump. The image is
  a raw code image starting with executable code, not a vector table.
- `0x2300` is a textbook RISC-V C startup: `gp`/`sp` setup, `.data` copy loop,
  `.bss` clear.
- 87,505 instructions decode under a linear RV32IMAC sweep.

### Load address — **inference, not confirmed**

The `sp` setup is `auipc sp, 0x1FFF3` @`0x2308` then `addi sp, sp, -0x308`, giving
`sp = BASE + 0x1FFF5000`. For the stack top to be `0x20008000` — the top of a
32 KB SRAM at `0x20000000`, the CH58x layout — **BASE = 0x13000**.

Two function-pointer tables (`0x435EC` n=42, `0x439A0` n=38) hold values in
`0x03C52E`-`0x04CAAC`, which only constrains BASE to `[0x00803C, 0x03C52E]`. A
prologue-matching heuristic across candidate bases was **inconclusive** (best 5/80)
because a linear sweep misaligns at arbitrary offsets. So `0x13000` rests on the
stack argument alone. **[T4]**

> **CORRECTED 2026-09-29 [T2]:** Now firmly supported (§74's thunk pointers, plus
> the startup copy loop at `0x2318` targets `BASE + 0x1FFED000` = exactly
> `0x20000000`, RAM start, at base `0x13000`). Note `fwtool.py base` prints
> "sp setup not found" on this image — it only scans the first 40 decoded
> instructions, and the `sp` setup is at `0x2308`; the derivation above was manual.

**This does not affect most analysis**: for flash-internal references the base
cancels, since an `auipc`+`addi` pair at file offset P targets file offset
`P + (hi<<12) + lo` regardless of load address. All cross-references below were
derived that way.

### Code map (file offsets)

| range | contents |
|-------|----------|
| `0x00000` | reset jump -> `0x2300` |
| `0x02300` | C runtime startup |
| `0x05FD0` | keycode processing (`dynamic_keycode: %x, raw_keycode: %x`) |
| `0x0675A`, `0x0686A`, `0x06EB6`, `0x06F8A` | keymap lookup (`Keymap ID out of range: %d`) |
| `0x06782` | `Unknown priority level: 0x%02X` |
| **`0x06B1E`** | **tap-hold logic** (`more tap hold`) |
| `0x09AF8` | **`set_led(index, r, g, b)`** thunk -> real function `0x02D5C` (§74) — see below |
| `0x0CFEC` | device-name formatting (`Air100 V3`, `%s-%d`) |
| `0x0D6B8`, `0x0D724` | per-LED loops, `0..118` |
| `0x0F5BE`-`0x1A6xx` | BLE + 2.4 GHz RF stack |
| `0x2EC40` | RAM self-test (fill patterns `F0 AA FF 00 0F 55`) |
| `0x3FFEC`-`0x449F4` | string table |
| `0x42600`-`0x43200` | USB / HID descriptors |
| `0x435EC`, `0x439A0` | function-pointer tables (42 and 38 entries) |

### The LED primitive

Two loops iterate `s0 = 0..0x77` (119) and call the **same** function at file
offset **`0x09AF8`**:

```
0x0D6B8  li s5, 0x77          ; loop bound = 119 LEDs
0x0D6C6  jal  -0x3bce         ; -> 0x09AF8, args (a0=index, a1,a2,a3 = colour)
0x0D6CA  bne s0, s5, -0xe

0x0D724  li s1, 0x77          ; same loop, a1=a2=a3=0  -> clear all to black
```

So `set_led(index, r, g, b)` is the primitive the whole lighting engine sits on —
the hook point for any custom effect work. **CORRECTED 2026-09-29 [T2]:**
`0x09AF8` is only a jump thunk (pointer at `0x409BC`); the function body is at
**`0x02D5C`** (§74).

### USB / HID descriptors (file `0x42600`-`0x43200`)

```
device:  12 01 10 01 00 00 00 40 F5 19 2D 10 00 00 01 02 03 01
         USB 1.10, EP0 64B, VID 0x19F5, PID 0x102D, 1 configuration
serial string (iSerial=3): "NuPhy Keybord 0720"     (NuPhy's own typo)
    CORRECTED 2026-09-29 [T2]: was labelled "product string"; the GET_DESCRIPTOR
    code returns it for string index 3 (0x15B44), and the device descriptor's
    iSerial = 3 — matching the serial observed in §69.
```

Report descriptors found: mouse (report ID 2), system control (3), consumer (4),
several keyboard variants (boot, ID 1, ID 6), and **the raw-HID interface**:

```
06 01 00   Usage Page 0x0001
09 00      Usage 0x00
A1 01      Collection
   ... 95 40 75 08 81 02     Report Count 64, Report Size 8, INPUT
   09 02 ... 95 40 75 08 91 02   Report Count 64, Report Size 8, OUTPUT
C0
```

**64-byte in and out, no report ID** — exactly the transport in §1, now confirmed
from the firmware's own descriptor rather than from probing.

### What was NOT found

- **No command dispatch table.** The 39 known opcodes appear scattered as
  immediates with no clustering, no ascending byte table at any stride 1-24, and
  the two `0x55`/`0xAA` windows turned out to be a RAM test and a UART path. The
  dispatcher is likely a computed branch. **Opcode completeness therefore still
  rests on NuPhy's own enum (`opcodes.json`, module 40877 export S4), not on the
  firmware.**
- **No `caps`/`ctrl`/`swap`/`lock` string** anywhere — consistent with §58's swap
  not being a named feature.

### Custom-firmware implications

Positive: unencrypted, standard toolchain (`riscv-none-elf-gcc` 12.2.0 + newlib
4.2.0), documented MCU, and a clean `set_led` primitive. Unknown: whether the
bootloader validates a signature. **Untested** — nothing has been rebuilt or
flashed, and the Upgrader (PID `0x072D`) has not been contacted.

## 66. `nuphykit` — total-coverage backup/restore

`tools/nuphykit.py` reads and writes **all five** storage spaces in one shot,
which is the gap `restore.py` left: it only ever covered config memory, so any
"backup" taken with it silently omitted mode settings, sleep, accessory type and
lighting.

```
uv run --with hidapi python tools/nuphykit.py show
uv run --with hidapi python tools/nuphykit.py backup <name>
uv run --with hidapi python tools/nuphykit.py verify <name>
uv run --with hidapi python tools/nuphykit.py restore <name>
```

Verified end to end: full backup, deliberate perturbation of **two different
spaces** (`func[1]` and a keymap byte), `verify` correctly reporting exactly 2
differing bytes, then `restore` returning all five spaces to match.

It honours the per-space write rules — whole-record for `sleep` and `light`,
byte-granular for the rest.

**Known gap, stated in the tool's own docstring:** the Ctrl<->Caps swap (§58) is
persistent and is *not* captured, because the device exposes no way to read it.

## 67. THE FLASH PROTOCOL — captured [T1/T2]

Knocklist item 4, done. Deliberate bootloader entry, full capture, automatic
recovery, zero settings lost.

### Bootloader entry is deterministic

```
0xEF SetIapMode, payload 02 00 00 00   (a normal sessioned frame)
```

The device drops off the bus mid-write (the CLI raises a read error, which is
expected) and re-enumerates within ~3 s.

### The Upgrader is NOT stock WCH ISP

```
PID 0x072D   usage_page 0xFF00  usage 0x01   "Air100 V3 Upgrader"   single interface
```

**The VID stays `0x19F5`.** It does *not* come up as WCH's `0x4348`/`0x1A86` ISP
device. So this is **NuPhy's own bootloader speaking raw HID**, and the §64
speculation that open `wchisp` tooling might drive it directly is **wrong** —
retracted. The protocol below is, however, simple enough to reimplement.

### The protocol — plaintext, no session, no XOR

Unlike application mode (§2-§3) there is **no `0x55` header, no checksum byte, no
session key and no XOR**. Byte 0 is the command, byte 1 the length.

```
begin/erase   81 07 00 00 00 00 ...                       x1
write         80 <len> <addr:32 LE> <data>                x5022
verify        82 <len> <addr:32 LE> <data>                x5022
finalize      83 02 00 00 00 00 ...                       x1     -> reboots into the app
```

**Total 10,046 frames.** A second capture (see below) recovered the pieces the
first one missed: the `0x83` finalize, and the fact that the **length field is
real and varies** — the last block of 1.0.6.6 is `0x18` (24 bytes) at
`0x044A58`, not a padded `0x38`.

- Payload is **56 bytes** (`0x38`) per frame, address advancing by `0x38`.
- Addresses run `0x000000` -> `0x044550`, i.e. from **zero**, covering the whole
  281,200-byte image. 281200 / 56 = 5021.4 -> 5022 frames.
- Observed totals, second capture: `0x81` x1, `0x80` x5022, `0x82` x5022,
  `0x83` x1 = **10,046**, then `55 EE` — the app-mode handshake, i.e. the board
  rebooting into the freshly written firmware.
- **Frame 1's payload is `6f 20 00 30`** — byte-for-byte the first four bytes of
  the image downloaded in §64. The image is written **verbatim**, unencrypted.

### A flash PRESERVES all five config spaces

Verified with `nuphykit` against a backup taken immediately before: `config`,
`func`, `sleep`, `appdefine` and `light` all came back **byte-identical**. This
is the opposite of a factory reset (§59), which clears everything.

### Recovery is fully automatic

NuPhyIO detects upgrade mode by itself ("Found the Air100 V3 device in upgrade
mode"), downloads the image and reflashes with **no physical intervention** and
no re-permissioning. HAZARD 4 stands — power cycling does not exit the
bootloader — but the recovery path is reliable and now exercised twice.

### Capture method (this is what failed last time)

The earlier attempt lost 20,092 frames because the log lived in page memory and
the page reloads when the device re-enumerates (HAZARD 3). This time the
`sendReport` hook wrote to **`localStorage`**, flushing every 20 frames plus on
`beforeunload`, on `visibilitychange` and on an 800 ms timer, keeping bounded
arrays (first 150 verbatim, every 500th, last 25, plus a full histogram).
The page did reload — and the capture survived it.

### Load base — RESOLVED (§69.1)

This section originally flagged a contradiction: §65 inferred BASE = `0x13000`
from the `sp` setup, yet the flash writes at address 0. **Resolved: the
bootloader addresses the app partition relative to its own base.**

The image's own absolute pointers run to `0x04CAAC`, which **exceeds the image
size** (`0x44A70`) by `0x803C`. So the CPU cannot be seeing the image at 0. The
pointers bound the base to `[0x0803C, 0x3C52E]`, and `0x13000` — the value that
makes `sp` land exactly on `0x20008000`, the top of a 32 KB SRAM at
`0x20000000` — falls inside that window. Two independent derivations agree.

That puts ~76 KB of flash below the application: the bootloader plus the CH58x
BLE library blob, which is a plausible size for both.

### What this means for custom firmware

The mechanism for writing arbitrary content to the board's flash is now fully
known and reimplementable. What is **not** known is whether the bootloader
validates the image (signature, CRC, magic). Nothing was written except NuPhy's
own signed-or-not image, so that remains **untested**.


## 68. The flash protocol, reimplemented and verified [T2]

`nuphykit.bootloader.build_frames(image)` is a **pure function** that constructs
the whole flash sequence without touching hardware, so it can be checked against
a capture before anything is ever written.

It reproduces NuPhyIO's sequence **byte for byte**:

```
built 10046 frames; capture had 10046
  by command: {0x80: 5022, 0x81: 1, 0x82: 5022, 0x83: 1}   -- identical

  n=1      81 07 00 00 00 00 ...            MATCH
  n=2      80 38 00 00 00 00 6f 20 00 30    MATCH   (image[0:4] verbatim)
  n=3..5   80 38 ...                        MATCH
  n=10041..10044  82 38 ...                 MATCH
  n=10045  82 18 58 4a 04 00 02 00 00 00    MATCH   (short final block, 24 bytes)
  n=10046  83 02 00 00 00 00 ...            MATCH   (finalize)
```

Frame layout: `<cmd> <arg> <addr:32 LE> <payload>`. For data frames `arg` is the
byte count; for `0x81`/`0x83` it is a fixed constant (`0x07` / `0x02`).

**`flash()` itself is still gated behind an explicit confirm string and has never
been executed.** Building the right bytes is proven; sending them is not, and it
is not the same claim.

### A flash preserves settings — now confirmed twice

Both flashes left all five config spaces byte-identical to a `nuphykit` backup
taken immediately beforehand.

### Still unknown: does the bootloader validate the image?

The image carries **no appended signature block** — the last 256 bytes have
entropy 3.88 (structured pointer data), where an RSA/ECDSA blob would be near 8.
That is evidence against cryptographic signing, **not proof**: a CRC check inside
the bootloader remains possible, and **the bootloader is not part of this image**,
so it cannot be inspected statically. Only NuPhy's own unmodified image has ever
been sent.

## 69. CUSTOM FIRMWARE PROVEN — the bootloader does not validate [T1]

The decisive experiment. A **one-byte modification** to NuPhy's own 1.0.6.6
image, flashed with **my own implementation**, booted successfully — and the
change is observable from the host.

### The experiment

The target was chosen so the result could not be ambiguous:

- **Never executed.** File offset `0x42650` is the last character of the USB
  **serial-number string descriptor** (`NuPhy Keybord 0720`, UTF-16LE at
  `0x4262E`). Descriptor data, not code, so it cannot break execution.
- **Directly observable.** The host reports that string over USB, so a successful
  boot *proves the modified bytes reached flash* — not merely that something
  booted.

```
0x42650: '0' (0x30) -> '1' (0x31)     exactly 1 byte differs, size unchanged
stock sha256 41ad7695...  modified sha256 d0a82c78...
```

### Result

```
tools/enter_iap.py               -> in bootloader: True
tools/flash.py <modified image>  -> sent 10046 frames in 22.4s

app-mode interfaces (PID 0x102D): 7      bootloader (PID 0x072D): 0
  manufacturer: 'NuPhy'
  product     : 'Air100 V3'
  serial      : 'NuPhy Keybord 0721'      <-- the modified byte
```

All five config spaces verified **byte-identical** to a backup taken immediately
before.

### What this establishes

1. **The bootloader performs no image validation** — no signature check, and no
   CRC rejection. It accepted an image NuPhy never produced.
2. **The flash implementation in `nuphykit.bootloader` is correct end to end** —
   10,046 frames, right data at right addresses, clean boot. Previously only the
   *frame construction* was verified; now the sender is too.
3. **Custom firmware for this board is feasible.** Combined with §64-§65
   (unencrypted RISC-V, `riscv-none-elf-gcc` 12.2.0, documented WCH CH58x, a
   located `set_led` primitive), the whole loop is open: read the image, modify
   it, flash it, boot it.

### What it does NOT establish

- Nothing has been *compiled*. Rebuilding from source needs the linker layout,
  and the load-base question (§65 vs §67) is still unresolved.
- Only **descriptor data** was altered. Modifying **code** has not been tried and
  carries real brick risk: an image that boots but breaks the `0xEF` handler
  would remove the software path back into the bootloader.
- Whether a *physical* bootloader entry exists (key combo at plug-in, or the WCH
  factory ISP pin) is **unknown** — and that is the safety net that would make
  code modification comfortable. **Find that before touching code.**

### Confirmed by the user

Kyle confirmed the keyboard **types normally** on the modified image, and chose
to leave it installed. So the board now runs firmware built and flashed from this
project — the strongest possible T1 on the whole write path.

**Board state going forward:** the installed image is
`firmware/Air100v3_MODIFIED_serial0721.bin`, identical to NuPhy 1.0.6.6 except
one byte at `0x42650`. It reports serial `NuPhy Keybord 0721`. Stock can be
restored at any time by flashing `Air100v3_US_v1.0.6.6_20260723.bin`.

### Reproducing

```
uv run --with hidapi python -m nuphykit backup safety
uv run --with hidapi python tools/enter_iap.py
uv run --with hidapi python tools/flash.py firmware/<image>.bin
uv run --with hidapi python -m nuphykit verify safety
```

If a flash fails partway the board stays in the bootloader, and NuPhyIO recovers
it automatically — observed three times.


## 70. Is VIA compatibility possible? [T2]

Asked directly: is the blocker the tap/double-tap/hold feature set? **No.** VIA
has supported tap dance for years. The blockers are structural.

### The firmware is not QMK

Searched the whole image for the markers real QMK/VIA firmware always carries:

```
qmk  QMK  via  VIA  vial  dynamic_keymap  DYNAMIC_KEYMAP
ChibiOS  chibios  tmk  keymap_config  eeconfig  raw_hid  QK_
                                              -> NONE PRESENT
```

What it does carry: `riscv-none-elf-gcc-12.2.0`, `newlib-4.2.0`,
`CH58x_BLE_LIB_V2.0`. This is **NuPhy's own firmware on WCH's CH58x SDK**. The
QMK-looking keycode values are a borrowed numbering convention.

### The VIA transport does not exist on this device

VIA speaks over a raw-HID interface declared as **usage page `0xFF60`, usage
`0x61`**, with 32-byte reports. Neither the firmware image nor the enumerated
device contains it:

```
descriptor bytes 06 60 FF 09 61 : NOT PRESENT in the image
usage page 0xFF60               : NOT PRESENT

enumerated interfaces:
  iface 0/1  0x0001/0x06   keyboard
  iface 2    0x0001/0x02, 0x01, 0x80, and 0x000C/0x01   mouse/sys/consumer
  iface 3    0x0001/0x00   NuPhy's raw HID, 64-byte reports
```

### QMK does not support the MCU

CH58x is a WCH "Qingke" RISC-V part. QMK's platforms are AVR and ARM/ChibiOS,
plus a little RISC-V via ChibiOS (GD32VF103). **There is no ChibiOS HAL for
CH58x**, and the BLE/2.4 GHz stack is WCH's closed binary library.

### So the routes to VIA are

| route | what it means | assessment |
|-------|---------------|------------|
| **A. Port QMK to CH58x** | new QMK platform: HAL, USB driver, matrix, LEDs | months; **loses BLE/2.4G**, since that stack is a WCH blob |
| **B. Write firmware on WCH's SDK implementing the VIA protocol** | matrix scan + USB HID (SDK provides) + the `0xFF60` interface + VIA command set + dynamic keymap in flash | tractable; the realistic bar |
| **C. Host-side shim presenting a fake VIA device** | usevia.app talks WebHID to a *real* device; faking one needs a DriverKit/kernel extension | not viable on macOS |
| **D. Don't** | `nuphykit` already covers more than VIA would | already done |

Worth noting for route D: VIA has no concept of this board's **five** config
spaces, its **synthetic knob row**, or the **Mac/Win bank duplication**. A VIA
port would be a downgrade in coverage unless those were mapped onto VIA's model.

### The real prerequisite for ANY custom code: a physical recovery path

Flashing modified **code** (as opposed to the descriptor byte in §69) risks an
image that boots but breaks the `0xEF` handler — which would remove the only
known way back into the bootloader.

**However:** WCH parts ship a **factory ISP bootloader in ROM**, which cannot be
erased, and which enumerates as **VID `0x4348`/`0x1A86`** — different from
NuPhy's `0x19F5`/`0x072D` IAP bootloader. If that ROM ISP can be entered on this
board (typically by holding a BOOT pin or a designated key while powering on),
then **the board is effectively unbrickable** and `wchisp` — which does speak the
ROM protocol — becomes the recovery tool.

Establishing that is the gate on items 2 and 3, and it is a **zero-risk physical
experiment**: hold a candidate key while plugging in, then check whether any
`0x4348`/`0x1A86` device appears. Nothing is written either way. **[UNTESTED]**

## 71. Open firmware options for CH58x — CORRECTS §70

§70 said "QMK does not support the MCU" and treated a VIA port as a from-scratch
project. **That was wrong.** A community QMK port for CH58x exists **and it
supports VIA**.

### The landscape, checked rather than assumed

| project | what it is | verdict for this board |
|---------|-----------|------------------------|
| **`rgoulter/qmk_port_ch5xx`** (fork of `O-H-M2/qmk_port_ch582`) | QMK adapted to WCH CH58x | **the viable route.** "All the basic functions needed by wired keyboards are done, including VIA support." Wired + BLE work; 2.4G is WIP. Tested on CH582M, "should also work for CH582F". LED drivers: WS2812 (SPI/PWM) and AW20216S. Toolchain: WCH's, or the public **xpack `riscv-none-elf-gcc`** — the same family NuPhy built with. |
| **ZMK** | keyboard firmware on **Zephyr** | **ruled out.** Zephyr has WCH **CH32V** support, not CH58x. Reported blockers: BLE registers undocumented, the BLE stack is a binary blob, and 32 KB RAM is very tight. |
| **`ch32-rs/ch58x-hal`** | Rust HAL for CH583/CH582/CH581 | exists, but its own crate page says it is "under random and active development and should NOT be used in production". |
| **`rgoulter/smart-keymap`** | keymap library | ships a `ch58x-ble-hid-keyboard-c` example — useful reference. |
| **`ElectronicCats/arduino-wch58x`** | Arduino core for CH58x | exists; a low-effort way to bring the board up. |

**So VIA compatibility is reachable via QMK after all** — not by "enabling VIA"
on NuPhy's firmware (which is not QMK, §70), but by **replacing** the firmware
with the CH58x QMK port and building a VIA definition for the Air100 V3 layout,
which `matrix.json` already describes.

### Which CH58x is this? — UNCONFIRMED (see §80)

Earlier text guessed **CH582** from `GetBase` byte 5 = `0x82`. **That is not a
silicon chip-ID read** — §80 shows `GetBase` is built from hardcoded constants and
the firmware never reads `R8_CHIP_ID`. CH582 vs CH583 **cannot be distinguished
from the firmware**; both fit the flash/RAM. Confirming needs the chip marking or
ROM ISP.

Independent constraints that agree with a 448 KB / 32 KB part:

```
flash:  base 0x13000 + image 0x44A70 = 0x57A70 (358 KB) in use  -> >=448 KB part
RAM:    sp = 0x20008000                                          -> 32 KB @ 0x20000000
```

### What is still missing to actually build one

1. **Exact part number** — settle CH582 vs CH583 (weak evidence above).
2. **Matrix wiring.** We know the *logical* matrix (18 columns, rows 0-5 plus a
   synthetic row 6 for the knob) but **not which GPIOs** drive rows/columns.
3. **LED hardware.** 119 LEDs confirmed, but not the driver type. The port
   supports WS2812 and AW20216S; which one this board uses is unknown.
4. **Link address.** NuPhy's IAP bootloader occupies flash below `0x13000` and
   its protocol writes the app partition from offset 0. A QMK build would have to
   link to match, *or* be flashed whole via WCH's ROM ISP.
5. **A physical recovery path** — still the gate (§70). Unchanged and unverified.

Items 2 and 3 are the real work and cannot be answered from the firmware image
alone; they need either a teardown, continuity probing, or disassembly of the
matrix-scan and LED routines (`set_led` is already located: thunk `0x09AF8`, body `0x02D5C`, §65/§74).

## 72. Hardware facts recovered from the firmware (no teardown) [T2]

§71 listed matrix wiring and LED driver as things needing "a teardown, continuity
probing, or disassembly". That **over-weighted the teardown**: most of it is
recoverable from the image, and this section is what came out in one pass.

### Peripheral map — which blocks the firmware actually drives

Counting references to CH58x peripheral base addresses:

```
0x40001000  SYS / GPIO            122 refs     <- matrix scan lives here
0x40002000  timers                  2
0x40003000  UART                    3
0x40004000  SPI0 / SPI1            10 refs     <- the LED driver
0x40005000  PWMX / ADC / TouchKey   0 refs     <- NOT USED
0x40008000  USB                    47
0x4000B000  BLE radio               0 refs     <- BLE goes via WCH's blob, not direct MMIO
```

### The chip family is confirmed from code, not inference

```
0x01FE4  lui  a4, 0x40001
0x01FE8  addi a3, a4, 0x40
0x01FEC  li   a1, 0x57
0x01FF0  li   a2, 0xA8
0x01FF4  sb   a1, 0(a3)      ; write 0x57 ...
0x01FF8  sb   a2, 0(a3)      ; ... then 0xA8 to 0x40001040
```

That is CH58x's **safe-access unlock sequence** (`R8_SAFE_ACCESS_SIG`), which
must be written before touching protected system registers. Independent of the
`CH58x_BLE_LIB` string.

### LEDs are SPI-driven, and PWM is ruled out

`0x40005000` (PWMX) has **zero** references, so the PWM-driven WS2812 option is
out. The SPI0 block (`0x40004000`) is driven directly:

```
0x01FA0  lui a5, 0x40004 ; sb 0x9F, 6(a5)     +6 = R8_SPI0_INT_FLAG: clear IRQ flags
0x130CE  (s3-2) <= 0xFD ?                     i.e. s3 in 2..255
0x130DE  lui a5, 0x40004 ; sb s3, 3(a5)       +3 = R8_SPI0_CLOCK_DIV = s3 (runtime)
```

**CORRECTED 2026-09-29 [T2]:** this was read as "clock divider `0x9F` (159)" and
"transfer length bounded by `0xFD` (253)". Backwards: `0x9F` goes to the
interrupt-flag register (write-1-to-clear), and the value range-checked against
`0xFD` is the **clock divider** itself (WCH's own `SPI0_CLKCfg` requires >= 2).
Register offsets are from the CH58x register map, not re-checked against the
header. So neither a clock rate nor a transfer-size bound follows from these
lines. The driver identification rests on §74's 216-channel geometry instead.

### What genuinely still needs hardware

| fact | recoverable from firmware? |
|------|---------------------------|
| peripheral usage | **done** (above) |
| chip family CH58x | **done** (safe-access sequence + BLE lib string) |
| LEDs SPI vs PWM | **done** — SPI |
| exact LED driver IC | partially; datasheet work or a look at the board |
| matrix row/col GPIO pins | **yes, in principle** — 122 GPIO refs; the scan loop can be read out |
| exact part (CH582 vs CH583) | the chip marking is definitive; may be inferable from flash size probing |

**A teardown is a last resort, not a prerequisite.** And the physical-recovery
test (§70 — hold a key while plugging in, watch for a `0x4348`/`0x1A86` device)
needs no disassembly at all.

## 73. MATRIX PIN MAP — recovered from the firmware [T2]

No teardown, no probing. Read out of the scan routine at `0x07F70`.

### The scan routine

```
0x07F74  sw  a4, 0xb4(a5)      PA_PD_DRV &= ~mask
0x07F78  lw  a4, 0xa0(a5)
0x07F7E  sw  a4, 0xa0(a5)      PA_DIR |= line        -> drive this line
0x07F82  lw  a4, 0xac(a5)
0x07F88  sw  a4, 0xac(a5)      PA_CLR |= line        -> drive it LOW
0x07F8C  jal ...                                      settle delay
         a4 = &col_table, a2 = &col_table_end, a3 = 1, s4 = 0
loop:
0x07FAC  lw  a5, 0(a4)         mask = *col++
0x07FB0  bltz a5, ...          high bit set -> read PB_PIN instead
0x07FB4  lw  a1, 0xa4(a6)      read PA_PIN
0x07FB8  and a5, a1
0x07FBC  or  s4, s4, a3        set result bit when the line reads LOW
0x07FC2  slli a3, 1
0x07FC4  bne a2, a4, loop
         PA_PU |= line ; PA_DIR &= ~line              -> restore to input+pullup
```

**Keys are ACTIVE LOW with pull-ups. Rows are driven, columns are read.**
The `bltz` branch is how one table serves both ports: bit 31 set means "this pin
is on port B".

### The two tables

Addresses computed from the `auipc`/`addi` pairs at `0x07F92` and `0x07F9A`.

```
column table  file 0x407DC, 18 entries x 4 bytes
row table     file 0x40824,  6 entries x 4 bytes
```

| | pins, in table order |
|---|---|
| **columns (18, read)** | `PA0 PA1 PA2 PA3 PA15 PA14 PA13 PA12 PA7 PA8 PB7 PB6 PB5 PB4 PB3 PB2 PB1 PB0` |
| **rows (6, driven low)** | `PB17 PB16 PB18 PB20 PB21 PB22` |

18 columns and 6 rows match the logical matrix exactly (stride 18, rows 0-5 plus
the synthetic knob row).

### Cross-check

The union of the six row bits is **`0x00770000`** — precisely the literal
`lui a4, 0x770` seen written to `PB_CLR` at `0x0F132`, an "all rows" operation
in unrelated code. Two independent derivations of the same pin set.

### For a QMK port

```c
#define MATRIX_ROW_PINS { PB17, PB16, PB18, PB20, PB21, PB22 }
#define MATRIX_COL_PINS { PA0, PA1, PA2, PA3, PA15, PA14, PA13, PA12, \
                          PA7, PA8, PB7, PB6, PB5, PB4, PB3, PB2, PB1, PB0 }
#define DIODE_DIRECTION COL2ROW
```

Saved as `matrix_pins.json`. **Caveat:** the *order* of each table is the
firmware's own scan order. Whether row index 0 in the keymap corresponds to
`PB17` (first table entry) has **not** been verified against a physical keypress
— that is a one-key test, and worth doing before trusting the row order in a port.

### Also spotted

`0x0F10E` reads **`PA_PIN` bit 5** as a single bit and stores it to a global.
~~Plausibly the Mac/Win slider (§20).~~ **CORRECTED 2026-09-29 [T2]: PA5 and PA6
are the knob's rotary-encoder A/B lines.** `0x025AA` reads PA5 or PA6 by index;
`0x0263C` combines them as `(old<<2 | new) & 0xF` and indexes a table at
`0x3FC84` = `00 FF 01 00 01 00 00 FF FF 00 00 01 00 01 FF 00` — QMK's
`encoder_LUT`, byte for byte. The `0x0F10E` read is sleep-entry code arming PA5/PA6
edge wake (`0x0EF76`), i.e. turning the knob wakes the board. ~~Where the Mac/Win
switch is read remains unlocated~~ **RESOLVED 2026-09-29 [T2]:** the Mac/Win
switch is **PB9** and the cable/wireless switch **PB8** (poll `0x0FE90`); PA4 is
most likely USB VBUS / cable detect. See §84.

## 74. LED DRIVER identified — 2x AW20216S-class over SPI [T2]

Chased the same way as the matrix (§73), from the firmware alone.

### Resolving `set_led`

`0x09AF8` is a thunk — `auipc a5, 0x37 ; lw a5, -0x13c(a5) ; jr a5` — loading a
pointer stored at file `0x409BC`. Its value is `0x00015D5C`, and
`0x15D5C - 0x13000 = 0x02D5C`, a valid file offset. **Four neighbouring pointers
resolve cleanly the same way, which is a third independent confirmation of
BASE = `0x13000`** (§65, §67).

### What the real function does (`0x02D5C`)

```
index * 4  ->  4-byte descriptor from a table at file 0x40A10
byte0 & 3  ->  driver chip index
               stride = idx*8 - idx = *7, then *32 - itself = *31   => idx * 217
byte1/2/3  ->  R, G, B channel offsets within that chip's buffer
               skips the write when the value is unchanged (dirty-check)
sb a4, 0xd8(a5)   ->  sets a dirty flag at offset 216
```

**Stride 217 = 216 channels + 1 dirty byte.** A 216-channel SPI LED driver is the
**AW20216S** (18x12). Confirmed against the descriptor table:

```
119 LEDs, 4 bytes each, at file 0x40A10
  distinct driver indices used : 0 and 1        -> TWO driver chips
  channel offsets out of range : 0
  highest channel offset used  : 215            -> exactly a 216-channel part
  offsets step by 18 (3,21,39,57,...)           -> the 18-column arrangement
```

Saved as `led_map.json` — directly usable as the per-LED channel table for a QMK
port, which already supports AW20216S over SPI (§71).

### Consistency with the earlier evidence

- PWM (`0x40005000`) has **zero** references, so WS2812-by-PWM was already out.
- ~~SPI clock divider `0x9F` gives ~380-500 kHz; transfers length-bounded against
  `0xFD`.~~ **CORRECTED 2026-09-29 [T2]:** misread — `0x9F` is an interrupt-flag
  clear and the `0xFD` check bounds the (runtime) clock divider (§72). Neither
  says anything about clock rate or transfer size, so drop both as evidence.
- The driver code at `0x130F8` drives a GPIO low after SPI setup, per chip — a
  chip-select, consistent with two SPI devices.

The remaining evidence agrees. **[T2]** — the part *number* is an inference from
the 216-channel geometry and SPI interface rather than from a marking, so
"AW20216S-class" is the honest phrasing until someone reads the chip.

## 75. Physical bootloader entry — NOT found, and probably not reachable by a key [T1]

Tested with `tools/usbwatch.py` polling the **whole USB tree** (not just HID —
WCH's ROM ISP is a vendor-class device and would be invisible to hidapi).

```
[  8.0s] REMOVED  VID 0x19F5 PID 0x102D   NuPhy
[ 13.8s] ADDED    VID 0x19F5 PID 0x102D   NuPhy      <- normal app mode
```

Esc held at plug-in: no `0x4348`/`0x1A86` device. **Negative result.**

### Why a key combo probably cannot work here

The CH58x ROM bootloader samples its BOOT pin **at reset, before any firmware
runs**. At that instant every GPIO is in its reset state — input, no firmware-
configured pull-up. In a key matrix, pressing a key merely connects a *row* pin
to a *column* pin; with neither driven nor externally pulled, both float and the
BOOT pin never reaches a defined level.

A key-at-boot entry therefore only works if either (a) the BOOT pin carries an
external pull resistor and the key ties it to a rail, or (b) the *vendor
firmware* checks a key and jumps to IAP itself — and (b) is useless as a safety
net, because it is exactly the firmware being replaced.

So: **no software-free recovery path is established.** Reaching WCH's ROM ISP
most likely needs a PCB pad, which does mean opening the board.

### But a teardown is probably still unnecessary — develop on a devboard

The failure mode we are guarding against is narrow: an image the **NuPhy
bootloader accepts** (so it boots) that nevertheless lacks a working `0xEF`
handler (so there is no way back). Note what is *already* safe:

- An **incomplete or rejected** flash leaves the board in IAP mode, which NuPhyIO
  recovers. Observed three times, including deliberately.
- The NuPhy IAP bootloader lives **below `0x13000`** and is never written by the
  app-partition flash, so it survives anything we do to the app.

The clean way to avoid the narrow failure mode is to **not debug on the
keyboard**. A WCH CH582 devboard is a few dollars and exposes the BOOT button, so
ISP is always available. Bring the firmware up there, prove USB HID and the IAP
re-entry command work, and only then flash the keyboard.

**Recommendation: buy a CH582 devboard before writing any custom code.** It
removes the need for both a teardown and a physical recovery path on the
keyboard itself.

## 76. THE COMMAND DISPATCHER — located, and 3 hidden opcodes found [T2]

This closes the coverage gap flagged since §65: opcode completeness no longer
rests on NuPhy's app enum. It rests on the firmware's own dispatch table.

### The frame parser (`0x14168`)

```
0x14186  lbu a4, 0(a0)          byte[0]
0x1418E  lbu s8, 1(a0)          byte[1] = OPCODE
0x14198  bne a4, 0x55, bail     require frame magic 0x55
0x141A0  sb  0xAA, 0(a0)        write reply header in place
0x141AA  beq s8, 0xEE, hs       0xEE (handshake) special-cased BEFORE the table
0x141C0  lbu a7, 0(gp-0x3d0)    session key
0x141DC  xor ...                XOR-decode payload (unrolled) + accumulate checksum
```

`gp-0x3d0` is the session key store (set by `0xEE`). This resolves several older
inferences to code fact: byte 0 magic, the reply header, and that the payload is
XOR'd with a single key byte.

### The dispatch (`0x143CC`)

```
0x143CC  s8 = opcode - 0x2F
0x143D8  if s8 > 0xCF: default          range 0x2F..0xFE
0x143E4  jump table[s8] at file 0x42108  (208 entries, self-relative offsets)
```

A 208-entry jump table. 167 entries point at the default/bail handler
(`0x14460`); 41 opcodes have non-default entries, plus `0xEE` handled before the
table = **42 commands accepted**. **CORRECTED 2026-09-29 [T2]:** three of those 41
(`0xE3`/`0xE5`/`0xE6`) land on a no-op ack (below), so **38 functional handlers**
+ `0xEE`.

### Coverage result

NuPhy's app enum (`opcodes.json`, 39 commands) is **complete for what it lists** —
all 39 are accepted (`0xEE` via the pre-table path), though three are no-op acks. But the firmware handles
**three commands the app never sends and the enum never named:**

| opcode | handler | family | what the code does |
|--------|---------|--------|--------------------|
| **`0xD8`** | `0x14824` | lighting | **SetKeyLightColor.** Loops over 4-byte payload records `(index, c, c, c)`, bound to 119, writing a 3-byte RGB entry per LED into the custom-colour table at `gp+0x350`. This is the per-key colour SET that §54 hypothesised did not exist. |
| **`0xC4`** | `0x148EA` | macro | Calls a macro-storage routine over a 2 KB region (`0x062E4`). Sits with `0xC1`-`0xC3` (key upload / macro). Purpose not pinned beyond "macro-family write". |
| **`0xF4`** | `0x146DC` | sleep | **CORRECTED 2026-09-29 [T2]:** takes one payload byte and calls **`0x0F088`** (not `0x0F488`, as first read): `sb a0, 0x5EE(gp)` + set a dirty flag. That is the **auto-sleep on/off byte** — the same setter `0xF5` uses for byte 0, read back by `0xF3`. A **RAM-only** auto-sleep toggle (not persisted). It does not read PA5 (§73) or touch the rows. |

### Also learned from the table

- `0xE3 SetDebounceTime`, `0xE5 SetTouchBarConfig`, `0xE6 GetTouchBarConfig` share
  one handler entry (`0x14698`). **CORRECTED 2026-09-29 [T2]:** not a dispatch
  group — `0x14698` is `lbu a7,0(s7); j 0x1446A`, the common reply tail. It touches
  no state; it differs from the default (`0x14460`) only in not setting status
  `0xFF`. **These three are no-op acks in 1.0.6.6**: debounce/touch-bar writes
  are acknowledged and ignored.
- `0xEF SetIapMode` (`0x14720`) and `0xF1 RestoreFactory` (`0x14714`) are ordinary
  table entries — nothing special guards them, which is exactly why the early
  opcode sweep hit the bootloader (§47).

### Status

**[T2]** — read from the dispatch table and handler code, not executed. The three
hidden opcodes' *behaviour* is inferred from what their handlers do to memory,
which is stronger than a readback but is not T1. `0xD8` in particular is a live,
testable claim: send `0xD8 <len> ... <index,R,G,B>...` in a fixed-colour lighting
mode and watch the key. Not done autonomously — it is a write via a hidden
opcode, and confirming it needs eyes on the board.

## 77. `0xD8` live test — CORRECTED: works fully under hidden effect >= 21 [T1]

> **This section first concluded per-key colour was "dormant". That was WRONG** —
> I had only swept the 20 app-visible effects. The render lives at effect index
> **>= 21**, which the app never selects. Resolution in §78. The original
> (mistaken) investigation is kept below for the record.


I told Kyle `0xD8` was a live, testable claim and offered to light WASD red. The
test result is more interesting than a clean win, and worth stating exactly.

### Method

Sent `0xD8` setting **all 119 LEDs to red** (RAM table `gp+0x350`), then — instead
of relying on eyes — used `0xD2 GetKeyLightColor` (which reads the **rendered**
frame) to check, across **all 20 effects**, whether the custom red actually
renders. `0xD2` is a readback through a different channel than the write, so this
is a real test, not an ack.

### Result: no standard effect renders the custom table

```
effect 1..20 set, custom buffer = all red:  0 effects showed red
every effect rendered its OWN colours (blue base / its animation)
```

Kyle also confirmed by eye: the board stayed dim blue, never red.

### Why — the gate found in the render code

The render path (§76, `0x0B106`) is:

```
lbu a5, 0x15a(perLED_mask + led)   per-LED enable byte
lbu a4, 1(flags)                   a flags byte
and ; beqz -> SKIP this LED         renders custom ONLY if both set
```

`0xD8` writes the colour table but sets **neither** the per-LED enable mask nor
that flag. No exposed effect sets them either. So **per-key colour is a real
firmware capability that is dormant in the shipped firmware** — the write lands,
but nothing renders it without an additional enable step I have not located (and
which may be reachable only from another hidden command or from custom firmware).

### Status (superseded by §78)

The "no visible colour" conclusion held only because the sweep covered effects
1-20. It was **wrong as a general claim** — see §78.

### Re-test with sleep disabled (Kyle's catch)

The first run risked contamination: auto-sleep (default ON, 6 min) turns the LEDs
off, and a slept board reads as zeros on `0xD2`. Re-ran with **auto-sleep off**
(`sleep[0]=0`, verified) AND re-sending the `0xD8` buffer before each effect's
readback (in case switching effects re-inits the RAM table). **Same result** — no
effect rendered the custom red. So the dormant-render finding is confirmed, not a
sleep artifact.

Incidental: effects 11/12/13 (Ripple2/Point/Grid) read all-zero even with sleep
OFF, so they are **reactive** (light-on-keypress) effects, not a slept board.
That raises a hypothesis worth a future test: the per-LED enable mask that gates
custom colour may be the same mechanism reactive effects use per-key on
keypress — in which case `0xD8` colour might render on pressed keys under a
reactive effect. **[HYPOTHESIS, untested.]**

`0xD8` writes RAM only; a reboot clears it and the five config spaces are
untouched (verified against a pre-test backup).


## 78. Per-key RGB WORKS — hidden effect index >= 21 [T1]

The `0xD8` render is not dormant. §77 swept only the app's 20 effects; sweeping
**above** 20 (with `0xD2` readback) found that **every effect index >= 21 renders
the custom per-key table continuously**:

```
effect 21..79, custom buffer = all red:  0xD2 reads FF 00 00 on all 119 LEDs
```

The app only ever writes effect 1-20, so this mode is invisible to NuPhyIO but
fully functional. Confirmed by eye: WASD lit red on a black board.

### The complete per-key colour recipe (stock firmware)

```
1. SetLightState (0xD6): set byte0 (effect) = 21, byte4 (colour mode) = 0
2. 0xD8: send records (index, R, G, B), up to 14 LEDs per frame
```

- **Record byte order is `(index, R, G, B)`** — confirmed: writing `(idx,255,0,0)`
  reads back `FF 00 00` on `0xD2` and shows red.
- **LED index is row-major, 18 per row** — LEDs 0-17 = the top row (ESC + F1-F12
  + DEL/HOME/END/PGUP/PGDN), verified by lighting them. So
  `LED = matrix_row * 18 + matrix_col`. WASD = 38 / 55 / 56 / 57, verified by eye
  and by `0xD2` (exactly those four red, all else off).
- The buffer is RAM (`gp+0x350`); a reboot clears it and the five config spaces
  are untouched.

Verified rows 0-3 physically. Rows 4-5 and the side/underglow LEDs (indices
~101-118) follow the same formula by inference but were not individually pressed.

### Packaged

`nuphykit.lighting.enable_custom()` + `set_key_colors({led: (r,g,b)})`, and the
CLI:

```
uv run --with hidapi python -m nuphykit keycolor 255,0,0 W A S D --clear
```

`key_led.json` maps legends to LED indices.

### Correction trail

This overturns the §77 "dormant" conclusion, which itself corrected the §54 "not
settable" hypothesis. Net: per-key RGB is fully usable on stock firmware. The
chain of corrections is the point — each was published wrong-then-fixed rather
than quietly. Kyle's "run it once more" (re: sleep) is what reopened §77, and
sweeping past effect 20 is what resolved it.

## 79. Tap-hold, the two remaining hidden opcodes, and sleep internals [T2]

Static decode, from the firmware image.

### Tap Dance "hold" — the firmware DOES have a real hold path (§13)

The tap-dance state machine is at `0x06A00`+. The tap and double-tap actions
(`0x06A70`, `0x06CAC`, `0x06D32`) are press+release pairs:

```
sb 1, 8(report) ; jal register(keycode)     ; press
sb 0, 8(report) ; jal unregister(keycode)   ; release   <- immediately after
```

~~Register then unregister as an unconditional pair; no code path leaves a keycode
held.~~ **CORRECTED 2026-09-29 [T2]:** the **hold** action is different. At
`0x06B2A`-`0x06B96`, once elapsed time exceeds the timing field, it sets a bit in
a held-mask (`gp+0x70`) and calls `register_code` (`0x033AA`) on the hold keycode
— or `layer_on` (`0x03D16`) / a press-only record — with **no** immediate
unregister. The release comes on **physical key-up**: `0x06F0E` (`pressed == 0`)
-> `0x06DB2`, which tests and clears the held bit and unregisters the hold keycode
(`0x06E9A`). So the code does not explain §13's "long-press does not hold"; that
cause is **unlocated**.

Record: 8 bytes, three 16-bit **big-endian** keycodes (tap @0, double @2, hold @4)
and a timing field @6. ~~Clamped/capped at 100.~~ **CORRECTED 2026-09-29 [T2]:**
`0x06AD0` is a **floor**: `if (t < 100) t = 100` — larger values are kept
(`0x06C80` is a keycode-range check, not a clamp). `more tap hold` (`0x06B1E`) is
printed immediately before the hold path runs, not for an unexpected state.

### `0xC4` (hidden) — macro-storage maintenance

Handler `0x148EA` -> `0x062E4`. Fetches a buffer via `0x38524`, then runs two
block operations over **2 KB regions** (`0x800`). Sits with `0xC1 SetKeyUpload` /
`0xC2 GetMacro` / `0xC3 SetMacro`. Consistent with a macro compact / save-to-flash
op. **Family and shape are clear; the exact semantics are not pinned.**

### `0xF4` (hidden) — RAM-only auto-sleep toggle

**CORRECTED 2026-09-29 [T2]** (was "re-read Mac/Win switch + re-init"). Handler
`0x146DC` is `lbu a0, 8(s0) ; jal 0x0F088` — the target is **`0x0F088`**, not
`0x0F488` as first read:

```
0x0F088  sb a0, 0x5EE(gp)     auto-sleep on/off byte
         sb 1, -0x3F1(gp)     dirty flag
         ret
```

The same setter `0xF5` uses for sleep byte 0 (`0x14B34`); `0xF3` reads it back
(`0x0F082`). So `0xF4` sets auto-sleep on/off **in RAM, without persisting**. The
app's report/event enum names `SleepCfgChange=0xF4` (§50) — the same number, though
there it is an event type, so the match is suggestive only. It reads no
GPIO; ~~Mac/Win switch = PA5~~ is withdrawn — PA5/PA6 are the knob encoder (§73);
the Mac/Win switch is PB9 (§84).
The PA5-sampling routine at `0x0F488` exists but is sleep-entry code, not `0xF4`.

### Sleep config is 6 bytes, not 4

`SetSleepCfg` (`0xF5`, `0x14740`) bounds-checks the count against **6** and
persists **6 bytes** to flash (via a save call, target ~`0x25`). But
`GetSleepInfo` (`0xF3`) returns only the first **4** (`auto, L1, L2, byte3`).

| byte | meaning | notes |
|------|---------|-------|
| 0 | auto-sleep on/off | consumed; live copy at `gp+0x5EE` (setter `0x0F088`, also used by `0xF4`) |
| 1 | Level-1 minutes | consumed |
| 2 | Level-2 minutes | consumed (read at `0x134B2`) |
| 3 | factory `0x04` | ~~no direct consumer found~~ **CORRECTED 2026-09-29 [T2]:** early-sleep delay, seconds — read at `0x0F37C` (`byte3 x 100` 10 ms ticks); enters L1 early only when three activity/LED flags are zero and PA4 is low |
| 4-5 | stored, persisted | not returned by GetSleepInfo; **byte 4 gates `0xD6`** (must be 1 for SetLightState to act, `0x14874`) and light loading |

So `nuphykit`'s `sleep` space (4 bytes) covers what the app uses, but the firmware
keeps two more bytes. Low impact — they were factory-default across every backup.

### Still genuinely unresolved (minor)

- **Light-speed gear scale** (`0xD5` byte 2) — the byte is identified; the mapping
  from gear value to animation rate is not decoded.
- **The 14-byte write at `0x0F44`** on first Mode Settings use — still unexplained;
  it lands in the macro arena and no toggle changes it again (§60).


## 80. CH582 vs CH583 — cannot be confirmed from firmware [T2]

Kyle asked whether we are actually sure it is a CH582. **We are not.**

### The `0x82` is a hardcoded constant, not a chip-ID read

`GetBase` (`0xA0`, handler `0x14914`) builds its reply from literals:

```
sb 0x08, 9(s0)     sb 0x04, 0xa(s0)   sb 0x06, 0xb(s0)   sb 0x12, 0xc(s0)
addi a5, zero, -0x7e ; = 0x82         sb a5, 0xd(s0)     <- byte 5 = 0x82, HARDCODED
```

`0x82` is an immediate baked into the firmware, not read from silicon. A full
scan finds **no read of `R8_CHIP_ID`** (`0x40001040`-`43`) anywhere. So the byte
is at best NuPhy's own model marker (they'd know their part) — not independent
hardware evidence, and possibly unrelated to the WCH family code.

### What the firmware can and cannot tell us

| discriminator | finding | verdict |
|---------------|---------|---------|
| flash used (358 KB @ base `0x13000`) | needs >=448 KB | CH582 (448) and CH583 (512) both fit |
| RAM | 32 KB @ `0x20000000` | both |
| USB **host** controller `0x40009000` | **not referenced** | consistent with CH582's single USB; a CH583 keyboard would also skip host |
| GPIO extent | matrix uses up to PB22 | both dies expose PB22 |
| `R8_CHIP_ID` read | **absent** | no help |

The no-host + hardcoded `0x82` *lean* CH582 but prove nothing; a CH583 board
looks identical to this firmware.

### To actually confirm (both need eyes on the PCB)

1. **Read the MCU marking** — remove the case (no desoldering). Definitive.
2. **WCH ROM ISP** — `wchisp` reports the exact chip, but ROM-ISP entry needs a
   BOOT pad, also inside the case.

The HID protocol cannot read arbitrary MCU registers (`0xB2` reads the config
store `0x0000`-`0x1BFF`, not `0x40001041`), so there is **no software-only way**
to read the chip ID from the running firmware.

### Practical impact

For a **development devboard**, CH582 and CH583 share the SDK, HAL, toolchain and
the keyboard-relevant peripherals (GPIO/SPI/USB-device), and the QMK port targets
CH582M — so a CH582 devboard is a reasonable *development* choice regardless. But
we have **not** verified the keyboard's actual part, and if it is a CH583, code
built for CH582 could need minor adjustment. If certainty matters, read the
marking off the board before buying.

## 81. Do we need a devboard? Recovery architecture [T2]

Kyle: is bad firmware recoverable on the device itself?

### How IAP entry actually works

`0xEF SetIapMode` -> `0x12BF2`:

```
read a flag from DataFlash (WCH EEPROM read op)
if flag != 0x55:  erase; write 0x55
reset
```

NuPhy's bootloader uses a **persistent "stay in IAP" flag** (`0x55` in DataFlash).
At power-on the bootloader reads it: `0x55` -> remain in bootloader (PID `0x072D`);
else -> jump to the app partition. The finalize frame (`0x83`) clears it. And per
§69 the bootloader does **no validation** — it jumps to whatever is in the app
partition, valid or not.

### Consequence for recovery

| flashed firmware | on-device recovery? |
|------------------|---------------------|
| runs + handles `0xEF` (e.g. the §69 string edit) | **YES** — send `0xEF`, reflash. Proven 3x. |
| runs + USB works, `0xEF` handler broken | only if the stock recovery code was preserved |
| does not enumerate / crashes in early startup | **NO** — needs WCH ROM ISP (BOOT pad, case open) |

### The key leverage: recoverability is buildable-in

Because the bootloader validates nothing and we flash the entire app partition,
**every custom image can carry the stock recovery path unchanged**: the frame
parser (`0x14168`), the dispatch table (`0x42108`), the `0xEF` handler
(`0x12BF2`), and the USB device code (`0x40008000` region) — a few KB total.
Preserve those bytes and `0xEF`-reflash always works. This is a guaranteeable
property, not luck, precisely because nothing checks the image.

The only failure it cannot cover is a bug that corrupts execution **before** the
USB/dispatch code runs. That residual risk is what a devboard — or a one-time
case-open to reach the BOOT pad for ROM ISP — insures against.

### Unknown

Whether NuPhy's bootloader has a **watchdog** that re-enters IAP on repeated
early app crashes. If it does, even a non-enumerating build self-recovers. The
bootloader is below `0x13000` and **not in the dumped image**, so this is
untested — it would need a bootloader dump (via ROM ISP) or an empirical
brick-and-see, which defeats the purpose.

### Answer

A devboard is **insurance, not a requirement.** Disciplined incremental
development — keeping the stock USB + `0xEF` recovery code byte-identical in every
flashed image — is recoverable on the keyboard itself with no case-opening. The
devboard (or a single case-open to locate the BOOT pad) only adds a safety net for
the "totally dead build" case, which careful development avoids.

## 82. The firmware debug log streams over the raw interface — radio visibility [T1/T2]

Found 2026-09-29 while chasing a dead 2.4G link. **The board pushes its printf
debug log to the host as `0xFE LogUpload` reports** on the raw interface — the
same strings §64 listed from the binary, live. `GetDebugEnable` (`0xFD`) reads
`0xBB` on this board; it was never set by us, so this is presumably the shipped
state [T4 for "shipped"]. Nothing needs enabling.

### Frame format [T2]

```
fe <parts> <index> <text, space-padded to 64>
```

**Plaintext — not XORed with the session key.** Listening needs no `0xEE`
handshake, so it does **not** orphan NuPhyIO's session (§60). A message longer
than 61 bytes spans frames sharing `parts`, index `0..parts-1`, continuing
mid-word. Two other unsolicited reports ride the same pipe, also plaintext:

| report | meaning | seen |
|--------|---------|------|
| `0xA2 ModeStateChange` | byte 1 = active layer; byte 2 = `01` in the Windows set | `a2 02` on `TG(2)`, `a2 01` while Fn (`MO(1)`) is held, `a2 04 01` on flipping to Win |
| `0xD7 LightStateChange` | the 17-byte lighting record of the mode just entered | every Mac/Win flip (§62) |

`nuphykit log` decodes all three live (`--raw` for hex).

### What the radio tells us

A 2.4G attempt that **failed** (keyboard switched to 2.4G, dongle plugged in the
whole time):

```
======cur channel 4, addr 7B00, mac 000000000000 ========      <- 2.4G slot is EMPTY
=========2.4g Mode, channel 8, addr 1903575337 ========
=========switch to rf 24==========
===========keyboard want to pair, channel 34, addr 1207380725 ======
                                                                 <- ...silence
```

And the fix — switch to 2.4G, then **unplug and replug the dongle**:

```
===========keyboard want to pair, channel 2, addr 1207380725 ======
dongle 1,  mac 11107D5E3D0C, rssi 62
choice mac 11107D5E3D0C, rssi 62
=======actory_test 0
rf has connected
err rate samples: 0 0 0 0 0
====chan 2, rate 0, rssi -60, ack 1 ===                        <- periodic link health
```

A BLE connect, for comparison (slot 1 = BT1, `mac` is the keyboard's own BLE
address, matching the host's view `F4:00:F5:2A:F7:47` byte-reversed):

```
=========switch to ble channel 1 ==========
======cur channel 1, addr 7800, mac 47F72AF500F4 ========
Initialized.. / Advertising.. / ble connected, remote mac 2018387EF908
Phy update Rx:2 Tx:2 ..                                         <- 2M PHY
set connect param failed 0x:18                                  <- every connect; link still works
```

Conclusions:

- **The link slots (`cur channel 1..4`, `addr 7800..7B00`) are separate storage**
  holding the BLE bonds and the 2.4G pairing. None of the five spaces (§63)
  contains them, so `backup`/`restore` cannot preserve them. **[T2]**
- **An empty 2.4G slot makes the keyboard pair on every 2.4G selection**, and the
  dongle only answers pairing just after it is plugged in. ~~The 2026-08-08 factory
  reset is the likely eraser~~ **CORRECTED 2026-09-29 [T2]:** factory reset does
  *not* touch the 2.4G record (it erases the BLE bonds). The record is invalidated
  at the **start of any 2.4G pairing** — holding `KC_FN_LINK_24G` (`0x7E02`) or
  selecting 2.4G while invalid — so a pairing the dongle never answered left it
  empty. See §84. **[T1 for the fix]**
- **Recovery: select 2.4G, then replug the dongle.** No app, no key combo. **[T1]**
- The periodic `chan / rate / rssi / ack` line and `err rate samples`, plus the
  hop messages (`do hop channel %d -> %d`, `channel %d is too bad, should jump`,
  `rollback to channel`), are the instrumentation for diagnosing 2.4G dropouts
  and key repeat. **[OPEN]**
- `0x2F GetDongelName` returns `01 ff ff...` with the dongle connected, so §51's
  "no dongle attached" reading was wrong. **[T2]**

## 83. The 2.4G dongle — its own firmware, forwards nothing [T2, spot-checked T2 live]

The receiver (VID `0x19F5` PID `0x2620`) runs **separate firmware**, also
published: `keyBoardList` gives the Air100 V3 `dongleIds: 1930094682698977282`,
and `getLastFirmwareVersionsByType?businessId=1930094682698977282&type=1`
returns **4.0.5.6** (`dongle_4.0.5.bin`, 172,852 B, sha256 `77b10b42…4762`
matching the API). Same platform as the keyboard: CH58x, `CH58x_BLE_LIB_V2.0`,
unencrypted, base `0x13000`; descriptor at `0x292E0` confirms `19F5:2620`.

### Its raw interface answers everything locally

Same `0x55` frame, same XOR/checksum (parser `0x26F8`, a compare chain, no table).
**No opcode is forwarded to the keyboard** — there is no path from the USB
parser to radio TX. The whole handler set:

| opcode | behaviour |
|--------|-----------|
| `0xEE` | handshake; key = raw frame byte `0x1C`, **no** length/non-zero check |
| `0xEF` | **bootloader entry** — writes `0x55` to data-flash 0 and resets. **Never send.** |
| `0xA1` | constant `05 00 04 aa 06 00` — **confirmed live** |
| `0xE4` | TestDelayTime echo |
| `0xFD` | GetDebugEnable — debug flag; `00` out of the box — **confirmed live** |
| `0xFE` | SetDebugLog — sets the flag and **persists** it (data-flash offset 4) |
| other  | status `0xFF`, payload echoed: `0xA0`, `0x2F`, all `B*`/`C*`/`D*` |

So NuPhyIO cannot configure the board *through* the dongle with these frames, and
the keyboard's `0xFE`/`0xA2`/`0xD7` reports never reach the host over 2.4G (the
RF→USB path accepts only the three HID report kinds; anything else is logged
"undeal data" and dropped). **Keyboard telemetry over 2.4G needs the cable (§82).**

### The dongle's own log

With the flag on (`nuphykit dongle-debug on`; off by default, persists across
replug), the dongle emits the same `fe <parts> <idx> <text>` plaintext frames.
It has **no RSSI or error-rate output** — those live only on the keyboard — but
does log channel hops (`jump to channel`, `hop success, save channel`,
`rollback to flash channel`), RF errors (`error onne`), and its USB-side
failures (below). A quiet link logs nothing: 20 s with the flag on produced no
frames. RX counters exist at `gp-0x684/-0x688/-0x68C` but are never exported.

### What this means for wireless key repeat

- **Key-up is implicit.** Reports are full-state (8-byte boot / 19-byte NKRO /
  mouse+consumer); a release is simply a later report without the key.
- **Every data packet is acked** at application level; duplicates are dropped by
  a 32-bit sequence number compared with the last delivered one. Retransmission
  is keyboard-driven.
- **Link-loss release after ~1 s.** Each valid RX re-arms a `0x640`-tick (~1.0 s)
  timer; if it fires, the dongle injects an all-zero report (unless the host has
  suspended USB). So a key held at a dropout is released about a second later.
  **With Hyprland's 250 ms repeat delay and 40/s rate that is ~30 repeats** — the
  size of the observed `rrrr` bursts. A 1 s dropout mid-keypress is therefore the
  prime suspect. [T4 — not yet caught live]
- **The dongle can drop a key-up itself** when its USB side is blocked: a failed
  IN send retries 5× (~2 ms) then 4× (~1.5 s, `equal > max`), then **flushes the
  whole 200-report queue** (`over send remove`); a full queue also flushes
  (`queue is full`). Those strings in the dongle log would pin a repeat on the
  receiver rather than the radio.

`nuphykit diag` merges the keyboard log (cable), the dongle log, and evdev key
timing into one timeline for catching an incident.

## 84. Modes, storage map, the radio's failure paths [T2 static; live checks marked]

Static analysis of fw 1.0.6.6 by three passes on 2026-09-29, spot-checked live
where a read could do it. File offsets; RAM code at file `0x4..0x22FC` runs at
`0x20000000`. TMOS tick = 625 us.

### Payload byte 3 selects the Mac/Win mode

The parser keeps decoded frame byte 7 — the "pad" byte every tool sent as 0 —
and `0xD5`/`0xD6`/`0xE1`/`0xE2` compare it with `mode()` (`0x0FE7E`: 0 = Mac,
1 = Win). Equal: the live RAM copy. Not equal: straight to that mode's record
in flash. **`GetBase` byte 0 is `mode()`** (`0x14914`).

Live [T2]: `0xA0` byte 0 = `00` in Mac; `0xD5` with pad `1` returns the Windows
record (`06 32 02 00 01 74 00 05 80 04 3c 02 01 00 ff 00 00`, matching the
`0xD7` pushed on a flip except byte 5, which the stored path assembles
differently), stable across 15 reads. `nuphykit` now reads and writes `func`
and `light` per mode and snapshots both.

### Data flash

| DF | contents |
|----|----------|
| `0x0000` | IAP flag — `0xEF` writes `0x55` |
| `0x0004`-`05` | debug flags; `0xFD` reads byte 5 (`0xBB`); `0xFE` programs **without erase** |
| `0x0500`-`052F` | **link info block**: `+0` current slot 0-3, `+0x14` 2.4G address (u32; `0x71764129` = default/unpaired), `+0x18` 2.4G channel, `+0x19` BLE bond bitmask, `+0x1A` 2.4G paired, `+0x1B` bit 0 = wipe all bonds at next boot, `+0x1C..` 20 bytes returned by `0x2F` |
| `0x4F00` | boot marker; `KC_FN_BOOT_ENTRY` `0x7E00` writes `0x0A` [T4] |
| `0x5000`-`6FFF` | QMK EEPROM emulation (below) |
| `0x7800`-`7BFF` | BLE bond storage, one page per slot |

QMK eeprom (DF `0x5000` + offset): `0x000`-`0x024` eeconfig incl. **`0x004`
`keymap_config`** (the Ctrl/Caps swap, §57/§58); `0x025` sleep (6 bytes);
`0x07F`-`0x438` appdefine; `0x425`/`0x461` Mac/Win light core, `0x443`/`0x47F`
Mac/Win light aux, `0x457`/`0x493` Mac/Win func; `0x49D` keymap-version magic;
`0x4A1`-`0xB60` keymap (8 x `0xD8`, big-endian); `0xB61` knob; `0xB81` Mac
macros; `0x1381` **Win macros**; `0x1B81`/`0x1C01` SOCD, `0x1C81`/`0x1D81`
TapDance, `0x1E81`/`0x1EC1` TGL, each Mac/Win.

So config memory (`0xB2`/`0xB3`) is a holey view of eeprom `0x4A1`-`0x2000` —
which is where the §56 knob alias comes from — and the macro/SOCD/TapDance/TGL
tables are **per mode**. **No command reaches eeprom below `0x7F` or the link
storage**, so the swap flag and the pairings cannot be backed up.

### Hazards found

- **`0xE2` is unbounded.** Active mode: `memcpy` to RAM `0x20003148 + addr`.
  Inactive mode: eeprom `0x457`/`0x493 + addr` up to `0x2000` — it can overwrite
  the keymap and macros. Keep `addr + len <= 4` (`nuphykit` refuses otherwise).
- **`0xFB`/`0xFC` are bounded at `0x400`, not `0x3BA`.** Appdefine `0x3A6`-`0x3B9`
  *is* the Mac light core and `0x3D8` the Mac func: live, `0xFB` at `0x3D8`
  returns `02 00 00 00` = `func@mac` [T2]. `nuphykit` stops appdefine writes at
  `0x3A6`.
- **`0xC4`** (hidden) zero-fills **both** macro buffers in flash.
- **`0xE4 TestDelayTime`** measures nothing: with payload byte 1 non-zero it
  **types Enter** through the active transport and sends no reply.

### Switches, debounce, battery

- **Mac/Win = PB9** (high = Mac, `kb_state[7] = 0xA2`, base layer 0; low = Win,
  `0xA1`, bank 4), **cable/wireless = PB8**; poll `0x0FE90`, 25-sample debounce.
  PA4 is most likely VBUS/cable detect. Wireless slot comes from `0x7E02`-`0x7E05`.
- **Debounce is QMK `sym_eager_pk`**, lock = `func[0] x 10 ms` (this board: 20 ms),
  matrix scanned every 1.875 ms; no range check (0 disables). `0xE3` is a no-op.
  A 29 ms re-press (seen once in `diag`) passes a 20 ms lock — chatter, not RF.
- **Battery** is measured (PA9/AIN13, ~every 400 s) and reported **only** over
  BLE Battery Service; nothing over 2.4G or raw HID. <=10 % blinks red and caps
  brightness; it changes nothing in the radio.

### Link slots: what erases them

Factory reset (`0xF1`, or holding `0x7E13`) erases **all BLE bonds** and resets
the slot to 2.4G, but **leaves the 2.4G record alone**. The 2.4G record is
invalidated at the **start of any 2.4G pairing** (`0x1AF78`) — holding
`KC_FN_LINK_24G` or selecting 2.4G while invalid — so an unanswered pairing
leaves it empty (§82). Separately, a BLE connect whose peer address reads as
all-zero sets the wipe-at-boot bit and erases every bond on next boot.

### The 2.4G link, keyboard side (`0x1A080`-`0x1B6D6`)

- **TX queue**: 100 x 40-byte FIFO; a failing head blocks everything behind it;
  a full queue is flushed whole. HID reports are RF type 0, full-state.
- **Retries**: every ~4 ms until acked, **at most 50 (~300 ms)**. Then the
  packet is **dropped** — log `over 50 times ... type 0` and `loss a key`.
  **A dropped key-up is never repaired**; nothing re-sends key state.
- **Keep-alive**: type 4, every 600 ms when idle or unanswered. It re-arms the
  dongle's 1 s release timer (§83), so a key stuck by a dropped key-up **stays
  down until the next report gets through**. Live [T1]: a 3.5 s hold on 2.4G
  was delivered as one continuous hold; the dongle passes no keep-alive to USB,
  so its interval cannot be seen from the host.
- **Disconnect**: 4 silent windows (~2.4-3 s) → `disconnect, and reconnect`,
  `rf has disconnect`, probing every 150 ms then channel stepping. **Reports are
  refused while reconnecting** (except just after sleep), so keys typed then are
  lost.
- **Hops**: `channel %d is too bad` is advisory only; a real hop happens when one
  packet needs >=14 retries (max once per 6 s): `prepare hop` → `do hop`.
- **Log fields**: `err rate samples` = per-600 ms-window retransmit % (5 windows
  per line); `rate` = share of those above 32 %; `rssi` = mean dBm of dongle
  packets in the last window; `ack` = mean ms to ack; `chan` = channel.

### Sleep

L1 (after `sleep[1]` minutes, or `sleep[3]` s early when lighting is off) stops
scanning and LEDs; **the radio stays up**. L2 (after `sleep[2]` more minutes, or
2 min disconnected) shuts the radio. Live [T1]: at ~6.3 min idle the keyboard
**dropped its USB device** even with the cable in, and re-enumerated on the
next keypress; the wake keystroke arrived intact. After an L2 wake each report
gets one blind transmission until sync, so first keys can be lost. If the
dongle reports its USB as suspended for 5 s, the keyboard logs `kbd shuld
sleep` and deep-sleeps — Linux USB autosuspend of the dongle would do this;
on this host it is off (`power/control=on`, never suspended).

### What causes "rrrr" — ranked, with the log line that would confirm each

1. **Key-up dropped after 50 retries during a short fade** while still
   "connected": `loss a key` / `over 50 times ... type 0`, high `err rate
   samples`; in `diag`, the release arrives with the *next* key. Fits repeats
   mid-sentence.
2. **Full disconnect/reconnect**: `rf has disconnect` ... `rf has connected`;
   the release comes ~1 s after the last report (dongle timer); keys typed
   during the reconnect are missing.
3. **Hop churn**: `prepare hop` / `do hop` here, `jump to channel` in the dongle log.
4. **Dongle USB-side flush**: `over send remove` / `queue is full` (dongle log).
5. **Post-sleep one-shot window**, **host suspend** — ruled out on this host
   for the reported mid-typing case.
6. **Switch chatter** (not RF): release→press 20-30 ms on one key; also on cable.

