# UI option sweep — map every NuPhyIO setting to its storage

Kyle's proposal, 2026-08-08: flip **every** option in the UI one at a time and
diff the whole device. This is the only way to reach settings that live outside
the `0x0000`-`0x1BFF` config region — which is exactly where the Ctrl/Caps swap
(PROTOCOL §58) turned out to hide, and why byte-guessing failed to find it.

## Procedure

```
uv run --with hidapi python tools/fullstate.py before
#   open NuPhyIO, change EXACTLY ONE option, quit NuPhyIO
uv run --with hidapi python tools/fullstate.py sleep_off
python3 tools/statediff.py before sleep_off
```

`fullstate.py` captures the config region **plus all 17 read-only `Get`
commands**. `statediff.py` reports changed byte runs (annotated with region,
bank, slot and legend) and any `Get` whose reply changed.

Rules:

1. **One option per capture.** Two changes in one round cannot be attributed.
2. **Name the capture after the change** (`sleep_off`, `debounce_3`) so the
   snapshot set is self-documenting.
3. **Record the UI value too**, not just the byte — `1/2/3` in the UI matters as
   much as `01/02/03` on the wire.
4. Re-diff `before -> after -> before` when a setting is reversible; a setting
   that does not return to its original bytes is doing something extra.
5. `0xD2 GetKeyLightColor` is **volatile** (live LED frame) and suppressed by
   default. Use `--all` to see it.

## Why the padding fix matters

Reply padding is **raw `0x00`**, which XOR-decodes to the **session key** — and
the key is fresh per session. Decoding before trimming made all 17 `Get` replies
appear to change every single time. `fullstate.py` trims on the raw bytes first.
Any future tool reading these replies must do the same.

## Checklist

Tick as each is mapped. Unknown storage is the interesting outcome.

| # | option | UI location | values | storage found | done |
|---|--------|-------------|--------|---------------|------|
| 1 | Auto Sleep | gear | 0/1 | **`0xF3`/`0xF5` index 0** | ☑ |
| 2 | Level 1 / Level 2 Sleep | gear | minutes | **index 1 / index 2** (factory 6 / 24) | ☑ |
| 2b | sleep index 3 | gear | — | present, factory `04`, ~~**purpose unknown**~~ early-sleep delay, seconds (PROTOCOL §79) | ☑ |
| 3 | Accessory Switch | gear | Knob/Button | **AppDefine `0xFB`/`0xFC` offset `0xA8`** | ☑ |
| 4 | Keyboard Layout | gear | 12 options | **app-only — sends NO device traffic** | ☑ |
| 5 | Disable Win key | Mode Settings | 0/1 | **`0xE1`/`0xE2` index 1** | ☑ |
| 6 | Alt+F4 | Mode Settings | 0/1 | **index 2** | ☑ |
| 7 | Alt+Tab | Mode Settings | 0/1 | **index 3** | ☑ |
| 8 | Anti-wobbliness | Mode Settings | 1=Low 2=Int 3=High | **index 0** = debounce lock x 10 ms, per Mac/Win mode (§84) | ☑ |
| 9 | Light effect | Lighting | 20 effects | **`0xD5`/`0xD6` byte 0**, 1-based | ☑ |
| 10 | Back light brightness | Lighting | 0-100 | **byte 1** (`00` = "off") | ☑ |
| 10b | Side light brightness | Lighting | 0-60 | **byte 10** (`00` = "off") | ☑ |
| 11 | Speed | Lighting | gears | **byte 2** (scale not pinned down) | ◐ |
| 12 | Colour / Custom Color | Lighting | | not exercised | ☐ |
| 13 | Per-key colour (does it exist?) | Lighting | | `0xD2` is read-only (§54); **CORRECTED 2026-09-29 [T1]:** yes — hidden `0xD8` under effect >= 21, no UI (§76-§78) | ☑ |
| 12b | Custom Color on/off + RGB | Lighting | | **byte 4** mode, **bytes 6-8** RGB (pre-scaled by brightness) | ☑ |
| 14 | Knob action | Key Bindings | | matrix slots 108/109 + slot 13; app model agrees (§63) | ☑ |
| 15 | Slider / TouchBar (`0xE6`) | — | — | **not on this model** — `especialKeys` is SquareKnob only | ☑ |
| 16 | Polling rate | — | — | **no such control on this model** | ☑ |
| 17 | Gear menu: Language, Theme | gear | — | app-only, no device traffic | ☑ |
| 18 | Gear menu: Reset Keyboard | gear | — | **destructive, not exercised** | ☐ |

## Better technique than snapshot-diffing: instrument WebHID

Snapshot diffing only sees settings that land in the config region. Wrapping
`HIDDevice.prototype.sendReport` from the page shows the **exact frame** the app
sends for each UI action, which mapped all of Mode Settings in one pass:

```js
const P = HIDDevice.prototype, orig = P.sendReport;
window.__hidLog = [];
P.sendReport = function (id, data) {
  window.__hidLog.push(Array.from(new Uint8Array(
    ArrayBuffer.isView(data) ? data.buffer : data)));
  return orig.apply(this, arguments);
};
```

Then decode: `[0]=0x55`, `[1]=opcode`, `[3]=checksum`, `[4..]=payload XOR key`.
Recover the key by finding the value that makes the payload parse as
`<len> <addr16> <pad> <data>` — it was `0x08` in the observed session.

**Session conflict (PROTOCOL §60):** every CLI command handshakes and orphans the
app's session; the app handshakes only at connect. So after any CLI call, the app
must be **reloaded** (`location.reload()`, NOT a hash navigation) before its
writes will land again.

## Sweep status: COMPLETE

All rows resolved. See PROTOCOL §63 for the four-space storage model and the
short list of things still unresolved.

## Priority target

~~**The Ctrl/Caps swap (§58).** Not exposed by NuPhyIO as far as the bundle shows,
so it may not be reachable this way — but if any option here toggles it, this
sweep finds it, and that is the one open item where the device disagrees with
both its own storage and its own app.~~ **RESOLVED 2026-09-29 [T2]:** no UI
option toggles it — the `0x7000` magic keycode does (`0x7001` clears), stored at
eeprom word `0x004`, which no command reads (PROTOCOL §57, §84).
