"""
Sampling profiler + stack walker for the running game.

This is what actually located the frame limiter. Static analysis of a 21 MB
stripped binary went nowhere (offset scans returned hundreds of false hits);
sampling the live process found it in two steps:

  1. --sample : suspend every thread repeatedly and histogram EIP. The main
                thread showed ~91% of samples parked in ntdll, i.e. blocked in
                a wait - the signature of a frame limiter sleeping.
  2. --stack  : walk the main thread's stack for return addresses inside
                g_SilentHill.sgl. That produced a stable 6-frame chain leading
                straight to FUN_10A4CC90, the limiter.

The stack walk scans raw stack memory for values that fall inside the module
and are preceded by a call instruction. It is a heuristic, not a real unwinder,
but on this binary it produced a clean and highly repeatable chain.

Usage:
    python shh_profile.py --sample            # where is time being spent?
    python shh_profile.py --stack             # call chain of the busiest thread
    python shh_profile.py --stack --tid 1234

Feed the resulting g_SilentHill.sgl+0xNNNNNN offsets to Ghidra as
VA 0x10000000 + offset.
"""

import argparse
import collections
import ctypes
import ctypes.wintypes as w
import os
import struct
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from shh_mem import Proc, find_pid, IMAGE_BASE

_k = ctypes.windll.kernel32
TH32CS_SNAPTHREAD = 0x00000004
THREAD_ALL_ACCESS = 0x1F03FF
WOW64_CONTEXT_CONTROL = 0x00010001
CTX_EIP_OFF = 0xB8   # offsets into WOW64_CONTEXT
CTX_ESP_OFF = 0xC4

MODULE_LO = IMAGE_BASE
MODULE_HI = IMAGE_BASE + 0x1800000


class _TE32(ctypes.Structure):
    _fields_ = [("dwSize", w.DWORD), ("cntUsage", w.DWORD), ("th32ThreadID", w.DWORD),
                ("th32OwnerProcessID", w.DWORD), ("tpBasePri", ctypes.c_long),
                ("tpDeltaPri", ctypes.c_long), ("dwFlags", w.DWORD)]


def thread_ids(pid):
    snap = _k.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    te = _TE32()
    te.dwSize = ctypes.sizeof(te)
    out = []
    if _k.Thread32First(snap, ctypes.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                out.append(te.th32ThreadID)
            if not _k.Thread32Next(snap, ctypes.byref(te)):
                break
    _k.CloseHandle(snap)
    return out


def _context(tid, flags=WOW64_CONTEXT_CONTROL):
    """Suspend a WOW64 thread, grab its context, resume. Returns (eip, esp)."""
    h = _k.OpenThread(THREAD_ALL_ACCESS, False, tid)
    if not h:
        return None, None
    if _k.Wow64SuspendThread(h) == 0xFFFFFFFF:
        _k.CloseHandle(h)
        return None, None
    ctx = ctypes.create_string_buffer(1400)
    struct.pack_into("<I", ctx, 0, flags)
    ok = _k.Wow64GetThreadContext(h, ctx)
    eip = struct.unpack_from("<I", ctx, CTX_EIP_OFF)[0] if ok else None
    esp = struct.unpack_from("<I", ctx, CTX_ESP_OFF)[0] if ok else None
    _k.ResumeThread(h)
    _k.CloseHandle(h)
    return eip, esp


def label(addr):
    if MODULE_LO <= addr < MODULE_HI:
        return f"g_SilentHill.sgl+0x{addr - IMAGE_BASE:06X}"
    return f"0x{addr:08X} (other module)"


def do_sample(pid, n):
    tids = thread_ids(pid)
    print(f"{len(tids)} threads in pid {pid}; sampling {n} rounds\n")
    per_thread = collections.defaultdict(collections.Counter)
    for _ in range(n):
        for tid in tids:
            eip, _ = _context(tid)
            if eip:
                per_thread[tid][eip] += 1
        time.sleep(0.002)
    ranked = sorted(per_thread.items(), key=lambda kv: -sum(kv[1].values()))
    print("=== per-thread hot spots (most active first) ===")
    for tid, cc in ranked[:12]:
        total = sum(cc.values())
        in_mod = sum(c for a, c in cc.items() if MODULE_LO <= a < MODULE_HI)
        print(f"  tid {tid:<6} samples={total:<5} in-module={in_mod}")
        for a, c in cc.most_common(3):
            print(f"      {c:5d}  {label(a)}")


def do_stack(pid, tid, rounds):
    p = Proc(pid)
    if tid is None:
        # busiest thread = the one with most in-module samples
        tids = thread_ids(pid)
        best, best_score = None, -1
        for t in tids:
            score = 0
            for _ in range(20):
                eip, _ = _context(t)
                if eip and MODULE_LO <= eip < MODULE_HI:
                    score += 1
                time.sleep(0.001)
            if score > best_score:
                best, best_score = t, score
        tid = best
        print(f"auto-selected tid {tid}\n")

    chains = collections.Counter()
    for _ in range(rounds):
        eip, esp = _context(tid, 0x00010007)  # CONTEXT_FULL
        if not esp:
            continue
        blob = p.read(esp, 0x3000)
        if not blob:
            continue
        frames = []
        for off in range(0, len(blob) - 4, 4):
            v = struct.unpack_from("<I", blob, off)[0]
            if MODULE_LO <= v < MODULE_HI:
                pre = p.read(v - 5, 5)
                # keep values that look like return addresses (preceded by a call)
                if pre and (pre[0] == 0xE8 or pre[2] == 0xFF or pre[3] == 0xFF):
                    frames.append(v)
        chains[tuple(frames[:14])] += 1
        time.sleep(0.05)

    print("Game-module return addresses on the stack (most common chains):\n")
    for chain, c in chains.most_common(3):
        print(f"--- seen {c}x ---")
        for f in chain:
            print(f"   {label(f)}   (VA 0x{f:08X})")
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pid", type=int)
    ap.add_argument("--tid", type=int, help="thread to walk (default: busiest)")
    ap.add_argument("--sample", action="store_true", help="histogram EIP across all threads")
    ap.add_argument("--stack", action="store_true", help="walk a thread's stack")
    ap.add_argument("--rounds", type=int, default=250)
    args = ap.parse_args()

    pid = args.pid or find_pid()
    if not pid:
        sys.exit("ERROR: game not running")

    if args.sample:
        do_sample(pid, args.rounds)
    elif args.stack:
        do_stack(pid, args.tid, min(args.rounds, 20))
    else:
        ap.error("choose --sample or --stack")


if __name__ == "__main__":
    main()
