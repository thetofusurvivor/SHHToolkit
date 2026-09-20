using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace SHHToolkit.Services;

/// <summary>
/// The practice checkpoint key. This one is NOT a file patch: it writes a small stub into
/// the running game and is gone when the game exits.
///
/// The game's own `SaveCheckpoint` (0x10991560 on the manager at [0x116C1020]) sets the
/// checkpoint it restores you to. It is not a disk save - writing a real save needs the
/// save menu's context and crashes when called during play.
/// </summary>
public static class RuntimeHook
{
    private const uint Hook = 0x10A4CC90;     // the frame limiter: runs once per frame
    private const uint Cave = 0x10D71600;     // unused 0xCC padding in .text
    private const uint DisplacedCall = 0x10007095;
    private const uint IatGetAsyncKeyState = 0x117EEF30;
    private const uint Mgr = 0x116C1020;
    private const uint SaveCheckpoint = 0x10991560;
    private const int StubMax = 160;
    private const int HookLen = 9;            // push ebx/ebp/esi/edi + call

    private static readonly byte[] HookOrig = Convert.FromHexString("5355565" + "7e8fca35bff");

    public sealed record Status(bool Installed, uint Frames, uint Presses, uint Checkpoints);

    public static Process? FindGame() => Process.GetProcessesByName("SilentHill").FirstOrDefault();

    public static bool IsGameRunning() => FindGame() is not null;

    public static Status Read()
    {
        var proc = FindGame();
        if (proc is null) return new Status(false, 0, 0, 0);
        using var h = Open(proc);
        if (h.IsInvalid) return new Status(false, 0, 0, 0);
        var site = ReadMem(h, Hook, 5);
        if (!site.AsSpan().SequenceEqual(JumpToCave())) return new Status(false, 0, 0, 0);
        var state = BitConverter.ToUInt32(ReadMem(h, Cave + 4, 4));   // the stub's own "inc [frames]" operand
        var c = ReadMem(h, state, 16);
        return new Status(true, BitConverter.ToUInt32(c, 0), BitConverter.ToUInt32(c, 4), BitConverter.ToUInt32(c, 8));
    }

    public static void Install(ushort virtualKey)
    {
        var proc = FindGame() ?? throw new InvalidOperationException("The game is not running.");
        using var h = Open(proc);
        if (h.IsInvalid) throw new InvalidOperationException("Could not open the game process.");

        var site = ReadMem(h, Hook, HookLen);
        var installed = ReadMem(h, Hook, 5).AsSpan().SequenceEqual(JumpToCave());
        if (!installed && !site.AsSpan().SequenceEqual(HookOrig))
            throw new InvalidOperationException(
                "The hook site is not this build's frame limiter, so nothing was written.");
        if (!installed && !ReadMem(h, Cave, StubMax).All(b => b == 0xCC))
            throw new InvalidOperationException("The code cave is not empty, so nothing was written.");

        var state = VirtualAllocEx(h, IntPtr.Zero, 0x1000, 0x3000, 0x04);   // COMMIT|RESERVE, RW
        if (state == IntPtr.Zero) throw new InvalidOperationException("Could not allocate memory in the game.");

        var stub = BuildStub((uint)state.ToInt64(), virtualKey);
        var padded = stub.Concat(Enumerable.Repeat((byte)0xCC, StubMax - stub.Length)).ToArray();

        WithThreadsSuspended(proc, () =>
        {
            WriteMem(h, Cave, padded);          // stub first, so the jump never lands on padding
            WriteMem(h, Hook, JumpToCave());
            FlushInstructionCache(h, (IntPtr)Cave, StubMax);
            FlushInstructionCache(h, (IntPtr)Hook, 16);
        });

        if (!ReadMem(h, Cave, stub.Length).AsSpan().SequenceEqual(stub))
            throw new InvalidOperationException("Verification failed - restart the game before trying again.");
    }

    public static void Remove()
    {
        var proc = FindGame() ?? throw new InvalidOperationException("The game is not running.");
        using var h = Open(proc);
        if (!ReadMem(h, Hook, 5).AsSpan().SequenceEqual(JumpToCave())) return;
        WithThreadsSuspended(proc, () =>
        {
            WriteMem(h, Hook, HookOrig);
            WriteMem(h, Cave, Enumerable.Repeat((byte)0xCC, StubMax).ToArray());
            FlushInstructionCache(h, (IntPtr)Hook, 16);
            FlushInstructionCache(h, (IntPtr)Cave, StubMax);
        });
    }

    private static byte[] JumpToCave()
    {
        var b = new List<byte> { 0xE9 };
        b.AddRange(BitConverter.GetBytes((int)(Cave - (Hook + 5))));
        return b.ToArray();
    }

    /// <summary>state page: +0 frames, +4 presses, +8 checkpoints, +12 previous key state.</summary>
    private static byte[] BuildStub(uint state, ushort vk)
    {
        var c = new List<byte>();
        void Emit(params byte[] b) => c.AddRange(b);
        void EmitU32(uint v) => c.AddRange(BitConverter.GetBytes(v));

        Emit(0x60, 0x9C);                                   // pushad / pushfd
        Emit(0xFF, 0x05); EmitU32(state);                   // inc [frames]
        Emit(0x6A, (byte)vk);
        Emit(0xFF, 0x15); EmitU32(IatGetAsyncKeyState);     // GetAsyncKeyState(vk)
        Emit(0xF6, 0xC4, 0x80);                             // test ah,0x80  (key down?)
        var jUp = c.Count; Emit(0x74, 0);
        Emit(0x83, 0x3D); EmitU32(state + 12); Emit(0x00);  // already held?
        var jHeld = c.Count; Emit(0x75, 0);
        Emit(0xC7, 0x05); EmitU32(state + 12); EmitU32(1);  // prev = 1
        Emit(0xFF, 0x05); EmitU32(state + 4);               // inc [presses]
        Emit(0x8B, 0x0D); EmitU32(Mgr);                     // ecx = [manager]
        Emit(0x85, 0xC9);
        var jNoMgr = c.Count; Emit(0x74, 0);
        Emit(0xE8); c.AddRange(BitConverter.GetBytes((int)(SaveCheckpoint - (Cave + (uint)c.Count + 4))));
        Emit(0xFF, 0x05); EmitU32(state + 8);               // inc [checkpoints]
        var jDone = c.Count; Emit(0xEB, 0);
        var up = c.Count;
        Emit(0xC7, 0x05); EmitU32(state + 12); EmitU32(0);  // prev = 0
        var done = c.Count;
        foreach (var (at, tgt) in new[] { (jUp, up), (jHeld, done), (jNoMgr, done), (jDone, done) })
            c[at + 1] = (byte)(tgt - (at + 2));
        Emit(0x9D, 0x61);                                   // popfd / popad
        Emit(0x53, 0x55, 0x56, 0x57);                       // the displaced pushes
        Emit(0xE8); c.AddRange(BitConverter.GetBytes((int)(DisplacedCall - (Cave + (uint)c.Count + 4))));
        Emit(0xE9); c.AddRange(BitConverter.GetBytes((int)(Hook + HookLen - (Cave + (uint)c.Count + 4))));
        if (c.Count > StubMax) throw new InvalidOperationException("stub too large");
        return c.ToArray();
    }

    /// <summary>The hook site executes every frame, so nothing runs while it is rewritten.</summary>
    /// <summary>Shared with the other runtime services: stop the game, swap bytes, resume.</summary>
    internal static void WithGameSuspended(Process proc, Action write) => WithThreadsSuspended(proc, write);

    private static void WithThreadsSuspended(Process proc, Action write)
    {
        var handles = new List<IntPtr>();
        foreach (ProcessThread t in proc.Threads)
        {
            var th = OpenThread(0x0002, false, (uint)t.Id);   // THREAD_SUSPEND_RESUME
            if (th == IntPtr.Zero) continue;
            if (SuspendThread(th) == unchecked((uint)-1)) { CloseHandle(th); continue; }
            handles.Add(th);
        }
        try { write(); }
        finally
        {
            foreach (var th in handles) { ResumeThread(th); CloseHandle(th); }
        }
    }

    // ------------------------------------------------------------------ interop
    private static SafeProcessHandle Open(Process p) =>
        new(OpenProcess(0x1F0FFF, false, (uint)p.Id), true);   // PROCESS_ALL_ACCESS

    /// <summary>Shared with the other runtime services so there is one interop layer.</summary>
    internal static SafeProcessHandle OpenProcessHandle(Process p) => Open(p);

    internal static byte[] ReadMemory(SafeProcessHandle h, uint addr, int len) => ReadMem(h, addr, len);

    internal static void WriteMemory(SafeProcessHandle h, uint addr, byte[] data) => WriteMem(h, addr, data);

    private static byte[] ReadMem(SafeProcessHandle h, uint addr, int len)
    {
        var buf = new byte[len];
        ReadProcessMemory(h, (IntPtr)addr, buf, len, out _);
        return buf;
    }

    private static void WriteMem(SafeProcessHandle h, uint addr, byte[] data)
    {
        VirtualProtectEx(h, (IntPtr)addr, (UIntPtr)data.Length, 0x40, out var old);   // RWX
        if (!WriteProcessMemory(h, (IntPtr)addr, data, data.Length, out _))
            throw new InvalidOperationException("Writing to the game's memory failed.");
        VirtualProtectEx(h, (IntPtr)addr, (UIntPtr)data.Length, old, out _);
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadProcessMemory(SafeProcessHandle h, IntPtr addr, byte[] buf, int size, out IntPtr read);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool WriteProcessMemory(SafeProcessHandle h, IntPtr addr, byte[] buf, int size, out IntPtr written);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool VirtualProtectEx(SafeProcessHandle h, IntPtr addr, UIntPtr size, uint prot, out uint old);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr VirtualAllocEx(SafeProcessHandle h, IntPtr addr, uint size, uint type, uint protect);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool FlushInstructionCache(SafeProcessHandle h, IntPtr addr, int size);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenThread(uint access, bool inherit, uint tid);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern uint SuspendThread(IntPtr h);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern int ResumeThread(IntPtr h);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr h);
}
