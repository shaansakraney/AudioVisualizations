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

import threading
from dataclasses import dataclass, field

import numpy as np

# How many bins Features.bands carries, and the frequency span they cover.
# Module-level so the dataclass default and FeatureExtractor can't drift
# apart -- they did: the tuple said 6 long after the extractor produced 24,
# which left resting mode drawing 6 bars where live audio drew 24.
N_SPECTRUM_BINS = 24
SPECTRUM_RANGE_HZ = (20, 21000)


@dataclass
class Features:
    rms: float = 0.0            # overall loudness, 0..1
    bass: float = 0.0           # low band energy, 0..1
    mid: float = 0.0            # mid band energy, 0..1
    treble: float = 0.0         # high band energy, 0..1
    centroid: float = 0.0       # spectral "brightness", 0..1 (dull -> bright)
    # N_SPECTRUM_BINS log-spaced bins, low -> high freq, 0..1 each. This is
    # the bar-graph view of the spectrum; rms/bass/mid/treble are the coarse
    # summary of the same FFT.
    bands: tuple = field(default_factory=lambda: (0.0,) * N_SPECTRUM_BINS)
    beat: bool = False          # True only on the frame a beat lands
    beat_strength: float = 0.0  # 1.0 on a beat, decays after -> great for flashes
    t: float = 0.0              # seconds since the source started


class FeatureExtractor:
    """Rolling-window analysis. The audio thread calls push() with new samples;
    the render thread calls read() once per frame to get a Features snapshot."""

    # ---- tuning knobs (all safe to tweak) ----------------------------------
    FFT_SIZE = 2048          # analysis window in samples (~46ms at 44.1k)
    # bass stops at 120Hz, not 250, and mid takes over there so the three bands
    # stay contiguous. On a limited master the audible difference between a
    # buildup and a drop is almost entirely sub-bass arriving, and 120-250Hz
    # carries enough of everything else to outvote it inside a band mean.
    # Measured over three tracks, narrowing this roughly doubled how much a
    # drop lifts f.bass above the section before it. See tools/analyze_wav.py.
    BANDS = {"bass": (20, 120), "mid": (120, 2000), "treble": (2000, 8000)}
    KEYS = ("rms", "bass", "mid", "treble")   # order of the auto-gain arrays
    ATTACK = 0.6             # envelope: how fast features rise toward a peak
    RELEASE = 0.15           # envelope: how slowly they fall back (the "musical" feel)

    # ---- auto-gain -------------------------------------------------------
    # The reference has two jobs that pull in opposite directions: absorbing
    # *input gain* (a mic, a line-in and a BlackHole loopback differ by tens of
    # dB, and that has to just work) while preserving *musical dynamics* (the
    # thing the visuals exist to show). This used to be a running max with
    # instant attack, dividing linearly. That does the first job well; what it
    # does to the second is subtler than it looks -- it does *not* mostly clip
    # (measured: ~1% of frames reach 1.0), it compresses section-to-section
    # contrast. Dividing by a near-global max maps the top of the range onto
    # the few dB a limited master actually spans, so a drop and the buildup
    # before it landed 0.08 apart on a 0..1 scale.
    # A slow reference plus a dB window separates the jobs: the reference
    # tracks the *setup* and nothing faster, and RANGE_DB decides how much
    # musical range fills the scale. Same three tracks, drop-vs-section
    # contrast went 0.08/0.26/0.11 -> 0.22/0.30/0.24 with per-beat punch
    # unchanged. tools/analyze_wav.py is how those numbers are produced.
    REF_RISE_S = 30.0        # time constant for the reference following levels up
    REF_FALL_S = 60.0        # ...and back down. Rising faster than it falls makes
                             # this settle near a high quantile of recent loudness
                             # rather than at its mean, without a hard max's habit
                             # of letting one door slam pin the gain for minutes.
    REF_WARMUP_S = 3.0       # for this long after start, use a much shorter time
    REF_WARMUP_TAU_S = 0.5   # constant, so a new source calibrates in a moment
                             # instead of spending half a minute settling.
    REF_FLOOR = 1e-5
    RANGE_DB = 16.0          # how many dB the window spans. The one knob for how
                             # much dynamic range the visuals cover, and it has
                             # to be matched to how little of it modern masters
                             # actually use: measured across three tracks, the
                             # 4s-smoothed level moves only ~1.5-5 dB between a
                             # loud section and the loudest one. At 30dB that
                             # difference lands in a tenth of the range and
                             # nothing reads; much under 15 and half the frames
                             # sit on the floor.
    HEADROOM_DB = 9.0        # the reference maps to 1 - HEADROOM/RANGE, not to
                             # 1.0, leaving room above a typical loud passage for
                             # a drop to actually read as louder.
    KNEE = 0.3               # soft-knee width at *both* ends of the window, so
                             # over- and under-shooting it compress instead of
                             # flat-out clipping. A window narrow enough to make
                             # drops read puts a lot of frames under it, and the
                             # bottom knee is what keeps those dim rather than
                             # dead. See the note in _autogain.
    BEAT_SENSITIVITY = 1.2   # bass must exceed running avg * this to count as a beat
    BEAT_FLOOR = 0.1        # ...and be at least this loud (ignores quiet noise)
    BEAT_REFRACTORY = 0.02   # min seconds between beats
    N_SPECTRUM_BINS = N_SPECTRUM_BINS      # bin count for Features.bands
    SPECTRUM_RANGE_HZ = SPECTRUM_RANGE_HZ  # low..high edge of the log spread
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

        lo, hi = self.SPECTRUM_RANGE_HZ
        n = self.N_SPECTRUM_BINS
        edges = np.geomspace(lo, min(hi, sample_rate / 2 * 0.999), n + 1)
        self._spec_masks = np.stack([
            (freqs >= edges[i]) & (freqs < edges[i + 1]) for i in range(n)
        ])
        self._ref_spec = np.full(n, self.REF_FLOOR, dtype=np.float32)
        self._env_spec = np.zeros(n, dtype=np.float32)

        # rms/bass/mid/treble as one array so the auto-gain is the same
        # vectorized expression here and on the spectrum path.
        self._env = np.zeros(len(self.KEYS), dtype=np.float32)
        self._ref = np.full(len(self.KEYS), self.REF_FLOOR, dtype=np.float32)
        self._elapsed = 0.0
        self._bass_avg = 1e-5
        # Per-frame internals of the last read(), for the HUD and
        # tools/analyze_wav.py. Written once a frame; never read by the pipeline.
        self.last_debug = {}
        self._last_beat_t = 0.0
        self._beat_strength = 0.0

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

    def _autogain(self, raw, ref, dt):
        """Normalize `raw` (any shape) to 0..1 against a slow reference.

        Returns the updated reference and the normalized values. Split out so
        the 4 headline features and the spectrum bins share one expression
        -- and so tools/analyze_wav.py can subclass it to measure alternatives.
        """
        if self._elapsed < self.REF_WARMUP_S:
            rise = fall = 1.0 - np.exp(-dt / self.REF_WARMUP_TAU_S)
        else:
            rise = 1.0 - np.exp(-dt / self.REF_RISE_S)
            fall = 1.0 - np.exp(-dt / self.REF_FALL_S)
        ref = ref + np.where(raw > ref, rise, fall) * (raw - ref)
        ref = np.maximum(ref, self.REF_FLOOR).astype(np.float32)

        # dB below the reference -> 0..1 across a fixed window
        db = 20.0 * np.log10(np.maximum(raw, 1e-9) / ref)
        x = (db + self.RANGE_DB - self.HEADROOM_DB) / self.RANGE_DB

        # Soft knees at both ends: linear through the middle, compressing
        # asymptotically toward 1 above and 0 below. The top knee is what lets
        # a drop that overshoots the reference still out-read one that merely
        # reaches it, instead of both flattening against a clip. The bottom
        # knee matters just as much in the other direction -- a window narrow
        # enough to make drops dramatic puts a large share of frames under it,
        # and hard-clipping those to 0 leaves the visuals dead through every
        # quiet passage rather than merely dim.
        k = self.KNEE
        top, bot = 1.0 - k, k
        x = np.where(x > top, top + k * np.tanh((x - top) / k), x)
        x = np.where(x < bot, bot + k * np.tanh((x - bot) / k), x)
        return ref, np.clip(x, 0.0, 1.0).astype(np.float32)

    def read(self, dt):
        """Called once per frame from the render thread. Returns a Features."""
        with self._lock:
            buf = self._buf.copy()

        spec = np.abs(np.fft.rfft(buf * self._win))

        raw = np.empty(len(self.KEYS), dtype=np.float32)
        raw[0] = np.sqrt(np.mean(buf ** 2))
        for i, name in enumerate(self.KEYS[1:], start=1):
            mask = self._band_masks[name]
            raw[i] = spec[mask].mean() if mask.any() else 0.0

        # spectral centroid -> normalized brightness
        total = spec.sum() + 1e-9
        centroid = float((self._freqs * spec).sum() / total) / (self.sr / 2)
        centroid = float(np.clip(centroid, 0.0, 1.0))

        self._elapsed += dt

        # auto-gain: a slow reference absorbs input level, a fixed dB window
        # below it maps the dynamics (see the constants above).
        self._ref, norm = self._autogain(raw, self._ref, dt)

        # envelope follower: fast attack, slow release
        coeff = np.where(norm > self._env, self.ATTACK, self.RELEASE)
        self._env = self._env + coeff * (norm - self._env)

        # the log-spaced spectrum: same auto-gain + envelope logic as above,
        # vectorized over the bin axis instead of a per-key dict. Per-bin
        # auto-gain is what keeps the top bins visible at all -- music has far
        # less energy up there, and one shared reference would flatten them.
        raw_spec = np.array(
            [spec[m].mean() if m.any() else 0.0 for m in self._spec_masks],
            dtype=np.float32)
        self._ref_spec, norm_spec = self._autogain(raw_spec, self._ref_spec, dt)
        coeff_spec = np.where(norm_spec > self._env_spec, self.ATTACK, self.RELEASE)
        self._env_spec = self._env_spec + coeff_spec * (norm_spec - self._env_spec)

        # simple energy-based beat detection on the low band. The clock is
        # accumulated dt rather than wall time: in the live app the two agree
        # (dt *is* the frame delta), but it keeps `t` in step with the frames
        # actually rendered, and it lets tools/analyze_wav.py run a track
        # faster than realtime without the refractory window eating every beat.
        now = self._elapsed
        e_low = float(norm[self.KEYS.index("bass")])
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

        self.last_debug = {
            name: dict(zip(self.KEYS, (float(x) for x in arr)))
            for name, arr in (("raw", raw), ("ref", self._ref),
                              ("norm", norm), ("env", self._env))
        }

        env = self._env
        return Features(
            rms=float(env[0]), bass=float(env[1]),
            mid=float(env[2]), treble=float(env[3]),
            centroid=centroid, bands=tuple(float(x) for x in self._env_spec),
            beat=beat, beat_strength=self._beat_strength, t=now,
        )
