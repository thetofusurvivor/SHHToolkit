#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - window and mouse fixes
=====================================================

*** THE BORDERLESS HALF OF THIS SCRIPT IS DEPRECATED (2026-09-14). ***

Restyling the game's live window works visually, but every restyle makes the
engine re-run its video setup, and that correlated with real instability:
4 application hangs, every one in a session where this script was running and
none ever without it, plus a crash 11 s after it was started while a save was
loading. A bounded retry budget was not enough.

Use `shh_borderless_patch.py` instead - it sets the window style at creation
time inside the game, so nothing ever restyles a live window. Borderless here
is now opt-in (`--borderless`) and only kept for comparison.

Still useful and unaffected:
  * `--setup`  - writes FullScreen=false + native resolution into vars_pc.cfg
  * the cursor lock (the default mode now), which never touches the window

Two multi-monitor annoyances, both fixed from outside the process. This script
never reads or writes the game's memory or files, so there is nothing to undo
and Steam file validation is unaffected.

1. The game auto-minimises when you tab out
-------------------------------------------
That is Direct3D 9 *exclusive fullscreen* behaviour: when the app loses
foreground the device is lost, and D3D9 minimises the window. It cannot be
suppressed from another process - the minimise happens inside D3D9's own
WM_ACTIVATEAPP handling.

The standard fix is **borderless windowed**: run the game windowed at your
monitor's native resolution, then strip the window border and position it to
cover the whole monitor. It looks identical to fullscreen, but the device is
never lost, so no minimising and no device-reset hitches when you tab away.

Requires these in Engine\\vars_pc.cfg (edit with the game CLOSED - it rewrites
the file on exit):

    FullScreen=false
    ScreenResWidth=<your monitor width>
    ScreenResHeight=<your monitor height>

`--setup` will do that edit for you, matching your primary monitor.

2. The mouse escapes onto other monitors
-----------------------------------------
The engine does confine the cursor - it calls ClipCursor with its client rect
from the function at VA 0x10BA2DE0 - but only on focus/state transitions.
Windows drops the cursor clip on any foreground change and the game never
re-applies it. Verified live: the game's own state said it had clipped
(g_clipMode=0, enable=1) while GetClipCursor reported the entire virtual
desktop, with the game in the foreground.

This script re-applies the clip continuously while the game is focused, and
releases it the moment it is not, so alt-tab still works normally.

Usage
-----
    python shh_window_fix.py --setup     # one-time: set windowed + native res
    python shh_window_fix.py             # run alongside the game (both fixes)
    python shh_window_fix.py --no-cursor-lock
    python shh_window_fix.py --no-borderless
    python shh_window_fix.py --verbose

Ctrl+C to stop. The cursor is always released on exit.
"""

import argparse
import atexit
import ctypes
import ctypes.wintypes as wt
import os
import re
import sys
import time

U = ctypes.windll.user32
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor DPI aware
except Exception:
    try:
        U.SetProcessDPIAware()
    except Exception:
        pass

WINDOW_TITLE = "Silent Hill: Homecoming"
PROC_NAME = "SilentHill"

GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_SYSMENU = 0x00080000
WS_BORDER = 0x00800000
WS_DLGFRAME = 0x00400000
WS_EX_DLGMODALFRAME = 0x00000001
WS_EX_WINDOWEDGE = 0x00000100
WS_EX_CLIENTEDGE = 0x00000200
WS_EX_STATICEDGE = 0x00020000
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040
SWP_NOZORDER = 0x0004
MONITOR_DEFAULTTONEAREST = 2

# How many times to re-apply the borderless style before giving up, so we never
# get into an endless restyle war with the game.
MAX_STYLE_TRIES = 8


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wt.DWORD)]


def release_clip():
    U.ClipCursor(None)


atexit.register(release_clip)


# ---------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------- #
def find_pid(name=PROC_NAME):
    import subprocess
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, timeout=15).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = [p.strip('"') for p in line.split('","')]
        if len(parts) > 1 and parts[0].lower().startswith(name.lower()):
            try:
                return int(parts[1])
            except ValueError:
                pass
    return None


def find_window(pid):
    """The titled game window (there is also an untitled D3DProxyWindow)."""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(h, _l):
        q = ctypes.c_ulong()
        U.GetWindowThreadProcessId(h, ctypes.byref(q))
        if q.value == pid and U.IsWindowVisible(h):
            n = ctypes.create_unicode_buffer(256)
            U.GetWindowTextW(h, n, 256)
            if n.value.strip() == WINDOW_TITLE:
                found.append(h)
        return True

    U.EnumWindows(cb, 0)
    return found[0] if found else None


def monitor_rect(hwnd):
    hm = U.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not U.GetMonitorInfoW(hm, ctypes.byref(mi)):
        return None
    return mi.rcMonitor


def primary_monitor_size():
    return U.GetSystemMetrics(0), U.GetSystemMetrics(1)


# --------------------------------------------------------------------------- #
# borderless
# --------------------------------------------------------------------------- #
def is_borderless(hwnd):
    """True only for a live window that genuinely has no frame.

    GetWindowLongW returns 0 for a dead handle, which would otherwise read as
    "no caption, no frame" -> borderless. Validate the handle first so a window
    that has just been destroyed is never mistaken for a styled one.
    """
    if not U.IsWindow(hwnd):
        return False
    style = U.GetWindowLongW(hwnd, GWL_STYLE)
    if style == 0:
        return False
    return not (style & (WS_CAPTION | WS_THICKFRAME))


def make_borderless(hwnd, verbose=False):
    """Strip the frame and cover the monitor the window is currently on."""
    mon = monitor_rect(hwnd)
    if mon is None:
        return False
    style = U.GetWindowLongW(hwnd, GWL_STYLE)
    style &= ~(WS_CAPTION | WS_THICKFRAME | WS_MINIMIZEBOX |
               WS_MAXIMIZEBOX | WS_SYSMENU | WS_BORDER | WS_DLGFRAME)
    style |= WS_POPUP
    U.SetWindowLongW(hwnd, GWL_STYLE, style)

    ex = U.GetWindowLongW(hwnd, GWL_EXSTYLE)
    ex &= ~(WS_EX_DLGMODALFRAME | WS_EX_WINDOWEDGE |
            WS_EX_CLIENTEDGE | WS_EX_STATICEDGE)
    U.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)

    w, h = mon.right - mon.left, mon.bottom - mon.top
    U.SetWindowPos(hwnd, 0, mon.left, mon.top, w, h,
                   SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOZORDER)
    if verbose:
        print(f"  borderless -> ({mon.left},{mon.top}) {w}x{h}")
    return True


# --------------------------------------------------------------------------- #
# cursor lock
# --------------------------------------------------------------------------- #
def client_rect_on_screen(hwnd, margin=0):
    """Client area in screen coords. None if minimised (ClientToScreen then
    reports the -32000 placeholder and clipping to it would strand the cursor)."""
    if U.IsIconic(hwnd):
        return None
    rc = RECT()
    if not U.GetClientRect(hwnd, ctypes.byref(rc)):
        return None
    o = POINT(0, 0)
    if not U.ClientToScreen(hwnd, ctypes.byref(o)):
        return None
    out = RECT(rc.left + o.x + margin, rc.top + o.y + margin,
               rc.right + o.x - margin, rc.bottom + o.y - margin)
    if out.right <= out.left or out.bottom <= out.top:
        return None
    return out


def same(a, b):
    return (a.left, a.top, a.right, a.bottom) == (b.left, b.top, b.right, b.bottom)


# --------------------------------------------------------------------------- #
# --setup
# --------------------------------------------------------------------------- #
def find_cfg():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from shh_fps_patch import find_game
        sgl = find_game()
        if sgl:
            root = os.path.dirname(os.path.dirname(sgl))   # ...\Bin\.. -> game root
            cfg = os.path.join(root, "Engine", "vars_pc.cfg")
            if os.path.isfile(cfg):
                return cfg
    except Exception:
        pass
    return None


def do_setup():
    if find_pid():
        sys.exit("ERROR: close the game first - it rewrites vars_pc.cfg on exit,\n"
                 "       which would overwrite these changes.")
    cfg = find_cfg()
    if not cfg:
        sys.exit("ERROR: could not locate Engine\\vars_pc.cfg - edit it by hand:\n"
                 "  FullScreen=false / ScreenResWidth=<W> / ScreenResHeight=<H>")
    w, h = primary_monitor_size()
    print(f"config  : {cfg}")
    print(f"monitor : {w}x{h}")
    s = open(cfg, "r", newline="").read()
    wanted = {"FullScreen": "false", "ScreenResWidth": str(w), "ScreenResHeight": str(h)}
    for k, v in wanted.items():
        new, n = re.subn(r"(?m)^%s=.*$" % re.escape(k), f"{k}={v}", s)
        if n == 0:
            new = s + f"{k}={v}\n"
        s = new
        print(f"  {k:<16} -> {v}")
    open(cfg, "w", newline="").write(s)
    print("\nOK - borderless-ready. Now launch the game and run:\n"
          "    python shh_window_fix.py")


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="Borderless windowed + cursor confinement for Silent Hill: Homecoming.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--setup", action="store_true",
                    help="edit vars_pc.cfg for borderless (windowed + native res), then exit")
    ap.add_argument("--borderless", action="store_true",
                    help="DEPRECATED: restyle the live window (caused hangs - use "
                         "shh_borderless_patch.py instead)")
    ap.add_argument("--no-borderless", action="store_true",
                    help=argparse.SUPPRESS)   # accepted for compatibility; now the default
    ap.add_argument("--no-cursor-lock", action="store_true", help="do not confine the cursor")
    ap.add_argument("--interval", type=float, default=0.15, help="poll seconds (default 0.15)")
    ap.add_argument("--margin", type=int, default=0, help="inset the clip rect by N pixels")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    if args.setup:
        return do_setup()

    do_border = args.borderless and not args.no_borderless
    do_clip = not args.no_cursor_lock
    print("Silent Hill: Homecoming - window fix")
    print("  borderless : %s" % ("ON (deprecated)" if do_border else "off"))
    print("  cursor lock: %s" % ("on" if do_clip else "off"))
    if do_border:
        print("\n  WARNING: restyling the live window correlated with 4 application\n"
              "           hangs and a load-time crash. The supported way to get\n"
              "           borderless is now:  python shh_borderless_patch.py --apply")
    if not do_clip and not do_border:
        sys.exit("Nothing to do: cursor lock disabled and borderless is opt-in "
                 "(--borderless).")
    print("Ctrl+C to stop.\n")

    pid = hwnd = None
    clipped = False
    styled_for = None
    announced = False
    style_tries = 0
    last_style_try = 0.0

    try:
        while True:
            if pid is None or not U.IsWindow(hwnd or 0):
                pid = find_pid()
                hwnd = find_window(pid) if pid else None
                if not hwnd:
                    if not announced:
                        print("waiting for the game...")
                        announced = True
                    if clipped:
                        release_clip(); clipped = False
                    styled_for = None
                    time.sleep(1.0)
                    continue
                announced = False
                style_tries = 0
                last_style_try = 0.0
                print(f"attached to pid {pid}, window 0x{hwnd:X}")

            # Borderless, with a bounded retry budget.
            #
            # A one-shot apply loses the race at startup: the game restyles its
            # own window during D3D init, so the frame comes back after we strip
            # it. But retrying forever is worse - if the game reasserts its
            # style every frame we end up in a restyle war with it, which can
            # hang the game. So: retry up to MAX_STYLE_TRIES, at most once a
            # second, then give up and leave it alone.
            if do_border and not U.IsIconic(hwnd):
                if is_borderless(hwnd):
                    if styled_for != hwnd:
                        if args.verbose:
                            print("  borderless confirmed")
                        styled_for = hwnd
                elif style_tries < MAX_STYLE_TRIES:
                    now = time.time()
                    if now - last_style_try >= 1.0:
                        last_style_try = now
                        style_tries += 1
                        make_borderless(hwnd, verbose=True)
                        if style_tries == MAX_STYLE_TRIES:
                            print("  note: the game keeps restoring its window frame; "
                                  "leaving it alone now to avoid fighting it.\n"
                                  "        (run with --no-borderless to skip this entirely)")

            if do_clip:
                if U.GetForegroundWindow() == hwnd:
                    rc = client_rect_on_screen(hwnd, args.margin)
                    if rc:
                        cur = RECT()
                        U.GetClipCursor(ctypes.byref(cur))
                        if not same(cur, rc):
                            if U.ClipCursor(ctypes.byref(rc)):
                                if args.verbose or not clipped:
                                    print(f"  cursor clipped -> ({rc.left},{rc.top})-({rc.right},{rc.bottom})")
                                clipped = True
                            elif args.verbose:
                                print("  ClipCursor failed:", ctypes.GetLastError())
                elif clipped:
                    release_clip(); clipped = False
                    if args.verbose:
                        print("  lost focus - cursor released")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        release_clip()
        print("cursor released")


if __name__ == "__main__":
    main()
