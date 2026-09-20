#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - unlock all costumes + New Game+ extras
=====================================================================

Makes the game treat every end-game unlock as earned, on every launch, without
editing your save:

  * all six costumes selectable at New Game (Young Alex, Sheriff, Trucker,
    Orderly, Order Soldier, Pyramid Head)
  * the "completed the game" flag set on every new game
  * the UFO flag set on every new game - which is what makes the Laser Gun
    appear by the ornate desk in Alex's house

Your save file is never touched. Your real unlock record stays exactly as it was
underneath; `--restore` makes the game read it normally again.

How the game stores this (all verified in the running game)
-----------------------------------------------------------
Each ending unlocks ONE costume, via an `ISilentHillCostumeUnlockTrigger` in its
ending level (Trucker / Order Soldier / Pyramid Head / Orderly / Sheriff). The
record is 8 bytes in the profile object:

    profile+0x230  Young Alex      +0x234  Order Soldier
    profile+0x231  Sheriff         +0x235  Pyramid Head
    profile+0x232  Trucker         +0x236  completed the game
    profile+0x233  Orderly         +0x237  got the UFO ending

Three edits, 7 bytes in total:

  1. 0x10A0BE10  the costume accessor, `return profile[0x230 + idx]`.
     Only called by the script lookup that answers IsPyramidUnlocked,
     IsOrderlyUnlocked and so on (8 call sites, all in 0x10A0AF40).
         8b 44 24 04 8a   mov eax,[esp+4] / mov al,[...]
      -> b0 01 c2 04 00   mov al,1 / ret 4               (always "unlocked")

  2. 0x1094FDF3  at new game, "completed" is copied into the Completed_Game
     variable only if the runtime flag or profile+0x236 is set:
         75 0c  jne  ->  eb 0c  jmp                     (always copy)

  3. 0x1094FE69  same for the UFO flag (profile+0x237 -> Got_UFO). Alex's house
     checks Got_UFO to show the Laser Gun.
         75 0c  jne  ->  eb 0c  jmp                     (always copy)

Both jumps land on the path the game already takes when the flag IS set, so
nothing new is executed - the game just stops asking.

Verified on build v6.30 (changelist #640742), stock g_SilentHill.sgl
md5 2af20d3f0b1d3902135a044966859d39.

Usage
-----
    python shh_unlock_patch.py --status
    python shh_unlock_patch.py --apply
    python shh_unlock_patch.py --restore

Close the game first - Windows locks the module while it is loaded.
"""

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shh_fps_patch import find_game  # noqa: E402  (same auto-detection)

# (file offset, bytes that must precede the patch for context, stock, patched, description)
PATCHES = (
    (0x00A0BE10, b"", bytes.fromhex("8b4424048a"), bytes.fromhex("b001c20400"),
     "costume check -> always unlocked"),
    (0x0094FDF3, bytes.fromhex("385e128b7e08"), bytes.fromhex("75"), bytes.fromhex("eb"),
     "new game: always set Completed_Game"),
    (0x0094FE69, bytes.fromhex("385e13"), bytes.fromhex("75"), bytes.fromhex("eb"),
     "new game: always set Got_UFO (Laser Gun)"),
)


def read_at(path, off, n):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


def site_state(path, off, ctx, stock, new):
    if ctx and read_at(path, off - len(ctx), len(ctx)) != ctx:
        return "UNEXPECTED"
    cur = read_at(path, off, len(stock))
    return "stock" if cur == stock else "patched" if cur == new else "UNEXPECTED"


def state(path):
    states = {site_state(path, o, c, s, n) for o, c, s, n, _ in PATCHES}
    if "UNEXPECTED" in states:
        return "unknown"
    return states.pop() if len(states) == 1 else "mixed"


def show(path):
    print(f"file    : {path}")
    for off, ctx, stock, new, desc in PATCHES:
        st = site_state(path, off, ctx, stock, new)
        cur = read_at(path, off, len(stock)).hex(" ")
        print(f"  0x{off:08X}  {cur:<15} {st:<10} {desc}")


def write_patch(path, restore):
    try:
        with open(path, "r+b") as f:
            for off, _ctx, stock, new, _desc in PATCHES:
                f.seek(off)
                f.write(stock if restore else new)
            f.flush()
            os.fsync(f.fileno())
    except PermissionError:
        sys.exit("ERROR: cannot write to the module - close Silent Hill: Homecoming first\n"
                 "(Windows locks the file while it is loaded).")


def main():
    ap = argparse.ArgumentParser(
        description="Unlock all costumes and the New Game+ extras in Silent Hill: Homecoming (PC).",
        epilog="Examples:\n"
               "  python shh_unlock_patch.py --status\n"
               "  python shh_unlock_patch.py --apply\n"
               "  python shh_unlock_patch.py --restore\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="treat all unlocks as earned")
    g.add_argument("--restore", action="store_true", help="back to your real unlocks")
    g.add_argument("--status", action="store_true", help="print the current state and exit")
    ap.add_argument("--file", metavar="PATH",
                    help="path to g_SilentHill.sgl (default: auto-detect from Steam)")
    args = ap.parse_args()

    path = args.file or find_game()
    if not path or not os.path.isfile(path):
        sys.exit("ERROR: could not find g_SilentHill.sgl - pass --file PATH")

    show(path)
    st = state(path)
    if st == "unknown":
        sys.exit("\nERROR: the bytes at these offsets are not what this build has.\n"
                 "Nothing was written. Supported: g_SilentHill.sgl md5 "
                 "2af20d3f0b1d3902135a044966859d39 (v6.30 / #640742).")
    if args.status:
        return

    want = "stock" if args.restore else "patched"
    if st == want:
        print(f"\nAlready {want} - nothing to do.")
        return

    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f"  backup created : {backup}")

    write_patch(path, restore=args.restore)
    if state(path) != want:
        sys.exit("ERROR: verification failed - the write did not stick.")
    print()
    show(path)
    if args.restore:
        print("\nOK - the game reads your real unlocks again.")
    else:
        print("\nOK - every costume is selectable at New Game, and each new game starts")
        print("with the completed + UFO flags (Laser Gun in Alex's house).")
        print("Your save file was not touched.")
        print("Note: Steam's 'Verify integrity of game files' will revert this.")


if __name__ == "__main__":
    main()
