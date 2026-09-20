"""
Static-analysis helpers for g_SilentHill.sgl - no Ghidra required.

Handy for quick questions ("where is this string?", "what reads this constant?")
without spinning up a 21 MB Ghidra session.

Key fact that makes addressing easy: this module is a PE32 DLL with
DllCharacteristics = 0 (no ASLR), preferred base 0x10000000, and for .text /
.rdata / .data the raw file offset EQUALS the RVA. So:

    VA = 0x10000000 + file_offset      (for those three sections)

That does NOT hold for .idata / .rsrc / .reloc - use --sections to check.

Usage:
    python shh_static.py --sections
    python shh_static.py --strings "fps|refresh|vsync"
    python shh_static.py --xref 0x1108E804        # who references this VA?
    python shh_static.py --float 33.323334        # find a float constant
    python shh_static.py --dis 0xA4CC90 --len 0xA8
    python shh_static.py --imports "sleep|query"

--dis needs capstone (pip install capstone); everything else is stdlib only.
"""

import argparse
import os
import re
import struct
import sys

IMAGE_BASE = 0x10000000
DEFAULT_REL = os.path.join("Bin", "g_SilentHill.sgl")


def load(path):
    if not path:
        # try the Steam install, then a local copy
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from shh_fps_patch import find_game
            path = find_game()
        except Exception:
            path = None
    if not path or not os.path.isfile(path):
        sys.exit("ERROR: pass --file <path to g_SilentHill.sgl>")
    return path, open(path, "rb").read()


def sections(d):
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    opt = pe + 24
    secoff = opt + struct.unpack_from("<H", d, pe + 20)[0]
    out = []
    for i in range(nsec):
        o = secoff + i * 40
        name = d[o:o + 8].rstrip(b"\0").decode(errors="replace")
        vsz, va, rsz, ptr = struct.unpack_from("<IIII", d, o + 8)
        out.append((name, va, vsz, ptr, rsz))
    return out


def rva2off(secs, rva):
    for _n, va, vsz, ptr, rsz in secs:
        if va <= rva < va + max(vsz, rsz):
            return ptr + (rva - va)
    return None


def text_range(secs):
    for n, va, vsz, ptr, rsz in secs:
        if n == ".text":
            return ptr, ptr + rsz
    return 0x1000, len(secs and b"") or 0xF7A000


def cmd_sections(d):
    print(f"{'name':<9}{'VA':>10}{'VSize':>10}{'RawPtr':>10}{'RawSize':>10}   off==rva?")
    for n, va, vsz, ptr, rsz in sections(d):
        print(f"{n:<9}{va:>10X}{vsz:>10X}{ptr:>10X}{rsz:>10X}   {'yes' if va == ptr else 'NO'}")


def cmd_strings(d, pattern, limit):
    rx = re.compile(rb"[\x20-\x7e]{4,}")
    cre = re.compile(pattern, re.I) if pattern else None
    n = 0
    for m in rx.finditer(d):
        s = m.group().decode("ascii", "replace")
        if cre and not cre.search(s):
            continue
        print(f"  file 0x{m.start():08X}  VA 0x{IMAGE_BASE + m.start():08X}  {s}")
        n += 1
        if n >= limit:
            print("  ...truncated")
            break
    if n == 0:
        print("  (no matches)")


def cmd_xref(d, va, limit):
    """Find 4-byte little-endian references to a VA inside .text."""
    secs = sections(d)
    lo, hi = 0x1000, rva2off(secs, 0xF79000) or 0xF7A000
    pat = struct.pack("<I", va)
    hits = []
    start = lo
    while True:
        i = d.find(pat, start, hi)
        if i == -1:
            break
        hits.append(i)
        start = i + 1
        if len(hits) >= limit:
            break
    print(f"references to VA 0x{va:08X}: {len(hits)}")
    for h in hits:
        print(f"  operand at file 0x{h:08X}  (instruction ~VA 0x{IMAGE_BASE + h - 1:08X})")
    if not hits:
        print("  (none - if this is a data address, it may be reached via a register)")


def cmd_float(d, value, limit):
    pat = struct.pack("<f", value)
    print(f"float {value} = {pat.hex()}")
    n = 0
    start = 0
    while n < limit:
        i = d.find(pat, start)
        if i == -1:
            break
        start = i + 1
        if i % 4:
            continue
        print(f"  file 0x{i:08X}  VA 0x{IMAGE_BASE + i:08X}")
        n += 1
    if n == 0:
        print("  (not found, 4-byte aligned)")


def cmd_imports(d, pattern):
    secs = sections(d)
    pe = struct.unpack_from("<I", d, 0x3C)[0]
    opt = pe + 24
    idd = struct.unpack_from("<I", d, opt + 96 + 8)[0]
    off = rva2off(secs, idd)
    cre = re.compile(pattern, re.I) if pattern else None
    i = 0
    while True:
        oft, _ts, _fc, nameRva, fthunk = struct.unpack_from("<IIIII", d, off + i * 20)
        if nameRva == 0:
            break
        no = rva2off(secs, nameRva)
        dll = d[no:d.find(b"\0", no)].decode(errors="replace")
        thunk = oft or fthunk
        j = 0
        while True:
            ent = struct.unpack_from("<I", d, rva2off(secs, thunk) + j * 4)[0]
            if ent == 0:
                break
            if not (ent & 0x80000000):
                p = rva2off(secs, ent) + 2
                nm = d[p:d.find(b"\0", p)].decode("ascii", "replace")
                if not cre or cre.search(nm):
                    print(f"  {dll:<16} {nm:<28} IAT VA 0x{IMAGE_BASE + fthunk + j * 4:08X}")
            j += 1
        i += 1


def cmd_dis(d, start_rva, length):
    try:
        from capstone import Cs, CS_ARCH_X86, CS_MODE_32
    except ImportError:
        sys.exit("ERROR: --dis needs capstone:  pip install capstone")
    md = Cs(CS_ARCH_X86, CS_MODE_32)
    for ins in md.disasm(d[start_rva:start_rva + length], IMAGE_BASE + start_rva):
        raw = " ".join(f"{b:02x}" for b in ins.bytes)
        print(f"  {ins.address - IMAGE_BASE:08x}  {raw:<24} {ins.mnemonic} {ins.op_str}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", help="path to g_SilentHill.sgl (default: auto-detect)")
    ap.add_argument("--sections", action="store_true")
    ap.add_argument("--strings", metavar="REGEX")
    ap.add_argument("--xref", metavar="VA", help="find references to a virtual address")
    ap.add_argument("--float", type=float, metavar="V", help="find a float32 constant")
    ap.add_argument("--imports", metavar="REGEX", nargs="?", const="")
    ap.add_argument("--dis", metavar="RVA", help="disassemble at a file offset / RVA")
    ap.add_argument("--len", metavar="N", default="0x80", help="bytes to disassemble")
    ap.add_argument("--limit", type=int, default=60)
    args = ap.parse_args()

    path, d = load(args.file)
    print(f"module: {path}  ({len(d)} bytes)\n")

    if args.sections:
        cmd_sections(d)
    elif args.strings is not None:
        cmd_strings(d, args.strings, args.limit)
    elif args.xref:
        cmd_xref(d, int(args.xref, 0), args.limit)
    elif args.float is not None:
        cmd_float(d, args.float, args.limit)
    elif args.imports is not None:
        cmd_imports(d, args.imports)
    elif args.dis:
        cmd_dis(d, int(args.dis, 0), int(args.len, 0))
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
