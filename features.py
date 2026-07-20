"""
features.py
-----------
The single most reusable part of the whole project.

`Features` is the universal contract every scene consumes. `FeatureExtractor`
turns raw audio into that contract. Because mic, line-in, and wav all funnel
through here (and the resting/noise source fakes the same contract), a scene
never has to care where its numbers came from.

All the 0..1 fields are already smoothed and auto-gained, so you can drive
visuals with them directly.
"""

import time
import threading
from dataclasses import dataclass

import numpy as np


@dataclass
class Features:
    rms: float = 0.0            # overall loudness, 0..1
    bass: float = 0.0           # low band energy, 0..1
    mid: float = 0.0            # mid band energy, 0..1
    treble: float = 0.0         # high band energy, 0..1
    centroid: float = 0.0       # spectral "brightness", 0..1 (dull -> bright)
    beat: bool = False          # True only on the frame a beat lands
    beat_strength: float = 0.0  # 1.0 on a beat, decays after -> great for flashes
    t: float = 0.0              # seconds since the source started


class FeatureExtractor:
    """Rolling-window analysis. The audio thread calls push() with new samples;
    the render thread calls read() once per frame to get a Features snapshot."""

    # ---- tuning knobs (all safe to tweak) ----------------------------------
    FFT_SIZE = 2048          # analysis window in samples (~46ms at 44.1k)
    BANDS = {"bass": (20, 250), "mid": (250, 2000), "treble": (2000, 8000)}
    ATTACK = 0.6             # envelope: how fast features rise toward a peak
    RELEASE = 0.15           # envelope: how slowly they fall back (the "musical" feel)
    PEAK_DECAY = 0.999       # auto-gain: how fast the running peak forgets (per frame)
    BEAT_SENSITIVITY = 1.4   # bass must exceed running avg * this to count as a beat
    BEAT_FLOOR = 0.15        # ...and be at least this loud (ignores quiet noise)
    BEAT_REFRACTORY = 0.12   # min seconds between beats
    # ------------------------------------------------------------------------

    def __init__(self, sample_rate):
        self.sr = sample_rate
        self._buf = np.zeros(self.FFT_SIZE, dtype=np.float32)
        self._lock = threading.Lock()
        self._win = np.hanning(self.FFT_SIZE).astype(np.float32)

        freqs = np.fft.rfftfreq(self.FFT_SIZE, 1.0 / sample_rate)
        self._freqs = freqs
        self._band_masks = {
            name: (freqs >= lo) & (freqs < hi)
            for name, (lo, hi) in self.BANDS.items()
        }

        self._env = {"rms": 0.0, "bass": 0.0, "mid": 0.0, "treble": 0.0}
        self._peak = {"rms": 1e-5, "bass": 1e-5, "mid": 1e-5, "treble": 1e-5}
        self._bass_avg = 1e-5
        self._last_beat_t = 0.0
        self._beat_strength = 0.0
        self._start = time.time()

    def push(self, block):
        """Called from the audio callback thread with a mono float32 block."""
        block = np.asarray(block, dtype=np.float32).ravel()
        n = len(block)
        if n == 0:
            return
        with self._lock:
            if n >= self.FFT_SIZE:
                self._buf = block[-self.FFT_SIZE:].copy()
            else:
                self._buf = np.concatenate((self._buf[n:], block))

    def read(self, dt):
        """Called once per frame from the render thread. Returns a Features."""
        with self._lock:
            buf = self._buf.copy()

        spec = np.abs(np.fft.rfft(buf * self._win))

        raw = {"rms": float(np.sqrt(np.mean(buf ** 2)))}
        for name, mask in self._band_masks.items():
            raw[name] = float(spec[mask].mean()) if mask.any() else 0.0

        # spectral centroid -> normalized brightness
        total = spec.sum() + 1e-9
        centroid = float((self._freqs * spec).sum() / total) / (self.sr / 2)
        centroid = float(np.clip(centroid, 0.0, 1.0))

        # auto-gain: divide by an adaptive running peak so any input level "just works"
        norm = {}
        for k, v in raw.items():
            self._peak[k] = max(v, self._peak[k] * self.PEAK_DECAY, 1e-5)
            norm[k] = float(np.clip(v / (self._peak[k] + 1e-9), 0.0, 1.0))

        # envelope follower: fast attack, slow release
        for k, v in norm.items():
            e = self._env[k]
            coeff = self.ATTACK if v > e else self.RELEASE
            self._env[k] = e + coeff * (v - e)

        # simple energy-based beat detection on the low band
        now = time.time() - self._start
        e_low = norm["bass"]
        self._bass_avg = 0.98 * self._bass_avg + 0.02 * e_low
        beat = False
        if (e_low > self._bass_avg * self.BEAT_SENSITIVITY
                and e_low > self.BEAT_FLOOR
                and now - self._last_beat_t > self.BEAT_REFRACTORY):
            beat = True
            self._last_beat_t = now
            self._beat_strength = 1.0
        else:
            self._beat_strength = max(0.0, self._beat_strength - dt * 3.0)

        return Features(
            rms=self._env["rms"], bass=self._env["bass"],
            mid=self._env["mid"], treble=self._env["treble"],
            centroid=centroid, beat=beat,
            beat_strength=self._beat_strength, t=now,
        )
