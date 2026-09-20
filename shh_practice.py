#!/usr/bin/env python3
"""
Silent Hill: Homecoming (PC) - checkpoint key for practice (runtime only)
=========================================================================

Adds a "set a checkpoint here" key to the RUNNING game, for speedrun practice.
Nothing is written to the game's files: the hook lives in the game's memory and
is gone the moment the game exits. Run it once after launching the game.

    python shh_practice.py              # F5 sets a checkpoint
    python shh_practice.py --key F6
    python shh_practice.py --status     # frames seen / key presses / checkpoints set
    python shh_practice.py --remove     # undo now, without restarting the game

This is NOT a save. It calls the engine's own `SaveCheckpoint` (0x10991560 on the
manager at `[0x116C1020]`), which sets the checkpoint the game restores you to.
Writing a real save from arbitrary places was tried and crashes: that code path
needs the save menu's context, which does not exist during play.

How it works
------------
* one scratch page allocated in the game holds the key state and three counters,
* a stub in unused `0xCC` padding at `0x10D71600` polls the key with
  `GetAsyncKeyState` (already imported by the game), edge-detects the press, and
  calls `SaveCheckpoint`,
* the first 5 bytes of the frame limiter (`0x10A4CC90`, which runs once per
  frame) jump to that stub, and the stub then performs the instructions it
  displaced - including the relative `call`, re-encoded for its new address.

All game threads are suspended while those bytes are written, because the hook
site executes every frame.

Caveats
-------
* `GetAsyncKeyState` is global, so the key counts even when another window has
  focus (the game keeps ticking in the background).
* A checkpoint is not a save: closing the game loses it.
* Verified on build v6.30 (#640742), g_SilentHill.sgl
  md5 2af20d3f0b1d3902135a044966859d39, loaded at its preferred base.
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
from shh_mem import Proc, find_pid  # noqa: E402

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.VirtualAllocEx.restype = ctypes.c_void_p
k32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]

HOOK = 0x10A4CC90          # frame limiter, runs once per frame
CAVE = 0x10D71600          # unused 0xCC padding in .text
HOOK_ORIG = bytes.fromhex("5355565" "7e8fca35bff")   # push ebx/ebp/esi/edi + call 0x10007095
DISPLACED_CALL = 0x10007095
IAT_GETASYNCKEYSTATE = 0x117EEF30
MGR = 0x116C1020
SAVE_CHECKPOINT = 0x10991560
STUB_MAX = 160

KEYS = {"F5": 0x74, "F6": 0x75, "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79,
        "F11": 0x7A, "F12": 0x7B, "INSERT": 0x2D, "HOME": 0x24, "END": 0x23,
        "PAGEUP": 0x21, "PAGEDOWN": 0x22, "SCROLLLOCK": 0x91, "PAUSE": 0x13}

TH32CS_SNAPTHREAD, THREAD_SUSPEND_RESUME = 0x04, 0x0002


class TE32(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD), ("th32ThreadID", wt.DWORD),
                ("th32OwnerProcessID", wt.DWORD), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", wt.DWORD)]


def threads_of(pid):
    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = TE32()
    te.dwSize = ctypes.sizeof(te)
    out = []
    if k32.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                out.append(te.th32ThreadID)
            if not k32.Thread32Next(snap, ctypes.byref(te)):
                break
    k32.CloseHandle(snap)
    return out


def build_stub(state, vk):
    """state page: +0 frames, +4 presses, +8 checkpoints, +12 previous key state."""
    c = bytearray()
    c += b"\x60\x9c"                                              # pushad / pushfd
    c += b"\xff\x05" + struct.pack("<I", state)                   # inc [frames]
    c += b"\x6a" + bytes([vk])
    c += b"\xff\x15" + struct.pack("<I", IAT_GETASYNCKEYSTATE)    # GetAsyncKeyState(vk)
    c += b"\xf6\xc4\x80"                                          # test ah,0x80  (key down?)
    j_up = len(c); c += b"\x74\x00"
    c += b"\x83\x3d" + struct.pack("<I", state + 12) + b"\x00"    # already held?
    j_held = len(c); c += b"\x75\x00"
    c += b"\xc7\x05" + struct.pack("<I", state + 12) + struct.pack("<I", 1)
    c += b"\xff\x05" + struct.pack("<I", state + 4)               # inc [presses]
    c += b"\x8b\x0d" + struct.pack("<I", MGR)                     # ecx = [manager]
    c += b"\x85\xc9"
    j_nomgr = len(c); c += b"\x74\x00"
    c += b"\xe8" + struct.pack("<i", SAVE_CHECKPOINT - (CAVE + len(c) + 5))
    c += b"\xff\x05" + struct.pack("<I", state + 8)               # inc [checkpoints]
    j_done = len(c); c += b"\xeb\x00"
    up = len(c)
    c += b"\xc7\x05" + struct.pack("<I", state + 12) + struct.pack("<I", 0)
    done = len(c)
    for at, tgt in ((j_up, up), (j_held, done), (j_nomgr, done), (j_done, done)):
        c[at + 1] = tgt - (at + 2)
    c += b"\x9d\x61"                                              # popfd / popad
    c += b"\x53\x55\x56\x57"                                      # the displaced pushes
    c += b"\xe8" + struct.pack("<i", DISPLACED_CALL - (CAVE + len(c) + 5))   # re-encoded call
    c += b"\xe9" + struct.pack("<i", (HOOK + 9) - (CAVE + len(c) + 5))
    assert len(c) <= STUB_MAX
    return bytes(c)


def hook_bytes():
    return b"\xe9" + struct.pack("<i", CAVE - (HOOK + 5))


def hooked(p):
    return p.read(HOOK, 5) == hook_bytes()


def patch(p, pid, cave_bytes, hook_patch):
    """The hook site runs every frame, so nothing executes while it is rewritten."""
    tids = threads_of(pid)
    handles = [k32.OpenThread(THREAD_SUSPEND_RESUME, False, t) for t in tids]
    susp = [h for h in handles if h and k32.SuspendThread(h) != 0xFFFFFFFF]
    if len(susp) != len(tids):
        print("  note: suspended %d of %d threads" % (len(susp), len(tids)))
    try:
        p.write(CAVE, cave_bytes)
        p.write(HOOK, hook_patch)
        k32.FlushInstructionCache(p.h, ctypes.c_void_p(CAVE), STUB_MAX)
        k32.FlushInstructionCache(p.h, ctypes.c_void_p(HOOK), 16)
    finally:
        for h in susp:
            k32.ResumeThread(h)
        for h in handles:
            if h:
                k32.CloseHandle(h)


def main():
    ap = argparse.ArgumentParser(description="Set a checkpoint on a key, in memory only.",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key", default="F5", help="checkpoint key (default F5)")
    ap.add_argument("--remove", action="store_true", help="remove the hook from the running game")
    ap.add_argument("--status", action="store_true", help="show whether it is active, and its counters")
    args = ap.parse_args()

    pid = find_pid()
    if not pid:
        sys.exit("ERROR: the game is not running. Start it first - this tool only patches memory.")
    p = Proc(pid)
    if not p.verify_base():
        sys.exit("ERROR: the module is not at its preferred base - nothing was written.")

    if args.status:
        if not hooked(p):
            print("checkpoint key: not active")
            return
        state = struct.unpack("<I", p.read(CAVE + 4, 4))[0]
        frames, presses, checkpoints = struct.unpack("<3I", p.read(state, 12))
        print("checkpoint key: ACTIVE  (state page 0x%08X)" % state)
        print("  frames seen : %d\n  key presses : %d\n  checkpoints : %d" % (frames, presses, checkpoints))
        return

    if args.remove:
        if not hooked(p):
            print("not active - nothing to do")
            return
        patch(p, pid, b"\xcc" * STUB_MAX, HOOK_ORIG)
        print("removed" if p.read(HOOK, len(HOOK_ORIG)) == HOOK_ORIG else "REMOVE FAILED")
        return

    key = args.key.upper()
    vk = KEYS.get(key)
    if vk is None:
        try:
            vk = int(args.key, 0)
        except ValueError:
            sys.exit("ERROR: unknown key %r. Known: %s" % (args.key, ", ".join(sorted(KEYS))))

    if not hooked(p):
        if p.read(HOOK, len(HOOK_ORIG)) != HOOK_ORIG:
            sys.exit("ERROR: the hook site is not this build's frame limiter - nothing was written.")
        if p.read(CAVE, STUB_MAX) != b"\xcc" * STUB_MAX:
            sys.exit("ERROR: the code cave is not empty - nothing was written.")

    state = k32.VirtualAllocEx(p.h, None, 0x1000, 0x3000, 0x04)   # MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE
    if not state:
        sys.exit("ERROR: VirtualAllocEx failed (%d)" % ctypes.get_last_error())
    stub = build_stub(state, vk)
    patch(p, pid, stub + b"\xcc" * (STUB_MAX - len(stub)), hook_bytes())

    if not hooked(p) or p.read(CAVE, len(stub)) != stub:
        sys.exit("ERROR: verification failed - restart the game before trying again.")
    print("checkpoint key active: press %s in game to set a checkpoint." % key)
    print("It lives only in this session - closing the game removes it.")
    print("Check it with:  python shh_practice.py --status")


if __name__ == "__main__":
    main()
