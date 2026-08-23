# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A tiny, clean playground for building audio-reactive visuals, sized around a small TFT screen so effects will port to a microcontroller later. It renders to a logical canvas and scales it up to a desktop window via pygame.

## Setup and running

```bash
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

`sounddevice` needs PortAudio under the hood (macOS: `brew install portaudio`, Debian/Ubuntu: `sudo apt install libportaudio2`). If it's missing, resting mode still works — `sounddevice`/`soundfile` are imported lazily in `audio.py`.

```bash
python run.py                             # resting/idle mode — no audio hardware needed
python run.py --source mic                # microphone (default input device)
python run.py --source line --device 2    # line-in / a specific input
python run.py --source wav --wav song.wav # play + react to a wav file, in sync
python run.py --source loopback --spotify # react to Spotify + use its album art
python run.py --list-devices              # find your input device index
python nowplaying.py                      # print current Spotify track + palette
```

`--wav` accepts a bare filename and looks it up in `AudioFiles/` (created next
to `run.py`) if it isn't found as given — drop files there instead of typing
full paths. `AudioFiles/` is gitignored, so your music never ends up in git
history.

Spotify (`--spotify`) supplies **album art and colors only** — its API does not
expose the audio stream, and its Audio Analysis/Features endpoints were
deprecated for new apps in Nov 2024. Reactivity always comes from `--source`,
so pair `--spotify` with `--source loopback` (BlackHole; see README) or
`--source mic`. `--source loopback` falls back to the mic when no loopback
device is present.

There is no test suite, linter, or build step in this repo. Verify changes by running the app and watching the debug HUD (`h` key) — it shows fps, source, scene, and live rms/bass/mid/treble/centroid readouts, plus a beat indicator dot.

Controls: `1`-`9` switch scene, `h` toggles HUD, `esc`/window close quits.

## Architecture

Data flow is a strict one-way pipeline:

```
audio source  →  FeatureExtractor  →  Features  →  Scene.draw()  →  canvas → window
(mic/line/wav/resting/loopback)      (the contract)        ↑
                                                           │
Spotify  →  NowPlayingProvider  →  NowPlaying  ────────────┘
(metadata)  (background thread)    (art + palette, via Scene.now_playing)
```

The two inputs are independent: audio drives motion, Spotify drives color and
imagery. `Features` stays audio-only on purpose (it's the MCU-portable
contract), so album art rides the separate `Scene.now_playing` channel.

- **`features.py`** — the core reusable logic, meant to be the part eventually reimplemented on an MCU. `Features` (dataclass) is the universal contract every scene consumes: `rms`, `bass`, `mid`, `treble`, `centroid` (all 0..1, smoothed + auto-gained), `bands` (a 6-element tuple, a log-spaced 20Hz-16kHz spectrum for bar-style visualizers, same smoothing/auto-gain treatment), plus `beat`/`beat_strength`/`t`. `FeatureExtractor` does FFT band analysis, auto-gain (adaptive running peak per feature/band), an attack/release envelope follower, and simple energy-based beat detection on the bass band. `push()` is called from the audio callback thread; `read()` is called once per frame from the render thread — the two are separated by a lock. Tuning knobs (`FFT_SIZE`, `BANDS`, `N_BANDS6`/`BAND6_RANGE_HZ`, `ATTACK`/`RELEASE`, `PEAK_DECAY`, `BEAT_SENSITIVITY`/`BEAT_FLOOR`/`BEAT_REFRACTORY`) live as class constants at the top.
- **`audio.py`** — three interchangeable sources, all exposing `start()` / `read(dt) -> Features` / `stop()`: `LiveAudioSource` (mic/line-in/loopback, same code path, device index picks the input), `WavSource` (plays a wav out loud and analyzes the same audio in the output callback so visuals stay locked to what's heard; loops forever), and `RestingSource` (no hardware — synthesizes idle motion, including a fake 6-bin spectrum, from incommensurate LFOs so scenes work unchanged with zero setup). Also `find_loopback_device()`, which scans for BlackHole/Soundflower-style virtual inputs so `--source loopback` can capture system output. `sounddevice`/`soundfile` are imported in `try`/`except` so `RestingSource` works without the audio stack installed.
- **`nowplaying.py`** — the second input, parallel to and independent of the audio pipeline. `NowPlaying` (dataclass: `track_id`, `title`, `artist`, `art` Surface, `palette`, `accent`) is what scenes read off `self.now_playing`. Two interchangeable backends both exposing `poll()`: `AppleScriptBackend` (local Spotify desktop app, zero setup, macOS-only — and it checks System Events first so polling never *launches* Spotify) and `WebAPIBackend` (OAuth PKCE, cross-platform, needs `SPOTIFY_CLIENT_ID`). `NowPlayingProvider` polls on a daemon thread and downloads/analyzes art there; `read()` is a lock-guarded snapshot the render thread calls per frame and never blocks on I/O — the same split `FeatureExtractor` uses, and for the same real-time reason. All backend errors are swallowed so a Spotify hiccup can't take down the render loop.
- **`scene.py`** — the `Scene` interface: `update(f, dt)` advances animation state, `draw(surface)` does pure rendering onto the logical canvas. Also the `now_playing = None` class-attribute default that `App` fills in each frame. Keeping these separate makes scenes swappable.
- **`fx.py`** — shared rendering/math helpers scenes compose instead of re-deriving: color/scale helpers (`hsv`, `scale`, `aacircle`, `fade`, `scratch_surface`), a vectorized `Particles` system, lightning-bolt geometry, procedural field rendering (`field_grid`/`draw_field`), and album-art helpers (`palette_from_surface` k-means color extraction, `most_vivid`, `circle_masked`, `blurred_backdrop`). Check here before building a new visual primitive.
- **`scenes.py`** — `PulseScene` (breathing orb — radius from bass+rms, hue from centroid, beat triggers expanding rings; with a Spotify track the cover art *becomes* the orb, circle-masked, and the palette drives glow/rings/background), `BarsScene` (three band bars + rms line + beat flash; the "is the pipeline alive" diagnostic view), `SpectrumScene` (6-bin `f.bands` spectrum, bars growing symmetrically up/down from a center line, Apple-Music-style), `LightningScene` (beat-triggered branching bolts), `NebulaScene` (drifting glow-particle field), and `CymaticsScene` (nodal standing-wave interference patterns, one mode per band).
  - `SpectrumScene` color is pluggable: `SPECTRUM_COLOR_SCHEMES` maps a name to a `(i, n, val, f, np_) -> (r, g, b)` function, and `COLOR_SCHEME` picks one. `USE_ALBUM_COLORS` (default on) overrides that with the `album` scheme whenever a track is playing; `BAR_WIDTH_FRAC` sets bar width without moving bin centers. Add a scheme by writing the function and listing it in the registry.
- **`app.py`** — the pygame render loop. Owns `CANVAS_W`/`CANVAS_H`/`SCALE`/`FPS` constants (1920x1080 logical canvas, window at `SCALE`=0.5), draws to a fixed-size logical `Surface`, then nearest-neighbour-scales it into the actual window so pixel-art-style effects stay crisp and behave the same at the eventual target resolution. Also owns scene switching (number keys) and the debug HUD overlay.
- **`run.py`** — argument parsing (`--source`, `--wav`, `--device`, `--list-devices`, `--spotify`, `--spotify-source`), `--wav` path resolution against `AudioFiles/`, loopback fallback, and the scene registry (order in the `scenes` list maps to number keys 1-9).

## Adding a scene

Subclass `Scene` in `scenes.py`:

```python
class MyScene(Scene):
    name = "myscene"
    def update(self, f, dt):
        self.f = f
    def draw(self, surface):
        w, h = surface.get_size()
        surface.fill((0, 0, 0))
        # f.bass / f.mid / f.treble / f.rms / f.centroid are 0..1
        # f.beat is True on the beat frame; f.beat_strength decays after
        ...
```

Then register it in `run.py`: `scenes = [PulseScene(), BarsScene(), MyScene()]`. It reacts to mic, line-in, wav, and resting sources automatically since all sources emit the same `Features` contract.
