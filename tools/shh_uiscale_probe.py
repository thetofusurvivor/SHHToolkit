"""
Live experiment: retarget individual UI "get size" call sites.

Background (see NOTES.md): the engine has two sibling size getters reached via
jump thunks --

    thunk 0x10016978 -> 0x10B72CA0   returns the REAL screen size
    thunk 0x100644D9 -> 0x10B72D20   returns a FIXED 1280x720 reference size

Eleven call sites call the FIXED one. The map and journal images are clipped to
1280x720, so one (or more) of those sites is the culprit.

Both thunks are called with a 5-byte `E8 rel32`, so a call site can be
retargeted from FIXED to REAL by rewriting only the 4-byte displacement - same
instruction length, nothing moves. .text is made writable via VirtualProtectEx,
so this can be done in the RUNNING process and undone instantly.

That makes it safe to bisect: flip one site, look at the map, flip it back.

Usage (game must be running):
    python shh_uiscale_probe.py --list
    python shh_uiscale_probe.py --flip 0x104EBEA5
    python shh_uiscale_probe.py --restore-all
"""

import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shh_mem import Proc, find_pid

THUNK_FIXED = 0x100644D9   # -> GetSize_FIXED_720p
THUNK_REAL = 0x10016978    # -> GetSize_REAL

# every `call THUNK_FIXED` found by static scan
CALL_SITES = [
    0x1013E601, 0x1013F250, 0x1013FE07, 0x101401AA, 0x101405AC, 0x10140816,
    0x102D90AF, 0x10498983, 0x104EBEA5, 0x10A929AF, 0x10A9367E,
]

# rough attribution from nearby strings; the 0x1013E-0x10140 cluster is the
# debug text / stats overlay module (it holds the FPS overlay at 0x1013F7B0)
NOTE = {
    0x1013E601: "debug text module ('%7.2f')",
    0x1013F250: "debug text module",
    0x1013FE07: "debug text module ('<More: truncated>')",
    0x101401AA: "debug text module",
    0x101405AC: "debug text module",
    0x10140816: "debug text module",
    0x102D90AF: "?",
    0x10498983: "?",
    0x104EBEA5: "UI draw area (near 0x4EC0B0, seen in the UI crash stack)",
    0x10A929AF: "?",
    0x10A9367E: "?",
}


def target_of(p, site):
    """Decode the E8 rel32 at `site` and return its call target, or None."""
    b = p.read(site, 5)
    if not b or b[0] != 0xE8:
        return None
    rel = struct.unpack_from("<i", b, 1)[0]
    return site + 5 + rel


def retarget(p, site, new_target):
    rel = new_target - (site + 5)
    return p.write(site + 1, struct.pack("<i", rel))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="show each call site's current target")
    ap.add_argument("--flip", metavar="ADDR", help="point this site at the REAL size getter")
    ap.add_argument("--unflip", metavar="ADDR", help="point this site back at the FIXED getter")
    ap.add_argument("--flip-all-unknown", action="store_true",
                    help="flip every site outside the debug-text module")
    ap.add_argument("--restore-all", action="store_true", help="point every site back at FIXED")
    args = ap.parse_args()

    pid = find_pid()
    if not pid:
        sys.exit("ERROR: game is not running")
    p = Proc(pid)
    if not p.verify_base():
        sys.exit("ERROR: module not at its preferred base")

    def show():
        print("%-12s %-8s %s" % ("site", "target", "note"))
        print("-" * 78)
        for s in CALL_SITES:
            t = target_of(p, s)
            tag = {THUNK_FIXED: "FIXED", THUNK_REAL: "REAL"}.get(t, "0x%08X" % (t or 0))
            print("0x%08X  %-8s %s" % (s, tag, NOTE.get(s, "")))

    if args.list:
        show(); return

    if args.restore_all:
        for s in CALL_SITES:
            if target_of(p, s) != THUNK_FIXED:
                retarget(p, s, THUNK_FIXED)
        print("all sites restored to FIXED\n"); show(); return

    if args.flip_all_unknown:
        for s in CALL_SITES:
            if "debug text" not in NOTE.get(s, ""):
                retarget(p, s, THUNK_REAL)
                print("flipped 0x%08X -> REAL" % s)
        print(); show(); return

    if args.flip or args.unflip:
        addr = int((args.flip or args.unflip), 16)
        if addr not in CALL_SITES:
            sys.exit("ERROR: 0x%08X is not a known call site" % addr)
        want = THUNK_REAL if args.flip else THUNK_FIXED
        before = target_of(p, addr)
        if before is None:
            sys.exit("ERROR: no E8 call at 0x%08X" % addr)
        retarget(p, addr, want)
        after = target_of(p, addr)
        print("0x%08X : 0x%08X -> 0x%08X  (%s)" % (
            addr, before, after, "REAL" if want == THUNK_REAL else "FIXED"))
        return

    ap.print_help()


if __name__ == "__main__":
    main()
