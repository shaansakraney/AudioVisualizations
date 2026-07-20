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
python run.py --list-devices              # find your input device index
```

There is no test suite, linter, or build step in this repo. Verify changes by running the app and watching the debug HUD (`h` key) — it shows fps, source, scene, and live rms/bass/mid/treble/centroid readouts, plus a beat indicator dot.

Controls: `1`-`9` switch scene, `h` toggles HUD, `esc`/window close quits.

## Architecture

Data flow is a strict one-way pipeline:

```
audio source  →  FeatureExtractor  →  Features  →  Scene.draw()  →  canvas → window
(mic/line/wav/resting)               (the contract)
```

- **`features.py`** — the core reusable logic, meant to be the part eventually reimplemented on an MCU. `Features` (dataclass) is the universal contract every scene consumes: `rms`, `bass`, `mid`, `treble`, `centroid` (all 0..1, smoothed + auto-gained), plus `beat`/`beat_strength`/`t`. `FeatureExtractor` does FFT band analysis, auto-gain (adaptive running peak per feature), an attack/release envelope follower, and simple energy-based beat detection on the bass band. `push()` is called from the audio callback thread; `read()` is called once per frame from the render thread — the two are separated by a lock. Tuning knobs (`FFT_SIZE`, `BANDS`, `ATTACK`/`RELEASE`, `PEAK_DECAY`, `BEAT_SENSITIVITY`/`BEAT_FLOOR`/`BEAT_REFRACTORY`) live as class constants at the top.
- **`audio.py`** — four interchangeable sources, all exposing `start()` / `read(dt) -> Features` / `stop()`: `LiveAudioSource` (mic/line-in, same code path, device index picks the input), `WavSource` (plays a wav out loud and analyzes the same audio in the output callback so visuals stay locked to what's heard; loops forever), and `RestingSource` (no hardware — synthesizes idle motion from incommensurate LFOs so scenes work unchanged with zero setup). `sounddevice`/`soundfile` are imported in `try`/`except` so `RestingSource` works without the audio stack installed.
- **`scene.py`** — the `Scene` interface: `update(f, dt)` advances animation state, `draw(surface)` does pure rendering onto the logical canvas. Keeping these separate makes scenes swappable.
- **`scenes.py`** — starter scenes: `PulseScene` (breathing orb — radius from bass+rms, hue from centroid, beat triggers expanding rings) and `BarsScene` (three band bars + rms line + beat flash; the "is the pipeline alive" diagnostic view).
- **`app.py`** — the pygame render loop. Owns `CANVAS_W`/`CANVAS_H`/`SCALE`/`FPS` constants, draws to a fixed-size logical `Surface`, then nearest-neighbour-scales it into the actual window so pixel-art-style effects stay crisp and behave the same at the eventual target resolution. Also owns scene switching (number keys) and the debug HUD overlay.
- **`run.py`** — argument parsing (`--source`, `--wav`, `--device`, `--list-devices`) and the scene registry (order in the `scenes` list maps to number keys 1-9).

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
