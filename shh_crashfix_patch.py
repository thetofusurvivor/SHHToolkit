#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - flashlight re-attach crash guard
===============================================================

Guards the crash at g_SilentHill.sgl+0x554AB3 that hits during level loads.

The bug
-------
When a level loads, the player character re-attaches the flashlight to bone 35
of another game object. `FUN_10554A20` looks that object up by handle and reads
its skeleton pointer at +0x340:

    10554aa5  call Lookup(handle)
    10554aaa  mov ecx,[eax+0x340]      ; skeleton pointer
    10554ab0  mov eax,[edi+0x54]       ; bone index (35)
    10554ab3  mov edx,[ecx]            ; CRASH - ecx is text, not a pointer
    10554abd  call [edx+0x20]          ; skeleton->GetBoneMatrix(35, out)

The function null-checks that pointer, but here it is not null: intermittently
the handle resolves to an object that is not a finished character, and +0x340
holds the bytes "__ty" (from the engine's "__types__" reflection text). Four
crashes so far, byte-identical every time (same registers, same stack), all while
a level was loading.

The guard
---------
The 11 bytes at 0x10554AAA become a jump to a small stub in unused padding at
0x10D71500:

    mov ecx,[eax+0x340]            ; the original load
    IsBadReadPtr(ecx, 4)?  -> bail ; the game already imports this
    [ecx] not a vtable in .rdata? -> bail
    mov edx,[ecx] / mov eax,[edi+0x54]
    jmp 0x10554AB5                 ; back into the original code, unchanged
  bail:
    add esp,4                      ; drop the lookup argument, as the original does
    jmp 0x10554AC8                 ; the function's own exit

For a valid pointer the game runs exactly the instructions it always did. For the
garbage pointer it takes the exit the function already uses when the pointer is
NULL, returning the identity matrix it wrote at entry. Worst visible effect: the
flashlight sits oddly for a moment during that load, instead of a crash.

Scope: this guards only this one crash. The Havok physics crashes are separate.

Verified on build v6.30 (changelist #640742), stock g_SilentHill.sgl
md5 2af20d3f0b1d3902135a044966859d39. Coexists with the FPS, borderless and
unlock patches; the stub sits clear of the speed-patch cave (0x10D71300).

Usage
-----
    python shh_crashfix_patch.py --status
    python shh_crashfix_patch.py --apply
    python shh_crashfix_patch.py --restore

Close the game first - Windows locks the module while it is loaded.
"""

import argparse
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shh_fps_patch import find_game  # noqa: E402  (same auto-detection)

BASE = 0x10000000
SITE = 0x10554AAA            # file offset == VA - BASE
BACK = 0x10554AB5            # add esp,4 / push esi / ... (unchanged original code)
BAIL = 0x10554AC8            # pop edi / mov eax,esi / pop esi / mov esp,ebp / pop ebp / ret
CAVE = 0x10D71500            # unused 0xCC padding in .text
IAT_ISBADREADPTR = 0x117EEA7C
RDATA_LO, RDATA_HI = 0x10F7A000, 0x111BF7F8

SITE_STOCK = bytes.fromhex("8b8840030000" "8b4754" "8b11")   # mov ecx,[eax+340] / mov eax,[edi+54] / mov edx,[ecx]


def _rel(frm, to, size=5):
    return struct.pack("<i", to - (frm + size))


def _build():
    code = bytearray()
    code += bytes.fromhex("8b8840030000")                          # mov ecx,[eax+0x340]
    code += b"\x51\x6a\x04\x51"                                    # push ecx / push 4 / push ecx
    code += b"\xff\x15" + struct.pack("<I", IAT_ISBADREADPTR)      # call [IsBadReadPtr]
    code += b"\x59\x85\xc0"                                        # pop ecx / test eax,eax
    jumps = [len(code)]
    code += b"\x0f\x85\0\0\0\0"                                    # jnz bail
    code += b"\x8b\x11"                                            # mov edx,[ecx]
    code += b"\x81\xfa" + struct.pack("<I", RDATA_LO)              # cmp edx,.rdata lo
    jumps.append(len(code))
    code += b"\x0f\x82\0\0\0\0"                                    # jb bail
    code += b"\x81\xfa" + struct.pack("<I", RDATA_HI)              # cmp edx,.rdata hi
    jumps.append(len(code))
    code += b"\x0f\x83\0\0\0\0"                                    # jae bail
    code += b"\x8b\x47\x54"                                        # mov eax,[edi+0x54]
    code += b"\xe9" + _rel(CAVE + len(code), BACK)                 # jmp back
    bail = len(code)
    code += b"\x83\xc4\x04"                                        # add esp,4
    code += b"\xe9" + _rel(CAVE + len(code), BAIL)                 # jmp exit
    for at in jumps:
        struct.pack_into("<i", code, at + 2, bail - (at + 6))
    site = b"\xe9" + _rel(SITE, CAVE) + b"\x90" * 6
    assert len(site) == len(SITE_STOCK)
    return site, bytes(code)


SITE_PATCH, CAVE_CODE = _build()
CAVE_STOCK = b"\xcc" * len(CAVE_CODE)


def read_at(path, va, n):
    with open(path, "rb") as f:
        f.seek(va - BASE)
        return f.read(n)


def state(path):
    site = read_at(path, SITE, len(SITE_STOCK))
    cave = read_at(path, CAVE, len(CAVE_CODE))
    if site == SITE_STOCK and cave == CAVE_STOCK:
        return "stock"
    if site == SITE_PATCH and cave == CAVE_CODE:
        return "patched"
    return "unknown"


def write(path, restore):
    try:
        with open(path, "r+b") as f:
            if restore:
                f.seek(SITE - BASE); f.write(SITE_STOCK)
                f.seek(CAVE - BASE); f.write(CAVE_STOCK)
            else:
                f.seek(CAVE - BASE); f.write(CAVE_CODE)     # stub first, then the jump to it
                f.seek(SITE - BASE); f.write(SITE_PATCH)
            f.flush()
            os.fsync(f.fileno())
    except PermissionError:
        sys.exit("ERROR: cannot write to the module - close Silent Hill: Homecoming first\n"
                 "(Windows locks the file while it is loaded).")


def main():
    ap = argparse.ArgumentParser(
        description="Guard the flashlight re-attach crash (+0x554AB3) in Silent Hill: Homecoming (PC).",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true")
    g.add_argument("--restore", action="store_true")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--file", metavar="PATH", help="path to g_SilentHill.sgl (default: auto-detect)")
    args = ap.parse_args()

    path = args.file or find_game()
    if not path or not os.path.isfile(path):
        sys.exit("ERROR: could not find g_SilentHill.sgl - pass --file PATH")

    st = state(path)
    print(f"file    : {path}")
    print(f"site    : 0x{SITE:08X}  {read_at(path, SITE, len(SITE_STOCK)).hex(' ')}")
    print(f"stub    : 0x{CAVE:08X}  {len(CAVE_CODE)} bytes")
    print(f"state   : {st}")
    if args.status:
        return
    if st == "unknown":
        sys.exit("\nERROR: the patch site or stub area does not look like stock or this patch.\n"
                 "Nothing was written.")

    want = "stock" if args.restore else "patched"
    if st == want:
        print("\nAlready in that state - nothing to do.")
        return
    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f"  backup created : {backup}")
    write(path, args.restore)
    now = state(path)
    print(f"new     : {now}")
    if now != want:
        sys.exit("ERROR: verification failed.")
    print("\nOK - " + ("guard removed." if args.restore else
                       "flashlight re-attach crash guarded.\n"
                       "Note: Steam's 'Verify integrity of game files' will revert this."))


if __name__ == "__main__":
    main()
