namespace SHHToolkit.Services;

/// <summary>
/// Makes Alex's health stop changing, for practising a fight without dying to it.
///
/// <para>The engine applies every health change - damage and healing alike - through one
/// instruction, found by putting a hardware write watchpoint on the health field and taking
/// hits until it tripped. Four hits, one address every time:</para>
///
/// <code>
/// 1031F105  movss xmm0, [esi+0x164]    ; current health
/// 1031F114  addsd xmm0, xmm2           ; += delta   (negative when damaged)
/// 1031F11C  movss [esi+0x164], xmm0    ; store      &lt;- this is what we remove
/// </code>
///
/// <para>Replacing that store with nops means health is read, adjusted and thrown away, so
/// the field keeps whatever value it had. This is runtime only: the eight bytes live in the
/// game's memory, nothing is written to disk, and closing the game undoes it.</para>
///
/// <para>Two honest limits. It blocks <em>healing</em> too, because that is the same
/// instruction. And it only guards this path: a scripted death or an instant-kill that sets
/// health directly, or trips a death flag elsewhere, would not be stopped by it.</para>
/// </summary>
public static class HealthLock
{
    private const uint Store = 0x1031F11C;
    private const uint HealthField = 0x164;
    private const uint MaxHealthField = 0x168;
    private const uint PlayerRoot = 0x1158982C;      // [[0x1158982C]+4] is the player

    private static readonly byte[] Original = Convert.FromHexString("f30f118664010000");
    private static readonly byte[] Removed = Enumerable.Repeat((byte)0x90, 8).ToArray();

    public static PatchState Read()
    {
        var proc = GameProcess.Find();
        if (proc is null) return PatchState.Unknown;
        try
        {
            using var h = GameProcess.Open(proc);
            var cur = GameProcess.Read(h, Store, Original.Length);
            if (cur.AsSpan().SequenceEqual(Original)) return PatchState.Stock;
            if (cur.AsSpan().SequenceEqual(Removed)) return PatchState.Patched;
            return PatchState.Unknown;
        }
        catch (Exception) { return PatchState.Unknown; }
    }

    public static void Set(bool locked)
    {
        var proc = GameProcess.Find()
                   ?? throw new InvalidOperationException("The game is not running.");
        using var h = GameProcess.Open(proc);
        var cur = GameProcess.Read(h, Store, Original.Length);
        if (!cur.AsSpan().SequenceEqual(Original) && !cur.AsSpan().SequenceEqual(Removed))
            throw new InvalidOperationException(
                "The bytes where the health store should be are not what this build has, "
                + "so nothing was written.");

        // The instruction only runs when something changes Alex's health, but suspending
        // first means it cannot be mid-instruction while the bytes are swapped.
        GameProcess.WithSuspended(proc, () =>
            GameProcess.Write(h, Store, locked ? Removed : Original));
    }

    /// <summary>"100 / 150", or null when it cannot be read.</summary>
    public static string? ReadHealth()
    {
        var proc = GameProcess.Find();
        if (proc is null) return null;
        try
        {
            using var h = GameProcess.Open(proc);
            var root = BitConverter.ToUInt32(GameProcess.Read(h, PlayerRoot, 4));
            if (root == 0) return null;
            var player = BitConverter.ToUInt32(GameProcess.Read(h, root + 4, 4));
            if (player == 0) return null;
            var hp = BitConverter.ToSingle(GameProcess.Read(h, player + HealthField, 4));
            var max = BitConverter.ToSingle(GameProcess.Read(h, player + MaxHealthField, 4));
            if (!float.IsFinite(hp) || !float.IsFinite(max) || max <= 0 || max > 10000) return null;
            return string.Format("{0:0.#} / {1:0.#} health", hp, max);
        }
        catch (Exception) { return null; }
    }
}
