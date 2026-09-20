#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - runtime game-speed control

Requires `shh_speed_patch.py --apply` first. That patch routes the engine's
global frame delta time (0x116C7A14) through a multiplier we control:

    g_speedFactor @ 0x10D71300   float, 1.0 = normal

This sets that factor in the running game. The main use is fast-forwarding the
in-engine dialogue cutscenes, which genuinely cannot be skipped (no cutscene
object exists to abort - see NOTES.md).

The factor lives in .text, which is read-only at runtime, so writes go through
VirtualProtectEx. Proc.write already handles that.

Usage
-----
    python shh_speed.py --hold            # hold CAPS LOCK to fast-forward (default 4x)
    python shh_speed.py --hold --key F8 --factor 6
    python shh_speed.py --set 4           # set it and exit (stays until changed)
    python shh_speed.py --set 1           # back to normal
    python shh_speed.py --status

Ctrl+C in --hold mode restores 1.0 on the way out.
"""

import argparse
import atexit
import ctypes
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
from shh_mem import Proc, find_pid

FACTOR_ADDR = 0x10D71300

# Voice volume lives in the vars_pc.cfg settings object. Confirmed from the cvar
# registration: `lea ecx,[esi+0x144]` for "volumevoice" (and gamma at +0x148,
# reading -0.5, which corroborates the alignment).
#
# Audio does not follow the time scale - the sound engine runs on its own clock -
# so speech plays at normal rate while everything else runs 4x, which sounds
# broken. Muting voice while fast-forwarding avoids that artifact.
VOL_VOICE_OFF = 0x144

U = ctypes.windll.user32

# a few sensible choices; anything not listed can be given as a VK number
KEYS = {
    "CAPSLOCK": 0x14, "TAB": 0x09, "F7": 0x76, "F8": 0x77, "F9": 0x78,
    "F10": 0x79, "F11": 0x7A, "F12": 0x7B, "CTRL": 0x11, "ALT": 0x12,
    "SHIFT": 0x10, "PAGEUP": 0x21, "PAGEDOWN": 0x22, "END": 0x23, "HOME": 0x24,
    "INSERT": 0x2D, "BACKSPACE": 0x08, "TILDE": 0xC0,
}


def get_factor(p):
    return p.f32(FACTOR_ADDR)


def set_factor(p, v):
    return p.write(FACTOR_ADDR, struct.pack("<f", float(v)))


def check_patched(p):
    """The cave must hold our code, else the patch is not applied."""
    code = p.read(0x10D71310, 4)
    if code != bytes.fromhex("f30f5905"):
        sys.exit("ERROR: the speed patch is not applied to the running module.\n"
                 "Close the game, run:  python shh_speed_patch.py --apply\n"
                 "then start the game again.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--hold", action="store_true", help="fast-forward only while a key is held")
    g.add_argument("--set", type=float, metavar="N", help="set the factor and exit")
    g.add_argument("--status", action="store_true")
    ap.add_argument("--key", default="CAPSLOCK", help="key to hold (default CAPSLOCK)")
    ap.add_argument("--factor", type=float, default=4.0, help="speed while held (default 4)")
    ap.add_argument("--interval", type=float, default=0.03)
    ap.add_argument("--no-mute", action="store_true",
                    help="do NOT mute voice while fast-forwarding (speech will sound broken)")
    args = ap.parse_args()

    pid = find_pid()
    if not pid:
        sys.exit("ERROR: game is not running")
    p = Proc(pid)
    if not p.verify_base():
        sys.exit("ERROR: module not at its preferred base")
    check_patched(p)

    if args.status:
        print("factor = %.3f  (1.0 = normal)" % get_factor(p))
        return

    if args.set is not None:
        if args.set <= 0:
            sys.exit("ERROR: factor must be > 0")
        set_factor(p, args.set)
        print("factor = %.3f" % get_factor(p))
        return

    key = args.key.upper()
    vk = KEYS.get(key)
    if vk is None:
        try:
            vk = int(args.key, 0)
        except ValueError:
            sys.exit("ERROR: unknown key %r. Known: %s" % (args.key, ", ".join(sorted(KEYS))))

    # remember the player's real voice volume so it can always be put back
    settings = p.settings()
    voice_addr = (settings + VOL_VOICE_OFF) if settings else None
    orig_voice = p.f32(voice_addr) if voice_addr else None
    do_mute = (not args.no_mute) and orig_voice is not None

    def restore():
        set_factor(p, 1.0)
        if do_mute and orig_voice is not None:
            p.write(voice_addr, struct.pack("<f", orig_voice))

    atexit.register(restore)
    print("Hold %s to fast-forward at %.1fx. Ctrl+C to stop." % (key, args.factor))
    if do_mute:
        print("voice muted while held (audio runs on its own clock, so it "
              "cannot follow the time scale)")
    print("(the game must be the focused window for the key to register)\n")

    held = False
    try:
        while True:
            if not find_pid():
                print("game exited")
                return
            down = bool(U.GetAsyncKeyState(vk) & 0x8000)
            if down != held:
                set_factor(p, args.factor if down else 1.0)
                if do_mute:
                    p.write(voice_addr, struct.pack("<f", 0.0 if down else orig_voice))
                print("  %s  -> %.1fx%s" % ("fast-forward" if down else "normal      ",
                                            args.factor if down else 1.0,
                                            "  (voice muted)" if (do_mute and down) else ""))
                held = down
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        try:
            restore()
            print("factor restored to 1.0" +
                  (", voice volume restored" if do_mute else ""))
        except Exception:
            pass


if __name__ == "__main__":
    main()
