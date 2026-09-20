# PC Speedrunning Toolkit (GUI)

A dark WPF front end for everything in this repo, themed after the game (ash, rust,
fog) so the patches can be used without touching a command line. .NET 8, C#, XAML.

Built by **thetofusurvivor_**.

```
ui/SHHToolkit/
  SHHToolkit.csproj     net8.0-windows, WPF, x64
  App.xaml              app shell, merges the theme
  Theme.xaml            dark palette and control styles
  MainWindow.xaml       the window: wordmark, game row, feature sections, log
  MainWindow.xaml.cs    wiring: locate the game, toggle features, refresh state
  FeatureRow.cs         one feature line (state, label, what the button does)
  Services/
    GameLocator.cs      finds Bin\g_SilentHill.sgl via the registry + libraryfolders.vdf
    BinaryPatch.cs      guarded byte edits with .orig backup
    GamePatches.cs      FPS cap, borderless, unlocks, crash guard (stub generated in code)
    ConfigPatches.cs    cutscene skip and the mouse bindings, as marked config blocks
    RuntimeHook.cs      the practice checkpoint key, written into the running game
```

## Build

```bash
cd ui/SHHToolkit
dotnet build                     # needs the .NET 8 SDK
dotnet run
```

## Publish something shareable

Everything needed is already in the `.csproj` under a `Release` condition, so this is the
whole command:

```bash
cd ui/SHHToolkit
dotnet publish -c Release -o ../dist
```

That produces **one portable `SHHToolkit.exe`, about 64 MB**, in `ui/dist/`. It is
self-contained: the .NET runtime travels inside the file, so a tester who has never
installed .NET can double-click it. Nothing else ships beside it.

Two settings are deliberate and should not be "optimised" away:

* **`InvariantGlobalization` must stay `false`.** Turning it on saves a few MB and then the
  app dies at startup with *"The type initializer for `MS.Internal.FontCache.MajorLanguages`
  threw an exception"* - WPF's font cache initialises culture data. The failure looks like
  the app silently not opening: the process lives, but the only window is the
  unhandled-exception message box.
* **`PublishTrimmed` is absent on purpose.** WPF resolves types by name from XAML at
  runtime, so the trimmer removes code that is genuinely used.

If the exe is currently running, publishing fails on `GenerateBundle` because the output is
locked - close it and re-run.

## What it does

* **Frame rate cap** - rewrites the hard-coded 30 FPS frame-time constant.
* **Gameplay speed** (1x to 4x) - scales the engine's frame delta, so movement, animation
  and scripted sequences speed up together rather than drifting out of step. Pick it with
  the game closed; after that it can be changed *while you play* and takes effect at once,
  because the multiplier is a float the stub reads every frame.

  Two bounds are deliberate. **4x is the ceiling**: past it this engine's collision starts
  letting Alex through geometry. And the stub **clamps the scaled delta to 50 ms** — the
  engine's own tick already clamps at 80 ms, so ours is set below that deliberately: while
  sped up, the worst single step is smaller than the worst step the stock game takes.

  Pre-rendered movies run on Bink's own clock and are unaffected; in-engine scripted scenes
  run in the ordinary tick, so those do speed up.
* **Game files** (game must be closed): borderless windowed, all costumes + the New Game+
  extras, the flashlight-crash guard, skippable pre-rendered cutscenes, and the mouse
  bindings (Esc on the thumb button, weapon cycling on the wheel click).
* **Practice** (game must be running), runtime only - writes nothing to disk, gone when the
  game exits:
  * an **F5 key** that sets the checkpoint the game restores you to;
  * **Lock health** - the engine applies every health change through a single instruction,
    and this removes it, so Alex stops taking damage. It blocks *healing* too, for the same
    reason, and it guards only that path: a scripted death or an instant kill could still
    get you. The row shows your live health while the game runs.
* **Restore everything** puts the game back to stock.

## Safety rules it follows

* Every patch checks the exact bytes at its offsets first and refuses to write if they
  are neither "stock" nor "already patched" - a different build cannot be corrupted.
* A `.orig` copy of any file is made before the first write to it.
* File patches are blocked while the game is running (Windows locks the module), and the
  runtime hook suspends the game's threads while it rewrites bytes that execute every frame.

## A note on the logo

The header is typographic on purpose. The game's actual logo is Konami's artwork, and
this tool is meant to be shared, so none of it is bundled. Point the header at your own
image if you want something richer.
