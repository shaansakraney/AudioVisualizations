"""
audio.py
--------
Four ways to produce a stream of `Features`, all with the same tiny interface:

    source.start()
    features = source.read(dt)   # call once per frame
    source.stop()

- LiveAudioSource : mic or line-in (line-in is just a different device index)
- WavSource       : plays a .wav out loud AND analyzes it, perfectly in sync
- RestingSource   : no hardware; synthesizes smooth idle motion (the screensaver
                    mode). Emits the same Features, so every scene works unchanged.

sounddevice/soundfile are imported lazily so RestingSource runs even if you
haven't installed the audio libs yet.
"""

import numpy as np

from features import Features, FeatureExtractor

DEFAULT_SR = 44100
BLOCK = 2048  # frames/callback; bigger = more slack for the audio thread to
              # tolerate video-thread CPU/GIL contention before it underruns.
              # Doesn't affect analysis: FeatureExtractor keeps its own
              # FFT_SIZE=2048 rolling buffer regardless of callback size.

try:
    import sounddevice as sd
except Exception:  # keep resting mode usable without the audio stack
    sd = None

try:
    import soundfile as sf
except Exception:
    sf = None


class RestingSource:
    """Synthesizes features from slow incommensurate LFOs plus the occasional
    gentle beat. This is the idle look you'd fall back to when no audio is
    selected on the final device."""
    name = "resting"

    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self._next_beat = 0.6
        self._beat_strength = 0.0

    def start(self):
        pass

    def stop(self):
        pass

    def read(self, dt):
        self.t += dt
        t = self.t
        bass = 0.5 + 0.45 * np.sin(t * 0.70)
        mid = 0.5 + 0.40 * np.sin(t * 1.10 + 1.3)
        treble = 0.5 + 0.40 * np.sin(t * 1.70 + 2.6)
        rms = 0.40 + 0.30 * np.sin(t * 0.50)
        centroid = 0.5 + 0.40 * np.sin(t * 0.23)
        # 6 incommensurate LFOs, phase-staggered, so the spectrum scene sees
        # a wandering shape rather than 6 bars breathing in lockstep
        bands = tuple(
            float(np.clip(0.5 + 0.42 * np.sin(t * f + p), 0.0, 1.0))
            for f, p in ((0.55, 0.0), (0.81, 1.1), (1.05, 2.3),
                         (1.34, 0.4), (1.62, 3.0), (1.93, 1.7))
        )

        beat = False
        if t >= self._next_beat:
            beat = True
            self._beat_strength = 1.0
            self._next_beat = t + float(self.rng.uniform(0.5, 1.4))
        else:
            self._beat_strength = max(0.0, self._beat_strength - dt * 2.0)

        clip = lambda v: float(np.clip(v, 0.0, 1.0))
        return Features(
            rms=clip(rms), bass=clip(bass), mid=clip(mid), treble=clip(treble),
            centroid=clip(centroid), bands=bands, beat=beat,
            beat_strength=self._beat_strength, t=t,
        )


class LiveAudioSource:
    """Mic or line-in. Pick the input with `device` (see list_devices()). On the
    microcontroller this is the physical mic/line channel selector."""
    name = "live"

    def __init__(self, device=None, sample_rate=DEFAULT_SR, block=BLOCK):
        if sd is None:
            raise RuntimeError("sounddevice not installed. pip install sounddevice")
        self.device = device
        self.sr = sample_rate
        self.block = block
        self.extractor = FeatureExtractor(sample_rate)
        self._stream = None

    def _callback(self, indata, frames, time_info, status):
        mono = indata.mean(axis=1) if indata.ndim > 1 else indata
        self.extractor.push(mono)

    def _open(self, channels):
        return sd.InputStream(
            samplerate=self.sr, channels=channels, blocksize=self.block,
            device=self.device, dtype="float32", callback=self._callback,
            latency="high",  # extra PortAudio-side buffering headroom against
                              # scheduling jitter from the video thread
        )

    def start(self):
        try:
            self._stream = self._open(1)
            self._stream.start()
        except Exception:
            # some devices refuse mono capture; fall back to stereo
            self._stream = self._open(2)
            self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, dt):
        return self.extractor.read(dt)


class WavSource:
    """Plays a WAV file out loud and analyzes the very same audio in the output
    callback, so visuals stay locked to what you hear. Loops forever."""
    name = "wav"

    def __init__(self, path, block=BLOCK):
        if sd is None:
            raise RuntimeError("sounddevice not installed. pip install sounddevice")
        if sf is None:
            raise RuntimeError("soundfile not installed. pip install soundfile")
        self.path = path
        self.block = block
        self._sf = sf.SoundFile(path)
        self.sr = self._sf.samplerate
        self.channels = self._sf.channels
        self.extractor = FeatureExtractor(self.sr)
        self._stream = None

    def _callback(self, outdata, frames, time_info, status):
        data = self._sf.read(frames, dtype="float32", always_2d=True)
        if len(data) < frames:                       # hit end of file -> loop
            self._sf.seek(0)
            rest = self._sf.read(frames - len(data), dtype="float32", always_2d=True)
            if len(rest):
                data = np.vstack([data, rest])
        if len(data) < frames:                       # still short -> pad silence
            pad = np.zeros((frames - len(data), data.shape[1]), dtype="float32")
            data = np.vstack([data, pad])
        outdata[:] = data
        self.extractor.push(data.mean(axis=1))

    def start(self):
        self._sf.seek(0)
        self._stream = sd.OutputStream(
            samplerate=self.sr, channels=self.channels, blocksize=self.block,
            dtype="float32", callback=self._callback,
            latency="high",  # extra PortAudio-side buffering headroom against
                              # scheduling jitter from the video thread
        )
        self._stream.start()

    def stop(self):
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def read(self, dt):
        return self.extractor.read(dt)


# Virtual/loopback input drivers, in preference order. A loopback device is
# how you capture what the machine is *playing* (Spotify, a browser, anything)
# rather than what a mic hears -- macOS gives no way to tap system output
# without one. See the README for the BlackHole + Multi-Output setup.
LOOPBACK_HINTS = ("blackhole", "soundflower", "loopback", "vb-cable",
                  "virtual", "aggregate", "multi-output", "stereo mix")


def find_loopback_device():
    """Index of the first input device that looks like a loopback/virtual
    driver, or None. Returned index is fed straight to LiveAudioSource,
    which already takes a device index."""
    if sd is None:
        return None
    try:
        devices = sd.query_devices()
    except Exception:
        return None
    for hint in LOOPBACK_HINTS:
        for i, d in enumerate(devices):
            if d.get("max_input_channels", 0) > 0 and hint in d["name"].lower():
                return i
    return None


def list_devices():
    if sd is None:
        print("sounddevice not installed. pip install sounddevice")
        return
    print(sd.query_devices())
    idx = find_loopback_device()
    if idx is None:
        print("\nNo loopback device found. To react to Spotify/system audio:")
        print("  brew install blackhole-2ch")
        print("  then in Audio MIDI Setup create a Multi-Output Device")
        print("  (your speakers + BlackHole) and select it as system output.")
    else:
        print(f"\nLoopback device detected: [{idx}] "
              f"{sd.query_devices()[idx]['name']}  -> use --source loopback")
