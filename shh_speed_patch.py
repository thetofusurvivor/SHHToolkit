#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - game speed multiplier (cutscene fast-forward)
============================================================================

Why this exists
---------------
The in-engine dialogue cutscenes cannot be skipped. That is not a flag we can
flip - verified live: during a confirmed cutscene the ICutscene global
(0x11596118) stays NULL and the main-thread stack shows no cutscene player at
all, only the ordinary TickLoop. Those scenes are scripted sequences running
inside the normal game tick, so there is no playback object for
COMMAND_SKIP_CUTSCENE to abort.

The engine's own "cutscene fast-forward mode" was never a cut-to-end either; it
was time acceleration. This patch exposes exactly that, generally.

What it does
------------
`0x116C7A14` is the global frame delta time - verified live, it reads 0.00833 s
at 120 FPS. Every system multiplies by it to advance. It is written once per
frame by the timer update `FUN_10A4E940`:

    00a4e99c  f3 0f 11 05 14 7a 6c 11   movss [0x116C7A14], xmm0

This patch redirects that store through a code cave which scales it first, then
clamps it:

    mulss xmm0, [g_speedFactor]     ; a float we control, DEFAULT 1.0
    minss xmm0, [g_maxDelta]        ; a ceiling, DEFAULT 0.05 s
    movss [0x116C7A14], xmm0
    jmp   back

`xmm0` is not reused after the original store, and the tick dispatch called
immediately afterwards receives `&dt`, so the scaled value propagates to
everything - including scripted cutscene sequences.

    factor 1.0 -> identical behaviour (a multiply by 1.0; the patch is inert)
    factor 4.0 -> a 60-second cutscene takes 15 seconds

The ceiling matters because the multiply applies to *every* frame, including a
long one: a 200 ms loading hitch at 4x asks for an 800 ms step. The engine's own
tick already clamps dt at 0.08 s, so it would survive that anyway - ours is set
*below* that on purpose, so the worst step while sped up is smaller than the
worst step the stock game takes. Keep the factor at 4 or below: above that the
per-frame step grows past what this engine's collision handles, which is a
separate problem the ceiling does not solve.

Set the factor at runtime with `shh_speed.py` (hold a key to fast-forward), or
from the GUI's GAME SPEED row, which writes this same byte layout.

Layout
------
    patch site    0x00A4E99C   8 bytes  ->  jmp cave + 3 nops
    g_speedFactor 0x00D71300   4 bytes  float, default 1.0
    g_maxDelta    0x00D71304   4 bytes  float, default 0.05
    cave code     0x00D71310  29 bytes

Both cave addresses were verified to be 0xCC padding inside a 647 KB unused run
in .text, so nothing else is disturbed. The factor lives in .text, which is
read-only at runtime - `shh_speed.py` writes it via VirtualProtectEx.

Verified on build v6.30 (changelist #640742),
md5 2af20d3f0b1d3902135a044966859d39.

Usage
-----
    python shh_speed_patch.py --status
    python shh_speed_patch.py --apply     # inert until you set a factor
    python shh_speed_patch.py --restore

Close the game first - Windows locks the module while it is loaded.
"""

import argparse
import os
import shutil
import struct
import sys

BASE = 0x10000000
STORE_OFF = 0x00A4E99C          # file offset == RVA
FACTOR_OFF = 0x00D71300
MAXDT_OFF = 0x00D71304
CODE_OFF = 0x00D71310
DT_ADDR = 0x116C7A14

# The engine's own tick already clamps dt at 0.08 s, so a ceiling above that would never
# fire. 50 ms is deliberately tighter: a multiplied loading hitch then advances the world by
# less than the stock game's own worst frame does.
MAX_DELTA = 0.05

STOCK_STORE = bytes.fromhex("f30f1105147a6c11")          # movss [dt], xmm0
CAVE_BLANK = b"\xcc" * 29
FACTOR_BLANK = b"\xcc" * 8


def _build():
    jmp_to_cave = (BASE + CODE_OFF) - (BASE + STORE_OFF + 5)
    site = b"\xe9" + struct.pack("<i", jmp_to_cave) + b"\x90\x90\x90"
    cave = (bytes.fromhex("f30f5905") + struct.pack("<I", BASE + FACTOR_OFF) +   # mulss xmm0,[factor]
            bytes.fromhex("f30f5d05") + struct.pack("<I", BASE + MAXDT_OFF) +    # minss xmm0,[ceiling]
            bytes.fromhex("f30f1105") + struct.pack("<I", DT_ADDR))              # movss [dt],xmm0
    back = BASE + STORE_OFF + 8
    cave += b"\xe9" + struct.pack("<i", back - (BASE + CODE_OFF + len(cave) + 5))
    assert len(site) == 8 and len(cave) == 29
    return site, cave


PATCH_SITE, CAVE_CODE = _build()
FACTOR_ONE = struct.pack("<f", 1.0) + struct.pack("<f", MAX_DELTA)


def find_target(explicit=None):
    if explicit:
        return explicit
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from shh_fps_patch import find_game
        return find_game()
    except Exception:
        return None


def read(path, off, n):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


def write(path, off, data):
    try:
        with open(path, "r+b") as f:
            f.seek(off)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except PermissionError:
        sys.exit("ERROR: cannot write - close Silent Hill: Homecoming first "
                 "(Windows locks the module while it is loaded).")


def state(path):
    site = read(path, STORE_OFF, 8)
    cave = read(path, CODE_OFF, 29)
    if site == STOCK_STORE and cave == CAVE_BLANK:
        return "STOCK"
    if site == PATCH_SITE and cave == CAVE_CODE:
        return "PATCHED"
    return "UNKNOWN"


def main():
    ap = argparse.ArgumentParser(
        description="Add a game-speed multiplier so cutscenes can be fast-forwarded.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true")
    g.add_argument("--apply", action="store_true")
    g.add_argument("--restore", action="store_true")
    ap.add_argument("--file", help="path to g_SilentHill.sgl (default: auto-detect)")
    args = ap.parse_args()

    path = find_target(args.file)
    if not path or not os.path.isfile(path):
        sys.exit("ERROR: could not find g_SilentHill.sgl - pass --file <path>")

    st = state(path)
    print("file    : %s" % path)
    print("state   : %s" % st)
    if st == "PATCHED":
        f, ceiling = struct.unpack("<2f", read(path, FACTOR_OFF, 8))
        print("factor  : %.3f  (1.0 = no change)" % f)
        print("delta cap: %.3f s  (the scaled frame delta never exceeds this)" % ceiling)

    if args.status:
        return

    if st == "UNKNOWN":
        sys.exit("ERROR: the patch site or cave does not look like stock or our patch.\n"
                 "Nothing was written. Restore the module from backup if unsure.")

    want = "STOCK" if args.restore else "PATCHED"
    if st == want:
        print("\nAlready in that state - nothing to do.")
        return

    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print("  backup created : %s" % backup)
    else:
        print("  backup exists  : %s" % backup)

    if args.restore:
        write(path, STORE_OFF, STOCK_STORE)
        write(path, CODE_OFF, CAVE_BLANK)
        write(path, FACTOR_OFF, FACTOR_BLANK)
    else:
        # cave first, so the jump never points at blank padding
        write(path, FACTOR_OFF, FACTOR_ONE)
        write(path, CODE_OFF, CAVE_CODE)
        write(path, STORE_OFF, PATCH_SITE)

    now = state(path)
    print("new     : %s" % now)
    if now != want:
        sys.exit("ERROR: verification failed.")
    if want == "PATCHED":
        print("\nOK - patched, and INERT (factor 1.0). Restart the game, then use:")
        print("    python shh_speed.py --hold")
    else:
        print("\nOK - restored to stock.")


if __name__ == "__main__":
    main()
