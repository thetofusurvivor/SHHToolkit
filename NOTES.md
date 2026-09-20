# Working notes / handoff

State of the project and everything needed to pick it back up. Companion to
[README.md](README.md), which is the user-facing writeup.

Last session: 2026-09-19.

---

## Status

**Published 2026-09-20: https://github.com/thetofusurvivor/SHHToolkit** (public, MIT,
release `v0.1.0-beta` with the portable 63 MB `SHHToolkit.exe` attached).

**The toolkit is the product.** `ui/SHHToolkit` is where features ship; the `shh_*.py`
scripts are the research record and are not kept at feature parity.

### Where things stand, 2026-09-20

| | |
|---|---|
| Shipped and user-confirmed | FPS cap, borderless, per-item unlocks, crash guard, mouse bindings, gameplay speed 1x-4x, lock health |
| Removed from the toolkit | practice checkpoint key (records no position), Bink cutscene skip (user's request; the config line still works by hand) |
| Closed, will not be retried | save anywhere - every route disproved, see below |
| Open | map/journal clipping >720p, lag/stutter, true frame-rate ceiling, the Havok phantom crash (diagnosed, unguarded) |

### If you pick this up next

* **Read the dead ends before proposing anything.** Save-anywhere, position warping and
  the save-point move each looked obvious and each failed for a reason recorded here.
* **A write that holds proves nothing in this game.** Position and save-point writes both
  held and changed nothing on screen. Confirm by catching the *engine* writing a field
  (hardware watchpoint), or by what the player sees.
* **Every check needs a control.** Verifications that "passed" while being structurally
  incapable of failing cost real time on 2026-09-20 - see the measurement pitfalls.


| Issue from the [forum thread](https://www.speedrun.com/shh/forums/kl01r) | Status |
|---|---|
| 30 FPS cap despite a 144 Hz option | **Fixed** — `shh_fps_patch.py` |
| Controls: mouse escapes to other monitors | **Fixed, provisionally** — `shh_window_fix.py`, now cursor-lock-only by default |
| Auto-minimises when you tab out | **Fixed** — `shh_borderless_patch.py` (2 x 4 bytes, replaces that helper) |
| Unskippable **Bink movie** cutscenes | **Fixed** — one line in `default_pc.cfg` (user-confirmed). Dropped from the toolkit 2026-09-20 |
| Unskippable **in-engine** cinematics | **Cannot be skipped** — proven: no cutscene object exists. Mitigated by the speed patch |
| Game speed multiplier / fast-forward | **Shipped in the toolkit**, 1x-4x with a delta clamp (user-confirmed 2026-09-20) |
| Crashes "at many different points" | **Mostly resolved** — the external window restyling caused most of them; the flashlight crash is now guarded (`shh_crashfix_patch.py`), the Havok phantom one is not |
| Q&A dialogue scenes (DialogueTree) | **No skip exists in the engine** — mapped, no safe invocation path found |
| True frame-rate ceiling / does `vsync` cvar work? | Open — measurement was confounded |
| Map / journal images clipped at >720p | **Investigated, NOT fixed** — cause located, one fix attempted and reverted |
| Lag and stutter in certain sections | Not started |
| Unskippable PS3/PC-exclusive cutscene (~7 min) | Not started |
| Weapon switching / Esc on the mouse | **Fixed** — `binds_pc_mjs.cfg`: wheel click cycles weapons, side button = Esc (user-confirmed) |
| One costume per ending; Laser Gun needs the UFO ending | **Unlocked** — per-item in the toolkit (costumes user-confirmed) |
| Dying while practising a fight | **Fixed** — health lock in the toolkit (user-confirmed 2026-09-20) |
| Quicksave anywhere for practice | **Not possible** — every route closed, see below. The checkpoint key was built, found useless and removed |

The toolkit (`ui/SHHToolkit`) is the product; the `shh_*.py` scripts are the research
record. The checkpoint key and the Bink cutscene skip were removed from it on
2026-09-20 - the first because it records no position, the second at the user's request.

### Crash analysis — 2026-09-14 (supersedes everything below)

**The external window restyling was causing most of the instability.** The user
stopped running `shh_window_fix.py` on 09-13 around 20:25, and the crashes and
hangs stopped. The Application event log agrees:

| | before it existed (09-05→09-09) | helper in use (09-10→09-13) | since retiring it |
|---|---|---|---|
| AppHangs (event 1002 / WER `AppHangB1`) | 0 | **4** | 0 |
| crashes (event 1000) | 12 | 8 | 0 |

The 4 hangs were 09-10 20:41 and 09-13 20:06 / 20:15 / 20:23. Hangs had never
happened before that helper existed, and have not happened since.

Why: `SetWindowLong` + `SetWindowPos` on a live window makes the engine re-run its
video setup. One crash landed **11 s after the helper was started**, while a save
was loading; the 09-10 crash with the same signature came seconds after a restyle.
Replaced by `shh_borderless_patch.py`, which sets the style at window *creation*,
so nothing ever restyles a live window.

**I had this backwards before.** The previous note here argued borderless was
*helping*, because the old `+0xB8DBF2` crash stopped when borderless arrived. That
compared crash signatures across two eras differing in more than one variable, and
never looked at hangs at all — hangs leave no dump, only an event. The user's own
before/after was the better evidence.

Caveat: "helper in use" is by era, not per session; it was not verified running for
every one of those 8 crashes. The two engine bugs below are real regardless, and
neither is guarded yet.

**1. Havok phantom use-after-free — 4 crashes**

```
date         site       what faulted                                      uptime
09-12 11:02  +0x11CC99  write 0x3F555555 in AddToOverlapSet(ownerA+0xF0)   1:16:48
09-13 10:00  +0xA65FA7  ownerA->vfunc[0x1C8], vtable = 0x3F800000 (1.0f)   0:03:25
09-13 10:03  +0xA669C5  read 0x3F555555 in InOverlapSet(ownerA+0xF0)       0:03:33
09-13 17:12  0x74704F54 call edx at +0xA65FB4 jumped INTO TEXT             1:03:05
```

The 17:12 one is the same bug in disguise: WER logged the faulting module as
"unknown" because `eip` was `0x74704F54` = ASCII `"TOpt"`. The freed block had been
reallocated, so the overlap-set calls on `ownerA+0xF0` *succeeded* (writing into
someone else's memory), then `[[ownerA]+0x1C8]` produced string bytes and `call edx`
jumped into them. Return address `+0xA65FB6`, caller `+0xA661EB` — identical chain.

Chain, named from string refs (this build has no RTTI): `TickLoop` (`fn 0x10156110`)
→ Havok step → `TPhantom` handler (`fn 0x10A66020`) → notifier `FUN_10A65F30`.

The two 09-13 morning crashes hit 3:25 and 3:33 after launch — same save reloaded,
~2.5 min of play each time — so **a reproducible encounter probably exists** to test
a guard against.

**Guard design (ready, NOT applied):** code cave `0x10D71400` (verified `0xCC`, clear
of the speed-patch cave). At `FUN_10A65F30` entry require, for both owners: non-NULL,
`[owner]` inside `.rdata` (`0x10F7A000..0x111BF7F8`), **and** `[[owner]+0x1C8]` inside
`.text`; otherwise return without notifying. Those two levels cover both observed
variants (10:00 fails the first, 17:12 fails the second). Unknown for the two `+0xF0`
faults — triage dumps carry no heap. Full dumps (`DumpType=2`, elevated) would settle
it; still not enabled.

**2. `+0x554AB3` flashlight re-attach at level load — 2 crashes**

Byte-identical both times, and not a missing null check. Dedicated section below.

Crash count by signature, for the record:

| signature | stock (to 09-09 22:15) | FPS only | FPS + restyling helper |
|---|---|---|---|
| `+0xB8DBF2` null-deref, the old main one | **11** | 1 | 0 |
| Havok phantom UAF | 0 | 0 | **4** |
| `+0x554AB3` flashlight attach at load | 0 | 0 | **2** |
| `+0x4EC8CB` UI / DialogueTree | 0 | 0 | 1 |
| `nvd3dum.dll` driver | 0 | 0 | 1 |
| `windows.storage.dll` | 1 | 0 | 0 |
| AppHang (no dump) | 0 | 0 | **4** |

The `+0xB8DBF2` column is what made the old "borderless fixed it" claim look
plausible. It is a UI/menu stream bug, and the 09-05→09-09 sessions were spent in
menus far more than later ones.

**Next step if the phantom crash returns:** apply the guard **in memory only**
(`WriteProcessMemory` into the running game), replay the save that crashed twice at
~3.5 min, and only write it to the file if it holds.

### (superseded) Crash signatures observed (all with the FPS patch only, unless noted)

```
 12x  g_SilentHill.sgl  0x00b8dbf2   null-deref virtual call (the main one)
  1x  g_SilentHill.sgl  0x00554ab3   stale pointer ("__ty" ASCII used as a pointer)
  1x  g_SilentHill.sgl  0x0011cc99   PHYSICS (LtBroadPhase/TtCollide/
                                     TtreCollideAfterStepFailure) - occurred while
                                     the speed patch was applied
  1x  g_SilentHill.sgl  0x004ec8cb   UI code, DialogueTree frame on the stack
  1x  nvd3dum.dll       0x0163be8e   NVIDIA D3D9 driver, no game frames on the stack
  1x  windows.storage.dll 0x000c4f54
```

The physics one is the only one with a plausible link to the speed patch: the
multiplier scales the physics timestep, and at 9.5x `dt` sits right against the
engine's 0.08 s clamp on every frame. The patch never appeared on any crash
stack, but "my code isn't on the stack" is not proof of innocence. If the speed
patch is re-applied, **4x is the recommended setting** (dt 0.033 s, comfortable
headroom) rather than 9.5x.

---

## The target, in one screen

```
Bin\SilentHill.exe        33 KB stub. Scans for "g_*.sgl", LoadLibrary's it.
                          Relaunches itself with:
                            relaunch=1 reloadVidResWidth=%d reloadVidResHeight=%d
                            reloadRefresh=%d reloadLowQualityShaders=%d
Bin\g_SilentHill.sgl      The actual 21 MB engine. PE32 DLL, renamed.
                          ImageBase 0x10000000, DllCharacteristics = 0 (NO ASLR)
                          -> static addresses are valid at runtime, as-is.
                          For .text/.rdata/.data:  file offset == RVA.
                          Build v6.30 (#640742), md5 2af20d3f0b1d3902135a044966859d39
Engine\vars_pc.cfg        cvar dump, rewritten by the game on exit
Engine\pak, Engine\movies assets; movies are Bink (binkw32.dll)
```

### Addresses worth keeping

| What | Address |
|---|---|
| Frame limiter function | `FUN_10A4CC90` |
| **Frame cap constant** (float32 ms) | `VA 0x1108E804` = **file offset `0x0108E804`** |
| Settings object (backs `vars_pc.cfg`) | `*(*(*(0x111D2460) + 0x38) + 8)` |
| Renderer/stats object | `*(0x115890EC + 4)`, FPS float at `+0x32C`, raw at `+0x330` |
| **Per-tick frame counter** | `0x111C14FC` |
| cvar registration function | `FUN_10A27970` (parsed into [tools/cvars.json](tools/cvars.json)) |
| Main game tick | `FUN_101264F0` |
| FPS overlay draw | `FUN_1013F7B0` |
| FPS averaging | `FUN_1013FAC0` |

### The fix, restated

`FUN_10A4CC90` does sleep-then-spin against a hard-coded frame time:

```
00a4cc99   fld dword ptr [0x1108e804]     ; 0x42054B18 = 33.323334 ms = 30.009 FPS
```

That float has **exactly one xref in the whole module** (reconfirm any time with
`python tools/shh_static.py --xref 0x1108E804`). Patch it to `1000/target_fps`.

`fpsLimit` / `maxFPSLimit` / `ScreenRefresh` are **not** involved — proven by
running at 120 FPS with `fpsLimit` still at its stock `30`.

---

---

## Unskippable cutscenes — fixed, then dropped from the toolkit

> **Removed from the toolkit 2026-09-20** at the user's request, along with the
> checkpoint key. The one-line config change below still works if you want it by hand;
> it is simply no longer one of the toolkit's rows.

**The complaint is cumulative, not one long video.** All ten Bink files are
1280x720 @ ~29.97 fps and none exceeds 2m48s:

```
CIN_M14_050  2m48s   SHH_ATTRACT  2m02s   CIN_M09_030  1m59s
GURNEY_RIDE  1m22s   CIN_M09_020  1m04s   Start_Loop   1m02s
CIN_M09_040  0m41s   CIN_M02_010  0m38s   CIN_M03_030  0m31s + alt 0m06s
```

Story cinematics (excluding the attract and menu loops) total **~9 minutes** —
which is the "7 minutes behind" the thread describes.

**Root cause.** `COMMAND_SKIP_CUTSCENE` *is* bound on PC — `binds_pc_mjs.cfg`
line 59 maps it to `KEY_ESCAPE`, line 230 to controller `BUTTON_8`. The input
path is fine. The skip is refused by a config flag.

A second config object, separate from the `vars_pc.cfg` settings object, lives
at `*(*(0x111D2460)+0x38)+4` (note `+4`; the cvar settings object is `+8`).
Registration is at `0x10A49F00`-ish, via the registry at `0x116C7A30`:

```
mov edx,[0x111D2460] / mov eax,[edx+0x38] / mov ecx,[eax+4]
add ecx,<offset> / push ecx / push <name> / mov ecx,0x116C7A30 / call 0x10040B60
```

| flag | offset | shipped value |
|---|---|---|
| `allowskipmovie` | `+0x57` | 1 |
| `allowgameskipmovie` | `+0x58` | **0** ← the culprit |
| `allowSkippableLevelIntroMovies` | `+0x16D` | 1 |
| `forcevolumetextures` | `+0x79` | 0 (graphics, unrelated) |

So intro and level-intro movies skip fine; **in-game story cutscenes are gated
behind `allowgameskipmovie`, which defaults to false and appears in no shipped
config file.**

**Fix.** That registry is the one that parses `Engine\default_pc.cfg` —
confirmed because `loadingscreenxml` (a real key in that file) registers into
the same `0x116C7A30`. So one line makes it permanent:

```
allowgameskipmovie	= 1
```

(tab before `=`, CRLF line ending, matching the file's existing style)

Verified live first by writing 1 to `cfg+0x58` in the running process — the user
confirmed Escape then skips in-game cutscenes. No binary patch needed.

The full key list for that registry sits in `.rdata` around
`0x1108E1C0`-`0x1108E720` and includes other interesting knobs:
`logframerate`, `vsyncInterval`, `playlicensemovie`, `outromovie`,
`enablestreaming`, `streamingglobalbudget`, `antiAlias`, `preservebackbuffer`.
`vsyncInterval` is worth a look for the open frame-rate-ceiling question.

---

## Map / journal images clipped above 720p — investigated, NOT fixed

**Symptom.** The in-game map and images embedded in the journal (drawings,
photos) are cut off right and bottom. Measured clip boundary, by screenshot:

```
render 1280x720    fits exactly                     - correct
render 1920x1080   map panel (300,158)-(1280,728)   - clipped
render 2560x1440   map panel (589,234)-(1280,719)   - only the top-left quarter
journal drawing    (882,356)-(1279,719)             - same boundary
```

The clip is always at **(1280,720) in render pixels**, never at half the
backbuffer (ruled out: at 1920x1080 it clips at 1280, not 960). The surrounding
UI — the journal book, its text, the tabs, the arrows — lays out correctly
against the real screen size. Only dynamically rendered image content is hit.

**Where the 720p comes from.** The resolution init handler (engine init table
entry `INITRESOLUTION` / `Init_Resolution`, thunk `0x1001D4AD` → `FUN_10A4CD40`)
builds a display-params struct and hardcodes a second width/height pair:

```
00a4cdb8  mov edi,[ecx+0x1FC]          ; edi = ScreenResWidth
00a4cdb1  mov ebx,[ecx+0x200]          ; ebx = ScreenResHeight
00a4cdd6  call 0x1002c0b6              ; construct params struct
00a4cddb  mov [esp+0x28], edi          ; params.width     = real width
00a4cddf  mov [esp+0x2c], ebx          ; params.height    = real height
00a4cde3  mov dword [esp+0x30], 0x500  ; params.refWidth  = 1280   <-- hardcoded
00a4cdeb  mov dword [esp+0x34], 0x2D0  ; params.refHeight = 720    <-- hardcoded
```

That struct is `rep movsd`'d (19 dwords) into the globals at `0x111DE348`, which
at runtime reads `(realW, realH, 1280, 720)` — confirmed live at both 1920x1080
and 2560x1440. Two sibling virtual getters read the two pairs:

| getter | reads | returns |
|---|---|---|
| `0x10B72CA0` | `0x111DE348/34C` | real screen size |
| `0x10B72D20` | `0x111DE350/354` | fixed 1280x720 |

Both are vtable-dispatched, so they have no direct callers to grep for.

### Attempted fix — WRONG, do not repeat

Patched `0xA4CDE3` to store `edi`/`ebx` instead of the constants, so the ref
pair tracked the screen. Verified in memory: `0x111DE350` became `(2560,1440)`.

**Result: the map rendered at roughly 2x size, overflowing the screen.** Worse
than the original. Reverted; the module is byte-identical to stock apart from
the intended FPS constant.

**What that proves:** content size scales *with* `ref`, so `0x111DE350/354` is
the **design/reference resolution the UI art is authored against**, not a
surface or viewport size. Raising it just declares "the art is bigger".

```
ref 1280x720   -> drawn at 1x, clipped at 1280x720   (too small)
ref 2560x1440  -> drawn at 2x, overflows the screen  (too big)
```

**The real bug is a missing scale**, not a wrong constant: the content is drawn
in ref space and blitted 1:1 into screen pixels instead of being scaled by
`screen/ref`. No value of `ref` can fix that — it only trades one wrong size for
another.

### Decisive measurement: `ref` is used INCONSISTENTLY

Comparing identical screens at the two `ref` values, measuring the "Objectives"
label and the map content:

| | ref = 1280x720 (stock) | ref = screen (patched) | ratio |
|---|---|---|---|
| "Objectives" text width | 250 px | 124 px | **0.50x** |
| map content | clipped, small | overflows screen | **~2x** |

Text scales as `1/ref`; map content scales as `ref`. They move in **opposite
directions**, so **no single value of `ref` can be correct.** That definitively
rules out the "just fix the constant" class of fix, and confirms the defect is a
missing `screen/ref` scale applied to the map/journal-image draw specifically.

Worth noting `ref = screen` *does* remove the clip (the map overflowed rather
than being cut at 1280x720), so `ref` genuinely bounds the surface extent — it
just drags content scale along with it.

### The getters are reached through jump thunks

They are NOT virtual (neither address appears in any vtable). They are called
through the engine's jump-thunk table, which is why a direct `E8` caller scan
initially found nothing:

```
thunk 0x10016978 -> 0x10B72CA0   GetSize_REAL         8 callers
thunk 0x100644D9 -> 0x10B72D20   GetSize_FIXED_720p  11 callers
```

Both are 5-byte `E8 rel32` calls, so any call site can be retargeted by
rewriting 4 bytes — same length, and it works in live memory via
`VirtualProtectEx`. `tools/shh_uiscale_probe.py` does exactly this
(`--list` / `--flip ADDR` / `--restore-all`), which makes bisecting safe and
instantly reversible.

### Ruled out so far

Six of the eleven FIXED call sites are in the debug-text/stats module (the one
containing the FPS overlay at `0x1013F7B0`). The other five were each flipped to
REAL in a live process with the map open, and **none removed the clip**:

| site | effect of flipping to REAL |
|---|---|
| `0x102D90AF` | layout changed, still clipped |
| `0x10498983` | no visible change |
| `0x104EBEA5` | **whole UI turned greyscale** - it sizes a colour/post effect |
| `0x10A929AF` | layout changed, still clipped at 1280x720 |
| `0x10A9367E` | layout changed, still clipped at 1280x720 |

So the clip is not applied at any of these size queries.

### Decompiled: what the two getters actually do

```c
// 0x10B72D20  FIXED - returns sizes in REF space
*w = DAT_111de350;                      // 1280, raw
*h = DAT_111de354;                      // 720
if (rect && (rect->flags & 2)) {
    *w = DAT_111de33c * rect->size.x;   // scaled by ref/real
    *h = DAT_111de340 * rect->size.y;
}

// 0x10B72CA0  REAL - returns sizes in SCREEN space
*w = DAT_111de348;                      // real width
*h = DAT_111de34c;
if (rect && (rect->flags & 2)) { *w = rect->size.x; *h = rect->size.y; }
```

The ratio, computed in `FUN_10B73230`:

```c
DAT_111de33c = params[2] / DAT_111de348;   // refWidth  / realWidth  = 0.5 @ 2560x1440
DAT_111de340 = params[3] / DAT_111de34c;   // refHeight / realHeight
```

So the two getters are a coherent pair returning sizes in two coordinate
spaces — ref (1280x720 design space) and screen. That is deliberate design, not
a bug.

`FUN_10A4C530` (reached as `thunk` from the `call 0x1002c0b6` inside the
resolution init) is the params **defaults constructor**:

```c
params[0]=1280; params[1]=720;   // width/height - later overwritten with real res
params[2]=1280; params[3]=720;   // the ref pair - NEVER overwritten
params[4]=9; params[7]=0x2000; params[9]=0x20000;
params[0xb]=params[0xc]=0xE0; params[0xd]=0x200; params[0xf]=0x400; params[0x10]=0x1000;
```

### RULED OUT: the clip does not come from the FIXED getter

All eleven `GetSize_FIXED_720p` call sites were retargeted to `GetSize_REAL`
**simultaneously**, in a live process with the map open, and verified applied
(`--list` showed all eleven REAL). **The map was still clipped at exactly
1280x720.** So none of those size queries drives the clip.

Combined with the earlier finding that changing the ref value *does* unclip
(while breaking scale elsewhere), the consumer of `0x111DE350/354` that bounds
the surface is somewhere not yet traced — and it is a different consumer from
the one driving content scale. A correct fix has to separate those two.

### Next lead

The remaining approach is to find the surface/viewport consumer directly rather
than by constant-scanning, which is exhausted: a D3D9 frame capture (RenderDoc
or PIX) with the map open would show the actual draw, its render target size and
its transform in one step. That is the tool for this job and would likely settle
in minutes what static analysis has not.

Headless Ghidra works and does NOT need the MCP bridge — see
`tools/DecompileDump.java` and `tools/FindConstUse.java`. The project must not
be open in the Ghidra GUI (it holds an exclusive lock).

Note that live-poking `0x111DE350` has **no** effect once the game is running -
the value is consumed during resolution init - so `ref` experiments need a file
patch plus restart, whereas *call-site* experiments work live.

Prove any future fix in memory before touching the file. The one time that rule
was broken here, the result shipped a worse bug than the one being fixed.

---

## There are TWO cutscene systems — only one is fixed

This matters: "I can't skip cutscenes" can mean either of two unrelated things.

| | Mechanism | Gate | Status |
|---|---|---|---|
| **Bink movies** (pre-rendered .bik) | skip stops playback | `allowgameskipmovie` | **Fixed** (config line) |
| **In-engine cinematics** (real-time) | skip **fast-forwards** the scene | see below | **Not fixed** |

Evidence for the split: `RndMoviePlayer.cpp`, `PlayMovie`, `movieplayer` on one
side; `ICutscene.cpp`, `ICinematicsPlayer`, `ICinematicsManager`, `CutScene
Flags`, `TCinematics` on the other. In-engine cutscenes do not jump to the end,
they fast-forward — hence this engine string:

```
We're in cutscene fast-forward mode, but after 250 seconds of elapsed time it still isn't done...
```

### The fast-forward gate

`thunk_FUN_10490DC0` (reached via thunk `0x1004576E` -> `0x10143A10`), called
from the tick loop at `0x101566E8`:

```c
if (cutscene != NULL && cutscene->[0x210] == 2) {       // cutscene active
    settings = *(*(0x111D2460)+0x38)+8;                  // the vars_pc.cfg settings object
    if (settings->[0xED] == 0 && cutscene->[0x250] != 3)
        return false;                                    // fast-forward refused
    return true;
}
return false;
```

Two independent ways to allow fast-forward.

### DO NOT set settings+0xED — it aborts the game

`settings+0xED` is **not** a "may skip" permission. It is a developer
**force-always-fast-forward** switch, and it is deliberately not exposed as a
cvar (nothing in the registration table binds `+0xED`; offsets `+0xE8`
`maxFPSLimit` then `+0xEF` `debugKillAllies` bracket it).

Setting it to 1 in a live process put the engine into permanent fast-forward and
tripped its own 250-second watchdog:

```
ABORTING build [FINAL] v6.34 Changelist: #663064 Silent Hill:
We're in cutscene fast-forward mode, but after 250 seconds of elapsed time it still isn't done...
```

The game had to be killed. Reverted; nothing on disk was affected. **Treat any
unexposed flag in that object as a debug switch, not a feature toggle.**

### Skip Mode decoded (ICutscene only)

`cutscene+0x250` is an authored enum, registered as:

```c
RegisterEnumProperty("Skip Mode", this + 0x94, 0, <table 0x111C6978>, 6)
      // dword index 0x94 == byte offset 0x250

0 = None              <- Skip() bails out; cannot be skipped
1 = Load Level
2 = (Obsolete)
3 = (Obsolete)        <- the ONLY value the fast-forward gate accepts
4 = Abort
5 = Elapse Director   <- ICutscene constructor default
```

`Skip()` is `FUN_10491410`:

```asm
mov  ebp,[esi+0x250]        ; SkipMode
xor  ebx,ebx
cmp  byte [edx+0xed], bl    ; dev flag set?
lea  ebp,[ebx+3]            ;   -> forces mode 3, the OBSOLETE mode
cmp  ebp, ebx               ; SkipMode == 0 ?
je   bail                   ;   -> no skip at all
...
mov  dword [esi+0x210], 2   ; state 2 == "skip in progress"
```

This explains the `+0xED` abort precisely: that flag does not grant permission,
it **forces Skip Mode 3**, selecting an obsolete fast-forward path that never
terminates, so the 250-second watchdog fires. It is a broken code path, not a
random debug toggle.

### IMPORTANT: the dialogue cutscenes are NOT ICutscene objects

Verified live: during an in-engine dialogue cutscene (confirmed by screenshot —
sharp native-resolution engine rendering with subtitles, not a 1280x720 video),
the ICutscene global `0x11596118` is **NULL**. `0x10490D60` is
`SetCurrentCutscene()` and would populate it for a real ICutscene.

So all of the Skip Mode analysis above is real, but applies to a subsystem that
is **not** what plays during those scenes. There are at least three cinematic
systems in this engine:

```
Bink movies            RndMoviePlayer.cpp, PlayMovie      -> fixed via allowgameskipmovie
ICutscene              ICutscene.cpp, Skip Mode enum      -> decoded above, NOT what plays
ICinematics*           ICinematicsPlayer (38 refs), ICinematicsManager (12),
                       IStreamedCinematicManager (17), TCinematics
```

`tools/shh_cutscene_probe.py` reads the ICutscene global live and reported
"no cutscene active" throughout — that is the evidence, and it is why no patch
was attempted.

### Next step for cutscenes

Identify which subsystem actually drives dialogue cutscenes before touching
anything. Candidates by reference count: `ICinematicsPlayer` (`0x10483FD6` etc.),
`IStreamedCinematicManager` (`0x104974F0` etc.). Find its "current" global the
same way `0x10490D60` was found for ICutscene, then probe it live during a
cutscene to confirm before any patch.

### The legitimate path (ICutscene)

`cutscene->[0x250] == 3` is the real "skip was requested" state — that is what
pressing the (already correctly bound) `COMMAND_SKIP_CUTSCENE` should set. The
open question is why it is not being set for the cutscenes that refuse to skip:
either the input never reaches the cutscene object, or a per-cutscene
"skippable" flag blocks it (`CutScene Flags` suggests designer-set flags).

Next step: decompile the `ICutscene` state machine around `0x10490DC0` /
`0x10491D43` (which writes state 5) and find who writes 3. Note `+0x250` is a
very common struct offset module-wide, so a raw scan for writes is too noisy —
work from the ICutscene class code (roughly `0x1048D000`-`0x104F1000`) instead.

---

## DialogueTree system — the Q&A scenes (skip NOT implemented)

The "cutscenes with questions" are **not cutscenes at all**. They are
`IDialogueTree` conversations. Verified live, simultaneously:

```
[17:15:59] CONVERSATION ACTIVE  tree=0x25998E20  (mgr=0x163970A0)
           ICutscene global 0x11596118 = NULL
```

Active tree and NULL cutscene at the same instant — the two systems are
disjoint. That is why Escape does nothing (no cutscene to abort) and why all the
`ICutscene` Skip Mode work does not apply here.

### Verified live addresses

| What | Address |
|---|---|
| `DialogueTreeManager` | `0x116BD770` |
| active conversation | `[manager + 0x214]`, NULL when none |
| `DialogueTree` vtable (this class) | `0x11063C10` |
| tree field passed to ExitDialogueTree | `[tree + 0x220]` |

`tools/shh_cutscene_probe.py` has a `read_dialogue()` that reads this, and
`scratchpad/dlgwatch.py` polls it 5x/sec and timestamps transitions.

### Why time-scaling only half-helps

Spoken lines **do** accelerate under the speed patch (user-confirmed). What
cannot accelerate is the game waiting for the player to pick a response — that
is not elapsed time. So a conversation costs
`(spoken content / factor) + (however long you take to answer)`.

### The exit path is DEAD CODE

`FUN_108E8920` is a textbook `DialogueTree::Exit(this)`:

```asm
mov  eax,[0x116BD770]        ; manager
cmp  [eax+0x214], esi        ; is this the active tree?
jne  bail
mov  dword [eax+0x214], 0    ; clear active
mov  ecx,[esi+0x220]
call ExitDialogueTree        ; FUN_108E8500, takes NO arguments
```

But it has **zero references anywhere in the module** — no direct calls, no
thunk callers, not in any vtable (its thunk `0x10065B04` is itself uncalled).
It is unreachable in the shipped build, the same pattern as Skip Mode 3 being
"(Obsolete)". Do not build a fix around it without checking that again.

The paths that actually clear `[manager+0x214]` at runtime are
`FUN_108EA4D0` (via thunk `0x10012DE6`, one caller `0x108EA9FB`) and
`FUN_108EAD50` (via thunk `0x1005558D`, one caller `0x108EAFC2`). Both sit in
single call chains that were not yet walked to their roots.

### The tree object is STATIC — live state is in the dialog director

Diffed the first 0x300 bytes of the live `DialogueTree` object at 6 Hz while the
user played through a conversation. **Not one field changed** until the tree
pointer went NULL at the end. So the `DialogueTree` is a descriptor (the tree
definition), not the running state machine.

The live state is in a **dialog director component**. `ExitDialogueTree` reaches
it by name, not through a global:

```c
piVar5 = FindComponent("TTC_DialogDirectorControl");
*(undefined1 *)(piVar5 + 5) = 0;
```

So there is no fixed address to probe. Capturing it means either walking the
component list from the player object, or hooking the name lookup
(`thunk_FUN_1044A240`) to grab the returned pointer.

That component is where the line cursor and the audio-completion gate will live
— i.e. the thing that decides when a spoken line is "done", which is what makes
these scenes resist both skipping and (partly) time-scaling.

**Next time: arm the watcher BEFORE entering a conversation.** The one attempt
here only caught the tail end.

### What a skip would require

1. Walk those chains to a safe entry point that ends a conversation cleanly.
2. Hook an input path from a code cave so the call runs on the **game's own
   thread** — the engine is single-threaded, so calling in from a helper
   process would race the main loop.
3. Accept progression risk: conversations mutate state as they run
   (`TDialogueTreeTriggerChangeTopic`, `GhostResponse`, `EnableTree`,
   `ChangeFirstConversation`...). Exiting early skips whatever the remaining
   branches would have set. Unlike every other fix in this repo, this makes the
   game do something it was never designed to do.

Also note the DialogueTree UI script exposes only `FirstResponse`..
`FourthResponse` plus Activate/Deactivate — **there is no skip verb** anywhere
in cvars, config keys, strings, or UI bindings.

---

## Crashes — diagnosis (not yet fixed)

**Evidence:** 10 crash dumps in `%LOCALAPPDATA%\CrashDumps` (9/5–9/9) plus WER
events in the Application event log. **9 of 10 are byte-identical:**

```
Faulting module : g_SilentHill.sgl   (always loaded at 0x10000000)
Exception       : 0xC0000005 access violation, reading address 0
Fault offset    : 0x00B8DBF2         <-- same every time
WER bucket      : 1162283933         <-- same every time
eax             : 0x00000000         <-- in all 9
```

The 10th (dump `11028`) is different: `0xC0000096` privileged-instruction with
`eip` outside the module — a wild jump. Probably a separate, rarer bug.

**The faulting code** (function `+0xB8DBD0`, a buffered stream reader):

```
00b8dbeb  mov eax,[esi+0x28]   ; the underlying stream object
00b8dbf2  mov ecx,[eax]        ; read its vtable   <-- eax is NULL
00b8dc00  mov eax,[ecx+0x2c]   ; vtable slot 11
00b8dc03  call eax             ; virtual call
```

Object layout: `+0x10` size, `+0x14`/`+0x18` position, `+0x1C` buffer,
`+0x28` underlying stream. The function null-checks `+0x10` and `+0x1C`
elsewhere but **never checks `+0x28`**. The sibling function at `+0xB8DC50`
has the identical unguarded pattern (`mov esi,[esi+0x28]; mov ecx,[esi]`).

So: a stream that failed to open, or was already torn down, gets read anyway.

**Call path** (stable across all dumps, recovered by scanning dump stacks):

```
TickLoop / ObjectTimers                     +0x15634B
  TUIController / TUIControllerInputListener +0x4ED00B
    TUIController                            +0x94941D   (SplashScreen,
                                                          ForegroundScreen,
                                                          SwitchToStartScreen)
      TUISilentHillScriptInterface           +0x95161B
        +0x50E7AE -> +0x4EC152 -> +0x1580FE -> +0xB898E7
          CRASH at +0xB8DBF2
```

Every crash is in the **UI / menu script layer**, never gameplay code.

### `+0x554AB3` — flashlight re-attach during level load (4 crashes, GUARDED 2026-09-19)

09-10 20:37, 09-13 19:53, 09-16 21:10 and 09-19 13:59 — **identical in every register
except the object pointer** (`edi`), same `esp`, same 24-frame stack — deterministic,
not random corruption. The 09-19 one was loading `m02_sgtown1`; an earlier one was
loading `shell`. Uptimes 0:58 / 3:58 / 3:46 / 12:11, i.e. always a level load:

```
eip = 0x10554AB3   read at 0x79745F5F
ecx = 0x79745F5F   bytes 5F 5F 74 79 = "__ty"  (the module's only match is the
                   .rdata string "__types__" at 0x110DA490)
edx = 0x000008D3   entity handle, [edi+0x4C]
eax = 0x00000023   bone index,    [edi+0x54]
```

The code (`FUN_10554A20`, "world matrix of the attach target's bone"):

```
10554a76  mov eax,[edi+0x4c]; push; call Lookup    ; handle -> object
10554a82  test eax,eax / je out                    ; the object IS null-checked
10554a8a  Lookup([edi+0x4c]); cmp [eax+0x340],0 / je out    ; and so is +0x340
10554a9b  cmp [edi+0x54],-1 / je out
10554aa5  Lookup([edi+0x4c]); mov ecx,[eax+0x340]
10554ab3  mov edx,[ecx]                            ; CRASH - +0x340 holds text
10554abd  call [edx+0x20]                          ; skeleton->GetBoneMatrix(0x23, out)
```

**Correction to the earlier write-up:** it claimed the second lookup used a different
argument and was unchecked. Wrong — all three lookups pass the same handle
`[edi+0x4C]`, and the pointer *is* null-checked. The bug is that the handle resolves
to an object whose `+0x340` is non-NULL garbage (wrong type, or not finished
initialising). **A null guard would not have helped.**

Lookup path: `0x10076620 → 0x1014F490 → 0x1004FFC0 → 0x101434F0`, which either calls
vfunc0 of `[0x115895FC]` or `[[0x115890EC]+0xA4]->0x10040BE2(h, 1)`.

Call chain (saved-`ebp` walk, identical in both dumps):

```
+0x32334B  script call (fn 0x103231E0, refs "<Unknown script>")   [stack scan]
+0x568908  vfunc[7] of vtable 0x11000860 (ctor 0x105721F0) = the player character:
           base init loads "knife_equip" / "equip_rifle" / ... anim events, then
           if !byte[this+0x1590]: bind_flashlight(this)
+0x95D8B8  FUN_1095D8A0 "bind_flashlight" - attach node [this+0x1700]+0x1E50
+0x5554BB  FUN_10555480 attach-transform update
+0x555235  FUN_10555130 switch on attach mode [this+0x40]
  CRASH    FUN_10554A20 bone matrix of entity 0x8D3, bone 35
```

Leftovers on both stacks: `"Setting Level shell...Using pack mode"`, `"Alex"`,
`"ICharacter"`, `"ICinematicLoader"`. Session uptime **0:58** (09-13) and 3:58
(09-10) — during a load, not during play.

**Reading:** the player character's post-spawn init re-attaches the flashlight to
bone 35 of entity `0x8D3` while a level is still loading, and intermittently that
entity is not a valid model instance yet. Identical garbage both times means a
deterministic heap reuse in the load sequence (`"__types__"` is reflection text
parsed during load). Both occurrences were also in the restyling-helper era, and a
restyle forces video re-setup mid-load — that may be the trigger rather than the
load alone.

**Guard APPLIED 2026-09-19** (`shh_crashfix_patch.py`; live-tested in memory first,
then written to the file; the script's bytes were diffed against the live-tested
ones). 11 bytes at `0x10554AAA` jump to a stub at `0x10D71500`:

```
mov ecx,[eax+0x340]              ; the original load
push ecx / push 4 / push ecx
call [0x117EEA7C]                ; IsBadReadPtr - already imported by the game
pop ecx / test eax,eax / jnz bail
mov edx,[ecx]                    ; vtable
cmp edx,0x10F7A000 / jb bail     ; must point into .rdata
cmp edx,0x111BF7F8 / jae bail
mov eax,[edi+0x54] / jmp 0x10554AB5   ; back into the original code
bail: add esp,4 / jmp 0x10554AC8      ; the function's own exit (identity matrix)
```

Unproven until it actually catches one - the crash cannot be forced. The stub sits
clear of the speed-patch cave at `0x10D71300`.

**Original guard idea, for reference:** at `0x10554AAA`, validate `ecx` before dereferencing
(`IsBadReadPtr` is already imported, IAT slot `0x117EEA7C`; then `[ecx]` in `.rdata`,
`[[ecx]+0x20]` in `.text`); otherwise `add esp,4` and jump to `0x10554AC8`, leaving
the identity matrix the function already wrote. The `add esp,4` matters: `pop edi` /
`pop esi` at `0x10554AC8` run before `mov esp,ebp`, so skipping the caller's cleanup
would pop the wrong values.

### (back to `+0xB8DBF2`) trigger tests and candidate fix

**Trigger: still unknown.** Tested and ruled out:
- idling at the main menu for 75 s — no crash
- closing the game — no crash (one earlier dump did crash on close, so it is
  intermittent rather than deterministic)
- alt-tabbing out of fullscreen (user tested directly) — no crash

**Candidate fix, designed but NOT applied:** guard the null. There is a 647 KB
`0xCC` code cave at VA `0x10D71294`. Replace the 13 bytes at `0xB8DBE7`
(`mov edx,[esp+0x20]` / `mov eax,[esi+0x28]` / `mov ebx,[esp+0x14]` /
`mov ecx,[eax]`) with a `jmp` to a cave stub that runs the same three loads,
then `test eax,eax`; if non-zero it falls through exactly as before, and if
zero it does `lea edi,[esi+0x1c]` (edi is needed by the `0xB8DC3E` return
path), `xor eax,eax`, and jumps to `0xB8DC05` so the scope acquired at function
entry is still released and the function returns "0 bytes read". Stack stays
balanced because the 5 pushes before the virtual call are skipped along with
the call itself.

Not applied because there is no reproduction to validate it against, and a
wrong cave stub would be worse than the crash. Revisit when the crash recurs.

**To capture better evidence next time,** enable full dumps (elevated prompt —
default is type 1, stacks only, which is why the heap object at `esi` was not
in any dump):

```powershell
$k="HKLM:\SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps\SilentHill.exe"
New-Item $k -Force | Out-Null
New-ItemProperty $k -Name DumpType -Value 2 -PropertyType DWord -Force | Out-Null
```

With a full dump the object at `esi` becomes readable, which should reveal
which asset/stream is null.

---

## Controls: cursor escaping to other monitors — fixed

The engine **does** confine the cursor. `ClipCursor` is imported (IAT
`0x117EEF40`) and called from `0x10BA2DE0`:

```
if (g_clipDisabled[0x11782439]) return;
mode = g_clipMode[0x1178243C];
if (mode == 1) { ClipCursor(NULL); return; }
if (mode == 0 && enable && !check_0x100141A0())
     ClientToScreen + GetClientRect -> ClipCursor(&clientRect);
else ClipCursor(NULL);
```

(The other 8 `ClipCursor` call sites are all `ClipCursor(NULL)` in the
`MessageBoxA` "Warnings" dialog path — not the input path.)

**The bug:** it only runs on focus/state transitions. Windows drops the cursor
clip on any foreground change, and the game never re-applies it. Confirmed live
in the running process:

```
game state : g_clipMode=0, enable=1, clip-branch flag set   -> "I have clipped"
Windows    : GetClipCursor = full virtual desktop           -> not clipped
window     : foreground = True
```

**Fix (RETIRED 2026-09-14):** `shh_window_fix.py` re-applied the clip continuously
while the game was foreground. That part worked — `ClipCursor` from another process
does take effect, and the tool checked `IsIconic` first because `ClientToScreen`
returns `-32000,-32000` for a minimised window, which would strand the cursor.
But the same script also restyled the live window, and that half caused hangs (see
the crash analysis). The restyling is now opt-in (`--borderless`) and the script
runs **cursor-lock-only by default**, so the cursor fix still ships.

Provisional, though: the cursor half has never been played with for long in
isolation, so it is not independently cleared. The durable fix is to patch the
engine's own clip call at `0x10BA2DE0` to re-apply per frame instead of only on
focus transitions - then no helper process is needed at all.

---

## Auto-minimise on alt-tab — fixed (binary patch, 2026-09-14)

D3D9 **exclusive fullscreen** loses the device when the app loses foreground, and
D3D9 itself minimises the window from inside its `WM_ACTIVATEAPP` handling. No
external process can suppress that. The fix is borderless windowed.

**First approach (RETIRED):** `shh_window_fix.py` stripped `WS_CAPTION` /
`WS_THICKFRAME` from the live window and `SetWindowPos`ed it over the monitor.
Visually perfect:

```
BEFORE  rect=(0,0)-(2560,1440)  caption=True  thickframe=True  popup=False
AFTER   rect=(0,0)-(2560,1440)  caption=False thickframe=False popup=True
focus stolen -> minimised=False visible=True     (was: minimises)
```

— but every restyle makes the engine re-run video setup, which correlated with 4
hangs and a load-time crash. A bounded retry budget was not enough.

**Current approach: `shh_borderless_patch.py`** — have the game create the window
borderless itself. Two 4-byte immediates, both in the *windowed* branch only:

```
10ba43cc  cmp byte [eax+0x208], 0   ; fullscreen?
10ba43d4  mov edi, 0x00CF0000       ; WS_OVERLAPPEDWINDOW  <-- patch 1 -> WS_POPUP
10ba43dc  mov edi, 0x80000000       ; WS_POPUP (fullscreen path, untouched)
10ba443f  push edi                  ; dwStyle
10ba444b  call CreateWindowExA      ; [0x117EEEBC]
```

Size and position come from `FUN_10BA3CB0`, which asks `AdjustWindowRect` for frame
room using a **hardcoded** style rather than the real one:

```
10ba3cc2  push 0x86CA0000           ; caption|thickframe|sysmenu  <-- patch 2 -> WS_POPUP
10ba3cdb  call AdjustWindowRect
          then clamp to SM_CXSCREEN/SM_CYSCREEN and centre:
          left = (screenW - winW)/2,  top = (screenH - winH)/2
```

With both patched, `AdjustWindowRect` becomes a no-op, the window is exactly
`ScreenResWidth x ScreenResHeight`, and the centring yields (0,0) when that matches
the monitor. File offsets `0x00BA43D5` and `0x00BA3CC3` (stock `0000cf00` and
`0000ca86`). Still requires `FullScreen=false` + native resolution in `vars_pc.cfg`;
`shh_window_fix.py --setup` writes those three lines.

---

## Saves, profile and the unlockables

**Save file:** `C:\Users\Public\Documents\Silent Hill Homecoming\shv_save.bin`
(`shv` = Silent Hill V). It is in the **shared Public documents folder**, not the user
profile - that is why searching `Documents`, `AppData`, OneDrive, the VirtualStore and
Steam Cloud all came up empty. `save_vars` / `save_prefs` / `save_point` in the module
are console commands, not save files.

Format, so far: a header with a magic/checksum dword (`0x59CDFAF6`, not crc32 or adler32
of any obvious range), a version, a timestamp (`ea 07 09 10 15 1c 1d` = 2026-09-16
21:28:29), the level name (`m11_prison`), the inventory as text
(`barehands:0:0:0,largeknife:0:0:0,...`), and the global variables as `hash:value` pairs.

**The variable-name hash is NOT identified.** Ruled out: crc32, FNV-1/1a, djb2, sdbm,
ELF, x65599, Jenkins lookup2 (the game does contain lookup2 at `0x10866FD0`, but it has
no direct callers). All 167 keys are < 2^31, so it is masked to 31 bits; the engine's
hashed-string constructor is `0x1000B523`, which is where to look next. The unlock bytes
do **not** appear in the file as plain bytes, so the profile is packed some other way.

**Profile object:** `[[0x116C4130]+8]`, vtable `0x11089E68`. Unlock bytes at `+0x230`
(see README for the map). Accessor `0x10A0BE10` = `byte [profile+0x230+idx]`, with the
index per costume from the dispatcher at `0x10A0AF40`: Young 0, Sheriff 1, Trucker 2,
Orderly 3, Order Soldier 4, Pyramid Head 5.

At the **main menu the unlock bytes are all zero** - the real profile is loaded into a
*new* object (the pointer changes) when you enter New Game and reach the difficulty
screen. Any live tooling has to wait for that, not read at the title screen.

`0x1094FD05` copies the profile flags into the game variables at new game:
`if (obj+0x12 || profile+0x236) set Completed_Game`, and the same at `+0x13` / `+0x237`
for `Got_UFO`. Those two checks are what `shh_unlock_patch.py` forces.

**Endings** are routed in `M14_LAIR` by `SavedWheeler` / `ForgaveDad` / `KilledMom`
(which combination leads where is not mapped). Ending levels are `M15_010` (Trucker),
`M15_020` (Order Soldier), `M15_030` (Pyramid Head), `M15_040` (Orderly), `M15_045`
(Sheriff, and it sets `Got_UFO` next to Polaroid inventory checks).

### Input commands

The command table is at `0x111C0348`, 94 entries of name pointers; the index is the
command id. Useful ones: `EXT_5` 28 (`[`), `EXT_6` 29 (`]`), `WEAPON_PREV` 57,
`WEAPON_NEXT` 58, `SKIP_CUTSCENE` 69, `WEAPON_1` 81, `CAMERA_Z` 21.

`WEAPON_NEXT` / `WEAPON_PREV` are **dead on PC** - scanning every call site that passes a
command id, ids 57 and 58 are never asked about, while 28/29 are asked about dozens of
times. Weapon cycling is `[` and `]`.

Mouse: DirectInput `c_dfDIMouse` (data format at `0x110DB694`, device setup at
`0x10A43490`) - 3 axes and **4 buttons only**. `BUTTON_3` is the first side button and
is the last one the engine can see. Binding the wheel axis (`AXIS_Z`) to a non-camera
command did not work in any range tried.

---

## Health lock (2026-09-20) - works

Alex's health is `player+0x164` (float), maximum at `player+0x168`, player =
`[[0x1158982C]+4]`. It does not regenerate: it sat at exactly 98.0 for as long as it was
watched.

The engine applies **every** health change through one instruction. Found by putting a
hardware write watchpoint on the health field and taking hits until it tripped - four hits,
the same address every time, with the values walking down 150 → 135 → 125 → 115 → 100:

```
1031F105  movss xmm0, [esi+0x164]    ; current health
1031F10D  cvtps2pd xmm0, xmm0
1031F114  addsd xmm0, xmm2           ; += delta   (negative when damaged)
1031F118  cvtpd2ps xmm0, xmm0
1031F11C  movss [esi+0x164], xmm0    ; store back   <- 8 bytes, F3 0F 11 86 64 01 00 00
```

Replacing that store with eight `0x90` makes health read-adjust-discard, so the field keeps
its value. Verified in play: the user took repeated melee hits with the store nopped and
health held at exactly 100.00.

Shipped as a **runtime** toggle in the GUI's PRACTICE section (`Services/HealthLock.cs`) -
memory only, nothing written to disk, gone when the game exits. Two limits worth repeating
to anyone using it: it blocks **healing** as well, since that is the same instruction; and
it only guards this path.

**Scripted attacks still get through - user-confirmed 2026-09-20.** So those run their
damage or death through a different path than `0x1031F11C`. If a full lock is ever wanted,
that path has to be found the same way: hardware write watchpoint on `player+0x164`, then
take a scripted hit and see which instruction fires.

Method note: a *held write* proves nothing here (see the position-warp and save-point dead
ends, where writes held and changed nothing). What proved this field real was the watchpoint
catching the game itself writing decreasing values into it as damage landed.

## Quicksave / practice checkpoints (2026-09-19)

> **Removed from the toolkit 2026-09-20.** The checkpoint key worked exactly as
> described below and was still not useful: it records no position, so it does not do
> what a practice quicksave needs to do. The research stays here because it is what
> ruled the approach out.

**What works:** `SaveCheckpoint`, a script command the engine already has:

```
mgr = [0x116C1020];  if (mgr) mgr->SaveCheckpoint()      ; 0x10991560
```

Called from a per-frame hook it ran repeatedly with no crash, and it sets the checkpoint
the game restores you to. It writes **nothing to disk** - the save file's mtime and md5
were unchanged after it ran (verified twice).

**What does not work: a real save from arbitrary places.** The save menu, once you pick a
slot and confirm the overwrite, runs this at `0x10943D59`:

```
mgr  = [0x116C1020];  val = [mgr+0x16C]
prof = [[0x116C4130]+8]
prof->SaveToSlot(slot, val)      ; 0x100076B2, callee-cleanup
[0x116C4130]->flush()            ; 0x10028EB6
```

It needs no UI object, so it looks callable - and it is not. Called from the frame
limiter it crashed at the first instruction after the call, writing through a NULL
pointer (`+0x6C`, eax=ecx=0). The sequence is right but the *context* is wrong: that code
runs from the save screen, where the save session has been set up. The save file was not
touched or corrupted (verified against a backup).

The slot handlers are at `0x10948C0F`+ (`SaveFirstSlot` … `SaveFifthSlot` → slot index
0-4, second argument = "overwrite confirmed"). If this is picked up again, the route to
try is driving the game's own UI - push `SaveGameScreen` the way a save point does, from
the UI controller's context, rather than calling the writer directly.

### The slot writer does NOT write to disk (2026-09-20, debugger-confirmed)

Earlier notes treated `0x10943D59` as "the save writer". It is not. Live captures with a
breakpoint at `0x10943D6F` (the instruction that calls it) plus the disassembly show:

```
SaveToSlot  0x10A0C730 :  [profile+0x238] = slot
                          copy into the per-slot record at profile+0x190 + slot*32
                          ret 8                       <- memory only, no file I/O
"flush"     0x10A0BEA0 :  copies the unlock flags +0x230..+0x237   <- the costume bytes,
                                                                      nothing to do with saving
```

A hook was built that calls the slot *gate* `0x10943B90(this, slot, confirmed=1)` - which
does reach the real path, confirmed by the debugger (the capture's call chain contained the
stub's own return address `0x10D7143C`, with `edi=4` for slot 5 and a valid profile in
`ecx`). It ran 15 times with no crash and **wrote nothing**: `shv_save.bin` kept its md5.
A normal save at a save point, by contrast, rewrites the file within a second (verified by
md5 before/after). So the disk write is elsewhere and is almost certainly asynchronous -
consistent with the `IDS_SHELL_ACCESSING_SAVE_GAME` / `IDS_SHELL_SAVING` progress strings,
i.e. a job pumped by the save screen's own update loop, which does not exist during play.

**Do not call the gate from a frame hook.** After a save is *loaded*, `[[0x116C4130]+8]`
(the profile) is NULL for a while, and `SaveToSlot`'s first instruction writes through it:
the game died at `+0xA0C738` with `0xC0000005` exactly that way. If this is ever retried,
the next step is a breakpoint on `CreateFileW`/`WriteFile` during a normal save to find the
code that actually touches `shv_save.bin`, and then to see what pumps it.

### Dead end: moving a save point to the player (2026-09-20)

The idea was to let the engine do everything - put a save point where the player stands,
let its own trigger fire, and the real save menu opens with nothing injected. It does not
work, and the reason is worth recording.

Scanning committed private memory for the class vtables finds the level's trigger objects:

```
ISilentHillSavePoint   vtable 0x1107BA50     (church: object 0x257F4280)
ISilentHillCheckpoint  vtable 0x1107B788     (5 volumes in the same level)
```

The save point's transform translation is at `+0x1D0` (rotation rows `+0x1A0/+0x1B0/+0x1C0`,
the same hkTransform layout as the player), and `+0x0A8` points to a heap block holding a
second copy of the position at `+0x20`. **Both can be written and both hold** - nothing
rewrites them. And it changes nothing: with both copies moved 311 units away, the symbol
and its working trigger stayed exactly where they started (user walked into the original
spot and the real SAVE GAME menu opened normally). Those two are readback copies, exactly
like the player's `+0x780` and `[player+0xC4]+0x1D0`.

A third copy is the authority and was never found. An exact float search for
`(477.0, y, -1320.0)` across all committed private memory returns **only those two**, so
the authority does not store the position as plain floats - consistent with it living in
the Havok broadphase, which stores **quantized** AABBs. A derived bound at a nearby heap
block (`0x2647C7E0` in that session) is rewritten every frame and always snapped back to
the un-moved location, which is what exposed the third source in the first place.

Two other routes were closed at the same time:

* **There is no "you can stand here and save" flag.** Sampling `.data` (6 MB), the player
  object, the manager and the save point object while the player repeatedly walked in and
  out of the save zone, keeping only fields consistent across every near sample and every
  far sample: one candidate survived the first run (`0x11728390`, 0 inside / 5 outside) and
  did **not** survive a second run with more crossings. Its single xref is `cmp [count], 0`
  in an SSE loop - a scene count that happens to differ by location. Nothing tracks the
  save zone.
* **The save-flow object does not exist until the save UI is open.** `PlayerWantedToSave`
  (string `0x110718A4`) is dispatched by `HandleUIEvent` at `0x109488B0`
  (`__thiscall`, event passed as a 12-byte value struct; `[eax+4]` is the hash), and
  resolves to a plain function at `0x10943120` that could simply be called with the right
  `this`. But that class (vtable `0x11070D6C`, the event-send wrapper at slot 13) has
  **zero live instances** while the game is in play - the one scan hit was `6C 0D 07 11`
  occurring inside XML text in the heap. The object is built when the screen opens, so
  calling it to open the screen is circular.

Method note: the script that first "confirmed" the symbol had followed the object was
comparing the player's position against a value it had itself just written there, so it
could only ever agree. The user caught it ("no bro i walk into the save symbol where its
usually is located"). Any check of the form "did X move?" must compare against something
the experiment did not write.

### The hook technique (reusable)

* hook site: the frame limiter `0x10A4CC90` - `push ebx/ebp/esi/edi` + a **relative**
  `call 0x10007095`. Copying those bytes to a cave silently breaks the call: re-encode it
  for the new address (this bit me once; the disassembly caught it).
* cave: `0x10D71600`, unused `0xCC` padding, clear of the crash-guard stub (`0x10D71500`)
  and the speed-patch cave (`0x10D71300`).
* key polling: `GetAsyncKeyState` is imported at IAT slot `0x117EEF30`. Its low bit
  ("pressed since last call") proved unreliable here; edge-detect with your own byte
  instead. `.text` is read-only at runtime, so keep that state in a page from
  `VirtualAllocEx` - which also suits a runtime-only tool, since it dies with the process.
* suspend every game thread around the write: the hook site executes every frame.
* instrument first. Counting frames / presses / calls in that scratch page is what showed
  the hook was live but the key was never seen, and later that the call ran and returned.

**Gotcha:** the game barely ticks while it is not the foreground window, so counters look
frozen while the player is alt-tabbed talking to you. That is not a broken hook.

---

## Hard-won gotchas — read before measuring anything

These cost real time last session. Do not rediscover them.

1. **The game stops ticking when its window loses focus.** Every frame-rate
   reading will be `0.00` or nonsense unless focus is forced immediately before
   sampling. `tools/shh_measure.py` does this.
2. **Run WINDOWED for any measurement.** In exclusive fullscreen the game
   minimises the moment a console takes focus, and then it isn't rendering.
   Set `FullScreen=false` in `vars_pc.cfg` for test runs.
3. **The engine's own FPS floats (`stats+0x32C`) go STALE.** They keep returning
   the last computed value forever when the game is idle. This is actively
   misleading — it looks like a working measurement and reports a plausible
   `29.90`. Use the frame counter at `0x111C14FC` against a wall clock instead.
4. **The game rewrites `vars_pc.cfg` on exit.** If you edit the cfg while it is
   shutting down, your edits get clobbered. Edit only when it is fully closed,
   and re-read the file to confirm.
5. **Windows locks the .sgl while the game runs** — patching fails with a
   sharing violation. Close the game first.
6. **`Win32_VideoController.CurrentRefreshRate` lies.** It reported `119` while
   NVIDIA Control Panel showed `120 Hz`. Read the refresh rate from NVCP.
7. **Watch for a driver-level FPS cap.** The test machine had a 120 FPS limit in
   the NVIDIA app *and* a 120 Hz display — indistinguishable, which is why the
   true ceiling is still unknown. Clear both before measuring headroom.
8. **Crash dumps ROTATE at 10.** `%LOCALAPPDATA%\CrashDumps` keeps the 10 most
   recent, so a new crash *replaces* an old one and the file count stays at 10.
   A watcher that polls the count will never fire — watch the newest mtime, or
   the Application event log, instead. This silently missed a live crash.
   **Hangs leave no dump at all** — they exist only as event 1002 / WER
   `AppHangB1`, and were invisible until queried for explicitly. Query both
   before claiming anything about stability. Session uptime at a crash is free
   evidence too: WER's "Faulting application start time" vs the event timestamp.
9. **Never fight the game over its window style — patch how it creates the
   window.** External restyling looks right on screen, but each restyle makes
   this engine re-run video setup: it correlated with 4 hangs and a load-time
   crash, and a bounded retry budget did not save it. `shh_borderless_patch.py`
   sets the style at `CreateWindowExA` instead. Generalise: change the program's
   own constants rather than racing it from outside.
10. **`GetWindowLongW` returns 0 for a dead handle**, which naively reads as
   "no caption, no frame" = borderless. Always `IsWindow()` first, or a window
   that just vanished looks like a successfully styled one.
11. **Static offset scanning does not work on this binary.** Searching for
   `[reg+0xE4]` style accesses returned 445 hits, nearly all unrelated structs.
   What worked: sample the live process, find the blocked thread, walk its
   stack. Two steps, done in minutes. Reach for `tools/shh_profile.py` first.

---

## Tooling

`tools/` (stdlib only, except `--dis` which wants `pip install capstone`):

| Tool | Use |
|---|---|
| `shh_mem.py` | Shared library: process read/write, engine object resolution, all known addresses as constants |
| `shh_measure.py` | Reliable FPS measurement; `--ab` live-patches to A/B two caps without restarting; `--set N` changes the cap in-process |
| `shh_profile.py` | `--sample` histograms EIP across all threads; `--stack` walks the busiest thread for in-module return addresses. **This is what found the limiter.** |
| `shh_static.py` | Offline: `--sections`, `--strings REGEX`, `--xref VA`, `--float V`, `--imports`, `--dis` |
| `cvars.json` | All 91 cvars mapped to settings-object offsets |

Typical loop:

```bash
# 1. see where time goes
python tools/shh_profile.py --sample
# 2. get the call chain out of whatever is blocking/hot
python tools/shh_profile.py --stack
# 3. look the addresses up (VA = 0x10000000 + offset)
python tools/shh_static.py --dis 0xA4CC90 --len 0xA8
# 4. change something live and measure it
python tools/shh_measure.py --set 144
python tools/shh_measure.py
```

### Ghidra

Project at `ghidra/SHH.gpr`, ~937 MB, module already analyzed (93,595 functions).
Gitignored — rebuild if lost:

```bash
"<ghidra>/support/analyzeHeadless.bat" "<repo>/ghidra" SHH \
    -import "<repo>/work/g_SilentHill.sgl" -loader PeLoader
```

Notes: the Ghidra MCP bridge could not *create* a project (no such tool), and its
`open_project` talked to a headless server rather than the running GUI. Working
sequence was: create the project with `analyzeHeadless`, then launch
`ghidraRun.bat "<path>/SHH.gpr"` so the GUI owns it, then `open_program`.
`ghidraRun.bat` never exits — start it in the background.

---

## Next issues: where to start

### True frame-rate ceiling *(quickest win, finishes the current thread)*
Clear the NVIDIA app frame cap **and** change the display refresh rate, so vsync
and the driver cap can be told apart. Then `--uncap` and measure. Also settles
whether the `vsync` cvar does anything, which is currently unknown.

### Crashes
Highest value for players and speedrunners. Approach:
- Reproduce with the game under a debugger and catch the first-chance exception.
  Ghidra's debugger is available, or WinDbg.
- The `buglog` cvar (`+0x55`) and `Message.log` may already be recording
  something — `Message.log` is overwritten each launch, so copy it after a crash.
- The engine streams from `Engine\pak` ("Pak Mode", `streaming.log`); streaming
  and level-transition code is a prime suspect given crashes are reported at
  "many different points".
- Worth checking whether crashes correlate with the now-raised frame rate.

### Lag / stutter
`tools/shh_profile.py --sample` during a known-bad section. `AutoDownResTextures`
and `LowQualityShaders` cvars exist and may be mis-driven on modern hardware.

### Map
Start with `python tools/shh_static.py --strings "map|Map"` and the UI/XML assets
(`Engine\assets_pc_b.xml`, `Interface\LoadingScreen.xml` referenced from
`default_pc.cfg`). Symptom needs pinning down first — the thread just says "the map".

### Controls / mouse
`mousespeed`, `controlscheme`, `cameraInvert*` cvars are all registered; bindings
live in `Engine\binds_pc_mjs.cfg`. Check whether mouse input is sampled per-frame
(now that frame rate changed, sensitivity may scale with it — a classic bug and
worth testing right after the FPS patch).

### Unskippable cutscene (~7 min)
Cutscenes are Bink video (`binkw32.dll`, `Engine\movies`). Find the playback call
and whether an input check exists but is disabled on PC. `logCinematics` cvar
exists. This is the single biggest speedrun time loss vs Xbox 360.

---

## Open questions

- How high can the engine actually go? Untested above 120 FPS.
- Does the `vsync` cvar do anything at all, or is it dead like `fpsLimit`?
- Is any game logic frame-rate dependent? Only the opening area was tested. The
  tick uses delta time and clamps `dt` to 0.08 s, which is reassuring but not
  proof. Needs a longer playthrough, especially physics and scripted sequences.
- Do the 22 cvars with unresolved offsets in `cvars.json` matter? They use a
  registration form the parser did not match.
