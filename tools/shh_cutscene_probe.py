"""
Read the CURRENT cutscene's Skip Mode from the running game.

Background (see NOTES.md): in-engine cinematics carry an authored "Skip Mode"
enum at cutscene+0x250, registered by the property system as:

    RegisterEnumProperty("Skip Mode", this + 0x94, 0, <enumTable>, 6)
    (dword index 0x94 == byte offset 0x250)

    0 = None              <- Skip() bails out; cutscene CANNOT be skipped
    1 = Load Level
    2 = (Obsolete)
    3 = (Obsolete)        <- the only mode the fast-forward gate accepts
    4 = Abort
    5 = Elapse Director   <- the ICutscene constructor default

Skip() at 0x10491410 refuses only when Skip Mode == 0. So the hypothesis for
"this cutscene won't skip" is: it is authored with Skip Mode = None.

This tool reads the live value so that can be confirmed rather than assumed.
It only READS memory - it changes nothing.

Usage (with the game running, ideally during a cutscene):
    python shh_cutscene_probe.py
    python shh_cutscene_probe.py --watch
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shh_mem import Proc, find_pid

PTR_CURRENT_CUTSCENE = 0x11596118   # read by the fast-forward gate at 0x10490DC0

# DialogueTreeManager. FUN_108E8920 (DialogueTree::Exit) does:
#     mov eax,[0x116BD770] / cmp [eax+0x214], esi   ; is this tree the active one?
# so +0x214 holds the currently-active conversation, or NULL.
PTR_DIALOGUE_MANAGER = 0x116BD770
OFF_ACTIVE_TREE = 0x214
OFF_STATE = 0x210                   # 0 = idle, 2 = skip in progress
OFF_SKIPMODE = 0x250

SKIP_MODES = {
    0: "None            (Skip() refuses - NOT skippable)",
    1: "Load Level",
    2: "(Obsolete)",
    3: "(Obsolete)      (the only mode the fast-forward gate accepts)",
    4: "Abort",
    5: "Elapse Director (constructor default)",
}


def read_dialogue(p, verbose=True):
    """Currently-active DialogueTree, or None."""
    mgr = p.u32(PTR_DIALOGUE_MANAGER)
    if not mgr:
        if verbose:
            print("  dialogue manager not created yet")
        return None
    tree = p.u32(mgr + OFF_ACTIVE_TREE)
    if verbose:
        print("  dialogue manager : 0x%08X" % mgr)
        print("  active tree      : %s" % ("0x%08X  <-- CONVERSATION ACTIVE" % tree
                                           if tree else "NULL (no conversation)"))
    return tree or None


def read_once(p, verbose=True):
    cut = p.u32(PTR_CURRENT_CUTSCENE)
    if not cut:
        if verbose:
            print("  no cutscene active (global is NULL)")
        return None
    state = p.i32(cut + OFF_STATE)
    mode = p.i32(cut + OFF_SKIPMODE)
    if verbose:
        print("  cutscene object : 0x%08X" % cut)
        print("  state  (+0x210) : %s" % (
            "%d  %s" % (state, {0: "(idle)", 2: "(SKIP IN PROGRESS)"}.get(state, ""))))
        print("  SkipMode(+0x250): %d  %s" % (mode, SKIP_MODES.get(mode, "(unknown)")))
    return (cut, state, mode)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--watch", action="store_true",
                    help="poll continuously and report every change")
    ap.add_argument("--interval", type=float, default=0.3)
    args = ap.parse_args()

    pid = find_pid()
    if not pid:
        sys.exit("ERROR: game is not running")
    p = Proc(pid)
    if not p.verify_base():
        sys.exit("ERROR: module not at its preferred base")
    print("pid %d\n" % pid)

    if not args.watch:
        read_once(p)
        return

    print("watching for cutscenes - play until one starts, Ctrl+C to stop\n")
    last = None
    seen = {}
    try:
        while True:
            cur = read_once(p, verbose=False)
            if cur != last:
                if cur is None:
                    print("  [%s] no cutscene" % time.strftime("%H:%M:%S"))
                else:
                    cut, state, mode = cur
                    print("  [%s] cutscene 0x%08X  state=%-2d  SkipMode=%d  %s" % (
                        time.strftime("%H:%M:%S"), cut, state, mode,
                        SKIP_MODES.get(mode, "(unknown)")))
                    seen[cut] = mode
                last = cur
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nsummary of cutscenes seen:")
        for cut, mode in seen.items():
            print("   0x%08X  SkipMode=%d  %s" % (cut, mode, SKIP_MODES.get(mode, "?")))


if __name__ == "__main__":
    main()
