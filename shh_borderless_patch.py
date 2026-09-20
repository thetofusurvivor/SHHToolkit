#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - borderless windowed patch
========================================================

Makes the game create its own borderless window, sized and positioned to fill
the monitor, with no helper process running alongside it.

Why patch instead of restyling the live window
----------------------------------------------
The first version of this fix (`shh_window_fix.py`) stripped the frame from
outside with SetWindowLong + SetWindowPos. It worked, but every restyle sends
the game a frame/size change, and the engine reacts to those by re-running
video setup. Crashes and hangs lined up with it:

  * 4 application hangs, all in sessions where that script was running,
    none in any session without it
  * one crash 11 s after the script was started, while a save was loading
  * the same crash signature on 09-10, seconds after a restyle

Creating the window borderless in the first place avoids all of it: the style
is correct from the start, so nothing ever changes it afterwards.

What it changes
---------------
Module: Bin\\g_SilentHill.sgl (a renamed PE32 DLL loaded at 0x10000000, so
file offset == VA - 0x10000000 in these sections).

The window is created at 0x10BA444B. The style in EDI is picked a few
instructions earlier, and the *windowed* branch is the one we want:

    10ba43cc  cmp byte [eax+0x208], 0    ; fullscreen?
    10ba43d4  mov edi, 0x00CF0000        ; WS_OVERLAPPEDWINDOW  <-- patch 1
    10ba43dc  mov edi, 0x80000000        ; WS_POPUP (fullscreen path, untouched)
    ...
    10ba443f  push edi                   ; dwStyle
    10ba444b  call CreateWindowExA

Size and position come from the helper at 0x10BA3CB0, which asks
AdjustWindowRect how much room a frame needs - using a *hardcoded* style
constant rather than the one actually used:

    10ba3cc2  push 0x86CA0000            ; caption|thickframe|sysmenu  <-- patch 2
    10ba3cdb  call AdjustWindowRect
              ... then centres the result on the primary monitor:
              left = (screenW - winW) / 2,  top = (screenH - winH) / 2

Setting that to WS_POPUP too makes AdjustWindowRect a no-op, so the window is
exactly ScreenResWidth x ScreenResHeight. When that equals your monitor size
the centring maths yields (0,0) - pixel-exact, no stretching, no overscan.

Both patches are 4-byte immediates inside the windowed path only. Exclusive
fullscreen behaves exactly as before.

Requirements (Engine\\vars_pc.cfg, edited with the game CLOSED - it rewrites
that file on exit):

    FullScreen=false
    ScreenResWidth=<your monitor width>
    ScreenResHeight=<your monitor height>

`shh_window_fix.py --setup` still writes those three lines for you. Do not run
the rest of that script once this patch is applied - its job is done here.

Verified on build v6.30 (changelist #640742), stock g_SilentHill.sgl
md5 2af20d3f0b1d3902135a044966859d39.

Usage
-----
    python shh_borderless_patch.py --status
    python shh_borderless_patch.py --apply
    python shh_borderless_patch.py --restore

A .orig backup is written next to the file the first time you patch.

Note: the cursor can still wander onto a second monitor - that is a separate
issue, and this patch does not address it (see NOTES.md).
"""

import argparse
import ctypes
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shh_fps_patch import find_game  # noqa: E402  (same auto-detection)

WS_POPUP = bytes.fromhex("00000080")            # 0x80000000, little-endian

# (file offset of the immediate, opcode byte that must precede it, stock value,
#  patched value, description)
PATCHES = (
    (0x00BA43D5, 0xBF, bytes.fromhex("0000cf00"), WS_POPUP,
     "CreateWindowExA dwStyle  (WS_OVERLAPPEDWINDOW -> WS_POPUP)"),
    (0x00BA3CC3, 0x68, bytes.fromhex("0000ca86"), WS_POPUP,
     "AdjustWindowRect style   (0x86CA0000 -> WS_POPUP)"),
)

CFG_REL = os.path.join("Engine", "vars_pc.cfg")


def read_at(path, off, n=4):
    with open(path, "rb") as f:
        f.seek(off)
        return f.read(n)


def opcode_at(path, off):
    return read_at(path, off - 1, 1)[0]


def state(path):
    """'stock', 'patched', 'mixed', or 'unknown'."""
    seen = set()
    for off, op, stock, new, _ in PATCHES:
        if opcode_at(path, off) != op:
            return "unknown"
        cur = read_at(path, off)
        seen.add("stock" if cur == stock else "patched" if cur == new else "other")
    if "other" in seen:
        return "unknown"
    return seen.pop() if len(seen) == 1 else "mixed"


def show(path):
    print(f"file    : {path}")
    for off, op, stock, new, desc in PATCHES:
        cur = read_at(path, off)
        tag = "stock" if cur == stock else "patched" if cur == new else "UNEXPECTED"
        val = int.from_bytes(cur, "little")
        print(f"  0x{off:08X}  0x{val:08X}  {tag:<10} {desc}")


def config_check(path):
    """Warn (never block) if vars_pc.cfg is not set up for borderless."""
    root = os.path.dirname(os.path.dirname(path))       # ...\Bin\.. -> game root
    cfg = os.path.join(root, CFG_REL)
    if not os.path.isfile(cfg):
        print(f"note    : could not find {CFG_REL} to check the video settings")
        return
    values = {}
    with open(cfg, "r", errors="replace") as f:
        for line in f:
            if "=" in line:
                k, _, v = line.partition("=")
                values[k.strip().lower()] = v.strip()
    full = values.get("fullscreen", "?")
    w, h = values.get("screenreswidth", "?"), values.get("screenresheight", "?")
    print(f"config  : FullScreen={full}  {w}x{h}")
    if full.lower() != "false":
        print("  WARNING: FullScreen is not false - the game will still use exclusive\n"
              "           fullscreen and this patch will have no effect.\n"
              "           Close the game, then run: python shh_window_fix.py --setup")
    try:
        mw = ctypes.windll.user32.GetSystemMetrics(0)
        mh = ctypes.windll.user32.GetSystemMetrics(1)
        if (str(mw), str(mh)) != (w, h):
            print(f"  note   : primary monitor is {mw}x{mh}; the window will be {w}x{h}\n"
                  f"           centred on it (set them equal for edge-to-edge).")
    except Exception:
        pass


def write_patch(path, restore=False):
    try:
        with open(path, "r+b") as f:
            for off, op, stock, new, _ in PATCHES:
                f.seek(off)
                f.write(stock if restore else new)
            f.flush()
            os.fsync(f.fileno())
    except PermissionError:
        sys.exit(
            "ERROR: cannot write to the module.\n"
            "  * Close Silent Hill: Homecoming first - Windows locks the file\n"
            "    while it is loaded.\n"
            "  * If it is still refused, run this from an elevated prompt."
        )


def main():
    ap = argparse.ArgumentParser(
        description="Borderless windowed for Silent Hill: Homecoming, patched into the game itself.",
        epilog="Examples:\n"
               "  python shh_borderless_patch.py --status\n"
               "  python shh_borderless_patch.py --apply\n"
               "  python shh_borderless_patch.py --restore\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--apply", action="store_true", help="create the window borderless")
    g.add_argument("--restore", action="store_true", help="back to the stock bordered window")
    g.add_argument("--status", action="store_true", help="print the current values and exit")
    ap.add_argument("--file", metavar="PATH",
                    help="path to g_SilentHill.sgl (default: auto-detect from Steam)")
    args = ap.parse_args()

    path = args.file or find_game()
    if not path:
        sys.exit("ERROR: could not find g_SilentHill.sgl automatically - pass --file PATH")
    if not os.path.isfile(path):
        sys.exit(f"ERROR: not found: {path}")
    if os.path.getsize(path) < max(o for o, *_ in PATCHES) + 4:
        sys.exit("ERROR: file is too small - this is not the expected module.")

    show(path)
    st = state(path)
    if st == "unknown":
        sys.exit(
            "\nERROR: the bytes at these offsets are not what this build has.\n"
            "Nothing was written. This patch only supports g_SilentHill.sgl\n"
            "md5 2af20d3f0b1d3902135a044966859d39 (build v6.30 / #640742)."
        )

    if args.status:
        config_check(path)
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
        print("\nOK - stock bordered window restored.")
        return

    config_check(path)
    print("\nOK - the game will now create a borderless window.")
    print("Start the game normally. Do NOT run shh_window_fix.py alongside it.")
    print("Note: Steam's 'Verify integrity of game files' will revert this.")


if __name__ == "__main__":
    main()
