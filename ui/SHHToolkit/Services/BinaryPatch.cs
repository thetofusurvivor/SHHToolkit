using System.IO;

namespace SHHToolkit.Services;

public enum PatchState
{
    Stock,      // the game as shipped
    Patched,    // exactly this patch is in place
    Mixed,      // some sites patched, some not - repair by applying or restoring
    Unknown     // bytes belong to neither - a different build, or someone else's patch
}

/// <summary>One byte range this patch owns.</summary>
/// <param name="Offset">File offset (module VA minus 0x10000000).</param>
public sealed record PatchSite(long Offset, byte[] Stock, byte[] Patched, string Note)
{
    public int Length => Stock.Length;
}

/// <summary>
/// A set of byte edits applied to g_SilentHill.sgl as one unit. Every write is
/// guarded: a site must currently hold either its stock or its patched bytes,
/// so a different build or a foreign patch is never overwritten.
/// </summary>
public sealed class BinaryPatch(string name, string description, params PatchSite[] sites)
{
    public string Name { get; } = name;
    public string Description { get; } = description;
    public IReadOnlyList<PatchSite> Sites { get; } = sites;

    /// <summary>One line for the row. The full Description goes in the tooltip.</summary>
    public string? Summary { get; init; }

    /// <summary>A requirement the user must meet, appended to the tooltip.</summary>
    public string? Note { get; init; }

    public PatchState Read(string modulePath)
    {
        try
        {
            using var f = File.OpenRead(modulePath);
            bool anyStock = false, anyPatched = false;
            foreach (var site in Sites)
            {
                var cur = ReadAt(f, site.Offset, site.Length);
                if (cur.AsSpan().SequenceEqual(site.Stock)) anyStock = true;
                else if (cur.AsSpan().SequenceEqual(site.Patched)) anyPatched = true;
                else return PatchState.Unknown;
            }
            if (anyStock && anyPatched) return PatchState.Mixed;
            return anyPatched ? PatchState.Patched : PatchState.Stock;
        }
        catch (IOException)
        {
            return PatchState.Unknown;
        }
    }

    public void Apply(string modulePath, bool restore)
    {
        var state = Read(modulePath);
        if (state == PatchState.Unknown)
            throw new InvalidOperationException(
                "The bytes at this patch's offsets are not what this build has, so nothing was written. " +
                "This toolkit supports g_SilentHill.sgl from build v6.30 (#640742).");

        EnsureBackup(modulePath);

        using var f = new FileStream(modulePath, FileMode.Open, FileAccess.ReadWrite, FileShare.Read);
        // Order matters for the hook-style patches: write the stub before the jump
        // that reaches it, and remove the jump before the stub.
        var ordered = restore ? Sites.OrderBy(s => s.Length).ToList() : Sites.OrderByDescending(s => s.Length).ToList();
        foreach (var site in ordered)
        {
            f.Seek(site.Offset, SeekOrigin.Begin);
            f.Write(restore ? site.Stock : site.Patched);
        }
        f.Flush(true);
    }

    /// <summary>A single .orig copy of the untouched module, made before the first write.</summary>
    public static string BackupPath(string modulePath) => modulePath + ".orig";

    public static bool HasBackup(string modulePath) => File.Exists(BackupPath(modulePath));

    private static void EnsureBackup(string modulePath)
    {
        var backup = BackupPath(modulePath);
        if (!File.Exists(backup)) File.Copy(modulePath, backup);
    }

    private static byte[] ReadAt(FileStream f, long offset, int length)
    {
        var buf = new byte[length];
        f.Seek(offset, SeekOrigin.Begin);
        var got = 0;
        while (got < length)
        {
            var n = f.Read(buf, got, length - got);
            if (n <= 0) break;
            got += n;
        }
        return buf;
    }
}
