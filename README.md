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
  `4` cymatics, `5` spectrum, `6` nebula, `7` constellation)
- `h` — toggle the debug HUD (fps + live feature readout + beat dot)
- `f` — toggle fullscreen
- `esc` — leave fullscreen, or quit if already windowed

The window is freely resizable, and the image always keeps its 16:9 shape —
odd window sizes get black letterbox bars rather than a stretched picture. For
a TV, `--fullscreen --display 1` opens directly on the second monitor:

```bash
python run.py --fullscreen                  # fill the main screen
python run.py --fullscreen --display 1      # fill the TV
python run.py --scale 1.0                   # start at a 1920x1080 window
```

### Image quality

By default the render resolution follows the window, so nothing is upscaled —
make the window bigger and you get more detail, not a blurrier picture. On top
of that each scene declares how much supersampling (SSAA) it needs, because
pygame draws rects and polygons with no anti-aliasing of its own; `spectrum`,
`bars` and `lightning` render at 2x and average down, which is what keeps
their edges smooth on a big screen.

```bash
python run.py --supersample 2   # multiply every scene's AA (needs headroom)
python run.py --supersample 1   # the default
python run.py --canvas 1920x1080  # pin a fixed logical size instead
```

The HUD (`h`) shows the live render resolution and fps. If a scene drops
frames on your machine, the per-scene dials are documented in `scenes.py` —
`FIELD_MAX_PX` for cymatics, `SPLAT_K` for constellation, `GLOW_DOWNSCALE`
for pulse.

The HUD is your quickest sanity check: play music into the mic or load a wav
and watch the rms / bass / mid / treble numbers move.

## How it fits together

```
audio source  →  FeatureExtractor  →  Features ─┬─> Scene.draw()  →  canvas → window
(mic/line/wav/resting)               (the contract)
                                                └─> Scene.led(f)  →  LedSink → ESP32 → strip
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
- `led.py` — the *second output*, parallel to the canvas: `LedSink` takes a
  scene's LED frame, resamples it to the physical strip length, smooths it,
  pulses it on the beat, gamma-corrects it, and streams it to a
  microcontroller on its own thread (so the render loop never blocks on I/O).
- `app.py` — pygame loop, upscaling, HUD, scene switching.
- `run.py` — argument parsing, `AudioFiles/` wav lookup, and scene registration.

## LED strip output

Drive a real LED strip in sync with what's on screen. The Mac decides all the
colors — including the Spotify album palette — and streams finished frames over
WiFi to an ESP32, which is a dumb driver. So color schemes are tuned in Python
with no reflashing, and if frames stop the sketch falls back to its own idle
animation.

```bash
# 1. try it with no hardware: a fake strip in your terminal
python tools/led_monitor.py                                # terminal A
python run.py --leds udp://127.0.0.1:4210 --led-count 16    # terminal B

# 2. the real thing (the sketch prints its IP over serial on boot)
python run.py --source loopback --spotify \
              --leds udp://192.168.1.50:4210 --led-count 60

# USB instead of WiFi (needs: pip install pyserial)
python run.py --leds serial:///dev/tty.usbmodem1101 --led-count 60
```

`--led-count 1` is the right setting for an analog 12V RGB strip, which shows
one color end to end; `LedSink` averages a scene's colors down to it. Use
`--led-brightness 0..1` to tame a strip that's too bright.

**Wiring, sketches, and a troubleshooting table live in
[`firmware/README.md`](firmware/README.md)** — read it before ordering parts.
Two things bite people: analog strips need *logic-level* MOSFETs (IRLZ44N, not
IRF540) because ESP32 GPIO is only 3.3V, and WS2812 data may need a 74AHCT125
level shifter.

Every scene lights the strip. Scenes that don't define `led()` get a default
color derived from `Features`; `PulseScene` sends the orb's color and
`SpectrumScene` sends one pixel per frequency bin through the very same
`SPECTRUM_COLOR_SCHEMES` entry the bars use — so with no Spotify connected the
strip follows your configured `COLOR_SCHEME`, and with a track playing both
screen and strip switch to the album palette together. The beat pulse is
applied by `LedSink` to every frame, so the strip throbs in all scenes.

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
    def led(self, f):                  # optional -- LED strip output
        return [(255 * f.bass, 0, 255 * f.treble)]   # any length; resampled
```

`led()` is optional: omit it and the strip gets a sensible default color from
`Features`. Return any number of pixels — `LedSink` resamples them onto however
many LEDs are actually connected, so a scene never needs to know the strip's
length. Don't add a beat flash yourself; `LedSink` pulses every frame it sends.

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
