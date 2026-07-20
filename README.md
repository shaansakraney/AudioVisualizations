# audioviz — audio-reactive visuals starter (Phase 0 + 1)

A tiny, clean playground for building audio-reactive visuals on your computer,
sized around a small TFT screen so the effects will port later. It renders to a
240×320 logical canvas and scales it up to a window.

## Setup

```bash
cd audioviz
python -m venv .venv && source .venv/bin/activate   # optional but recommended
pip install -r requirements.txt
```

`sounddevice` needs PortAudio under the hood. If pip doesn't pull it in
automatically: macOS `brew install portaudio`, Debian/Ubuntu
`sudo apt install libportaudio2`.

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

## Controls

- `1`–`9` — switch scene (currently `1` pulse, `2` bars)
- `h` — toggle the debug HUD (fps + live feature readout + beat dot)
- `esc` / window close — quit

The HUD is your Phase 0 verification: play music into the mic or load a wav and
watch the rms / bass / mid / treble numbers move.

## How it fits together

```
audio source  →  FeatureExtractor  →  Features  →  Scene.draw()  →  canvas → window
(mic/line/wav/resting)               (the contract)
```

- `features.py` — `Features` (the contract) + `FeatureExtractor` (FFT bands,
  spectral centroid, envelope smoothing, auto-gain, beat detection). The most
  reusable file; this is the logic you'd eventually re-implement on the MCU.
- `audio.py` — the four sources, all emitting `Features`. Resting mode fakes the
  contract from LFOs, so scenes don't care whether audio is real.
- `scene.py` / `scenes.py` — the visual interface and two starter scenes.
- `app.py` — pygame loop, upscaling, HUD, scene switching.
- `run.py` — argument parsing and scene registration.

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
        # f.beat is True on the beat frame; f.beat_strength decays after
        ...
```

Then add it to the list in `run.py`: `scenes = [PulseScene(), BarsScene(), MyScene()]`.
It's now on key `3`, and it reacts to mic, line-in, wav, and resting for free.

## Tuning

Most knobs live at the top of `FeatureExtractor` in `features.py`:
envelope `ATTACK`/`RELEASE` (jittery vs smooth), `BEAT_SENSITIVITY`/`BEAT_FLOOR`
(beat detection), and the band frequency ranges. The beat detector is
deliberately simple — good enough to build against, worth upgrading later.
