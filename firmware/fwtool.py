"""Static analysis for the Air100 V3 firmware (RISC-V RV32IMAC, WCH CH58x).

    uv run --with capstone python firmware/fwtool.py strings
    uv run --with capstone python firmware/fwtool.py xref <file_offset_hex>
    uv run --with capstone python firmware/fwtool.py imm <byte_value_hex>
    uv run --with capstone python firmware/fwtool.py dis <off_hex> [count]
    uv run --with capstone python firmware/fwtool.py base

Key trick: the image base cancels for flash-internal references. An
`auipc rX, hi` + `addi rX, rX, lo` pair at file offset P refers to file offset
P + (hi<<12) + lo, whatever the load address is. So string cross-references work
without knowing the base.
"""
import sys, os, collections
import capstone as C

HERE = os.path.dirname(os.path.abspath(__file__))
BIN = os.path.join(HERE, "Air100v3_US_v1.0.6.6_20260723.bin")
DATA = open(BIN, "rb").read()

md = C.Cs(C.CS_ARCH_RISCV, C.CS_MODE_RISCV32 | C.CS_MODE_RISCVC)
md.detail = True


def disasm_all():
    """Linear sweep. Returns list of (offset, mnemonic, op_str)."""
    out = []
    for i in md.disasm(DATA, 0):
        out.append((i.address, i.mnemonic, i.op_str))
    return out


def find_strings(minlen=5):
    runs, cur, start = [], [], 0
    for i, b in enumerate(DATA):
        if 32 <= b < 127:
            if not cur:
                start = i
            cur.append(chr(b))
        else:
            if len(cur) >= minlen:
                runs.append((start, "".join(cur)))
            cur = []
    if len(cur) >= minlen:
        runs.append((start, "".join(cur)))
    return runs


def parse_imm(s):
    s = s.strip()
    try:
        return int(s, 0)
    except ValueError:
        return None


def build_refs(insns):
    """auipc rX,hi followed (soon) by addi rX,rX,lo  ->  referenced file offset."""
    refs = collections.defaultdict(list)      # target_file_off -> [pc]
    pend = {}                                  # reg -> (pc, hi)
    for off, mn, ops in insns:
        parts = [p.strip() for p in ops.split(",")]
        if mn == "auipc" and len(parts) == 2:
            hi = parse_imm(parts[1])
            if hi is not None:
                if hi & 0x80000:
                    hi -= 0x100000
                pend[parts[0]] = (off, hi << 12)
        elif mn in ("addi", "c.addi") and len(parts) == 3:
            rd, rs, lo = parts[0], parts[1], parse_imm(parts[2])
            if rd == rs and rd in pend and lo is not None:
                pc, hi = pend.pop(rd)
                refs[pc + hi + lo].append(pc)
        elif mn in ("lw", "sw", "lbu", "lb", "lhu", "lh", "sb", "sh") and len(parts) == 2:
            # form: rd, imm(rs)
            m = parts[1]
            if "(" in m:
                lo = parse_imm(m.split("(")[0])
                rs = m.split("(")[1].rstrip(")")
                if rs in pend and lo is not None:
                    pc, hi = pend.pop(rs)
                    refs[pc + hi + lo].append(pc)
    return refs


def cmd_base(insns):
    """Derive the load address from the sp setup in the startup code."""
    for off, mn, ops in insns[:40]:
        parts = [p.strip() for p in ops.split(",")]
        if mn == "auipc" and parts and parts[0] == "sp":
            hi = parse_imm(parts[1])
            if hi & 0x80000:
                hi -= 0x100000
            print(f"  auipc sp at 0x{off:05X}, hi=0x{hi:05X}")
            for off2, mn2, ops2 in insns:
                if off2 > off and mn2 == "addi" and ops2.startswith("sp, sp"):
                    lo = parse_imm(ops2.split(",")[2])
                    v = off + (hi << 12) + lo
                    print(f"  addi sp at 0x{off2:05X}, lo={lo}")
                    print(f"  sp = BASE + 0x{v & 0xFFFFFFFF:08X}")
                    for top, label in ((0x20008000, "32KB RAM @0x20000000"),
                                       (0x20006000, "24KB"), (0x20004000, "16KB")):
                        print(f"    if stack top = 0x{top:08X} ({label}): "
                              f"BASE = 0x{(top - v) & 0xFFFFFFFF:08X}")
                    return
    print("  sp setup not found")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cmd = sys.argv[1]
    insns = disasm_all()
    print(f"# {len(insns)} instructions decoded from {len(DATA)} bytes\n")

    if cmd == "base":
        cmd_base(insns)
        return

    strs = dict(find_strings())
    refs = build_refs(insns)

    if cmd == "strings":
        hit = sum(1 for o in strs if o in refs)
        print(f"strings: {len(strs)}   with code xrefs: {hit}")
        for o, t in sorted(strs.items()):
            if o in refs:
                who = ", ".join(f"0x{p:05X}" for p in refs[o][:4])
                print(f"  0x{o:05X}  {t[:60]:60}  <- {who}")
    elif cmd == "xref":
        t = int(sys.argv[2], 16)
        best = [o for o in strs if o <= t < o + len(strs[o]) + 1]
        if best:
            print(f"target 0x{t:05X} is inside string 0x{best[0]:05X} {strs[best[0]]!r}")
        print(f"xrefs to 0x{t:05X}: " + (", ".join(f"0x{p:05X}" for p in refs.get(t, [])) or "none"))
    elif cmd == "imm":
        val = int(sys.argv[2], 16)
        hits = [(o, mn, ops) for o, mn, ops in insns
                if mn in ("li", "c.li", "addi", "c.addi", "sltiu", "xori", "andi", "ori")
                and (parse_imm(ops.split(",")[-1]) == val)]
        print(f"instructions with immediate 0x{val:X}: {len(hits)}")
        for o, mn, ops in hits[:60]:
            print(f"  0x{o:05X}  {mn:8} {ops}")
    elif cmd == "dis":
        off = int(sys.argv[2], 16)
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 60
        for o, mn, ops in insns:
            if o >= off:
                print(f"  {o:05X}  {mn:10} {ops}")
                n -= 1
                if n <= 0:
                    break


if __name__ == "__main__":
    main()
