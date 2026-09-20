using System.IO;

namespace SHHToolkit.Services;

/// <summary>
/// Per-item unlocks. The game answers "is costume N unlocked?" from
/// <c>byte [profile + 0x230 + index]</c> via one accessor at 0x10A0BE10, called only by
/// the script lookup behind IsPyramidUnlocked / IsOrderlyUnlocked / ... (8 call sites).
///
/// That accessor is redirected to a stub holding a 6-byte table we own: a 1 forces the
/// costume on, a 0 falls through to the game's real answer. So unticking something never
/// takes away what you actually earned.
///
/// The Laser Gun and the "completed the game" flag are separate one-byte edits: at new
/// game the engine copies them from the profile only if they are set, and flipping those
/// jne into jmp copies them always.
/// </summary>
public static class UnlockPatch
{
    private const uint Base = 0x10000000;
    private const uint Accessor = 0x10A0BE10;
    private const uint Cave = 0x10D71700;          // free 0xCC padding, clear of the other stubs
    private const uint Table = Cave + 0x40;        // 6 bytes, one per costume index
    private const long AccessorOff = Accessor - Base;
    private const long CaveOff = Cave - Base;
    private const long TableOff = Table - Base;

    private const long UfoOff = 0x0094FE69;        // jne -> jmp: always copy Got_UFO (Laser Gun)
    private const long CompletedOff = 0x0094FDF3;  // jne -> jmp: always copy Completed_Game

    private static readonly byte[] AccessorStock =
        Convert.FromHexString("8b442404" + "8a84083002 0000".Replace(" ", "") + "c20400");
    private static readonly byte[] AccessorLegacy =        // the old all-or-nothing patch
        Convert.FromHexString("b001c20400" + "84083002 0000".Replace(" ", "") + "c20400");

    public static readonly string[] CostumeNames =
        ["Young Alex", "Sheriff", "Trucker", "Orderly", "Order Soldier", "Pyramid Head"];

    public sealed record State(bool[] Costumes, bool LaserGun, bool Completed, bool Readable);

    private static byte[] AccessorPatched()
    {
        var b = new List<byte> { 0xE9 };
        b.AddRange(BitConverter.GetBytes((int)(Cave - (Accessor + 5))));
        while (b.Count < AccessorStock.Length) b.Add(0x90);
        return b.ToArray();
    }

    /// <summary>
    /// eax = costume index (the stack argument), ecx = the profile (this).
    ///     if (table[index] != 0) return 1;
    ///     return byte [profile + index + 0x230];      // the game's own answer
    /// </summary>
    private static byte[] Stub()
    {
        var c = new List<byte>();
        c.AddRange(Convert.FromHexString("8b442404"));          // mov eax,[esp+4]      (index)
        c.AddRange([0x8A, 0x90]);                               // mov dl,[eax+Table]
        c.AddRange(BitConverter.GetBytes(Table));
        c.AddRange([0x84, 0xD2]);                               // test dl,dl
        c.AddRange([0x74, 0x05]);                               // jz  real
        c.AddRange([0xB0, 0x01]);                               // mov al,1
        c.AddRange(Convert.FromHexString("c20400"));            // ret 4
        c.AddRange(Convert.FromHexString("8a840830020000"));    // real: mov al,[eax+ecx+0x230]
        c.AddRange(Convert.FromHexString("c20400"));            // ret 4
        return c.ToArray();
    }

    public static State Read(string modulePath)
    {
        try
        {
            using var f = File.OpenRead(modulePath);
            var accessor = At(f, AccessorOff, AccessorStock.Length);
            var costumes = new bool[6];

            if (accessor.SequenceEqual(AccessorPatched()) && At(f, CaveOff, Stub().Length).SequenceEqual(Stub()))
            {
                var table = At(f, TableOff, 6);
                for (var i = 0; i < 6; i++) costumes[i] = table[i] != 0;
            }
            else if (accessor.SequenceEqual(AccessorLegacy))
            {
                for (var i = 0; i < 6; i++) costumes[i] = true;     // the old all-or-nothing patch
            }
            else if (!accessor.SequenceEqual(AccessorStock))
            {
                return new State(costumes, false, false, false);
            }

            return new State(costumes, At(f, UfoOff, 1)[0] == 0xEB, At(f, CompletedOff, 1)[0] == 0xEB, true);
        }
        catch (IOException)
        {
            return new State(new bool[6], false, false, false);
        }
    }

    public static void Write(string modulePath, bool[] costumes, bool laserGun, bool completed)
    {
        if (!Read(modulePath).Readable)
            throw new InvalidOperationException(
                "The unlock code in this file is not what this build has, so nothing was written.");
        if (!BinaryPatch.HasBackup(modulePath)) File.Copy(modulePath, BinaryPatch.BackupPath(modulePath));

        var anyCostume = costumes.Any(c => c);
        using var f = new FileStream(modulePath, FileMode.Open, FileAccess.ReadWrite, FileShare.Read);

        if (anyCostume)
        {
            Put(f, CaveOff, Stub());                                        // stub before the jump to it
            Put(f, TableOff, costumes.Select(c => (byte)(c ? 1 : 0)).ToArray());
            Put(f, AccessorOff, AccessorPatched());
        }
        else
        {
            Put(f, AccessorOff, AccessorStock);                             // jump first, then clear the stub
            Put(f, CaveOff, Enumerable.Repeat((byte)0xCC, Stub().Length).ToArray());
            Put(f, TableOff, Enumerable.Repeat((byte)0xCC, 6).ToArray());
        }

        Put(f, UfoOff, [laserGun ? (byte)0xEB : (byte)0x75]);
        Put(f, CompletedOff, [completed ? (byte)0xEB : (byte)0x75]);
        f.Flush(true);
    }

    private static byte[] At(FileStream f, long off, int len)
    {
        var buf = new byte[len];
        f.Seek(off, SeekOrigin.Begin);
        var got = 0;
        while (got < len)
        {
            var n = f.Read(buf, got, len - got);
            if (n <= 0) break;
            got += n;
        }
        return buf;
    }

    private static void Put(FileStream f, long off, byte[] data)
    {
        f.Seek(off, SeekOrigin.Begin);
        f.Write(data);
    }
}
