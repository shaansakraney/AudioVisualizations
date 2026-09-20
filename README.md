# audioviz — audio-reactive visuals, on a screen and on a light strip

A small, clean playground for building audio-reactive visuals. Audio comes in
from a mic, a line-in, a wav file, or your computer's own output; it becomes a
single set of normalized features; and scenes turn those into something to
look at — on screen, on an LED strip, or both at once.

The feature pipeline is deliberately sized to be re-implementable on a
microcontroller later, so it stays small, allocation-light and free of any
dependency on pygame.

## Setup

```bash
cd audioviz
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

`sounddevice` needs PortAudio under the hood. If pip doesn't pull it in
automatically: macOS `brew install portaudio`, Debian/Ubuntu
`sudo apt install libportaudio2`. If it's missing entirely, resting mode still
works — `sounddevice` and `soundfile` are imported lazily.

## Run

```bash
python run.py                             # resting/idle mode — no audio hardware needed
python run.py --source mic                # microphone (default input device)
python run.py --source line --device 2    # line-in / a specific input
python run.py --source wav --wav song.wav # play + react to a wav file, in sync
python run.py --source loopback --spotify # react to Spotify + use its album art
python run.py --list-devices              # find your input device index
```

Start with `python run.py`. Resting mode works with zero setup and synthesizes
its own motion, so you can confirm rendering works before touching audio.

For `--source wav`, drop files into an `AudioFiles/` folder next to `run.py`
(create it if it doesn't exist) and pass just the filename — `--wav song.wav`
finds `AudioFiles/song.wav` automatically. That folder is gitignored, so your
music never ends up in version control.

Two headless tools, neither of which opens a window:

```bash
python nowplaying.py                  # print the current Spotify track + palette
python tools/analyze_wav.py song.wav  # measure the loudness pipeline (see Tuning)
python tools/led_monitor.py           # a fake LED strip in your terminal
```

## Controls

| key | |
|---|---|
| `1`–`9` | switch scene — `1` pulse, `2` spectrum, `3` cymatics, `4` constellation, `5` chasm, `6` vortex, `7` resonance, `8` cartograph, `9` lattice |
| `h` | toggle the debug HUD (fps, live feature readout, auto-gain state, beat dot) |
| `l` | toggle the LED panel — tune the strip live ([below](#tuning-the-strip-the-l-panel)) |
| `f` | toggle fullscreen |
| `esc` | leave fullscreen, or quit if already windowed |

The window is freely resizable, and the image always keeps its 16:9 shape —
odd window sizes get black letterbox bars rather than a stretched picture. For
a TV, `--fullscreen --display 1` opens directly on the second monitor:

```bash
python run.py --fullscreen                  # fill the main screen
python run.py --fullscreen --display 1      # fill the TV
python run.py --scale 1.0                   # start at a 1920x1080 window
```

### Image quality

The render resolution follows the window — make the window bigger and you get
more detail, not a blurrier picture. There is normally no canvas-to-screen
rescale at all.

On top of that, each scene declares how much supersampling (SSAA) it needs,
because pygame draws rects and polygons with no anti-aliasing of its own.
`spectrum` and `cartograph` are the hard-edged ones and render at 2x;
everything else relies on its own soft falloff and renders at 1x.
`--supersample` multiplies whatever each scene asks for:

```bash
python run.py                     # --supersample 2, the default
python run.py --supersample 1     # each scene's own setting, nothing more
python run.py --supersample 3     # maximum quality, needs headroom
python run.py --canvas 1920x1080  # pin a fixed logical size instead
```

Note that these multiply: at the default `--supersample 2`, `spectrum` renders
at 4x the window's pixel count. `MAX_CANVAS_PX` in `app.py` caps the result so
a 4K fullscreen can't ask for an 8K render target.

The HUD (`h`) shows the live render resolution and fps. If a scene drops frames
on your machine, the per-scene dials are documented at the top of each class in
`scenes.py` — `FIELD_MAX_PX` for cymatics, and `MAX_SPLAT_PX` / `DOT_RADIUS` /
`KERNEL_R` / `GLOW_DOWNSCALE` for the six 3D scenes.

The HUD is also your quickest sanity check: play music into the mic or load a
wav and watch the rms / bass / mid / treble numbers move.

## The scenes

Nine are registered, on the nine number keys. Six of them are the same 3D
substrate seen from different angles.

| | |
|---|---|
| **pulse** | breathing orb; radius from bass+rms, beats trigger expanding rings. Optionally becomes the album cover. |
| **spectrum** | one bar per spectrum bin, growing symmetrically from a center line |
| **cymatics** | nodal standing-wave interference patterns, one mode per band |
| **constellation** | X = frequency, Y = level, Z = time — each older spectrum drifts back toward a vanishing point |
| **chasm** | constellation mirrored about the horizon into a corridor |
| **vortex** | the same history as rings receding down a tunnel |
| **resonance** | cymatics in 3D: a sphere of points displaced by the standing-wave sum |
| **cartograph** | hidden-line ridgelines — an animated *Unknown Pleasures* plot |
| **lattice** | a fixed 3D grid with band-driven plane waves sweeping through it while the camera orbits |

`BarsScene`, `LightningScene` and `NebulaScene` are still in `scenes.py` but
aren't registered — there are only nine number keys. Swap one into the list in
`run.py` if you want it.

### Colors

Most scenes take their palette from one registry, `SPECTRUM_COLOR_SCHEMES` in
`scenes.py`: `blue_pink`, `rainbow`, `reactive`, `fire`, `me1`, `me2`, `drift`,
`centroid`, `album`. A scheme is one function —

```python
def my_scheme(i, n, val, f, np_):   # bar index, bar count, level 0..1,
    return (r, g, b)                # Features, NowPlaying-or-None
```

— so writing one and listing it in the registry reaches `spectrum`, `pulse`,
`constellation` and the rest of the 3D family at once. `cymatics` has its own
registry for field-based coloring, which also mirrors every spectrum scheme as
`spectrum:<name>`, so a scheme added in one place shows up in all of them.

Pick one per scene with its `COLOR_SCHEME` class attribute.

## Spotify (album art + colors)

`--spotify` pulls the currently-playing track's cover art and color palette and
hands them to scenes as `Scene.now_playing`.

**It is opt-in per scene, and off by default.** Every scene ships with
`USE_ALBUM_COLORS = False` (and `PulseScene.USE_ALBUM_ART = False`), so out of
the box a track playing changes nothing on screen. Flip the switch on the scene
you want in `scenes.py`:

- `USE_ALBUM_COLORS = True` — the album palette overrides that scene's
  `COLOR_SCHEME` whenever a track is playing.
- `PulseScene.USE_ALBUM_ART = True` — the cover itself becomes the orb,
  circle-masked and scaled by the same bass+rms radius.

They're separate switches on purpose, so "cover art, but my colors" and "my own
disc, tinted by the album" are both reachable.

**Important:** Spotify's API does not expose the audio stream, so `--spotify`
only supplies art and color — the reactivity still comes from whatever
`--source` you pick. (Spotify also deprecated its Audio Analysis / Audio
Features endpoints for new apps in Nov 2024, so there's no beat grid to fetch
either; `FeatureExtractor` remains the beat source.) That means you want two
things at once: `--spotify` for the art, and an audio source that hears
Spotify.

### Hearing Spotify — the loopback device

macOS gives no way to capture system output without a virtual audio driver:

```bash
brew install blackhole-2ch
```

Then open **Audio MIDI Setup** → **+** → *Create Multi-Output Device* → tick
both your speakers and **BlackHole 2ch**, and select that as your system
output. You may have to restart if it doesn't show up immediately. Now audio
still plays out loud *and* is readable as an input. `--source loopback` finds
BlackHole automatically (`--list-devices` tells you whether it was detected).

No loopback driver? `--source mic` works fine — play out loud and let the mic
hear it. `--source loopback` falls back to the mic automatically when it can't
find a loopback device.

#### Your volume keys while the visuals run

A Multi-Output Device exposes **no master volume**, so while it is selected the
keyboard volume keys and the menu-bar slider do nothing and the level is
whatever the speakers were last set to — which feels exactly like being muted
even though BlackHole is getting full-scale audio. That is the device, not a
broken setup.

So don't live on Multi-Output; borrow it for the run:

```bash
brew install switchaudio-osx
```

`--source loopback` then switches the system output to `Multi-Output Device`
on start and puts your old output back on exit (including on Ctrl-C), so the
volume keys work again the moment the window closes.

```bash
python run.py --source loopback --spotify              # automatic
python run.py --source mic --switch-output             # any source, on demand
python run.py --switch-output "Some Other Device"      # a different target
python run.py --source loopback --switch-output=none   # leave my output alone
```

Without switchaudio-osx installed it prints the hint above once and carries on,
and you pick the output in the menu bar yourself. While you *are* on
Multi-Output, app-level volume still works — use Spotify's own slider or the
speaker's control.

### Getting the metadata

Two backends, selected with `--spotify-source`:

- **`applescript`** (default) — talks to the local Spotify desktop app. No
  developer account, no OAuth, nothing to configure. macOS only, and only
  sees playback from the desktop app. Polling never launches Spotify.
- **`web`** — the Spotify Web API. Works cross-platform and sees playback on
  any device (including your phone). Register a free app at
  [developer.spotify.com](https://developer.spotify.com/dashboard), add
  `http://127.0.0.1:8888/callback` as a redirect URI, then:

  ```bash
  export SPOTIFY_CLIENT_ID=your_client_id
  python run.py --source loopback --spotify --spotify-source web
  ```

  It opens a browser once for consent and caches the refresh token in
  `.spotify_token.json` (gitignored).

Quick check without opening a window:

```bash
python nowplaying.py            # prints the current track + its palette
```

## LED strip output

Drive a real LED strip in sync with what's on screen. The computer decides all
the colors — including the Spotify album palette — and streams finished frames
over WiFi to an ESP32, which is a dumb driver. So palettes and reactivity are
tuned in Python with no reflashing, and if frames stop the sketch falls back to
its own idle animation.

```bash
# 1. try it with no hardware: a fake strip in your terminal
python tools/led_monitor.py                                # terminal A
python run.py --leds udp://127.0.0.1:4210 --led-count 16    # terminal B

# 2. the real thing (the sketch prints its IP over serial on boot)
python run.py --source loopback --spotify \
              --leds udp://audioviz.local:4210 --led-count 60

# USB instead of WiFi (needs: pip install pyserial)
python run.py --leds serial:///dev/tty.usbmodem1101 --led-count 60
```

`--led-count 1` is the right setting for an analog 12V RGB strip, which shows
one color end to end; `LedSink` averages a scene's colors down to it. Scenes
never know the strip length — they return however many pixels are natural for
them and `LedSink` resamples, which is what makes a 1-pixel analog strip and a
300-LED WS2812 the same code path.

Every registered scene lights the strip with its own colors, so screen and
strip never diverge. A scene that defines no `led()` falls back to a default
color derived from `Features`. Don't add a beat flash inside `led()` — the sink
pulses every frame it sends.

### Tuning the strip: the `l` panel

A strip is a light in a room, not an image on a screen — it has to be tuned
against your actual wall, with the music playing. Press `l` for a panel of
knobs; `↑`/`↓` pick one, `←`/`→` adjust it (hold shift for a 5x step), `s`
saves, `r` resets.

| | |
|---|---|
| **brightness, floor, gamma** | how bright, and how dim a quiet moment is allowed to get before the strip switches off |
| **gain, contrast** | how far the strip swings with the music — contrast above 1 keeps a verse dark so a drop can hit |
| **attack, release** | how fast it brightens and how slowly it falls |
| **beat gain, beat white** | the snap on each beat |
| **scheme, saturation, hue shift** | `scene` mirrors whatever palette the running scene uses; pick any `SPECTRUM_COLOR_SCHEMES` name to override it everywhere |
| **reverse, mirror, offset** | which way round the strip runs, and where its middle is |

These settings are **global, not per-scene** — the point is tuning *the light*,
so an adjustment holds across all nine scenes. They save to `led_profile.json`
next to `run.py` (gitignored; `--led-profile PATH` picks a different one), and
load automatically next time. A fresh profile is a no-op: out of the box the
strip behaves exactly as it did before the panel existed.

**Setting up a board? [`firmware/QUICKSTART.md`](firmware/QUICKSTART.md)** is
the linear checklist, from flashing to the board on a wall socket. **Wiring,
sketches, and a troubleshooting table live in
[`firmware/README.md`](firmware/README.md)** — read it before ordering parts.
Two things bite people: analog strips need *logic-level* MOSFETs (IRLZ44N, not
IRF540) because ESP32 GPIO is only 3.3V, and WS2812 data may need a 74AHCT125
level shifter.

## How it fits together

Two independent inputs, two independent outputs, one contract in the middle.

```
audio source  →  FeatureExtractor  →  Features ─┬─→  Scene.draw()  →  canvas → window
(mic/line/wav/resting/loopback)      (the contract)  ↑
                                                │    │
Spotify  →  NowPlayingProvider  →  NowPlaying  ─│────┘
(metadata)  (background thread)    (art + palette, via Scene.now_playing)
                                                │
                                                └─→  Scene.led(f) → LedSink → ESP32 → strip
                                                          ↑          (background thread)
                                                     LedProfile (the `l` panel)
```

Audio drives motion; Spotify drives color and imagery. `Features` stays
audio-only on purpose — it's the part meant to be ported to a microcontroller —
so album art rides the separate `Scene.now_playing` channel.

| file | |
|---|---|
| `features.py` | `Features` (the contract) + `FeatureExtractor`: FFT bands, a 24-bin log-spaced spectrum, spectral centroid, envelope smoothing, auto-gain, beat detection. The most reusable file. |
| `audio.py` | the sources — `LiveAudioSource` (mic/line/loopback), `WavSource`, `RestingSource` — all emitting `Features`, plus `resolve_wav()` and `find_loopback_device()` |
| `nowplaying.py` | the second, independent input: Spotify track metadata and cover art, polled on a background thread |
| `scene.py` | the `Scene` interface: `update`, `draw`, optional `led`, `SUPERSAMPLE` |
| `scenes.py` | the scenes themselves, and the color-scheme registries |
| `fx.py` | shared rendering/math helpers scenes compose: color, particles, procedural fields, album-art palette extraction, and the 3D point-cloud stack |
| `led.py` | the second output: `LedSink` resamples, smooths, pulses, gamma-corrects and streams frames on its own thread, so the render loop never blocks on I/O |
| `ledprofile.py` | the strip's own dials, applied by `LedSink`, edited from the `l` panel, saved to `led_profile.json` |
| `app.py` | the pygame loop, canvas sizing, HUD, LED panel, scene switching |
| `run.py` | argument parsing and the scene registry |
| `tools/` | `led_monitor.py` (fake strip in the terminal), `analyze_wav.py` (loudness measurement) |
| `firmware/` | two ESP32 sketches sharing a byte-identical `av_proto.h` |

## Add your own scene

```python
# in scenes.py
class MyScene(Scene):
    name = "myscene"
    def update(self, f, dt):
        self.f = f
    def draw(self, surface):
        w, h = surface.get_size()
        surface.fill((0, 0, 0))
        # f.bass / f.mid / f.treble / f.rms / f.centroid are 0..1
        # f.bands is a 24-bin spectrum, low -> high frequency, 0..1 each
        # f.beat is True on the beat frame; f.beat_strength decays after
        ...
    def led(self, f):                  # optional -- LED strip output
        return [(255 * f.bass, 0, 255 * f.treble)]   # any length; resampled
```

Then add it to the list in `run.py`, which maps one-to-one onto the number
keys:

```python
scenes = [PulseScene(), SpectrumScene(), CymaticsScene(),
          ConstellationScene(), ChasmScene(), VortexScene(),
          ResonanceScene(), CartographScene(), MyScene()]
```

It reacts to mic, line-in, wav, loopback and resting sources automatically,
since every source emits the same `Features` contract. Check `fx.py` before
building a new visual primitive — the 3D scenes in particular are projections
over a shared substrate (`SpectrumHistory`, `PointCloud`, `perspective`), so a
new one of those is usually a `_project()` method, not a renderer.

## Tuning

### Loudness and dynamics — `features.py`

The knobs live as class constants at the top of `FeatureExtractor`: `FFT_SIZE`,
the three band ranges (`BANDS`), the spectrum resolution
(`N_SPECTRUM_BINS` / `SPECTRUM_RANGE_HZ`), envelope `ATTACK`/`RELEASE`, the
beat detector (`BEAT_SENSITIVITY` / `BEAT_FLOOR` / `BEAT_REFRACTORY`), and the
auto-gain.

**The auto-gain is where loudness dynamics live or die**, and it is the one
thing here you should not tune by eye. It is a slow reference
(`REF_RISE_S` / `REF_FALL_S`) with a fixed dB window below it (`RANGE_DB`,
`HEADROOM_DB`) and a soft knee at both ends. The split is deliberate: the
reference absorbs *input gain*, which differs by tens of dB between a mic, a
line-in and a loopback, while the window maps *musical dynamics*, which is what
the visuals exist to show.

`RANGE_DB` is the knob to reach for, and it has to stay matched to how little
dynamic range modern masters actually use — measured on real tracks, the
4s-smoothed level moves only ~1.5–5 dB from a loud section to the loudest one.
Too wide and a drop is invisible; too narrow and half the frames sit on the
floor.

`tools/analyze_wav.py` exists for exactly this. It reads a file directly — no
audio device, no playback — and pushes a 4-minute track through the real
extractor in a couple of seconds:

```bash
python tools/analyze_wav.py song.wav             # summary table
python tools/analyze_wav.py song.wav --compare   # against the legacy auto-gain
python tools/analyze_wav.py song.wav --csv out.csv
```

The number to watch is **drop**: p95 minus p50 of the 4s-smoothed envelope, i.e.
how far a drop lifts above the loud section before it. Per-frame statistics
mislead — `beat` stayed healthy through the exact failure where buildups and
drops had become indistinguishable.

### Everything else

- **A scene's look** — class constants at the top of each scene in `scenes.py`,
  each documented where it's defined. Tune the 3D scenes by subclassing rather
  than mutating an instance; some geometry is precomputed in `__init__`.
- **The strip** — the `l` panel, live, saved to `led_profile.json`. Don't edit
  `ledprofile.py`'s defaults for taste; that's what the panel is for.
