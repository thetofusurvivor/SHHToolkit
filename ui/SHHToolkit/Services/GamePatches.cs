using System.IO;

namespace SHHToolkit.Services;

/// <summary>
/// The binary patches, all verified against g_SilentHill.sgl build v6.30 (#640742).
/// Offsets are file offsets: the module loads at 0x10000000 and these sections map 1:1,
/// so file offset = VA - 0x10000000.
/// </summary>
public static class GamePatches
{
    private const uint Base = 0x10000000;

    private static byte[] H(string hex) => Convert.FromHexString(hex.Replace(" ", ""));

    // ---------------------------------------------------------------- borderless
    public static readonly BinaryPatch Borderless = new(
        "Borderless windowed",
        "Stops the game minimising whenever you alt-tab, by having it create a frameless "
        + "window that covers the monitor. Exclusive fullscreen is untouched.",
        new PatchSite(0x00BA43D5, H("0000cf00"), H("00000080"),
            "CreateWindowExA style: WS_OVERLAPPEDWINDOW -> WS_POPUP"),
        new PatchSite(0x00BA3CC3, H("0000ca86"), H("00000080"),
            "AdjustWindowRect style, so no space is reserved for a frame")
    )
    {
        Summary = "No minimising when you alt-tab",
        Note = "Needs FullScreen=false and your monitor's resolution in Engine\\vars_pc.cfg." };

    // --------------------------------------------------------------- crash guard
    private const uint GuardSite = 0x10554AAA;   // mov ecx,[eax+0x340] / mov eax,[edi+0x54] / mov edx,[ecx]
    private const uint GuardBack = 0x10554AB5;   // back into the original code
    private const uint GuardBail = 0x10554AC8;   // the function's own early exit
    private const uint GuardCave = 0x10D71500;   // unused 0xCC padding
    private const uint IatIsBadReadPtr = 0x117EEA7C;
    private const uint RdataLo = 0x10F7A000, RdataHi = 0x111BF7F8;

    public static readonly BinaryPatch CrashGuard = new(
        "Crash guard: flashlight re-attach",
        "Guards a crash during level loads. The game re-attaches Alex's flashlight to another "
        + "object's bone and, intermittently, that object is not a finished character: the "
        + "pointer it reads holds text instead. Seen four times, identical every time.",
        new PatchSite(GuardSite - Base, H("8b8840030000" + "8b4754" + "8b11"), BuildGuardJump(),
            "jump to the guard stub"),
        new PatchSite(GuardCave - Base, Enumerable.Repeat((byte)0xCC, BuildGuardStub().Length).ToArray(),
            BuildGuardStub(), "the guard stub itself")
    )
    { Summary = "Stops a crash that hits during level loads" };

    private static byte[] BuildGuardJump()
    {
        var jump = new List<byte> { 0xE9 };
        jump.AddRange(BitConverter.GetBytes((int)(GuardCave - (GuardSite + 5))));
        while (jump.Count < 11) jump.Add(0x90);       // pad to the length displaced
        return jump.ToArray();
    }

    /// <summary>
    /// if (IsBadReadPtr(ptr,4) || [ptr] is not a vtable in .rdata) take the function's
    /// NULL path; otherwise run exactly the instructions the jump displaced.
    /// </summary>
    private static byte[] BuildGuardStub()
    {
        var c = new List<byte>();
        void Emit(params byte[] b) => c.AddRange(b);
        void EmitU32(uint v) => c.AddRange(BitConverter.GetBytes(v));
        void EmitI32(int v) => c.AddRange(BitConverter.GetBytes(v));

        Emit(H("8b8840030000"));                       // mov ecx,[eax+0x340]
        Emit(0x51, 0x6A, 0x04, 0x51);                  // push ecx / push 4 / push ecx
        Emit(0xFF, 0x15); EmitU32(IatIsBadReadPtr);    // call [IsBadReadPtr]
        Emit(0x59, 0x85, 0xC0);                        // pop ecx / test eax,eax
        var j1 = c.Count; Emit(0x0F, 0x85, 0, 0, 0, 0);          // jnz bail
        Emit(0x8B, 0x11);                              // mov edx,[ecx]
        Emit(0x81, 0xFA); EmitU32(RdataLo);            // cmp edx,.rdata lo
        var j2 = c.Count; Emit(0x0F, 0x82, 0, 0, 0, 0);          // jb bail
        Emit(0x81, 0xFA); EmitU32(RdataHi);            // cmp edx,.rdata hi
        var j3 = c.Count; Emit(0x0F, 0x83, 0, 0, 0, 0);          // jae bail
        Emit(0x8B, 0x47, 0x54);                        // mov eax,[edi+0x54]
        Emit(0xE9); EmitI32((int)(GuardBack - (GuardCave + (uint)c.Count + 4)));   // jmp back
        var bail = c.Count;
        Emit(0x83, 0xC4, 0x04);                        // add esp,4  (drop the lookup argument)
        Emit(0xE9); EmitI32((int)(GuardBail - (GuardCave + (uint)c.Count + 4)));   // jmp exit

        foreach (var at in new[] { j1, j2, j3 })
        {
            var rel = BitConverter.GetBytes(bail - (at + 6));
            for (var i = 0; i < 4; i++) c[at + 2 + i] = rel[i];
        }
        return c.ToArray();
    }

    // ------------------------------------------------------------------ FPS cap
    public static class FpsCap
    {
        public const long Offset = 0x0108E804;          // a lone float32 in .rdata, one xref
        public static readonly byte[] Stock = H("184b0542");   // 33.323334 ms -> 30.009 FPS
        public const double StockFps = 30.009;

        /// <summary>Current cap in FPS, 0 when uncapped, null when unreadable/foreign.</summary>
        public static double? Read(string modulePath)
        {
            try
            {
                using var f = File.OpenRead(modulePath);
                var buf = new byte[4];
                f.Seek(Offset, SeekOrigin.Begin);
                if (f.Read(buf, 0, 4) != 4) return null;
                var ms = BitConverter.ToSingle(buf);
                if (ms == 0) return 0;
                if (ms is < 0 or > 1000) return null;
                return Math.Round(1000.0 / ms, 2);
            }
            catch (IOException) { return null; }
        }

        public static bool IsStock(string modulePath)
        {
            using var f = File.OpenRead(modulePath);
            var buf = new byte[4];
            f.Seek(Offset, SeekOrigin.Begin);
            return f.Read(buf, 0, 4) == 4 && buf.AsSpan().SequenceEqual(Stock);
        }

        /// <param name="fps">Target cap, or 0 to remove the engine limiter.</param>
        public static void Write(string modulePath, double fps)
        {
            if (Read(modulePath) is null)
                throw new InvalidOperationException(
                    "The frame-time constant is not what this build has, so nothing was written.");
            if (!BinaryPatch.HasBackup(modulePath)) File.Copy(modulePath, BinaryPatch.BackupPath(modulePath));

            var bytes = fps <= 0 ? BitConverter.GetBytes(0f) : BitConverter.GetBytes((float)(1000.0 / fps));
            using var f = new FileStream(modulePath, FileMode.Open, FileAccess.ReadWrite, FileShare.Read);
            f.Seek(Offset, SeekOrigin.Begin);
            f.Write(bytes);
            f.Flush(true);
        }

        public static void Restore(string modulePath)
        {
            using var f = new FileStream(modulePath, FileMode.Open, FileAccess.ReadWrite, FileShare.Read);
            f.Seek(Offset, SeekOrigin.Begin);
            f.Write(Stock);
            f.Flush(true);
        }
    }

    public static IReadOnlyList<BinaryPatch> All => new[] { Borderless, CrashGuard };
}
