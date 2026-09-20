using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Controls.Primitives;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using SHHToolkit.Services;

namespace SHHToolkit;

public partial class MainWindow : Window
{
    private string? _module;
    private readonly List<FeatureRow> _fileRows = [];
    private readonly List<FeatureRow> _runtimeRows = [];
    private const ushort CheckpointKey = 0x74;   // F5

    private static readonly (string Label, double Fps)[] FpsChoices =
    [
        ("30 (stock)", 0), ("60", 60), ("75", 75), ("100", 100),
        ("120", 120), ("144", 144), ("165", 165), ("240", 240), ("Uncapped", -1)
    ];

    /// <summary>Stops at 4x: past that this engine's collision starts being tunnelled through.</summary>
    private static readonly (string Label, double Factor)[] SpeedChoices =
    [
        ("1x (off)", 1.0), ("1.25x", 1.25), ("1.5x", 1.5), ("2x", 2.0),
        ("2.5x", 2.5), ("3x", 3.0), ("4x (max)", 4.0)
    ];

    public MainWindow()
    {
        InitializeComponent();
        foreach (var c in FpsChoices) FpsCombo.Items.Add(c.Label);
        FpsCombo.SelectedIndex = 5;   // 144
        foreach (var c in SpeedChoices) SpeedCombo.Items.Add(c.Label);
        SpeedCombo.SelectedIndex = 0; // 1x

        LoadLogo();
        BuildRows();
        FilePatchList.ItemsSource = _fileRows;
        RuntimeList.ItemsSource = _runtimeRows;

        Log("Beta build. Keep the .orig backups, and report anything that looks wrong.");
        Locate(GameLocator.Find());

        var timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1.5) };
        timer.Tick += (_, _) => RefreshLive();
        timer.Start();
    }

    /// <summary>
    /// The header image is the game's own artwork, so it is not distributed with the source.
    /// When it is absent the header simply shows the wordmark, which is why this is a
    /// try/catch rather than a missing-file error.
    /// </summary>
    private void LoadLogo()
    {
        try
        {
            var image = new BitmapImage();
            image.BeginInit();
            image.UriSource = new Uri("pack://application:,,,/logo.png");
            image.CacheOption = BitmapCacheOption.OnLoad;
            image.EndInit();
            LogoImage.Source = image;
            LogoImage.Visibility = Visibility.Visible;
        }
        catch (Exception)
        {
            LogoImage.Visibility = Visibility.Collapsed;
        }
    }

    // ------------------------------------------------------------------ rows
    private void BuildRows()
    {
        foreach (var patch in GamePatches.All)
            _fileRows.Add(new FeatureRow
            {
                Name = patch.Name,
                Summary = patch.Summary ?? FirstSentence(patch.Description),
                Tooltip = Join(patch.Description, patch.Note),
                GetState = () => _module is null ? PatchState.Unknown : patch.Read(_module),
                Set = on => patch.Apply(_module!, !on)
            });

        var configs = new (ConfigPatch Patch, string Summary)[]
        {
            (new CutsceneSkipPatch(), "Esc skips the pre-rendered movies"),
            (new MouseBindsPatch(), "Esc on the thumb button, weapons on the wheel click")
        };
        foreach (var (patch, summary) in configs)
            _fileRows.Add(new FeatureRow
            {
                Name = patch.Name,
                Summary = summary,
                Tooltip = Join(patch.Description, patch.Note),
                GetState = () => _module is null ? PatchState.Unknown : patch.Read(_module),
                Set = on => patch.Apply(_module!, !on)
            });

        _runtimeRows.Add(new FeatureRow
        {
            Name = "Checkpoint key (state only)",
            Summary = "F5 snapshots health/ammo state - not your position",
            Tooltip = "Press F5 to run the engine's own SaveCheckpoint: it snapshots health, "
                    + "weapons, ammo and persistent data.\n\nIt does NOT record where you are "
                    + "standing - that code contains no position at all. On death the game returns "
                    + "you to the last checkpoint volume you walked through, not to where you "
                    + "pressed F5.\n\nIt is also not a save: nothing is written to disk, and the "
                    + "hook lives in the game's memory only, disappearing when it exits.",
            RequiresGameRunning = true,
            GetState = () => !RuntimeHook.IsGameRunning()
                ? PatchState.Unknown
                : RuntimeHook.Read().Installed ? PatchState.Patched : PatchState.Stock,
            GetDetail = () =>
            {
                var s = RuntimeHook.Read();
                return s.Installed
                    ? string.Format("{0:n0} frames   {1} presses   {2} checkpoints",
                                    s.Frames, s.Presses, s.Checkpoints)
                    : null;
            },
            Set = on => { if (on) RuntimeHook.Install(CheckpointKey); else RuntimeHook.Remove(); }
        });

        _runtimeRows.Add(new FeatureRow
        {
            Name = "Lock health",
            Summary = "Alex stops taking damage, for practising a fight",
            Tooltip = "The engine applies every health change through one instruction. This "
                    + "removes it, so health keeps whatever value it had.\n\nIt blocks healing "
                    + "too, because that is the same instruction: health drinks will not top "
                    + "you up while this is on.\n\nIt guards that path only. A scripted death "
                    + "or an instant kill that sets health directly could still kill you.\n\n"
                    + "Runtime only: nothing is written to disk and it is gone when the game exits.",
            RequiresGameRunning = true,
            GetState = HealthLock.Read,
            GetDetail = HealthLock.ReadHealth,
            Set = HealthLock.Set
        });
    }

    private static string FirstSentence(string text)
    {
        var i = text.IndexOf(". ", StringComparison.Ordinal);
        return i < 0 ? text : text[..i];
    }

    private static string Join(string description, string? note) =>
        note is null ? description : description + "\n\n" + note;

    // -------------------------------------------------------------- refresh
    private void Locate(string? module)
    {
        _module = module;
        if (module is null)
        {
            GamePathText.Text = "not found - use Browse to pick Bin\\g_SilentHill.sgl";
            Log("Could not find the game automatically.");
        }
        else
        {
            GamePathText.Text = module;
            Log("Game: " + module);
            if (!GameLocator.LooksLikeSupportedBuild(module))
                Log("This file is not the size of build v6.30 (#640742). Patches will refuse to write "
                    + "unless the bytes match exactly.");
        }
        RefreshAll();
    }

    private void RefreshAll()
    {
        foreach (var r in _fileRows) r.Refresh();
        RefreshLive();
        RefreshFps();
        RefreshSpeed();
        RefreshUnlocks();
    }

    /// <summary>Everything that can change while the window is open.</summary>
    private void RefreshLive()
    {
        var running = RuntimeHook.IsGameRunning();
        WarnText.Visibility = running ? Visibility.Visible : Visibility.Collapsed;
        if (running)
            WarnText.Text = "Game is running: file patches are locked until you close it. "
                          + "Practice works only while it runs.";

        foreach (var r in _runtimeRows)
        {
            r.Refresh();
            r.Detail = running ? r.GetDetail?.Invoke() : "start the game first";
        }
    }

    private void RefreshFps()
    {
        if (_module is null) { FpsDetail.Text = ""; return; }
        var fps = GamePatches.FpsCap.Read(_module);
        FpsDetail.Text = fps switch
        {
            null => "unreadable - not the supported build",
            0 => "uncapped: vsync or the GPU decides",
            _ => GamePatches.FpsCap.IsStock(_module) ? "30 FPS (stock)" : string.Format("{0:0.##} FPS", fps)
        };
    }

    private void RefreshSpeed()
    {
        if (_module is null) { SpeedDetail.Text = ""; return; }
        var state = SpeedPatch.ReadState(_module);
        var inFile = SpeedPatch.ReadFactor(_module) ?? 1f;
        var live = RuntimeHook.IsGameRunning() ? SpeedPatch.ReadLive() : null;

        SpeedDetail.Text = state switch
        {
            PatchState.Unknown => "unreadable - not the supported build",
            PatchState.Stock => "normal speed: the frame loop is untouched",
            _ => string.Format("{0:0.##}x in the game files", inFile)
                 + (live is not null && Math.Abs(live.Value - inFile) > 0.01f
                     ? string.Format(", {0:0.##}x in the running game", live.Value) : "")
        };

        var shown = live ?? inFile;
        var index = Array.FindIndex(SpeedChoices, c => Math.Abs(c.Factor - shown) < 0.01);
        if (index >= 0) SpeedCombo.SelectedIndex = index;
    }

    private CheckBox[] CostumeBoxes => [CbYoung, CbSheriff, CbTrucker, CbOrderly, CbOrder, CbPyramid];

    private void RefreshUnlocks()
    {
        if (_module is null) return;
        var s = UnlockPatch.Read(_module);
        for (var i = 0; i < CostumeBoxes.Length; i++) CostumeBoxes[i].IsChecked = s.Costumes[i];
        CbLaser.IsChecked = s.LaserGun;
        CbCompleted.IsChecked = s.Completed;
        foreach (var b in CostumeBoxes.Concat([CbLaser, CbCompleted])) b.IsEnabled = s.Readable;

        var count = s.Costumes.Count(c => c);
        UnlockDetail.Text = !s.Readable
            ? "unreadable - not the supported build"
            : count == 0 && !s.LaserGun && !s.Completed
                ? "nothing forced: the game uses what you earned"
                : string.Format("{0} of 6 costumes forced{1}{2}", count,
                    s.LaserGun ? ", Laser Gun" : "", s.Completed ? ", completed" : "");
    }

    // ------------------------------------------------------------- handlers
    private void OnRowToggle(object sender, RoutedEventArgs e)
    {
        var button = (ToggleButton)sender;
        if (button.DataContext is not FeatureRow row) return;
        var wanted = button.IsChecked == true;

        if (_module is null && !row.RequiresGameRunning)
        {
            Log("Pick the game first.");
            row.Refresh();
            return;
        }
        if (!row.RequiresGameRunning && RuntimeHook.IsGameRunning())
        {
            Log("Close the game first: Windows locks " + GameLocator.ModuleName + " while it is loaded.");
            row.Refresh();
            return;
        }

        try
        {
            row.Set(wanted);
            Log((wanted ? "Enabled: " : "Disabled: ") + row.Name);
        }
        catch (Exception ex)
        {
            Log(row.Name + " failed: " + ex.Message);
        }
        row.Refresh();       // the row shows what the file says, not what was clicked
        RefreshLive();
    }

    private void OnSetFpsClick(object sender, RoutedEventArgs e)
    {
        if (!CanPatch()) return;
        var choice = FpsChoices[Math.Max(FpsCombo.SelectedIndex, 0)];
        try
        {
            if (choice.Fps == 0) GamePatches.FpsCap.Restore(_module!);
            else GamePatches.FpsCap.Write(_module!, choice.Fps < 0 ? 0 : choice.Fps);
            Log("Frame rate cap: " + choice.Label);
        }
        catch (Exception ex) { Log("Frame rate failed: " + ex.Message); }
        RefreshFps();
    }

    /// <summary>
    /// Unlike the other file patches this one can be retuned mid-session: the multiplier is a
    /// float the stub reads every frame, so a running game takes a new value immediately.
    /// </summary>
    private void OnSetSpeedClick(object sender, RoutedEventArgs e)
    {
        if (_module is null) { Log("Pick the game first."); return; }
        var choice = SpeedChoices[Math.Max(SpeedCombo.SelectedIndex, 0)];

        if (RuntimeHook.IsGameRunning())
        {
            if (SpeedPatch.TryWriteLive(choice.Factor))
                Log("Gameplay speed: " + choice.Label + " - applied to the running game.");
            else
                Log("The speed hook is not in the running game. Close the game, apply a speed, "
                    + "then start it: after that this can be changed while you play.");
            RefreshSpeed();
            return;
        }

        try
        {
            SpeedPatch.Write(_module, choice.Factor);
            Log(choice.Factor <= 1
                ? "Gameplay speed: normal - the patch was removed."
                : "Gameplay speed: " + choice.Label);
        }
        catch (Exception ex) { Log("Gameplay speed failed: " + ex.Message); }
        RefreshSpeed();
    }

    private void OnApplyUnlocksClick(object sender, RoutedEventArgs e)
    {
        if (!CanPatch()) return;
        try
        {
            var costumes = CostumeBoxes.Select(b => b.IsChecked == true).ToArray();
            UnlockPatch.Write(_module!, costumes, CbLaser.IsChecked == true, CbCompleted.IsChecked == true);
            var chosen = UnlockPatch.CostumeNames.Where((_, i) => costumes[i]).ToList();
            if (CbLaser.IsChecked == true) chosen.Add("Laser Gun");
            if (CbCompleted.IsChecked == true) chosen.Add("completed flag");
            Log(chosen.Count == 0 ? "Unlocks cleared: the game uses your real progress."
                                  : "Unlocks: " + string.Join(", ", chosen));
        }
        catch (Exception ex) { Log("Unlocks failed: " + ex.Message); }
        RefreshUnlocks();
    }

    private void OnBrowseClick(object sender, RoutedEventArgs e)
    {
        var dlg = new Microsoft.Win32.OpenFileDialog
        {
            Title = "Select g_SilentHill.sgl (in the game's Bin folder)",
            Filter = "Silent Hill: Homecoming module|g_SilentHill.sgl|All files|*.*"
        };
        if (dlg.ShowDialog() == true) Locate(dlg.FileName);
    }

    private void OnRefreshClick(object sender, RoutedEventArgs e)
    {
        if (_module is null) Locate(GameLocator.Find());
        else RefreshAll();
    }

    private void OnToggleLogClick(object sender, RoutedEventArgs e)
    {
        LogPanel.Visibility = LogPanel.Visibility == Visibility.Visible
            ? Visibility.Collapsed
            : Visibility.Visible;
        if (LogPanel.Visibility == Visibility.Visible) LogScroll.ScrollToEnd();
    }

    private void OnRestoreAllClick(object sender, RoutedEventArgs e)
    {
        if (_module is null) return;
        if (RuntimeHook.IsGameRunning())
        {
            try { RuntimeHook.Remove(); Log("Practice hook removed."); }
            catch (Exception ex) { Log("Could not remove the practice hook: " + ex.Message); }
            try
            {
                if (HealthLock.Read() == PatchState.Patched) { HealthLock.Set(false); Log("Health lock removed."); }
            }
            catch (Exception ex) { Log("Could not remove the health lock: " + ex.Message); }
            Log("Close the game to restore the file patches too.");
            RefreshLive();
            return;
        }
        foreach (var row in _fileRows.Where(r => r.State is PatchState.Patched or PatchState.Mixed))
        {
            try { row.Set(false); Log("Disabled: " + row.Name); }
            catch (Exception ex) { Log(row.Name + " failed: " + ex.Message); }
        }
        try { SpeedPatch.Restore(_module); Log("Gameplay speed: normal"); }
        catch (Exception ex) { Log("Gameplay speed failed: " + ex.Message); }
        try { UnlockPatch.Write(_module, new bool[6], false, false); Log("Unlocks cleared."); }
        catch (Exception ex) { Log("Unlocks failed: " + ex.Message); }
        try { GamePatches.FpsCap.Restore(_module); Log("Frame rate cap: 30 (stock)"); }
        catch (Exception ex) { Log("Frame rate failed: " + ex.Message); }
        RefreshAll();
    }

    private bool CanPatch()
    {
        if (_module is null) { Log("Pick the game first."); return false; }
        if (RuntimeHook.IsGameRunning())
        {
            Log("Close the game first: Windows locks " + GameLocator.ModuleName + " while it is loaded.");
            return false;
        }
        return true;
    }

    private void Log(string message)
    {
        StatusText.Text = message;
        LogText.Text += (LogText.Text.Length > 0 ? "\n" : "") + message;
        LogScroll.ScrollToEnd();
    }
}
