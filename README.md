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
`sudo apt install libportaudio2`. If it's missing, resting mode still works.

## Run

```bash
python run.py                             # resting/idle mode — no audio hardware needed
python run.py --source mic                # microphone (default input device)
python run.py --source line --device 2    # line-in / a specific input
python run.py --source wav --wav song.wav # play + react to a wav file, in sync
python run.py --source loopback --spotify # react to Spotify + use its album art
python run.py --list-devices              # find your input device index
```

Start with `python run.py`. Resting mode works with zero setup and shows the
orb breathing, so you can confirm rendering works before touching audio.

For `--source wav`, drop files into an `AudioFiles/` folder next to `run.py`
(create it if it doesn't exist) and pass just the filename — `--wav song.wav`
finds `AudioFiles/song.wav` automatically. That folder is gitignored, so your
music never ends up in version control.

## Spotify (album art + colors)

`--spotify` pulls the currently-playing track's cover art and uses it in the
visuals: in `pulse` the cover *becomes* the orb, and in `spectrum` the bars
take their colors from the cover's palette. Other scenes ignore it.

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
output. You may have to restart your device if you it doesn't recognize BlackHole immediately. Now audio still plays out loud *and* is readable as an input.
`--source loopback` finds BlackHole automatically (`--list-devices` tells you
whether it was detected).

No loopback driver? `--source mic` works fine — play out loud and let the mic
hear it. `--source loopback` falls back to the mic automatically when it can't
find a loopback device.

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
  `RestingSource`), all emitting `Features`, plus `find_loopback_device()`.
  Resting mode fakes the contract from LFOs, so scenes don't care whether
  audio is real.
- `nowplaying.py` — the *second*, independent input: Spotify track metadata
  and cover art, polled on a background thread and handed to scenes as
  `Scene.now_playing`. Deliberately kept out of `Features`, which stays
  audio-only so it can be ported to a microcontroller.
- `scene.py` / `scenes.py` — the visual interface and the starter scenes:
  Pulse, Bars, Lightning, Cymatics, Spectrum, Nebula.
- `fx.py` — shared rendering/math helpers (color, particles, lightning
  geometry, procedural fields, album-art palette extraction) scenes build on.
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
