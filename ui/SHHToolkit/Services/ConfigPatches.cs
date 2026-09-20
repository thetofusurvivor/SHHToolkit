using System.IO;

namespace SHHToolkit.Services;

/// <summary>
/// Changes that live in the game's own text config, not in the binary. Each one is
/// written as a marked block so it can be removed again exactly.
/// </summary>
public abstract class ConfigPatch(string name, string description)
{
    public string Name { get; } = name;
    public string Description { get; } = description;
    public string? Summary { get; init; }
    public string? Note { get; init; }

    public abstract string FilePath(string modulePath);
    public abstract bool IsApplied(string modulePath);
    public abstract void Apply(string modulePath, bool restore);

    public PatchState Read(string modulePath)
    {
        try
        {
            if (!File.Exists(FilePath(modulePath))) return PatchState.Unknown;
            return IsApplied(modulePath) ? PatchState.Patched : PatchState.Stock;
        }
        catch (IOException) { return PatchState.Unknown; }
    }

    protected static void EnsureBackup(string path)
    {
        var backup = path + ".orig";
        if (!File.Exists(backup)) File.Copy(path, backup);
    }

    protected const string Begin = "### [SHH Toolkit] ";
    protected const string End = "### [SHH Toolkit] end ";
}

/// <summary>allowgameskipmovie: lets Esc skip the pre-rendered (Bink) cutscenes.</summary>
public sealed class CutsceneSkipPatch() : ConfigPatch(
    "Skippable pre-rendered cutscenes",
    "The game ships with movie skipping disabled. This turns it on, so Esc skips the "
    + "pre-rendered cutscenes (roughly 9 minutes of them). In-engine scenes cannot be skipped.")
{
    private const string Key = "allowgameskipmovie";

    public override string FilePath(string modulePath) =>
        Path.Combine(GameLocator.EngineDir(modulePath), "default_pc.cfg");

    public override bool IsApplied(string modulePath) =>
        File.ReadLines(FilePath(modulePath))
            .Any(l => l.TrimStart().StartsWith(Key, StringComparison.OrdinalIgnoreCase)
                      && l.Contains('1'));

    public override void Apply(string modulePath, bool restore)
    {
        var path = FilePath(modulePath);
        EnsureBackup(path);
        var text = File.ReadAllText(path);
        var eol = text.Contains("\r\n") ? "\r\n" : "\n";
        var lines = text.Split(eol).ToList();
        lines.RemoveAll(l => l.TrimStart().StartsWith(Key, StringComparison.OrdinalIgnoreCase));
        if (!restore)
        {
            var insert = lines.FindLastIndex(l => l.Contains('=')) + 1;
            lines.Insert(Math.Max(insert, 0), Key + "\t= 1");
        }
        File.WriteAllText(path, string.Join(eol, lines));
    }
}

/// <summary>Mouse bindings: Esc on the side button, weapon cycling on the wheel click.</summary>
public sealed class MouseBindsPatch() : ConfigPatch(
    "Mouse: Esc on the side button, weapons on the wheel click",
    "Adds Esc (skip movie / pause / back) on the thumb button, and weapon cycling on the "
    + "wheel click. \"Look at\" moves off the wheel click to the L key so one press does one thing.")
{
    private const string Tag = "mouse-binds";
    private static readonly string BlockBegin = Begin + Tag;
    private static readonly string BlockEnd = End + Tag;

    // The engine reads the mouse as DirectInput c_dfDIMouse: 4 buttons only -
    // BUTTON_0 left, BUTTON_1 right, BUTTON_2 wheel click, BUTTON_3 first side button.
    // COMMAND_WEAPON_NEXT/PREV exist but the PC build never queries them; the commands
    // that actually cycle weapons are EXT_5 ([) and EXT_6 (]).
    private static readonly string[] Lines =
    [
        "addbind 0 COMMAND_GAME_START     MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 0 COMMAND_SKIP_CUTSCENE  MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 0 COMMAND_UI_START       MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 0 COMMAND_UI_BACK        MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 1 COMMAND_GAME_START     MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 1 COMMAND_SKIP_CUTSCENE  MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 1 COMMAND_UI_START       MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 1 COMMAND_UI_BACK        MOUSE      0 BUTTON_3        -1.0 1.0 1.0",
        "addbind 0 COMMAND_EXT_6          MOUSE      0 BUTTON_2        -1.0 1.0 1.0",
        "addbind 1 COMMAND_EXT_6          MOUSE      0 BUTTON_2        -1.0 1.0 1.0",
        "setbind 0 COMMAND_RIGHT_THUMBSTICK_BUTTON KEYBOARD 0 KEY_L    -1.0 1.0 1.0",
    ];

    public override string FilePath(string modulePath) =>
        Path.Combine(GameLocator.EngineDir(modulePath), "binds_pc_mjs.cfg");

    public override bool IsApplied(string modulePath) =>
        File.ReadAllText(FilePath(modulePath)).Contains(BlockBegin);

    public override void Apply(string modulePath, bool restore)
    {
        var path = FilePath(modulePath);
        EnsureBackup(path);
        var text = File.ReadAllText(path);
        var eol = text.Contains("\r\n") ? "\r\n" : "\n";

        // strip any previous block, and un-comment whatever it had disabled
        var kept = new List<string>();
        var inBlock = false;
        foreach (var line in text.Split(eol))
        {
            if (line.StartsWith(BlockBegin)) { inBlock = true; continue; }
            if (line.StartsWith(BlockEnd)) { inBlock = false; continue; }
            if (inBlock) continue;
            kept.Add(line.StartsWith("#[SHH] ") ? line["#[SHH] ".Length..] : line);
        }

        if (!restore)
        {
            // the wheel click ships as "look at"; disable that line, keep it recoverable
            for (var i = 0; i < kept.Count; i++)
            {
                var l = kept[i];
                if (l.StartsWith("setbind 0 COMMAND_RIGHT_THUMBSTICK_BUTTON") && l.Contains("BUTTON_2"))
                    kept[i] = "#[SHH] " + l;
            }
            kept.Add(BlockBegin);
            kept.AddRange(Lines);
            kept.Add(BlockEnd);
        }

        File.WriteAllText(path, string.Join(eol, kept).TrimEnd('\r', '\n') + eol);
    }
}
