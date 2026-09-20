using System.IO;
using System.Text.RegularExpressions;
using Microsoft.Win32;

namespace SHHToolkit.Services;

/// <summary>Finds Bin\g_SilentHill.sgl, the module every patch applies to.</summary>
public static class GameLocator
{
    public const string ModuleName = "g_SilentHill.sgl";
    public const long ExpectedSize = 20959232;          // build v6.30 (#640742)

    private static readonly string RelPath =
        Path.Combine("steamapps", "common", "Silent Hill Homecoming", "Bin", ModuleName);

    /// <summary>Full path to the module, or null when it cannot be found.</summary>
    public static string? Find()
    {
        foreach (var lib in SteamLibraries())
        {
            var candidate = Path.Combine(lib, RelPath);
            if (File.Exists(candidate)) return candidate;
        }
        return null;
    }

    /// <summary>The game root (…\Silent Hill Homecoming) for a module path.</summary>
    public static string GameRoot(string modulePath) =>
        Path.GetFullPath(Path.Combine(Path.GetDirectoryName(modulePath)!, ".."));

    public static string EngineDir(string modulePath) =>
        Path.Combine(GameRoot(modulePath), "Engine");

    /// <summary>True when the file is the size this toolkit was built against.</summary>
    public static bool LooksLikeSupportedBuild(string modulePath)
    {
        try { return new FileInfo(modulePath).Length == ExpectedSize; }
        catch { return false; }
    }

    private static IEnumerable<string> SteamLibraries()
    {
        var roots = new List<string>();

        foreach (var (hive, key, name) in new[]
                 {
                     (Registry.CurrentUser, @"Software\Valve\Steam", "SteamPath"),
                     (Registry.LocalMachine, @"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                     (Registry.LocalMachine, @"SOFTWARE\Valve\Steam", "InstallPath"),
                 })
        {
            try
            {
                using var k = hive.OpenSubKey(key);
                if (k?.GetValue(name) is string p && p.Length > 0) roots.Add(p.Replace('/', '\\'));
            }
            catch { /* registry not readable - fall through to the fixed paths */ }
        }

        roots.Add(@"C:\Program Files (x86)\Steam");
        roots.Add(@"C:\Program Files\Steam");

        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        foreach (var root in roots)
        {
            if (!seen.Add(root) || !Directory.Exists(root)) continue;
            yield return root;

            // other drives are listed in libraryfolders.vdf
            var vdf = Path.Combine(root, "steamapps", "libraryfolders.vdf");
            if (!File.Exists(vdf)) continue;
            string text;
            try { text = File.ReadAllText(vdf); } catch { continue; }
            foreach (Match m in Regex.Matches(text, "\"path\"\\s+\"([^\"]+)\""))
            {
                var lib = m.Groups[1].Value.Replace("\\\\", "\\");
                if (seen.Add(lib) && Directory.Exists(lib)) yield return lib;
            }
        }
    }
}
