# Silent Hill: Homecoming — PC Speedrunning Toolkit

> **Beta.** It works on the build below and has been used in real play sessions, but it
> wants testers. Report anything that looks wrong.

Fixes and practice tools for the PC release of *Silent Hill: Homecoming*
(2008, Double Helix / Konami), in one Windows app — with the reverse-engineering notes
behind every one of them.

Motivated by this thread on speedrun.com:
**[PC version is allowed here?](https://www.speedrun.com/shh/forums/kl01r)**

> "This game really need a patch for PC (Official or not). [I] find it hilarious that
> the game have an option to go to 144hz but it's hard coded to 30."
> — MasterDarkseid

That is precisely correct. It came down to a single float.

---

## Quick start

1. Download **`SHHToolkit.exe`** and run it. Nothing to install — the .NET runtime is
   inside the file.
2. It finds the game itself (Steam libraries on any drive, via `libraryfolders.vdf` and
   the registry). If it can't, point it at `Bin\g_SilentHill.sgl` with **Browse**.
3. **Close the game** before changing anything under *Frame rate*, *Game speed*, *Game
   files* or *Unlocks* — Windows locks the module while the game is loaded. The
   *Practice* rows are the opposite: they need the game **running**.

**Restore all** puts everything back to stock.

## What it does

| | |
|---|---|
| **Frame rate cap** | Removes the hard-coded **30 FPS** limit. Pick 60 / 120 / 144 / your refresh rate, or uncapped. |
| **Gameplay speed** | **1x–4x** time scaling for practising a route. Capped at 4x (collision tunnels above that), with the scaled frame delta clamped tighter than the engine's own limit. Changeable *while you play*. |
| **Borderless windowed** | Stops the game minimising when you alt-tab, by patching how it creates its window. |
| **All costumes + Laser Gun** | Per-item checkboxes, without replaying the game for each ending. Your save file is never touched. |
| **Crash guard** | Guards a crash that hits during level loads (the flashlight re-attach bug). |
| **Mouse bindings** | Esc on a thumb button, weapon cycling on the wheel click. Config only. |
| **Practice: lock health** | Alex stops taking damage. Runtime only. Blocks healing too, and scripted attacks still get through — see [NOTES.md](NOTES.md). |

## Safety

* Every patch **checks the exact bytes** at its offsets first and refuses to write if
  they are neither "stock" nor "already patched" — a different build cannot be corrupted.
* A `.orig` copy of any file is made **before the first write** to it.
* File patches are blocked while the game is running; the runtime hooks suspend the
  game's threads while rewriting bytes that execute every frame.
* The *Practice* features are **memory only**. Nothing is written to disk and they are
  gone when the game exits.

> Steam's **Verify integrity of game files** reverts the file patches. Re-run the
> toolkit afterwards. Restoring is byte-for-byte identical to the original (verified by
> md5), so it is safe to restore before validating.

## Supported build

`g_SilentHill.sgl` from **build v6.30 (#640742)**, md5
`2af20d3f0b1d3902135a044966859d39`, 20,959,232 bytes. Every offset here was verified
against that file. On anything else the patches refuse to write rather than guess.

## Building it yourself

See [ui/README.md](ui/README.md). One command produces the portable .exe.

The `shh_*.py` scripts at the repo root are **development tools**, not the product:
they are how each patch was proven in live memory before it was written to a file, and
they are kept because they are still the fastest way to test a theory against a running
game. The toolkit is what people should use.

---

## Borderless windowed

**In the toolkit:** *Game files* → **Borderless windowed** (game closed).

The game runs **D3D9 exclusive fullscreen**, so losing focus loses the device and D3D9
minimises the window. That can't be suppressed from outside the process — the minimise
happens inside D3D9's own `WM_ACTIVATEAPP` handling. Borderless windowed avoids it
entirely: the device is never lost, so no minimising and no device-reset hitch when you
tab back.

```bash
python shh_window_fix.py --setup        # one-time: windowed + native res in the cfg
python shh_borderless_patch.py --apply  # make the game create a frameless window
python shh_borderless_patch.py --status
python shh_borderless_patch.py --restore
```

Nothing runs alongside the game. The patch changes two 4-byte constants in the
*windowed* branch of the game's own window creation: the style passed to
`CreateWindowExA` (`WS_OVERLAPPEDWINDOW` → `WS_POPUP`), and the hardcoded style its
sizing helper passes to `AdjustWindowRect`, so no space is reserved for a frame the
window no longer has. The engine's own centring then lands the window on `(0,0)` at
exactly your resolution. Exclusive fullscreen is untouched, and `--restore` puts both
constants back.

> **Earlier versions of this repo did it from outside**, with `shh_window_fix.py`
> restyling the live window. It works visually, but every restyle makes the engine
> re-run its video setup: 4 application hangs and a load-time crash lined up with it,
> and no hang ever happened without it. Don't run it alongside this patch. Its
> `--setup` (which only edits `vars_pc.cfg`) is still the easy way to switch the game
> to windowed at your native resolution.

### Mouse escaping to other monitors — still fixed, provisionally

The engine *does* confine the cursor — it calls `ClipCursor` with its client rect from
`0x10BA2DE0` — but only on focus **transitions**. Windows drops the clip on any
foreground change, and the game never re-applies it:

```
game's own state : g_clipMode=0, enable=1, clip-branch flag set  -> "I have clipped"
Windows          : GetClipCursor = entire virtual desktop        -> no clip at all
game window      : foreground = True
```

Re-applying the clip from another process fixes it, and that half never touches the
window — so it still ships. It is now what `shh_window_fix.py` does by default:

```bash
python shh_window_fix.py       # cursor lock only; borderless is opt-in (--borderless)
```

Treat it as provisional: it has not yet been played with for long *without* the
restyling half, so it is not independently cleared of the instability that half
caused. The durable fix is to patch the engine's own clip call to re-apply per
frame; see [NOTES.md](NOTES.md).

---

## Game speed multiplier / cutscene fast-forward

**In the toolkit:** *Game speed* → pick 1x–4x and **Apply**. Set it with the game
closed; after that it can be changed while you play.

```bash
python shh_speed_patch.py --apply      # game closed; ships INERT (factor 1.0)
python shh_speed.py --hold             # hold CAPS LOCK for 8x, release for normal
python shh_speed.py --hold --key F8 --factor 4
python shh_speed_patch.py --restore    # undo
```

### Why this exists

**In-engine cutscenes cannot be skipped at all.** That was verified, not assumed:
during a confirmed cutscene the `ICutscene` global (`0x11596118`) stayed **NULL**
with a probe polling 5x/sec, and the main-thread stack showed **no cutscene
player** — only the ordinary `TickLoop`. Those scenes are scripted sequences
running inside the normal game tick, so there is no playback object for
`COMMAND_SKIP_CUTSCENE` to abort.

The engine's own "cutscene fast-forward mode" was never a cut-to-end either; it
was time acceleration. This exposes that generally.

### How it works

`0x116C7A14` is the global frame delta time — verified live, reading 0.00833 s at
120 FPS. It is written once per frame by the timer update `FUN_10A4E940`:

```
00a4e99c  f3 0f 11 05 14 7a 6c 11   movss [0x116C7A14], xmm0
```

The patch redirects that store through a code cave that scales it, then clamps it:

```
    mulss xmm0, [g_speedFactor]    ; default 1.0
    minss xmm0, [g_maxDelta]       ; default 0.05 s
    movss [0x116C7A14], xmm0
    jmp   back
```

`xmm0` is not reused after the original store, and the tick dispatch immediately
after receives `&dt`, so the scaled value reaches everything.

| | |
|---|---|
| patch site | `0x00A4E99C`, 8 bytes -> `jmp` + 3 nops |
| `g_speedFactor` | `0x00D71300`, float, default **1.0** |
| `g_maxDelta` | `0x00D71304`, float, default **0.05** |
| cave code | `0x00D71310`, 29 bytes |

All three cave addresses were verified as `0xCC` padding inside a 647 KB unused run in
`.text`. **Factor 1.0 means the toolkit removes the patch entirely**, rather than
leaving an inert multiply in the frame loop.

The ceiling exists because the multiply applies to *every* frame, including a long one:
a 200 ms loading hitch at 4x asks for an 800 ms step. The engine's own tick already
clamps `dt` at 0.08 s, so it would survive that regardless — ours is set *below* that
deliberately, so the worst step while sped up is smaller than the worst step the stock
game takes.

The multiplier is a float the stub reads every frame, so the toolkit can change speed in
a **running** game by writing those four bytes: no restart, no re-patching.

`shh_speed.py` also **mutes voice while held** (restoring your real
`volumevoice` on release and on exit). Audio runs on its own clock and cannot
follow the time scale, so without muting speech plays at 1x over 8x visuals.
`--no-mute` disables that.

### Limits worth knowing

* **It scales everything** — physics, animation, scripted timers. Fine for covering
  ground and sitting through dialogue; be careful through combat or timed interactions.
* **The toolkit stops at 4x, and that is the number to trust.** The engine will *run*
  to roughly 8x before the tick's own 0.08 s clamp stops buying you speed, and past
  about 10x you step over scripted triggers instead of going faster — but well before
  that, the per-frame step grows past what this engine's collision handles cleanly and
  Alex starts catching on, or passing through, geometry. 4x is the setting this was
  tested at; the older script will let you ask for more, and that is not a recommendation.
* **It does not speed up Q&A dialogue scenes.** Those advance on voice-line
  completion and player input, not on elapsed time, so there is nothing for a
  time multiplier to accelerate.
* Not leaderboard-legal — this alters game timing, unlike the other fixes which
  restore intended behaviour.

---

## All costumes and the Laser Gun

**In the toolkit:** *Unlocks* → tick the costumes you want and **Apply** (game closed).

Finishing the game unlocks **one** costume - the one belonging to the ending you got -
and the Laser Gun needs the UFO ending specifically. Getting everything legitimately
means replaying to five different endings.

Your save file is never touched: the patch changes what the game *asks*, so your real
unlock record stays underneath and restoring brings it back.

```bash
python shh_unlock_patch.py --apply     # dev tool: all-or-nothing, unlike the toolkit's checkboxes
python shh_unlock_patch.py --status
python shh_unlock_patch.py --restore   # back to your real unlocks
```

### What the game actually stores

Unlocks live in a profile object as 8 bytes, one per item:

```
profile+0x230  Young Alex      +0x234  Order Soldier
profile+0x231  Sheriff         +0x235  Pyramid Head
profile+0x232  Trucker         +0x236  completed the game
profile+0x233  Orderly         +0x237  got the UFO ending
```

Each ending level carries an `ISilentHillCostumeUnlockTrigger` naming its costume:

| Ending | Costume |
|---|---|
| road / exterior | Trucker |
| bathroom flashback, Dad in the attic | Order Soldier |
| Alex becomes the new Pyramid Head | Pyramid Head |
| asylum (electroshock, gurney) | Orderly |
| Elle ending - also sets `Got_UFO` | Sheriff |

Young Alex is unlocked by none of them; its condition is still unknown. The UFO ending
path sits next to inventory checks for the **Polaroid photos**, and Alex's house checks
`Got_UFO` by the ornate desk - that is the Laser Gun.

### The three edits

```
0x10A0BE10  the costume accessor, "return profile[0x230+idx]", reached only by the
            script lookup behind IsPyramidUnlocked / IsOrderlyUnlocked / ...
              8b 44 24 04 8a  ->  b0 01 c2 04 00     mov al,1 / ret 4
0x1094FDF3  at new game, "completed" is copied into the Completed_Game variable only
            if the profile says so:   75 (jne) -> eb (jmp)
0x1094FE69  the same for the UFO flag (Got_UFO):   75 -> eb
```

Both jumps land on the path the game already takes when the flag *is* set, so nothing
new runs - the game just stops asking.

---

## Crash guard: flashlight re-attach

**In the toolkit:** *Game files* → **Crash guard** (game closed).

One crash signature hit four times, always while a level was loading, and always
byte-identical (same registers, same stack). When a level loads, the player character
re-attaches the flashlight to bone 35 of another object, looks that object up by handle,
and reads its skeleton pointer:

```
10554aa5  call Lookup(handle)
10554aaa  mov ecx,[eax+0x340]      ; skeleton pointer
10554ab3  mov edx,[ecx]            ; CRASH - ecx holds text, not a pointer
10554abd  call [edx+0x20]          ; skeleton->GetBoneMatrix(35, out)
```

The pointer *is* null-checked. The problem is that it is not null: intermittently the
handle resolves to an object that is not a finished character, and `+0x340` holds the
bytes `"__ty"`, from the engine's own `"__types__"` reflection text. A null guard would
not have helped.

```bash
python shh_crashfix_patch.py --apply
python shh_crashfix_patch.py --restore
```

The patch redirects those 11 bytes to a stub in unused padding: if the pointer is
unreadable (`IsBadReadPtr`, which the game already imports) or does not point at a real
vtable, it takes the function's own early-exit - the same one the game uses when the
pointer is NULL, returning the identity matrix the function already wrote. Otherwise it
runs the original instructions unchanged. Worst visible effect should be the flashlight
sitting oddly for a moment during a load, instead of a crash.

This guards that one crash only. The Havok physics crashes are separate bugs.

---

## Controls: Esc and weapon switching on the mouse

**In the toolkit:** *Game files* → **Mouse bindings** (game closed).

Config only, in `Engine\binds_pc_mjs.cfg` (a `.orig` backup is written beside it):

| Input | Does |
|---|---|
| Thumb / side button (`BUTTON_3`) | Everything Esc does: skip movies, pause menu, back |
| Wheel click (`BUTTON_2`) | Cycle weapons (the `]` command) |
| `L` | "Look at", moved off the wheel click |

Notes from working this out:

* The engine reads the mouse with DirectInput's `c_dfDIMouse`, which is **4 buttons
  only**: left, right, wheel click, first side button. A second side button cannot be
  bound.
* `COMMAND_WEAPON_NEXT` / `COMMAND_WEAPON_PREV` exist in the command table but the PC
  build **never queries them**. Weapon cycling really runs on `COMMAND_EXT_5` /
  `COMMAND_EXT_6`, the `[` and `]` keys (D-pad left/right on a controller).
* Binding the **scroll wheel** (`AXIS_Z`) to a non-camera command did not work, with
  either half-ranges or the full range the stock file uses. The wheel axis appears to be
  camera-only, which is why weapon cycling sits on the wheel *click*.
* These are `addbind` lines, so the stock keys keep working.

---

## Practice: lock health

**In the toolkit:** *Practice* → **Lock health**. It needs the game **running**.

Health is `player+0x164` (float, maximum at `+0x168`) and does not regenerate. Every
health change — damage *and* healing — goes through a single instruction:

```
1031F105  movss xmm0, [esi+0x164]    ; current health
1031F114  addsd xmm0, xmm2           ; += delta  (negative when damaged)
1031F11C  movss [esi+0x164], xmm0    ; store back   <- replaced with 8 nops
```

With the store gone, health is read, adjusted and discarded, so the value never moves.
Runtime only: nothing is written to disk, and it is gone when the game exits.

Two limits, both confirmed in play rather than assumed: it blocks **healing** as well,
since that is the same instruction; and **scripted attacks still kill you**, so those
reach health by some other path.

It was found by putting a hardware write watchpoint on the health field and taking hits
until it tripped — four hits, the same instruction every time, values walking
150 → 135 → 125 → 115 → 100. That mattered: in this game a write that *holds* proves
nothing (position and save-point writes both held and changed nothing). Catching the
game itself writing the field is what established it was real.

---

## FPS cap: root cause

**In the toolkit:** *Frame rate* → pick a cap and **Apply** (game closed).

The game exposes three things that all *look* like frame rate controls. None of them
are.

| Setting | Where | What it actually does |
|---|---|---|
| `ScreenRefresh` | menu + `Engine\vars_pc.cfg` | Only sets the D3D9 **display mode**. The launcher stub even relaunches the game with `relaunch=1 reloadVidResWidth=%d reloadVidResHeight=%d reloadRefresh=%d ...` to apply it — so the display really does switch to 144 Hz. |
| `fpsLimit` / `maxFPSLimit` | `Engine\vars_pc.cfg` | Registered with `INT_MIN..INT_MAX` bounds (no clamping), parsed and written back correctly, and clamped once per tick as `fpsLimit = min(fpsLimit, maxFPSLimit)` — but **never read by the render loop.** Vestigial. |
| `vsync` | cvar | Untested. Setting `vsync=0` did not raise the observed frame rate, but an external 120 FPS driver limiter was active during testing, so this cvar was never actually isolated. |

The real limiter is `FUN_10a4cc90` in `Bin\g_SilentHill.sgl`. Note that
`Bin\SilentHill.exe` is only a 33 KB stub that `LoadLibrary`s the first `g_*.sgl` it
finds — the entire 21 MB engine is the renamed PE32 DLL.

```
00a4cc99   fld dword ptr [0x1108e804]     ; <-- hard-coded target frame time

target = ToTicks(thatFloat)
now    = GetTicks()
if (now - lastFrame) < target:
    Sleep(TicksToMs(target - (now - lastFrame)))   # sleep the remainder
    while elapsed < remaining: Sleep(0)            # then spin the rest
lastFrame = GetTicks()
```

The constant at `0x1108E804` is `0x42054B18` = **33.323334 ms → 30.009 FPS**.

It is a standalone 4-byte float in `.rdata`, sitting between unrelated string data,
and it has **exactly one cross-reference in the entire 21 MB module** — the frame
limiter above. Nothing else reads it, which is what makes this a safe one-value patch.

| | |
|---|---|
| Module | `Bin\g_SilentHill.sgl` (PE32 DLL, `IMAGE_FILE_DLL`, no ASLR) |
| Image base | `0x10000000` (`DllCharacteristics = 0`, so it always loads here) |
| File offset | `0x0108E804` — equal to the RVA, since raw and virtual addresses coincide for `.text`/`.rdata`/`.data` in this build |
| Virtual address | `0x1108E804` |
| Stock bytes | `18 4B 05 42` |
| Build | v6.30, changelist #640742 |
| md5 | `2af20d3f0b1d3902135a044966859d39` |

---

## FPS cap: verification

Frame rate was measured by sampling the engine's own frame counter at `0x111C14FC`
against a wall clock — not by eye. Runs were interleaved to rule out thermal or
focus-related drift:

| Limiter constant | Measured |
|---|---|
| stock `33.3233 ms` | **29.83 FPS** |
| patched `6.9444 ms` | **119.99 FPS** |
| stock again `33.3233 ms` | 29.83 FPS |
| patched again `6.9444 ms` | 119.99 FPS |
| `--uncap` (`0.0 ms`) | 119.99 FPS |

Then confirmed end-to-end from the patched file on disk, in real gameplay at
2560x1440 fullscreen, with an independent on-screen overlay reading **120 FPS** —
while `fpsLimit` was still at its stock `30`, which is what proves those cvars gate
nothing.

**About that 119.99 ceiling:** it is *not* the engine — but the test setup cannot say
which downstream limiter it is. The display runs at **120 Hz** and the NVIDIA app also
had a **120 FPS** cap configured. Both sit at exactly 120, so vsync and the driver cap
are indistinguishable in this data (600 frames / 5.00 s = 120.00 either way).

What the measurements *do* establish: the engine limiter is gone, and the bottleneck
moved somewhere downstream. What they do **not** establish: how high the engine can
actually go, or whether the `vsync` cvar does anything. Settling that needs a run with
the driver cap cleared *and* the refresh rate changed, so the two can be told apart.

Test system: RTX 5070 Ti, Samsung Odyssey over HDMI, 2560x1440 @ 120 Hz,
NVIDIA app frame limit 120 FPS.

(A `Win32_VideoController` query reported `CurrentRefreshRate = 119` on this machine
while NVIDIA Control Panel showed 120 Hz — don't trust WMI for this.)

---

## Known limits

* **Something downstream will still bound you.** Once the engine limiter is gone, your
  frame rate is governed by whatever comes next — a driver-level frame cap (NVIDIA app
  / RTSS), vsync, or the GPU itself. On the test system a 120 Hz display and a 120 FPS
  driver cap coincided exactly, so the engine's true headroom above 120 FPS remains
  unmeasured. Check both your refresh rate and your driver frame cap before concluding
  the patch didn't work.
* **Frame-rate-dependent game logic is not fully verified.** The engine is delta-time
  driven (it clamps `dt` to 0.08 s and runs a 5-frame moving average), so it should be
  well behaved, but only the opening area was tested — not a full playthrough. If you
  hit physics or animation oddities at high frame rates, try `--fps 60` before
  assuming the patch is at fault.
* **Speedrunning:** a patched binary is very unlikely to be leaderboard-legal, and a
  higher frame rate could affect run timing. Treat this as a quality-of-life fix for
  casual play unless the board rules say otherwise.
* Only build **v6.30 (#640742)** is verified. The toolkit refuses to write to anything
  whose patch slot doesn't look right, so other builds fail safe rather than corrupt.
* **The toolkit runs unelevated.** Patching writes into the game folder, which is
  normally user-writable for a Steam install. If yours sits somewhere locked down, the
  file patches will fail with an access error — run it as administrator in that case.

---

## Roadmap

Other complaints from the same thread, not yet investigated:

- [x] **FPS** — hard-coded 30 FPS cap *(this patch)*
- [ ] **True frame rate ceiling** — re-measure with the driver FPS cap cleared *and* the
      refresh rate changed, so vsync and the driver cap can be told apart; find where the
      engine actually tops out and whether the `vsync` cvar does anything
- [x] **Controls (mouse)** — cursor escaping to other monitors *(`shh_window_fix.py`,
      now cursor-lock-only by default)*. Provisional — the durable fix is an engine
      patch that re-applies the clip per frame
- [x] **Auto-minimise on alt-tab** — exclusive fullscreen device loss
      *(`shh_borderless_patch.py`)*
- [x] **Crashes** — "victim of crashing all the time... at many different points".
      Mostly self-inflicted: retiring the live-window restyling stopped the crashes
      *and* the hangs. Two engine bugs (a Havok phantom use-after-free, and a
      flashlight re-attach during level load) are diagnosed down to the instruction;
      the flashlight one is now guarded by `shh_crashfix_patch.py`. See
      [NOTES.md](NOTES.md).
- [ ] **Map / journal images clipped above 720p** — cause located (hardcoded 1280x720
      reference resolution at `0xA4CDE3`), but it is a *missing scale*, not a wrong
      constant. One patch attempted and reverted — see [NOTES.md](NOTES.md).
- [x] **Controls (rest)** — Esc on a mouse side button, weapon cycling on the wheel
      click *(bindings; see [Controls](#controls-esc-and-weapon-switching-on-the-mouse))*
- [ ] **Lag/stutter** — "more lag somehow, which can get pretty bad on certain sections"
- [x] **Unskippable cutscenes** — in-engine scenes cannot be skipped at all (proven, see
      [NOTES.md](NOTES.md)); the speed multiplier is the answer for those

Practice tooling beyond the thread:

- [x] **Gameplay speed 1x–4x**, bounded and retunable while playing
- [x] **Lock health** — the single instruction that applies every health change,
      found with a hardware write watchpoint. Scripted attacks still get through.
- [ ] **Save anywhere** — *closed, not abandoned lightly.* Moving a save point to the
      player, a "can save here" flag, and calling the engine's own save path were all
      tried and all fail; the disk write is asynchronous and pumped by the save
      screen's own update loop. Every dead end is written up in [NOTES.md](NOTES.md)
      so nobody repeats them.

---

## Repo layout

**The product:**

```
ui/SHHToolkit/         the toolkit (.NET 8 / WPF) — see ui/README.md
  MainWindow.xaml      the window: every feature is a row or a section here
  Services/
    GameLocator.cs     finds the install (Steam libraries on any drive, registry)
    BinaryPatch.cs     byte-verified patch sets, with .orig backups
    GamePatches.cs     borderless, crash guard, FPS cap
    SpeedPatch.cs      gameplay speed: the delta hook, its clamp, live retuning
    ConfigPatches.cs   cutscene skip and mouse bindings (Engine\*.cfg)
    UnlockPatch.cs     per-item costumes and the Laser Gun
    GameProcess.cs     finding the game and reading/writing its memory
    HealthLock.cs      removes the instruction that applies health changes
README.md              this file
NOTES.md               the reverse-engineering handoff: addresses, live-verified
                       findings, dead ends written up so they are not redone
```

**Research harness** — how the findings were made, not needed to use the toolkit:

```
shh_*.py               one script per patch, each proving it in live memory first
tools/
  shh_mem.py           process read/write + engine object resolution
  shh_measure.py       reliable frame-rate measurement, live A/B of the cap
  shh_profile.py       EIP sampler + stack walker (this is what found the limiter)
  shh_static.py        offline: strings, xrefs, float constants, imports, disasm
  cvars.json           all 91 cvars mapped to settings-object offsets
```

See [NOTES.md](NOTES.md) for how the pieces fit together, and for a list of measurement
pitfalls that will otherwise waste your time.

## Nothing here belongs to Konami

This repo ships a **patcher, not the game**, and no game content of any kind:

* no game binaries — `g_SilentHill.sgl`, `SilentHill.exe`, `binkw32.dll`;
* no game data, saves, or configuration copied out of an install;
* **no game artwork.** The toolkit shows the game's logo in its header when a
  `logo.png` is present in `ui/SHHToolkit/`, and that file is deliberately not
  distributed. Without it the app builds and runs exactly the same, with a
  text-only header. Supply your own copy if you want the image.

`backup/`, `work/` and `ghidra/` are local working directories holding copies of the
module and a ~1 GB Ghidra project. `.gitignore` excludes all of the above.

---

## Credits

Built by **thetofusurvivor_**.

Issue reported by **MasterDarkseid**, **Ecdycis** and **Sasam** in the
[Silent Hill: Homecoming speedrun.com forums](https://www.speedrun.com/shh/forums/kl01r).

Reverse engineering done with [Ghidra](https://ghidra-sre.org/).

Not affiliated with Konami or Double Helix Games.
