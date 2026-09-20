"""
Measure the game's real frame rate, and optionally A/B the limiter constant.

Frame rate is derived from the engine's own per-tick frame counter
(FRAME_COUNTER) sampled against a wall clock. This is the only method that
proved trustworthy:

  * the engine's averaged FPS floats (stats+0x32C) go STALE - they keep
    reporting the last computed value when the game is idle, so they will
    happily show "29.90" forever and look like a working measurement.
  * the game stops ticking entirely when its window is not focused, which
    reads as 0 FPS. So focus must be forced before every sample.

Usage:
    python shh_measure.py                 # measure the running game
    python shh_measure.py --pid 1234
    python shh_measure.py --ab            # A/B stock 30 vs 144 by live-patching
    python shh_measure.py --set 144       # live-patch the cap, no restart needed

NOTE: run the game WINDOWED for this. In exclusive fullscreen the game
minimises when focus moves to the console and stops ticking. Set
FullScreen=false in Engine\\vars_pc.cfg for measurement runs.
"""

import argparse
import ctypes
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shh_mem import Proc, find_pid, FRAME_COUNTER, LIMITER_MS, CV_FPS_LIMIT, CV_MAX_FPS_LIMIT, CV_VSYNC

_u = ctypes.windll.user32


def game_window(pid):
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _l):
        p = ctypes.c_ulong()
        _u.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and _u.IsWindowVisible(h):
            n = ctypes.create_unicode_buffer(256)
            _u.GetWindowTextW(h, n, 256)
            if n.value.strip():
                found.append(h)
        return True

    _u.EnumWindows(cb, 0)
    return found[0] if found else None


def focus(hwnd):
    if hwnd:
        _u.ShowWindow(hwnd, 9)  # SW_RESTORE
        _u.SetForegroundWindow(hwnd)
        _u.SetActiveWindow(hwnd)
        time.sleep(0.4)


def measure(p, hwnd, secs=5.0):
    focus(hwnd)
    time.sleep(1.0)
    a = p.u32(FRAME_COUNTER)
    t0 = time.perf_counter()
    time.sleep(secs)
    b = p.u32(FRAME_COUNTER)
    t1 = time.perf_counter()
    if a is None or b is None:
        return None
    return (b - a) / (t1 - t0)


def describe_limiter(p):
    ms = p.limiter_ms()
    if ms is None:
        return "unreadable"
    return f"{ms:.4f} ms -> " + (f"{1000.0 / ms:.2f} FPS cap" if ms > 0 else "UNCAPPED")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int, help="game pid (default: auto-detect)")
    ap.add_argument("--secs", type=float, default=5.0, help="seconds per sample")
    ap.add_argument("--samples", type=int, default=4, help="number of samples")
    ap.add_argument("--ab", action="store_true", help="A/B the stock cap against 144 FPS")
    ap.add_argument("--set", type=float, metavar="FPS",
                    help="live-patch the cap in the running process (0 = uncap)")
    args = ap.parse_args()

    pid = args.pid or find_pid()
    if not pid:
        sys.exit("ERROR: game not running (start SilentHill.exe first)")
    p = Proc(pid)
    if not p.verify_base():
        sys.exit("ERROR: module not at 0x10000000 - addresses would be wrong")

    s = p.settings()
    print(f"pid      : {pid}")
    print(f"cvars    : fpsLimit={p.i32(s + CV_FPS_LIMIT)} "
          f"maxFPSLimit={p.i32(s + CV_MAX_FPS_LIMIT)} vsync={p.u8(s + CV_VSYNC)}")
    print(f"limiter  : {describe_limiter(p)}")

    hwnd = game_window(pid)
    if not hwnd:
        print("warning  : no visible game window found; focus cannot be forced")

    if args.set is not None:
        p.set_limiter_fps(args.set)
        print(f"\nlive-patched limiter -> {describe_limiter(p)}")
        return

    if args.ab:
        orig = p.read(LIMITER_MS, 4)
        print()
        for label, fps in [("stock 30 FPS", 30.009), ("patched 144 FPS", 144.0),
                           ("stock again", 30.009), ("patched again", 144.0)]:
            p.set_limiter_fps(fps)
            time.sleep(0.6)
            f = measure(p, hwnd, args.secs)
            print(f"  {label:<20} {f:8.2f} FPS" if f is not None else f"  {label:<20}   n/a")
        p.write(LIMITER_MS, orig)
        print(f"\nrestored : {describe_limiter(p)}")
        return

    print()
    for _ in range(args.samples):
        f = measure(p, hwnd, args.secs)
        print(f"  {f:8.2f} FPS" if f is not None else "  n/a")


if __name__ == "__main__":
    main()
