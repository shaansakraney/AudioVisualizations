# audioviz — audio-reactive visuals starter

A tiny, clean playground for building audio-reactive visuals, sized around a
small TFT screen so the effects will port later. It renders to a fixed
1920x1080 logical canvas and scales it into a desktop window via pygame.

## Setup

```bash
cd audioviz
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

`sounddevice` needs PortAudio under the hood. If pip doesn't pull it in
automatically: macOS `brew install portaudio`, Debian/Ubuntu
`sudo apt install libportaudio2`. If it's missing, resting mode still works —
`sounddevice`/`soundfile` are imported lazily.

## Run

```bash
python run.py                             # resting/idle mode — no audio hardware needed
python run.py --source mic                # microphone (default input device)
python run.py --source line --device 2    # line-in / a specific input
python run.py --source wav --wav song.wav # play + react to a wav file, in sync
python run.py --list-devices              # find your input device index
```

Start with `python run.py` — resting mode works with zero setup and shows the
orb breathing, so you can confirm rendering works before touching audio.

For `--source wav`, drop files into an `AudioFiles/` folder next to `run.py`
(create it if it doesn't exist) and pass just the filename — `--wav song.wav`
finds `AudioFiles/song.wav` automatically. That folder is gitignored, so your
music never ends up in version control.

## Controls

- `1`–`9` — switch scene (currently: `1` pulse, `2` bars, `3` lightning,
  `4` cymatics, `5` spectrum, `6` nebula)
- `h` — toggle the debug HUD (fps + live feature readout + beat dot)
- `esc` / window close — quit

The HUD is your quickest sanity check: play music into the mic or load a wav
and watch the rms / bass / mid / treble numbers move.

## How it fits together

```
audio source  →  FeatureExtractor  →  Features  →  Scene.draw()  →  canvas → window
(mic/line/wav/resting)               (the contract)
```

- `features.py` — `Features` (the contract) + `FeatureExtractor` (FFT bands,
  a 6-bin log-spaced spectrum, spectral centroid, envelope smoothing,
  auto-gain, beat detection). The most reusable file; this is the logic
  you'd eventually re-implement on the MCU.
- `audio.py` — three sources (`LiveAudioSource`, `WavSource`,
  `RestingSource`), all emitting `Features`. Resting mode fakes the contract
  from LFOs, so scenes don't care whether audio is real.
- `scene.py` / `scenes.py` — the visual interface and the starter scenes:
  Pulse, Bars, Lightning, Cymatics, Spectrum, Nebula.
- `fx.py` — shared rendering/math helpers (color, particles, lightning
  geometry, procedural fields) the scenes build on.
- `app.py` — pygame loop, upscaling, HUD, scene switching.
- `run.py` — argument parsing, `AudioFiles/` wav lookup, and scene registration.

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
        # f.bands is a 6-tuple, low -> high frequency, 0..1 each
        # f.beat is True on the beat frame; f.beat_strength decays after
        ...
```

Then add it to the list in `run.py`: `scenes = [PulseScene(), BarsScene(), MyScene()]`.
It's now on the next number key, and it reacts to mic, line-in, wav, and
resting sources automatically since every source emits the same `Features`
contract.

## Tuning

Most knobs live at the top of `FeatureExtractor` in `features.py`:
envelope `ATTACK`/`RELEASE` (jittery vs smooth), `BEAT_SENSITIVITY`/`BEAT_FLOOR`
(beat detection), the 3-band frequency ranges (`BANDS`), and the 6-bin spectrum
range (`N_BANDS6`/`BAND6_RANGE_HZ`). The beat detector is deliberately simple —
good enough to build against, worth upgrading later.
