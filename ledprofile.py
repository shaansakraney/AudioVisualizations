"""
ledprofile.py
-------------
The LED strip's own set of dials, separate from the visuals.

A scene's `led()` decides *what* the strip shows -- which pixel is which
frequency, which color belongs to which level. This decides *how it lands in
the room*: how bright, how twitchy, how saturated, which way round. Those are
two different questions, and only the second one changes when you move the
strip behind the TV or swap the diffuser.

Three properties make it worth being its own object rather than more class
constants in led.py:

1. **It is global, not per-scene.** Color defaults to `scheme = "scene"`,
   which mirrors whatever palette the running scene chose -- so with a fresh
   profile nothing about the strip changes. But every adjustment you make
   holds across all nine scenes, because the whole point is tuning *the
   light*, not tuning a scene.
2. **It is live.** `App` mutates these fields from the render thread while
   `LedSink` reads them on the sender thread. Every knob is a plain float,
   bool or short string, so a torn read is impossible in CPython -- the worst
   case is one LED frame using the old value, which is 16ms of nothing.
3. **It persists.** `save()`/`load()` round-trip to JSON, so a strip you
   tuned once against your actual wall stays tuned.

`PARAMS` is the single source of truth: the adjust logic and the on-screen
panel are both generated from it, so adding a knob is one entry here plus one
line of use in led.py.
"""

import json
import os
from dataclasses import asdict, dataclass, field, fields

import numpy as np

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "led_profile.json")

# "follow the scene" -- the sentinel value of `scheme` that means "don't
# recolor at all, use the RGB the scene handed us".
SCENE_SCHEME = "scene"


@dataclass
class Param:
    """One knob, as the panel and the adjust logic both see it."""
    name: str
    label: str
    lo: float = 0.0
    hi: float = 1.0
    step: float = 0.05
    kind: str = "float"      # float | bool | choice
    fmt: str = "{:.2f}"


@dataclass
class LedProfile:
    # -- brightness & floor ---------------------------------------------------
    brightness: float = 1.0    # master output scale
    floor: float = 0.22        # dimmest a lit pixel may go (see LedSink._lift)
    gamma: float = 2.2         # LEDs are linear, eyes are not

    # -- reactivity -----------------------------------------------------------
    gain: float = 1.0          # multiplies level before anything else
    contrast: float = 1.0      # gamma on level; >1 pushes quiet parts down
    attack: float = 0.55       # smoothing coefficient on the way up
    release: float = 0.20      # ...and on the way down (the "musical" feel)
    beat_gain: float = 0.9     # extra brightness at beat_strength 1.0
    beat_white: float = 0.35   # how far a beat snaps the color toward white

    # -- color ----------------------------------------------------------------
    scheme: str = SCENE_SCHEME  # "scene", or a SPECTRUM_COLOR_SCHEMES key
    saturation: float = 1.0     # 0 = white, 1 = as-is, >1 toward pure hue
    hue_shift: float = 0.0      # rotate the whole palette around the wheel

    # -- spatial --------------------------------------------------------------
    reverse: bool = False       # flip the frame end for end
    mirror: bool = False        # fold it so the strip runs centre-outward
    offset: float = 0.0         # rotate the mapping along the strip, 0..1

    # Not a knob: where save() writes. Excluded from the JSON.
    path: str = field(default=DEFAULT_PATH, compare=False, repr=False)

    # The panel's contents and order. Grouped the way you actually tune:
    # get the level right, then the feel, then the color, then the geometry.
    PARAMS = [
        Param("brightness", "brightness", 0.0, 1.0, 0.05),
        Param("floor",      "floor",      0.0, 0.8, 0.02),
        Param("gamma",      "gamma",      1.0, 3.2, 0.1, fmt="{:.1f}"),
        Param("gain",       "gain",       0.2, 4.0, 0.1, fmt="{:.2f}"),
        Param("contrast",   "contrast",   0.3, 4.0, 0.1, fmt="{:.2f}"),
        Param("attack",     "attack",     0.02, 1.0, 0.02),
        Param("release",    "release",    0.02, 1.0, 0.02),
        Param("beat_gain",  "beat gain",  0.0, 3.0, 0.1),
        Param("beat_white", "beat white", 0.0, 1.0, 0.05),
        Param("scheme",     "scheme",     kind="choice", fmt="{}"),
        Param("saturation", "saturation", 0.0, 2.0, 0.05),
        Param("hue_shift",  "hue shift",  0.0, 1.0, 0.02),
        Param("reverse",    "reverse",    kind="bool", fmt="{}"),
        Param("mirror",     "mirror",     kind="bool", fmt="{}"),
        Param("offset",     "offset",     0.0, 1.0, 0.02),
    ]

    # -- the scheme choice ---------------------------------------------------

    @staticmethod
    def scheme_names():
        """"scene" plus every spectrum palette. Imported lazily: scenes.py
        pulls in pygame and fx, and neither run.py's argument parsing nor a
        headless tool should pay for that just to read a profile."""
        from scenes import SPECTRUM_COLOR_SCHEMES
        return [SCENE_SCHEME] + list(SPECTRUM_COLOR_SCHEMES)

    def scheme_fn(self):
        """The active color function, or None while `scheme` is "scene"."""
        if self.scheme == SCENE_SCHEME:
            return None
        from scenes import SPECTRUM_COLOR_SCHEMES
        return SPECTRUM_COLOR_SCHEMES.get(self.scheme)

    # -- editing -------------------------------------------------------------

    def adjust(self, name, direction, coarse=False):
        """Nudge one knob. `direction` is +1/-1; `coarse` takes a 5x step, so
        the same two keys cover both a hair and a sweep."""
        p = next((p for p in self.PARAMS if p.name == name), None)
        if p is None:
            return
        if p.kind == "bool":
            setattr(self, name, not getattr(self, name))
        elif p.kind == "choice":
            names = self.scheme_names()
            i = names.index(self.scheme) if self.scheme in names else 0
            self.scheme = names[(i + direction) % len(names)]
        else:
            step = p.step * (5 if coarse else 1)
            v = getattr(self, name) + direction * step
            # snap to the step grid so repeated nudges don't drift onto
            # values like 0.30000000000000004
            v = round(v / p.step) * p.step
            setattr(self, name, float(min(p.hi, max(p.lo, v))))

    def display(self, name):
        p = next((p for p in self.PARAMS if p.name == name), None)
        v = getattr(self, name)
        if p is None:
            return str(v)
        if p.kind == "bool":
            return "on" if v else "off"
        return p.fmt.format(v)

    def reset(self):
        """Back to defaults, keeping the path we were loaded from."""
        keep = self.path
        for fld in fields(self):
            if fld.name == "path":
                continue
            setattr(self, fld.name, fld.default)
        self.path = keep

    # -- persistence ---------------------------------------------------------

    def to_dict(self):
        d = asdict(self)
        d.pop("path", None)
        return d

    def save(self, path=None):
        """Write to JSON. Returns the path written, or raises OSError."""
        path = path or self.path
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2, sort_keys=True)
            fh.write("\n")
        return path

    @classmethod
    def load(cls, path=None):
        """Read a profile, falling back to defaults if the file is missing or
        unreadable. Unknown keys are ignored and missing ones keep their
        default, so a file written by an older build still loads after a knob
        is added or renamed -- this is a preferences file, not a schema."""
        path = path or DEFAULT_PATH
        prof = cls(path=path)
        try:
            with open(path) as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return prof
        if not isinstance(data, dict):
            return prof
        known = {f.name for f in fields(cls)} - {"path"}
        for k, v in data.items():
            if k not in known:
                continue
            cur = getattr(prof, k)
            try:
                setattr(prof, k, bool(v) if isinstance(cur, bool)
                        else v if isinstance(cur, str) else float(v))
            except (TypeError, ValueError):
                pass
        return prof


# ---------------------------------------------------------------------------
# the stages LedSink applies from a profile
# ---------------------------------------------------------------------------

def spatial_map(px, count, profile, resample):
    """Lay a scene's frame onto the physical strip: mirror, then reverse, then
    rotate. `resample` is LedSink._resample, passed in so the stretching rule
    stays in one place.

    Mirror folds the frame in half so the strip reads centre-outward -- the
    scene's first pixel sits at the middle and its last at both ends, which is
    what makes a strip behind a screen look symmetric instead of like it has a
    left and a right.
    """
    if profile is not None and profile.mirror and count > 1:
        half = resample(px, (count + 1) // 2)
        out = np.concatenate([half[::-1], half], axis=0)[:count]
    else:
        out = resample(px, count)
    if profile is None:
        return out
    if profile.reverse:
        out = out[::-1]
    shift = int(round(profile.offset * count)) % count if count else 0
    if shift:
        out = np.roll(out, shift, axis=0)
    return out


def apply_level(out, profile):
    """Gain and contrast, applied to each pixel's *level* rather than to its
    channels, so brightening the strip never shifts its hue. Returns
    `(out, level)` with level 0..1 -- the recolor stage wants it too.

    Contrast is a gamma on level: above 1 it drags the quiet parts down while
    leaving a full-scale peak alone, which is how you get a strip that sits
    dark through a verse and still hits the ceiling on a drop.
    """
    peak = out.max(axis=1)
    lvl = np.clip(peak / 255.0, 0.0, 1.0)
    if profile is None:
        return out, lvl
    adj = np.clip(lvl * profile.gain, 0.0, 1.0)
    if profile.contrast != 1.0:
        adj = adj ** profile.contrast
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(peak > 1e-6, adj * 255.0 / np.maximum(peak, 1e-6), 0.0)
    return out * scale[:, None].astype(np.float32), adj


def recolor(out, level, profile, f, np_):
    """Replace the scene's palette with the profile's, when one is chosen.

    The scheme functions are the same `(i, n, val, f, np_) -> (r,g,b)` ones
    the scenes use (SPECTRUM_COLOR_SCHEMES), called with the pixel's position
    along the strip and its level -- so an index-based palette paints a
    gradient down the strip and a level-based one moves with the music,
    exactly as they do on screen. They are evaluated per pixel rather than
    through a LUT because a strip is at most 488 pixels on a background
    thread, where a scene is millions on the render thread.
    """
    if profile is None:
        return out
    fn = profile.scheme_fn()
    if fn is not None:
        n = out.shape[0]
        cols = np.array([fn(i, n, float(v), f, np_) for i, v in enumerate(level)],
                        dtype=np.float32)
        # the scheme picks the hue; the level still decides the brightness
        out = cols * level[:, None].astype(np.float32)

    if profile.saturation != 1.0 or profile.hue_shift != 0.0:
        from fx import hsv_array, rgb_array_to_hsv
        h, s, v = rgb_array_to_hsv(np.clip(out, 0, 255) / 255.0)
        h = (h + profile.hue_shift) % 1.0
        s = np.clip(s * profile.saturation, 0.0, 1.0)
        out = hsv_array(h, s, v).astype(np.float32)
    return out
