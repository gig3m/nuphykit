# Evidence audit — NuPhy Air100 V3 protocol

Every claim in `PROTOCOL.md` re-classified by **the method that produced it**,
not by how confident it felt. Written after a run of confident claims that turned
out wrong (address formula, keycode width, layer count, slot indexing).

## Evidence tiers

| tier | meaning | can it be reported as proven? |
|------|---------|-------------------------------|
| **T1** | physical device behaviour observed by a human | yes |
| **T2** | readback through a **different channel** than the write | yes |
| **T3** | device acknowledgement | **no** — the device acks writes it discards |
| **T4** | inference, or reading NuPhy's source | **no** — hypothesis until exercised |

Rules this audit enforces:

1. No rule from fewer than **3 samples spanning the extremes** of its domain.
2. Every rule must have a **falsifying test that was actually run**.
3. No promotion across tiers. An ack is never "confirmed".
4. Unknowns are split into *named* and *unprobed regions* — the second list is
   where every past error lived.
5. **The discriminator must not live in the same domain as the mechanism under
   test.** Testing a modifier-swapping switch with modifier keycodes cost four
   rounds and produced a self-contradictory result. Prefer an inert, unambiguous
   probe — a plain letter — whose failure mode cannot be confused with the
   negative case.
5b. **A reset differential shows correlation, never causation.** A factory reset
   clears everything simultaneously, so "byte X changed across the reset" does not
   make byte X the cause. The `0xE1` Ctrl/Caps candidate looked compelling and all
   four reconstructions of it failed (PROTOCOL §59). Reconstruct the state
   deliberately from a clean baseline before believing any reset differential.
5a. **T1 is only as good as the observation channel.** "Physical behaviour a human
   observed" still passes through the OS, which may rewrite it. A host-side
   remapper (Raycast's Hyper Key, on the Caps Lock scancode) silently inverted a
   T1 result for four rounds. **Before any keypress test, verify the host is not
   transforming input** — see the checklist in docs/BENCH-NOTES.md. Corollary: prefer probe
   keycodes that no remapper would plausibly target. Plain letters again.
6. **Ask for the control state explicitly at every step.** The contradiction
   survived two extra rounds because switch position was assumed rather than
   restated per press.

---

## A. Claims that survive the audit

| § | claim | tier | samples | falsifier run |
|---|-------|------|---------|---------------|
| 1 | transport: 64-byte reports, ID 0, usage_page 0x01/usage 0x00 | T2 | hundreds of ops | wrong interface fails |
| 2 | checksum = `sum(bytes[4..63]) & 0xFF` | T2 | every packet captured | mismatched cs rejected |
| 3 | writes require a session; unsessioned writes are ack'd then discarded | T2 | plaintext write → readback unchanged | yes — that *is* the falsifier |
| 4.1 | `0xB3` sets a keycode | T1 | typing verified repeatedly | yes |
| 19/34 | `addr16 = layer*0xDC + 2*(row*18+col)` | T2 | 4 keys + full 110-slot bulk read + app byte-match at `0x014A` | yes — the old formula failed on arrows |
| 21 | keymap entries are **16-bit** | T2 | `0xF0FE00` truncated to `0xFE00` in readback | yes |
| 22 | modifier range `0x0100`–`0x1FFF` works | T1 | Ctrl+C on F14 | yes |
| 22.1 | `TG(n)` locks a layer; `TT(n)` degrades to momentary | T1 | both tested on device | yes |
| — | layer chaining 3 deep (L0→L2→L3) | T1 | distinct letters at each depth | yes |
| 13 | Tap Dance long-press **fires discretely**, does not hold | T1 | HYPR→nothing, LCTL→no Ctrl, KC_B→visible `b` | yes — three probes, one positive. **CORRECTED 2026-09-29 [T2]:** the firmware *does* have a hold path (§79), so the cause of this observation is unlocated; not re-tested. QMK mod-tap works (§22) |
| 26 | macro JSON ↔ wire encoding | T2 | byte-for-byte vs captured `0xC3` | yes |
| 35 | macro offset table at `0x0700`, 32 entries | T2 | differential scan | yes |
| 36 | TD/TGL/SOCD table bases and record sizes | T2 | differential, offsets 0/3/7/16/32 | yes — exposed the byte-offset bug |
| 32 | the 19 wire codes, via rendered DOM | T2 | icon-id match against picker | partial (see C) |

---

## B. Claims DEMOTED by this audit

### B1. "Handshake requires 56 random bytes" — **FALSIFIED, now resolved (T2)**
Swept 0,1,8,16,17..32,48,55,56 and an all-zero 56.

```
 0 -> key 0x00 (degenerate)      1,8,16,17,18,19,20 -> REJECTED
21..32,48,55,56 -> accepted      56 ZERO bytes      -> REJECTED
```

**Minimum challenge length is 21 bytes, and content matters** — a full-length
all-zero challenge is refused. "56 required" was wrong on both counts. `nuphy`
now sends 32.

### B2. "The four init commands are required before writes" — **FALSIFIED (T2)**
Tested with none / only 0xFA / only 0xA0 / all four, each followed by a write and
a readback:

```
init=none       wrote 0x0005 -> read 0x0005   WRITE TOOK
init=only 0xFA  wrote 0x0005 -> read 0x0005   WRITE TOOK
init=only 0xA0  wrote 0x0005 -> read 0x0005   WRITE TOOK
init=all four   wrote 0x0005 -> read 0x0005   WRITE TOOK
```

**No init command is required.** The handshake alone authorises writes. `nuphy`
no longer sends them (`--init` retained for parity only).

### B3. "The physical Mac/Win switch selects the base layer" — **now T1, CONFIRMED**
Was demoted to T4 (inferred from Fn holding `MO(1)` in bank 0 and `MO(5)` in bank
4, switch never flipped). **Now properly established.** Different plain letters
written to the same slot in bank 0 and bank 4, switch flipped, one key pressed:

```
slot 33  bank0='a' bank4='z'   Win -> z    Mac -> a    Win -> z
slot 54  bank0='b' bank4='y'   Win -> y    Mac -> b
slot 54  bank0=HYPR bank4='y'  Win -> y    Mac -> Hyper
```

Same switch position agreed on repeat, so it selects rather than merely
triggering a reload. Full-image diff across a flip: **0 differences** — the switch
writes nothing. Mac → bank 0, Windows → bank 4, live, no replug.

**Cost: four rounds — and the real cause was NOT what I first wrote.** The first
two attempts used modifiers (Caps=Hyper, and the LALT/LGUI pair the switch itself
swaps) and returned a flat contradiction: bank 0's Caps *and* bank 4's numpad
appeared live in the same switch position. I attributed that to a mod-mask
failing silently, and to a mis-set switch. **Both explanations were wrong.**

**Actual cause: a host-side remapper.** Raycast's Hyper Key feature was enabled
with `keyCode 57` (`0x39` = Caps Lock) and `includeShiftKey`. On Win the board
correctly served bank 4, whose Caps holds the literal `0x0039` scancode — and
**macOS turned that into Hyper before it reached the browser.** The bank model
was right from the first test; the observation channel was lying.

~~Distinguishing signature, visible in the capture the whole time: the keyboard's
own `0x0F00` sets four modifier bits across successive HID reports, so keydowns
arrive **staggered** (~5 ms apart, building `ctrl` → `ctrl+shift` → ...). Raycast
injects all four in **one atomic event**. Kyle flagged that difference early and
it was parked as noise; it was the entire answer.~~ **CORRECTED 2026-09-29 [T1]:**
raw HID capture shows the keyboard sends `0x0F00` in **one** report; the stagger
was the host splitting it. There is no timing tell — read reports below the OS
(PROTOCOL §20, BENCH-NOTES HAZARD 8).

### B4. "There is no commit opcode" — was CONFIRMED, now **unfalsifiable as stated**
What is established (T1) is that writes survive unplug/replug *without* a commit.
"No such opcode exists" is a claim about absence over an unenumerated opcode
space. Restate as: **no commit is required.**

### B5. "DKS/RS/HT are impossible on this board" — **restated, structural**
Was T4 (read from the app's model definition: `isMachineAxis: true`, empty
precision arrays). **Now a structural fact:** this model's keycode table has zero
entries tagged `0x90`-`0x95`; those tags belong to the hall-effect enum in module
`99726`. **There is no such keycode to bind**, so the "bind one and press it"
test cannot be constructed. Whether the firmware would honour a synthesised code
remains untested and is not worth pursuing (mechanical switches, no analog
travel). See PROTOCOL §57.

### B6. enum→wire translation table — **T4** (one leg now T1)
Built by aligning 99 rendered keys against 99 non-empty matrix slots, assuming
the 2 extras are the knob. The alignment is inference. Individual pairs were not
independently verified by writing a wire code and confirming the resulting
behaviour.

**Update:** the load-bearing assumption — that slots 108/109 are the knob — is
now **T1-confirmed** (PROTOCOL §56). The rest of the alignment remains inference.

### B7. "Address space extends to 0x2000" — **RESOLVED (T2)**
Probed 0x2000, 0x3000, 0x4000, 0x8000, 0xC000, 0xF000, 0xFF00. **Every offset
replies**; all return zeros beyond 0x1BFF. So the device answers reads across the
whole 16-bit offset range, and the *populated* region is `0x0000`-`0x1BFF`.
The earlier phrasing conflated "where I stopped" with "where data ends".

### B9. `golden.bin` was a contaminated baseline — **found 2026-08-08**
Every "verified 0 differences" check in this project measured against a reference
that carried 664 bytes of non-factory state, including `0xCDCD` / `0x2B2D`
corruption in bank 5 and `0x0306` in bank 3 left by the opcode-sweep incident.
No conclusion depended on those bytes, but `0x0306` **was written up in §56 as
genuine factory data**. Rebuilt from a true factory reset; see PROTOCOL §59.

**Rule this adds: a baseline must be established from a known-clean device state,
not from "the earliest snapshot I happen to have."** The earliest snapshot was
taken *after* the damage.

### B8. "NuPhyIO does not revert writes" — **T2, n=1**
One dump → connect cycle → dump. True as far as it goes, but a single trial, and
the app has since proven unreliable in ways I could not diagnose.

---

## C. Regions and subsystems never probed at all

This is the list that matters — every past error came from here, not from B.

1. ~~Anything above `0x2000`~~ — RESOLVED: device replies at every offset to
   0xFF00; data and writability end at 0x1BFF.
2. ~~**Config blobs at `0x0900`, `0x0E00`, `0x1100`, `0x1400`.** Structured data,
   no correlation to any UI control attempted.~~ — RESOLVED: stale flash in the
   unallocated macro arena (PROTOCOL §55.1).
3. ~~**`0x1700`–`0x174B`**~~ — **FULLY RESOLVED.** Knob claim falsified (T1, §56):
   letters planted there did nothing on rotation while matrix slots 108/109 typed.
   Then a factory reset left the whole region reading `0xFFFF` — **erased,
   unallocated**; the volume codes were residue, not structure (§59). Named from
   content in Part 5 and wrong for five sessions.
4. ~~**Per-key RGB persistence.** `0xD2` is a live stream; whether custom colours
   are stored, and where, is untested.~~ — RESOLVED: `0xD2` is a read; per-key
   colour is set by hidden `0xD8` under effect >= 21 and lives in RAM only
   (T1, PROTOCOL §76-§78).
5. **Import Macros.** Never exercised.
6. ~~**Firmware update path / Upgrader device (PID `0x072D`).** Never contacted.~~
   — RESOLVED: protocol captured, reimplemented, and a modified image flashed
   (PROTOCOL §67-§69).
7. ~~**Quantum blocks `0x5600`, `0x7000`.**~~ **RESOLVED T1** — bound and pressed:
   `0x5600`, `0x56F1` (swap-hands toggle) ~~and `0x7000`~~ all do **nothing**. ~~Both
   blocks are inert;~~ a configurator must not offer them. Scope limit: `0x7000`
   was tested only for the control/caps-lock swap semantic. PROTOCOL §57.
   **CORRECTED 2026-09-29 [T2]:** `0x7000` is NOT inert — it persistently sets
   QMK's Ctrl<->Caps swap (eeprom word `0x004`); the effect only shows on the next
   Ctrl/Caps press, and it almost certainly caused §58. `0x7001` clears it (§84).
8. ~~Windows-mode banks 4-7 writable~~ — RESOLVED: 0x0372 write/readback/restore
   verified. **T2**
9. **Opcodes not characterised:** `0xFB` sub-`0x01`, `0xE1`, `0xF3`, `0xD5`,
   `0xC1`, `0xA0`, `0xFA`, `0xB4`. **DO NOT SWEEP** — one opcode in 0x40-0xFF
   enters the bootloader (PROTOCOL sec 47).
10. ~~The `02` prefix~~ — RESOLVED: it is a LENGTH field (PROTOCOL sec 42).
11. ~~**Knob/slider configuration UI** — the model defines `SquareKnob` and
    `LeftRightSlider`; neither was opened.~~ — RESOLVED: knob = matrix slots
    108/109 + 13 (T1, PROTOCOL §56); no slider on this model (§63).
12. ~~**The app's gear/settings menu, keyboard icon, chat icon.** Never opened.~~
    — gear menu mapped (PROTOCOL §61).

---

## D. Structural defect in the document

`PROTOCOL.md` grew by appending corrections as new parts. §5 and §6 remained
**actively wrong and tagged CONFIRMED** for three sessions while the corrections
sat 500 lines below. Fixed now by rewriting those sections in place with pointers
forward.

**Rule going forward:** a correction edits the original claim. Appending a newer,
truer section is not enough — the stale one has to be neutralised at its source.

---

## E. Session 7-8 resolutions

| §C item | outcome |
|---------|---------|
| 1. above `0x2000` | RESOLVED — replies to 0xFF00, data/writability end at 0x1BFF |
| 2. config blobs `0x0900`/`0x0E00`/`0x1100`/`0x1400` | **RESOLVED** — unallocated macro arena holding stale flash (PROTOCOL §55.1). Four competing hypotheses falsified first. |
| 3. `0x1700` = knob | **RESOLVED — falsified.** Knob = matrix slots 108/109 (T1, §56). `0x06E0` turned out to be an *alias window* onto those same slots, not a table. `0x1700` itself is ~~unexplained~~ erased/unallocated (§59). |
| 4. per-key RGB persistence | RESOLVED direction — `0xD2` is `GetKeyLightColor`, a **read**, ~~with no Set counterpart~~; the app polls it to animate its preview. **CORRECTED:** the Set is hidden `0xD8` (§76-§78) |
| 7. quantum blocks `0x5600`/`0x7000` | store but unverified — needs T1. (Since: swap-hands inert T1; `0x7000` = live Ctrl<->Caps magic, T2 — see C7) |
| 8. Windows banks writable | RESOLVED — verified |
| 9. uncharacterised opcodes | **RESOLVED** — full named enum recovered (`opcodes.json`, 39 commands) |
| 10. the `02` prefix | RESOLVED — a length field |

New in this run: `0xEF SetIapMode` identified as the bootloader-entry opcode;
`0xEE SetSecretKey` confirms the session model by name; Reset commands exist for
every advanced function; `GetLightCount`=119 independently confirms the LED count.

Corrections made **in place** (per rule 5): §5, §6, §53.
