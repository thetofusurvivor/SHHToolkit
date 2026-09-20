#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - frame rate cap patch
===================================================

The PC build hard-codes its frame limiter to a fixed frame time of
33.323334 ms (30.009 FPS). The in-game refresh-rate option (which can be set
to 144) only ever affects the D3D9 display mode, and the `fpsLimit` /
`maxFPSLimit` values in Engine\\vars_pc.cfg are read, clamped and written back
correctly but are never consulted by the render loop. That is why the game
runs at 30 FPS no matter what you pick.

Where the cap lives
-------------------
Module : Bin\\g_SilentHill.sgl   (a renamed PE32 DLL; Bin\\SilentHill.exe is
                                  only a 33 KB stub that LoadLibrary's the
                                  first g_*.sgl it finds)
Limiter: FUN_10a4cc90 @ VA 0x10A4CC90

    00a4cc99   fld dword ptr [0x1108e804]   ; <-- 33.3233 ms target frame time

    target = ToTicks(thatFloat)
    now    = GetTicks()
    if (now - lastFrame) < target:
        Sleep(TicksToMs(target - (now - lastFrame)))   # sleep the remainder
        while elapsed < remaining: Sleep(0)            # then spin
    lastFrame = GetTicks()

The constant is a standalone 4-byte float in .rdata at

    VA 0x1108E804  ==  file offset 0x0108E804

It has exactly ONE cross-reference in the whole 21 MB module - the frame
limiter above - so changing it affects nothing else. Patching it is a 4-byte
write of the desired frame time in milliseconds (1000 / target_fps) as a
little-endian float32.

Verified on build v6.30 (changelist #640742), g_SilentHill.sgl
md5 2af20d3f0b1d3902135a044966859d39.

Usage
-----
    python shh_fps_patch.py --status             # show current value
    python shh_fps_patch.py --fps 144            # set a 144 FPS cap
    python shh_fps_patch.py --fps 60             # set a 60 FPS cap
    python shh_fps_patch.py --uncap              # no engine cap (vsync/GPU bound)
    python shh_fps_patch.py --restore            # back to the stock 30 FPS cap

The game folder is auto-detected from your Steam libraries; use --file to
point at a specific g_SilentHill.sgl (GOG, retail disc, or a second install).
A .orig backup is written next to the file the first time you patch.
"""

import argparse
import os
import re
import shutil
import struct
import sys

# --- constants established by reverse engineering ---------------------------
PATCH_OFFSET = 0x0108E804                # file offset == RVA for this section
PATCH_VA = 0x1108E804                    # VA when loaded at base 0x10000000
STOCK_BYTES = bytes.fromhex("184b0542")  # float 33.323334 ms -> 30.009 FPS
STOCK_FPS = 30.009
EXPECTED_MD5 = "2af20d3f0b1d3902135a044966859d39"
MODULE_NAME = "g_SilentHill.sgl"
REL_PATH = os.path.join("steamapps", "common", "Silent Hill Homecoming", "Bin", MODULE_NAME)

STEAM_ROOTS = [
    r"C:\Program Files (x86)\Steam",
    r"C:\Program Files\Steam",
    r"C:\Steam",
    os.path.expanduser(r"~\Steam"),
]


def steam_libraries():
    """Yield every Steam library folder, including ones on other drives."""
    seen = []
    roots = list(STEAM_ROOTS)

    # Registry tells us where Steam actually is, if it is installed.
    try:
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            roots.insert(0, winreg.QueryValueEx(k, name)[0])
                        except OSError:
                            pass
            except OSError:
                pass
    except ImportError:
        pass  # not on Windows

    for root in roots:
        if not root:
            continue
        root = os.path.normpath(root)
        if root in seen or not os.path.isdir(root):
            continue
        seen.append(root)
        yield root

        # libraryfolders.vdf lists additional library drives
        vdf = os.path.join(root, "steamapps", "libraryfolders.vdf")
        try:
            with open(vdf, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError:
            continue
        for m in re.finditer(r'"path"\s+"([^"]+)"', text):
            lib = os.path.normpath(m.group(1).replace("\\\\", "\\"))
            if lib not in seen and os.path.isdir(lib):
                seen.append(lib)
                yield lib


def find_game():
    """Locate g_SilentHill.sgl, or return None."""
    for lib in steam_libraries():
        candidate = os.path.join(lib, REL_PATH)
        if os.path.isfile(candidate):
            return candidate
    # Non-Steam installs: look beside this script and in the CWD.
    here = os.path.dirname(os.path.abspath(__file__))
    for base in (here, os.getcwd()):
        for sub in (MODULE_NAME, os.path.join("Bin", MODULE_NAME)):
            candidate = os.path.join(base, sub)
            if os.path.isfile(candidate):
                return candidate
    return None


def ms_to_bytes(ms):
    return struct.pack("<f", ms)


def bytes_to_ms(b):
    return struct.unpack("<f", b)[0]


def describe(b):
    ms = bytes_to_ms(b)
    if ms <= 0:
        return f"{b.hex()}  ({ms:.6f} ms -> uncapped)"
    return f"{b.hex()}  ({ms:.4f} ms -> {1000.0 / ms:.2f} FPS cap)"


def read_current(path):
    with open(path, "rb") as f:
        f.seek(PATCH_OFFSET)
        return f.read(4)


def write_value(path, new_bytes):
    try:
        with open(path, "r+b") as f:
            f.seek(PATCH_OFFSET)
            f.write(new_bytes)
            f.flush()
            os.fsync(f.fileno())
    except PermissionError:
        sys.exit(
            "ERROR: cannot write to the module.\n"
            "  * Close Silent Hill: Homecoming if it is running (Windows locks\n"
            "    the file while it is loaded), then try again.\n"
            "  * If it is still refused, run this from an elevated prompt."
        )


def ensure_backup(path):
    backup = path + ".orig"
    if not os.path.exists(backup):
        shutil.copy2(path, backup)
        print(f"  backup created : {backup}")
    else:
        print(f"  backup exists  : {backup}")
    return backup


def main():
    ap = argparse.ArgumentParser(
        description="Remove or adjust the hard-coded 30 FPS cap in Silent Hill: Homecoming (PC).",
        epilog="Examples:\n"
               "  python shh_fps_patch.py --status\n"
               "  python shh_fps_patch.py --fps 144\n"
               "  python shh_fps_patch.py --uncap\n"
               "  python shh_fps_patch.py --restore\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--fps", type=float, metavar="N", help="target FPS cap (e.g. 60, 120, 144)")
    g.add_argument("--uncap", action="store_true",
                   help="remove the engine cap entirely (frame rate then bounded by vsync/GPU)")
    g.add_argument("--restore", action="store_true", help="restore the stock 30 FPS cap")
    g.add_argument("--status", action="store_true", help="print the current value and exit")
    ap.add_argument("--file", metavar="PATH",
                    help="path to g_SilentHill.sgl (default: auto-detect from Steam)")
    args = ap.parse_args()

    path = args.file or find_game()
    if not path:
        sys.exit(
            "ERROR: could not find g_SilentHill.sgl automatically.\n"
            "Pass it explicitly, e.g.:\n"
            '  python shh_fps_patch.py --status --file "D:\\Games\\Silent Hill Homecoming\\Bin\\g_SilentHill.sgl"'
        )
    if not os.path.isfile(path):
        sys.exit(f"ERROR: not found: {path}")

    size = os.path.getsize(path)
    if size < PATCH_OFFSET + 4:
        sys.exit(f"ERROR: file is only {size} bytes - this is not the expected module.")

    current = read_current(path)
    print(f"file    : {path}")
    print(f"offset  : 0x{PATCH_OFFSET:08X}  (VA 0x{PATCH_VA:08X})")
    print(f"current : {describe(current)}")

    if args.status:
        return

    # Safety: the slot must hold either the stock constant or a previous patch
    # of ours (a sane frame time). Anything else means wrong file or offset.
    if current != STOCK_BYTES:
        ms = bytes_to_ms(current)
        if not (0.0 <= ms < 1000.0):
            sys.exit(
                "ERROR: unexpected value at the patch offset.\n"
                "This does not look like the supported build, so nothing was written.\n"
                f"Expected stock bytes {STOCK_BYTES.hex()} (md5 {EXPECTED_MD5})."
            )
        print("note    : already patched (value differs from stock)")

    if args.restore:
        new, label = STOCK_BYTES, f"stock {STOCK_FPS:.3f} FPS cap"
    elif args.uncap:
        new, label = ms_to_bytes(0.0), "uncapped"
    else:
        if args.fps <= 0:
            sys.exit("ERROR: --fps must be positive")
        new, label = ms_to_bytes(1000.0 / args.fps), f"{args.fps:g} FPS cap"

    if new == current:
        print(f"\nAlready set to {label} - nothing to do.")
        return

    ensure_backup(path)
    write_value(path, new)

    verify = read_current(path)
    print(f"new     : {describe(verify)}")
    if verify != new:
        sys.exit("ERROR: verification failed - the write did not stick.")

    print(f"\nOK - patched to {label}.")
    print("Note: Steam's 'Verify integrity of game files' will revert this.")


if __name__ == "__main__":
    main()
