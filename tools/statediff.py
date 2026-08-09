"""Diff two fullstate.py captures and report exactly what one UI change touched.

    python3 tools/statediff.py before after
    python3 tools/statediff.py before after --all      # include volatile fields

Reports config-region byte runs (annotated with the region they fall in and, for
keymap bytes, the bank/slot/legend) and any Get command whose reply changed.
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def region_of(a):
    if a < 0x06E0:  return "keymap"
    if a < 0x0700:  return "knob alias window"
    if a < 0x0740:  return "macro offset table"
    if a < 0x1700:  return "macro arena"
    if a < 0x174C:  return "0x1700 unallocated"
    if a < 0x1850:  return "SOCD table"
    if a < 0x1A58:  return "TapDance table"
    if a < 0x1B00:  return "TGL table"
    return "above known tables"


def load(name):
    p = os.path.join(ROOT, "snapshots", f"state_{name}")
    return json.load(open(p + ".json")), open(p + ".bin", "rb").read()


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    a, b = sys.argv[1], sys.argv[2]
    show_volatile = "--all" in sys.argv
    sa, ra = load(a)
    sb, rb = load(b)

    matrix = {}
    try:
        for k in json.load(open(os.path.join(ROOT, "matrix.json")))["keys"]:
            matrix[k["addr"] // 2] = k["legend"]
    except Exception:
        pass

    print(f"=== {a} -> {b} ===\n")

    diff = [i for i in range(min(len(ra), len(rb))) if ra[i] != rb[i]]
    if not diff:
        print("config region 0x0000-0x1BFF: IDENTICAL")
    else:
        runs, s, p = [], diff[0], diff[0]
        for x in diff[1:]:
            if x > p + 1:
                runs.append((s, p)); s = x
            p = x
        runs.append((s, p))
        print(f"config region: {len(diff)} bytes in {len(runs)} run(s)")
        for s, e in runs:
            note = ""
            if region_of(s) == "keymap":
                bank, slot = s // 0xDC, (s % 0xDC) // 2
                note = f"  bank{bank} slot {slot} {matrix.get(slot, '?')}"
            print(f"  0x{s:04X}-0x{e:04X}  [{region_of(s)}]{note}")
            print(f"      {a}: {ra[s:e+1].hex()}")
            print(f"      {b}: {rb[s:e+1].hex()}")
    print()

    vol = set(sa.get("volatile", []))
    changed = quiet = 0
    for c in sorted(set(sa["gets"]) | set(sb["gets"]), key=lambda x: int(x, 16)):
        va = sa["gets"].get(c, {}).get("data")
        vb = sb["gets"].get(c, {}).get("data")
        nm = (sb["gets"].get(c) or sa["gets"].get(c))["name"]
        if va == vb:
            quiet += 1
            continue
        if c in vol and not show_volatile:
            print(f"  {c} {nm}: changed (VOLATILE, suppressed - use --all)")
            continue
        changed += 1
        print(f"  {c} {nm}  CHANGED")
        print(f"      {a}: {va}")
        print(f"      {b}: {vb}")
    if not changed:
        print(f"Get commands: no non-volatile changes ({quiet} identical)")


if __name__ == "__main__":
    main()
