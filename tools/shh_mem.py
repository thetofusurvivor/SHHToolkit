"""
Shared runtime-inspection helpers for Silent Hill: Homecoming (PC).

g_SilentHill.sgl is a PE32 DLL with DllCharacteristics = 0, i.e. no ASLR, so it
always loads at its preferred base 0x10000000. That means every address below is
a hard constant at runtime - no rebasing needed.

All addresses verified against build v6.30 (#640742),
md5 2af20d3f0b1d3902135a044966859d39.
"""

import ctypes
import struct

# --- known runtime addresses (build v6.30) ---------------------------------
IMAGE_BASE = 0x10000000

# Root pointer used all over the engine. The settings object that backs
# Engine\vars_pc.cfg is reached as:  *(*(*(0x111D2460) + 0x38) + 8)
PTR_ROOT = 0x111D2460

# Renderer/stats object:  *(*(0x115890EC) + 4)
PTR_STATS = 0x115890EC
STATS_FPS = 0x32C          # float, averaged frame rate (limited)
STATS_FPS_NOVSYNC = 0x330  # float, averaged frame rate (raw)

# Incremented once per game tick in FUN_101264F0. Sampling this against a wall
# clock is the ONLY frame-rate measurement here that proved reliable - the
# STATS_FPS floats go stale whenever the game is idle or unfocused.
FRAME_COUNTER = 0x111C14FC

# The hard-coded frame limiter constant (float32, milliseconds per frame).
# Read by exactly one instruction: fld dword ptr [0x1108E804] in FUN_10A4CC90.
LIMITER_MS = 0x1108E804

# Settings-object field offsets, recovered by parsing the cvar registration
# function FUN_10A27970. See cvars.json for the full map.
CV_VSYNC = 0xE2            # bool
CV_FPS_LIMIT = 0xE4        # int   (registered INT_MIN..INT_MAX; never read by render loop)
CV_MAX_FPS_LIMIT = 0xE8    # int   (ditto)
CV_FPS_OVERLAY = 0x50      # bool  ("fps" cvar - draws the FPS text)
CV_SCREEN_W = 0x1FC        # int
CV_SCREEN_H = 0x200        # int
CV_SCREEN_REFRESH = 0x204  # int   (only feeds the D3D9 display mode)
CV_FULLSCREEN = 0x208      # bool

_k = ctypes.windll.kernel32
PROCESS_ALL_ACCESS = 0x1F0FFF


class Proc:
    """Minimal read/write access to the running game process."""

    def __init__(self, pid):
        self.h = _k.OpenProcess(PROCESS_ALL_ACCESS, False, int(pid))
        if not self.h:
            raise OSError(f"OpenProcess({pid}) failed: {ctypes.GetLastError()} "
                          f"(is the game still running?)")

    # -- raw ---------------------------------------------------------------
    def read(self, addr, n):
        buf = ctypes.create_string_buffer(n)
        got = ctypes.c_size_t(0)
        ok = _k.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, n, ctypes.byref(got))
        return buf.raw if ok and got.value == n else None

    def write(self, addr, data):
        """Write bytes, temporarily making the page writable (.rdata is RO)."""
        old = ctypes.c_ulong(0)
        _k.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(data), 0x40, ctypes.byref(old))
        got = ctypes.c_size_t(0)
        ok = _k.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(got))
        _k.VirtualProtectEx(self.h, ctypes.c_void_p(addr), len(data), old, ctypes.byref(old))
        return bool(ok) and got.value == len(data)

    # -- typed -------------------------------------------------------------
    def u32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<I", b)[0] if b else None

    def i32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<i", b)[0] if b else None

    def f32(self, addr):
        b = self.read(addr, 4)
        return struct.unpack("<f", b)[0] if b else None

    def u8(self, addr):
        b = self.read(addr, 1)
        return b[0] if b else None

    def set_f32(self, addr, value):
        return self.write(addr, struct.pack("<f", value))

    # -- engine objects ----------------------------------------------------
    def verify_base(self):
        """Confirm the module really is at 0x10000000 before trusting anything."""
        return self.read(IMAGE_BASE, 2) == b"MZ"

    def settings(self):
        a = self.u32(PTR_ROOT)
        if not a:
            return None
        b = self.u32(a + 0x38)
        if not b:
            return None
        return self.u32(b + 8)

    def stats(self):
        p = self.u32(PTR_STATS)
        return self.u32(p + 4) if p else None

    def limiter_ms(self):
        return self.f32(LIMITER_MS)

    def set_limiter_fps(self, fps):
        """Live-patch the frame cap. fps<=0 means uncapped."""
        return self.set_f32(LIMITER_MS, 0.0 if fps <= 0 else 1000.0 / fps)


def find_pid(name="SilentHill"):
    """Return the game's pid via tasklist, or None."""
    import subprocess
    try:
        out = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {name}.exe", "/FO", "CSV", "/NH"],
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
