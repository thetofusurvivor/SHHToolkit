using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

namespace SHHToolkit.Services;

/// <summary>
/// Finding the running game and reading or writing its memory. One interop layer, shared by
/// every runtime feature, so the P/Invoke declarations and the RWX dance live in one place.
/// </summary>
public static class GameProcess
{
    public static Process? Find() => Process.GetProcessesByName("SilentHill").FirstOrDefault();

    public static bool IsRunning() => Find() is not null;

    public static SafeProcessHandle Open(Process p) =>
        new(OpenProcess(0x1F0FFF, false, (uint)p.Id), true);   // PROCESS_ALL_ACCESS

    public static byte[] Read(SafeProcessHandle h, uint addr, int len)
    {
        var buf = new byte[len];
        ReadProcessMemory(h, (IntPtr)addr, buf, len, out _);
        return buf;
    }

    public static void Write(SafeProcessHandle h, uint addr, byte[] data)
    {
        VirtualProtectEx(h, (IntPtr)addr, (UIntPtr)data.Length, 0x40, out var old);   // RWX
        if (!WriteProcessMemory(h, (IntPtr)addr, data, data.Length, out _))
            throw new InvalidOperationException("Writing to the game's memory failed.");
        VirtualProtectEx(h, (IntPtr)addr, (UIntPtr)data.Length, old, out _);
        FlushInstructionCache(h, (IntPtr)addr, data.Length);
    }

    /// <summary>
    /// Stop every thread, run the write, resume. Used when swapping bytes the game may be
    /// executing, so it cannot be part-way through the instruction being replaced.
    /// </summary>
    public static void WithSuspended(Process proc, Action write)
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

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern IntPtr OpenProcess(uint access, bool inherit, uint pid);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool ReadProcessMemory(SafeProcessHandle h, IntPtr addr, byte[] buf, int size, out IntPtr read);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool WriteProcessMemory(SafeProcessHandle h, IntPtr addr, byte[] buf, int size, out IntPtr written);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool VirtualProtectEx(SafeProcessHandle h, IntPtr addr, UIntPtr size, uint prot, out uint old);

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
