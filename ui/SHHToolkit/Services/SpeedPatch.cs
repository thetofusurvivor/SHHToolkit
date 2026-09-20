using System.Diagnostics;
using System.IO;

namespace SHHToolkit.Services;

/// <summary>
/// Game speed multiplier, for practising a route without replaying every walk.
///
/// <para>The engine keeps its frame delta in one global (<c>0x116C7A14</c>) written once per
/// frame by the timer update. The patch redirects that single store through a stub that
/// scales the value first, so every system that advances by delta - movement, animation,
/// scripted sequences - runs faster together, rather than any one of them being nudged out
/// of step with the others.</para>
///
/// <para>Two things keep it inside sane bounds. The multiplier is clamped to
/// <see cref="MaxFactor"/>, past which collision starts being tunnelled through at this
/// engine's fixed step. And the stub clamps the scaled delta to <see cref="DefaultMaxDelta"/>
/// - tighter than the 0.08 s the engine's own tick already enforces - so a multiplied
/// loading hitch advances the world by less than the stock game's own worst frame does.</para>
///
/// <para>Pre-rendered movies are played by Bink on its own clock and are not affected. In-engine
/// scripted scenes run in the ordinary tick, so those do speed up.</para>
/// </summary>
public static class SpeedPatch
{
    private const uint Base = 0x10000000;
    private const uint DeltaTime = 0x116C7A14;          // the frame delta the whole engine reads

    private const long StoreOffset = 0x00A4E99C;        // movss [delta], xmm0
    private const long FactorOffset = 0x00D71300;       // our multiplier
    private const long MaxDeltaOffset = 0x00D71304;     // our delta ceiling
    private const long CodeOffset = 0x00D71310;         // the stub

    /// <summary>Above this the engine's collision starts letting Alex through geometry.</summary>
    public const float MaxFactor = 4.0f;
    public const float MinFactor = 1.0f;

    /// <summary>
    /// 50 ms. The engine's own tick already clamps delta at 0.08 s, so a ceiling above that
    /// would never fire; this is deliberately *tighter*, which means a multiplied loading
    /// hitch hands the physics a smaller step than the stock game's own worst case.
    /// </summary>
    public const float DefaultMaxDelta = 0.05f;

    private static byte[] H(string hex) => Convert.FromHexString(hex.Replace(" ", ""));

    private static readonly byte[] StockStore = H("f30f1105147a6c11");

    private static byte[] BuildJump()
    {
        var b = new List<byte> { 0xE9 };
        b.AddRange(BitConverter.GetBytes((int)(Base + CodeOffset - (Base + StoreOffset + 5))));
        while (b.Count < StockStore.Length) b.Add(0x90);
        return b.ToArray();
    }

    private static byte[] BuildStub()
    {
        var c = new List<byte>();
        c.AddRange(H("f30f5905")); c.AddRange(BitConverter.GetBytes((uint)(Base + FactorOffset)));    // mulss xmm0,[factor]
        c.AddRange(H("f30f5d05")); c.AddRange(BitConverter.GetBytes((uint)(Base + MaxDeltaOffset)));  // minss xmm0,[ceiling]
        c.AddRange(H("f30f1105")); c.AddRange(BitConverter.GetBytes(DeltaTime));                      // movss [delta],xmm0
        c.Add(0xE9);
        c.AddRange(BitConverter.GetBytes((int)(Base + StoreOffset + (uint)StockStore.Length
                                               - (Base + CodeOffset + (uint)c.Count + 4))));
        return c.ToArray();
    }

    private static readonly byte[] Stub = BuildStub();

    /// <summary>
    /// Only the store and the stub are verified bytes. The multiplier itself is deliberately
    /// not a patch site: it changes every time a different speed is chosen, and a site whose
    /// contents vary would make the whole patch read as Unknown.
    /// </summary>
    public static readonly BinaryPatch Hook = new(
        "Game speed multiplier",
        "Scales the engine's frame delta so the game runs faster, for practising a route without "
        + "replaying every walk. The stub also caps the scaled delta, so a loading hitch cannot "
        + "hand the physics an enormous step.",
        new PatchSite(StoreOffset, StockStore, BuildJump(), "the frame-delta store -> the stub"),
        new PatchSite(CodeOffset, Enumerable.Repeat((byte)0xCC, Stub.Length).ToArray(), Stub,
            "scale, clamp, store, return")
    );

    public static PatchState ReadState(string modulePath) => Hook.Read(modulePath);

    /// <summary>The multiplier in the file, or null when the patch is not applied.</summary>
    public static float? ReadFactor(string modulePath)
    {
        if (ReadState(modulePath) != PatchState.Patched) return null;
        try
        {
            using var f = File.OpenRead(modulePath);
            var buf = new byte[4];
            f.Seek(FactorOffset, SeekOrigin.Begin);
            if (f.Read(buf, 0, 4) != 4) return null;
            var v = BitConverter.ToSingle(buf);
            return float.IsFinite(v) && v is > 0 and <= 100 ? v : null;
        }
        catch (IOException) { return null; }
    }

    public static float Clamp(double factor) =>
        (float)Math.Clamp(factor, MinFactor, MaxFactor);

    /// <summary>
    /// Applies the hook if needed and sets the multiplier. A factor of 1 removes the patch
    /// outright rather than leaving an inert multiply in the frame loop.
    /// </summary>
    public static void Write(string modulePath, double factor)
    {
        var wanted = Clamp(factor);
        if (wanted <= MinFactor) { Restore(modulePath); return; }

        if (ReadState(modulePath) != PatchState.Patched) Hook.Apply(modulePath, restore: false);

        using var f = new FileStream(modulePath, FileMode.Open, FileAccess.ReadWrite, FileShare.Read);
        f.Seek(FactorOffset, SeekOrigin.Begin);
        f.Write(BitConverter.GetBytes(wanted));
        f.Write(BitConverter.GetBytes(DefaultMaxDelta));
        f.Flush(true);
    }

    public static void Restore(string modulePath)
    {
        if (ReadState(modulePath) == PatchState.Stock) return;
        Hook.Apply(modulePath, restore: true);
        using var f = new FileStream(modulePath, FileMode.Open, FileAccess.ReadWrite, FileShare.Read);
        f.Seek(FactorOffset, SeekOrigin.Begin);
        f.Write(Enumerable.Repeat((byte)0xCC, 8).ToArray());   // both floats back to padding
        f.Flush(true);
    }

    /// <summary>
    /// Pokes the multiplier into the running game so a change takes effect without a restart.
    /// Returns false when the game is not running or the stub is not loaded.
    /// </summary>
    public static bool TryWriteLive(double factor)
    {
        var proc = RuntimeHook.FindGame();
        if (proc is null) return false;
        try
        {
            using var h = RuntimeHook.OpenProcessHandle(proc);
            var stub = RuntimeHook.ReadMemory(h, (uint)(Base + CodeOffset), Stub.Length);
            if (!stub.AsSpan().SequenceEqual(Stub)) return false;    // patch not in this process
            RuntimeHook.WriteMemory(h, (uint)(Base + FactorOffset), BitConverter.GetBytes(Clamp(factor)));
            RuntimeHook.WriteMemory(h, (uint)(Base + MaxDeltaOffset), BitConverter.GetBytes(DefaultMaxDelta));
            return true;
        }
        catch (Exception) { return false; }
    }

    /// <summary>The multiplier the running game is actually using, if it can be read.</summary>
    public static float? ReadLive()
    {
        var proc = RuntimeHook.FindGame();
        if (proc is null) return null;
        try
        {
            using var h = RuntimeHook.OpenProcessHandle(proc);
            var v = BitConverter.ToSingle(RuntimeHook.ReadMemory(h, (uint)(Base + FactorOffset), 4));
            return float.IsFinite(v) && v is > 0 and <= 100 ? v : null;
        }
        catch (Exception) { return null; }
    }
}
