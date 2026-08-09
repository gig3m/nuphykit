# Firmware

**The firmware binary is not included in this repository.** It is NuPhy's
copyrighted work and is not ours to redistribute. It is, however, published by
NuPhy over a plain public API, so you can fetch your own copy in two commands.

## Obtain the firmware

```bash
# 1. Get the current firmware metadata for the Air100 V3
curl -s "https://drive.nuphy.io/prod-api/api/nuphyIo/getLastFirmwareVersionsByType?businessId=1996757112579686401&type=1"
#    -> JSON with "firmwareFileUrl" (a .zip on cdn.nuphy.io) and its "sha256"

# 2. Download and unzip. The published sha256 is of the INNER .bin, not the zip.
curl -s -o fw.zip "<firmwareFileUrl from step 1>"
unzip fw.zip           # -> Air100v3_US_v1.0.6.6_20260723.bin
shasum -a 256 Air100v3_US_v1.0.6.6_20260723.bin   # compare to the "sha256" field
```

Version 1.0.6.6 is `Air100v3_US_v1.0.6.6_20260723.bin`, 281,200 bytes.

## What it is

- **Unencrypted** RISC-V code for a **WCH CH58x** BLE SoC (CH582 vs CH583
  unconfirmed — see `PROTOCOL.md` §80), built with `riscv-none-elf-gcc 12.2.0`.
- Loads at flash base `0x13000` (the NuPhy IAP bootloader sits below it).

## Analysis tool

`fwtool.py` does capstone-based RV32IMAC analysis — string xrefs, immediate
search, disassembly — with no toolchain install:

```bash
uv run --with capstone python firmware/fwtool.py strings
uv run --with capstone python firmware/fwtool.py dis 0x14168 40
```

It expects the `.bin` (from the steps above) alongside it.

Everything derived from the firmware — the matrix pin map, the LED channel map,
the command dispatch table, the flash protocol — is documented in `PROTOCOL.md`
and captured as data tables (`matrix_pins.json`, `led_map.json`, `opcodes.json`).
Those are facts extracted for interoperability; the binary itself stays with
NuPhy.
