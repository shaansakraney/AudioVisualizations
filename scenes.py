"""
scenes.py
---------
- PulseScene    : breathing orb; radius follows bass+rms, hue follows
                  spectral brightness, every beat throws an expanding ring.
- BarsScene     : three band bars + rms line + beat flash. The diagnostic
                  view -- great for eyeballing whether the audio pipeline
                  is alive.
- LightningScene: beat-triggered branching electric bolts from the center.
- NebulaScene   : a drifting glow-particle field; bass pushes it outward,
                  treble makes it twinkle, beats throw a firework burst.
- CymaticsScene : nodal standing-wave interference patterns, one mode per
                  band -- literally the physics of "shapes made by sound."
- ConstellationScene : the spectrum as a drifting 3D point cloud -- X is
                  frequency, Y is level, Z is time, so old spectra ridge
                  away toward a horizon. Legible like Spectrum, organic
                  like Cymatics.
- ChasmScene    : Constellation mirrored about the horizon -- a corridor
                  between two walls of sound, with the lower one dimmed
                  like a reflection on water.
- VortexScene   : the same history as rings instead of rows, receding down
                  a tunnel you are flying up. Frequency is the angle.
- ResonanceScene: Cymatics in 3D -- a globe of points driven by standing
                  waves, one mode per band.
- CartographScene : the history as hidden-line ridgelines. An animated
                  *Unknown Pleasures* plot; the only one that doesn't glow.
- LatticeScene  : a fixed 3D grid of points with band-driven waves sweeping
                  through it, camera orbiting. The structure stays on
                  screen through the quiet parts.

The last six all share one substrate: fx.SpectrumHistory for the "Z is time"
buffer, fx.PointCloud for the splat renderer, and the SpectrumColored mixin
below for palettes and led(). A new one of these is a projection, not a
renderer -- write _project()/draw() and everything else is inherited.

Add your own by subclassing Scene and dropping it into the list in run.py.
Color/scale/particle/field helpers live in fx.py -- see that module before
building something new; most scene ideas are a combination of what's there.
"""

import colorsys

import numpy as np
import pygame

import fx
from fx import hsv, aacircle, scale
from scene import Scene


class PulseScene(Scene):
    """Breathing orb. Two independent Spotify switches decide how much of the
    track it uses: USE_ALBUM_ART makes the cover itself the orb (circle-masked
    and scaled by the same bass+rms radius), USE_ALBUM_COLORS hands the
    palette to the glow, core, rings and background. With both off -- or with
    nothing playing -- the colors come from COLOR_SCHEME, the same
    SPECTRUM_COLOR_SCHEMES registry SpectrumScene and ConstellationScene
    draw from, so one scheme colors all three scenes."""

    name = "pulse"

    # ---- color -------------------------------------------------------------
    # Same pluggable registry SpectrumScene and ConstellationScene use, so a
    # scheme written once colors all three. A scheme is just
    #   (bar index, bar count, level 0..1, Features, NowPlaying) -> (r, g, b)
    # and the orb asks for COLOR_ROLES points along that ramp (see _colors).
    # "centroid" is the look this scene had before it took schemes; "drift"
    # is the slow fade through the wheel; add your own by writing a function
    # next to the others and listing it in SPECTRUM_COLOR_SCHEMES.
    COLOR_SCHEME = "me1"

    # Spotify, on two independent switches -- that's the point of splitting
    # them. USE_ALBUM_ART is whether the cover *becomes* the orb; when it's
    # off you get the flat disc even with a track playing. USE_ALBUM_COLORS
    # is whether the palette overrides COLOR_SCHEME. So "cover art, but my
    # colors" and "my own disc, tinted by the album" are both reachable, as
    # are both of the obvious ones.
    USE_ALBUM_ART = False
    USE_ALBUM_COLORS = False

    # The orb has three color roles -- glow, core, ring -- rather than n bars,
    # so it samples the scheme at three evenly spaced points on its ramp. An
    # index-based scheme ("blue_pink", "drift") therefore hands the three
    # roles related-but-distinct hues; a level-based one ("me1", "me2",
    # "fire") hands them the same hue and moves it with loudness instead.
    COLOR_ROLES = 3

    # How dark the background sits relative to the glow color. 0 for black.
    BACKGROUND_TINT = 0.20

    # Orb radius is quantized to this many pixels before the cover is scaled
    # to it. Without the quantization a continuously-changing radius would
    # miss fx.circle_masked's cache on literally every frame, turning a
    # once-per-size smoothscale+mask into a per-frame one.
    ART_RADIUS_STEP = 4

    def __init__(self):
        self.f = None
        self.rings = []  # each ring is [grown_radius, alpha]
        self._scratch = {}
        self._art_cache = {}
        self.color_fn = SPECTRUM_COLOR_SCHEMES[self.COLOR_SCHEME]

    def update(self, f, dt):
        self.f = f
        if f.beat:
            self.rings.append([0.0, 1.0])
        for r in self.rings:
            r[0] += dt * 260.0   # expand outward
            r[1] -= dt * 1.6     # fade out
        self.rings = [r for r in self.rings if r[1] > 0.0]

    def _active_color_fn(self, np_):
        """Album colors take over while something is playing, then hand back
        to whatever scheme COLOR_SCHEME selected -- the same rule, and the
        same single decision point, as SpectrumScene._active_color_fn."""
        if self.USE_ALBUM_COLORS and np_ is not None and np_.palette:
            return _spectrum_scheme_album
        return self.color_fn

    def _colors(self, f, np_):
        """(glow, core, ring) for this frame, from one scheme.

        The level handed to the scheme is the same bass+rms mix that drives
        the orb's radius, so a level-based scheme shifts hue exactly as the
        orb breathes. The ring keeps the cover's accent color when album
        colors are in charge -- that's the one place the palette knows
        something a ramp doesn't, namely which of its colors is the vivid
        one worth drawing a thin line in."""
        color_fn = self._active_color_fn(np_)
        n = self.COLOR_ROLES
        lvl = 0.5 * f.bass + 0.5 * f.rms
        glow, core, ring = (color_fn(i, n, lvl, f, np_) for i in range(3))
        if color_fn is _spectrum_scheme_album and np_.accent:
            ring = np_.accent
        return glow, core, ring

    def draw(self, surface):
        w, h = surface.get_size()
        s = scale(surface)
        f = self.f
        np_ = self.now_playing
        art = np_.art if (self.USE_ALBUM_ART and np_ is not None) else None

        if f is None:
            surface.fill((0, 0, 0))
            return

        glow_col, core_col, ring_col = self._colors(f, np_)

        # background: the glow color taken right down toward black, so it
        # tracks whichever scheme (or album palette) is driving the orb, with
        # the original treble lift on top
        bg_k = self.BACKGROUND_TINT * (1.0 + 0.6 * f.treble)
        surface.fill(tuple(int(c * bg_k) for c in glow_col))

        cx, cy = w // 2, h // 2
        base = min(w, h) * 0.1
        radius = base + (w * 0.2) * (0.5 * f.bass + 0.5 * f.rms)
        radius += (w * 0.05) * f.beat_strength

        # soft glow: several translucent circles, faint-and-wide to bright-and-tight.
        # More, tighter-spaced layers than the reference tuning so the falloff
        # stays smooth instead of banding at large canvas sizes.
        #
        # Rendered at 1/3 resolution and upscaled: gfxdraw.filled_circle is an
        # O(radius^2) fill, and profiling showed these 6 large circles (up to
        # ~1.7x the orb radius) were ~86% of this scene's frame time at full
        # 1920x1080 res -- enough to occasionally blow the audio thread's
        # real-time callback deadline. Downscaling cuts that fill cost by ~9x,
        # and the upscale blur is a bonus for a "glow" effect anyway.
        GLOW_DOWNSCALE = 3
        gw = max(1, w // GLOW_DOWNSCALE)
        gh = max(1, h // GLOW_DOWNSCALE)
        glow_small = fx.scratch_surface(self._scratch, "glow_small", (gw, gh))
        gcx, gcy = cx / GLOW_DOWNSCALE, cy / GLOW_DOWNSCALE
        layers = (1.7, 1.55, 1.4, 1.25, 1.1, 1.0)
        for i, k in enumerate(layers):
            aacircle(glow_small, (*glow_col, 18 + 14 * i),
                     (gcx, gcy), radius * k / GLOW_DOWNSCALE)
        # Small white halo immediately around orb
        white_glow_layers = (
            (1.16, 15),
            (1.12, 25),
            (1.08, 38),
            (1.04, 55),
            (1.01, 70),
        )
        for k, alpha in white_glow_layers:
            aacircle(
                glow_small,
                (255, 255, 255, alpha),
                (gcx, gcy),
                radius * k / GLOW_DOWNSCALE
            )
        glow = fx.scratch_surface(self._scratch, "glow", (w, h))
        pygame.transform.smoothscale(glow_small, (w, h), glow)
        surface.blit(glow, (0, 0))

        # the orb itself: album cover if we have one, else a flat disc
        if art is not None:
            # only ever one track's masked cover is worth keeping around
            if self._art_cache.get("track") != np_.track_id:
                self._art_cache.clear()
                self._art_cache["track"] = np_.track_id
            step = self.ART_RADIUS_STEP
            d = max(step, int(round(radius * 2 / step)) * step)
            cover = fx.circle_masked(self._art_cache, "orb", art, d)
            surface.blit(cover, (cx - d // 2, cy - d // 2))
        else:
            aacircle(surface, core_col, (cx, cy), radius)

        # expanding beat rings
        ring_width = max(2, round(3 * s))
        rings = fx.scratch_surface(self._scratch, "rings", (w, h))
        for grown, alpha in self.rings:
            aacircle(rings, (*ring_col, int(alpha * 180)),
                     (cx, cy), base + grown, width=ring_width)
        surface.blit(rings, (0, 0))

    def led(self, f):
        """A single color: the orb's own glow color -- the same _colors() the
        screen uses, so the strip follows COLOR_SCHEME, USE_ALBUM_COLORS and
        everything else without a second set of rules -- brightened by the
        same bass+rms mix that drives the radius. Returns one pixel; LedSink
        spreads it across the whole strip, pulses it on the beat, and holds
        it at its resting glow rather than black between beats."""
        if f is None:
            return None
        glow_col, _core, _ring = self._colors(f, self.now_playing)
        k = 0.2 + 0.8 * (0.5 * f.bass + 0.5 * f.rms)
        return [tuple(c * k for c in glow_col)]


class BarsScene(Scene):
    name = "bars"
    SUPERSAMPLE = 2      # plain rects, no AA of their own

    def __init__(self):
        self.f = None
        self._scratch = {}

    def update(self, f, dt):
        self.f = f

    def draw(self, surface):
        w, h = surface.get_size()
        s = scale(surface)
        f = self.f
        flash = int(30 * (f.beat_strength if f else 0.0))
        surface.fill((6 + flash, 6 + flash, 10 + flash))
        if f is None:
            return

        bands = [
            (f.bass, (255, 70, 90)),
            (f.mid, (90, 220, 120)),
            (f.treble, (90, 160, 255)),
        ]
        gap = max(6, round(10 * s))
        margin_bottom = round(40 * s)
        corner = max(3, round(4 * s))
        n = len(bands)
        bw = (w - gap * (n + 1)) // n
        # one shared glow layer for all bars instead of allocating a fresh
        # full-canvas surface per bar
        glow = fx.scratch_surface(self._scratch, "glow", (w, h))
        rects = []
        for i, (val, col) in enumerate(bands):
            x = gap + i * (bw + gap)
            bh = int((h - margin_bottom) * val)
            rect = (x, h - gap * 2 - bh, bw, bh)
            rects.append((rect, col))
            pygame.draw.rect(glow, (*col, 60), pygame.Rect(rect).inflate(gap, gap),
                              border_radius=corner * 2)
        surface.blit(glow, (0, 0))
        for rect, col in rects:
            pygame.draw.rect(surface, col, rect, border_radius=corner)

        # rms as an anti-aliased bar across the top
        line_y = round(14 * s)
        line_w = max(2, round(3 * s))
        for dy in range(line_w):
            pygame.draw.aaline(surface, (230, 230, 230),
                                (0, line_y + dy), (int(w * f.rms), line_y + dy))


# Color schemes take (bar index, bar count, that bar's 0..1 level, Features,
# NowPlaying-or-None) and return an (r, g, b). `f.t` gives you a clock for
# animated gradients; `np_` gives you the current album palette (see
# _spectrum_scheme_album). Schemes ignore whichever they don't need.

def _spectrum_scheme_blue_pink(i, n, val, f, np_):
    """Static ramp: blue (low freq) -> pink (high freq)."""
    hue = 0.62 + 0.3 * (i / (n))
    return hsv(hue, 1, 1.0)


def _spectrum_scheme_rainbow_cycle(i, n, val, f, np_):
    """Full rainbow across the bars, slowly cycling over time."""
    hue = (i / n + f.t * 0.05) % 1.0
    return hsv(hue, 1, 1.0)


def _spectrum_scheme_reactive(i, n, val, f, np_):
    """Blue-pink ramp, but each bar's brightness pulses with its own level."""
    hue = 0.4 + 0.4 * (i / (n))
    return hsv(hue, 1, 0.55 + 0.45 * val)


def _spectrum_scheme_fire(i, n, val, f, np_):
    """Single hue sweep (red->yellow) driven by how loud each bar is."""
    hue = 0.02 + 0.12 * val
    return hsv(hue, 1, 0.6 + 0.4 * val)


def _spectrum_scheme_me1(i, n, val, f, np_):
    hue = 0.5 + 0.37 * val #light blue -> purple
    #hue = 0.67 + 0.3 * val #blue -> pink
    #hue = 0.78 - 0.3 * val #purple -> light blue
    return hsv(hue, 1, 0.7 + 0.3 * val)


def _spectrum_scheme_me2(i, n, val, f, np_):
    #hue = 0.67 + 0.2 * val
    hue = 0.5 + 0.3 * val
    return hsv(hue, 1, 0.6 + 0.4 * val)


def _spectrum_scheme_drift(i, n, val, f, np_):
    """The fading one: a slow, continuous lap of the whole color wheel, about
    three minutes per cycle. Neighbouring bars sit only a little apart, so at
    any instant the scene is nearly a single color -- it just never stays that
    color. Nothing steps or flashes; everything fades."""
    hue = (f.t * 0.006 + 0.09 * (i / max(1, n - 1)) + 0.05 * val) % 1.0
    return hsv(hue, 0.85, 0.6 + 0.4 * val)


def _spectrum_scheme_centroid(i, n, val, f, np_):
    """Hue straight from spectral brightness, dull sounds low on the wheel and
    bright ones high -- how PulseScene colored itself before it took schemes,
    and what led.default_led still does. The index fans the hue out slightly
    and desaturates, which is what separates an orb's glow from its core."""
    k = i / max(1, n - 1)
    return hsv((f.centroid + 0.05 * k) % 1.0, 0.8 - 0.2 * k, 1.0)


def _spectrum_scheme_album(i, n, val, f, np_):
    """Colors sampled straight from the current album cover -- one palette
    entry per bin, brightness pulsing with that bin's level. Falls back to
    the fire ramp when no track is playing, so it's always safe to leave
    selected. fx.palette_from_surface merges near-duplicate colors and so
    can return fewer than n entries -- hence the modulo."""
    palette = np_.palette if np_ is not None else ()
    if not palette:
        return _spectrum_scheme_fire(i, n, val, f, np_)
    r, g, b = palette[i % len(palette)]
    k = 0.55 + 0.45 * val
    return int(r * k), int(g * k), int(b * k)


# Registry of selectable color schemes -- add new ones above and list them
# here, then flip SpectrumScene.COLOR_SCHEME (or the scheme kwarg) to swap.
SPECTRUM_COLOR_SCHEMES = {
    "blue_pink": _spectrum_scheme_blue_pink,
    "rainbow": _spectrum_scheme_rainbow_cycle,
    "reactive": _spectrum_scheme_reactive,
    "fire": _spectrum_scheme_fire,
    "me1": _spectrum_scheme_me1,
    "me2": _spectrum_scheme_me2,
    "drift": _spectrum_scheme_drift,
    "centroid": _spectrum_scheme_centroid,
    "album": _spectrum_scheme_album,
}

class SpectrumColored:
    """Shared plumbing for every scene that colors itself out of
    SPECTRUM_COLOR_SCHEMES. Mix it in *ahead* of Scene:

        class MyScene(SpectrumColored, Scene): ...

    Three things that were copy-pasted scene to scene live here instead: the
    COLOR_SCHEME / USE_ALBUM_COLORS pair, the album-override rule, and the
    standard led() body. `color_fn` is a property rather than something cached
    in __init__ so a subclass only has to set COLOR_SCHEME.
    """

    # See SPECTRUM_COLOR_SCHEMES above. Adding a scheme there reaches every
    # scene that mixes this in, plus CymaticsScene via its spectrum: mirror.
    COLOR_SCHEME = "me2"

    # When a Spotify track is playing, override COLOR_SCHEME with "album" so
    # the visual takes the cover's colors. Set False to keep your own scheme
    # regardless of what's playing.
    USE_ALBUM_COLORS = False

    @property
    def color_fn(self):
        return SPECTRUM_COLOR_SCHEMES[self.COLOR_SCHEME]

    def _active_color_fn(self, np_):
        """Album colors take over while something is playing, then hand back
        to whatever scheme COLOR_SCHEME selected once it stops. Shared by
        draw() and led() so the strip and the screen are never on different
        palettes -- in particular, with no Spotify connection the LEDs use
        your configured scheme ("me1", "fire", ...) rather than defaulting to
        some separate LED-only look."""
        if self.USE_ALBUM_COLORS and np_ is not None and np_.palette:
            return _spectrum_scheme_album
        return self.color_fn

    def _scheme_lut(self, color_fn, n, f, np_):
        """Sample a scheme into an (n, 3) float 0..1 lookup table, then index
        it with any normalized 0..1 quantity.

        This exists for the scenes with thousands of points. Constellation can
        afford NX=96 Python calls to color_fn per frame; Resonance and Lattice
        have ~6000 points and cannot, so they build a small LUT once a frame
        and `np.take` from it. Entry i is sampled at both index i/(n-1) *and*
        level i/(n-1), which is what makes one table work for both kinds of
        scheme: an index-based one ("blue_pink", "rainbow") ramps across the
        table by position, a level-based one ("me1", "fire") by loudness. What
        the caller indexes it *with* is what that scene's hue ends up meaning.
        """
        k = np.linspace(0.0, 1.0, n, dtype=np.float32)
        return np.array([color_fn(i, n, float(k[i]), f, np_) for i in range(n)],
                        dtype=np.float32) / 255.0

    def _lut_take(self, lut, x):
        """lut[i] for each 0..1 value in `x`, clipped. Kept next to
        _scheme_lut so the rounding rule is in one place."""
        idx = np.clip((x * (len(lut) - 1)).astype(np.int32), 0, len(lut) - 1)
        return lut[idx]

    def _spectrum_led(self, f, floor=0.15):
        """The live spectrum, one LED pixel per bin, through the very same
        color scheme the scene is drawn with -- so the strip reads as a
        physical extension of what's on screen. LedSink stretches these
        len(f.bands) pixels across however many LEDs are wired up (or averages
        them down to one for an analog strip) and adds the beat pulse on top,
        so there is deliberately no beat flash here."""
        if f is None:
            return None
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)
        bands = f.bands
        n = len(bands)
        return [tuple(c * (floor + (1.0 - floor) * val)
                      for c in color_fn(i, n, val, f, np_))
                for i, val in enumerate(bands)]




class SpectrumScene(SpectrumColored, Scene):
    """Apple-Music-style spectrum: one bar per f.bands bin, left-to-right, each
    growing symmetrically up and down from a horizontal center line as its
    band (f.bands[i], low -> high frequency) gets louder."""

    name = "spectrum"

    # Rounded-rect bars have hard, un-anti-aliased edges; at 1:1 the pill ends
    # visibly stair-step on a TV. This is the single biggest fidelity win in
    # this scene and only costs ~5ms.
    SUPERSAMPLE = 2

    # Active palette -- change this key (see SPECTRUM_COLOR_SCHEMES above)
    # to try a different color scheme; each scheme is just a function of
    # (bar index, bar count, that bar's 0..1 level, Features, NowPlaying)
    # -> (r, g, b), so f.t is available for time-based/animated gradients
    # and np_.palette for album-derived ones.
    COLOR_SCHEME = "me1"

    # When a Spotify track is playing, override COLOR_SCHEME with "album"
    # so the bars take the cover's colors. Set False to keep your own
    # scheme regardless of what's playing.
    USE_ALBUM_COLORS = False

    # Draw the cover blurred + darkened behind the bars.
    SHOW_ALBUM_BACKDROP = False

    # Fraction of each bin's slot width the bar actually fills (0..1).
    # Lower = narrower bars with more gap between them; the bin's center
    # position doesn't move since it's computed from the slot, not the bar.
    BAR_WIDTH_FRAC = 0.9

    def __init__(self):
        self.f = None
        self._scratch = {}
        self._art_cache = {}

    def update(self, f, dt):
        self.f = f

    def draw(self, surface):
        w, h = surface.get_size()
        s = scale(surface)
        f = self.f
        np_ = self.now_playing
        art = np_.art if np_ is not None else None

        flash = int(30 * (f.beat_strength if f else 0.0))
        surface.fill((6 + flash, 6 + flash, 10 + flash))
        if art is not None and self.SHOW_ALBUM_BACKDROP:
            if self._art_cache.get("track") != np_.track_id:
                self._art_cache.clear()
                self._art_cache["track"] = np_.track_id
            surface.blit(fx.blurred_backdrop(self._art_cache, "bg", art, (w, h)),
                         (0, 0))
        if f is None:
            return

        color_fn = self._active_color_fn(np_)

        bands = f.bands
        n = len(bands)
        gap = max(6, round(10 * s))
        glowsize = 10
        cy = h // 2
        max_half = (h - gap * 2) / 2.0
        # slot = fixed center-to-center spacing for each bin; bw is a
        # fraction of that slot, so BAR_WIDTH_FRAC resizes bars in place
        # instead of also changing where their centers sit.
        slot = (w - gap * (n + 1)) / n
        #print(f"{slot}    {w}    {h}    {gap}    {n}    {cy}")
        bw = max(4, int(slot * self.BAR_WIDTH_FRAC))
        pill = bw // 2  # border_radius == half the bar width -> fully round ends

        glow = fx.scratch_surface(self._scratch, "glow", (w, h))
        rects = []
        for i, val in enumerate(bands):
            col = color_fn(i, n, val, f, np_)
            #old method
            #half = max(int(max_half * val), bw / 2) 
            half = int(max_half * val) #current version
            slot_cx = gap + i * (slot + gap) + slot / 2
            x = int(slot_cx - bw / 2)
            rect = (x, cy - half, bw, half * 2)
            rects.append((rect, col))
            pygame.draw.rect(glow, (*col, 30), pygame.Rect(rect).inflate(glowsize, glowsize),
                              border_radius=pill + glowsize // 2)
        surface.blit(glow, (0, 0))
        for rect, col in rects:
            pygame.draw.rect(surface, col, rect, border_radius=pill)

    def led(self, f):
        """One LED pixel per spectrum bin, through the very same color scheme
        the bars are drawn with, so the strip reads as a physical extension of
        the on-screen spectrum -- see SpectrumColored._spectrum_led."""
        return self._spectrum_led(f)


class LightningScene(Scene):
    """Branching electric bolts from the center. Beats fire a main strike
    with a couple of forking branches; hot treble occasionally crackles a
    smaller bolt even off-beat. Geometry comes from fx.lightning_bolt() /
    fx.lightning_branches(), rendered with fx.draw_bolt()'s glow+core+hot
    layering, additive-blended so overlapping bolts brighten."""

    name = "lightning"
    SUPERSAMPLE = 2      # bolt polygons are hard-edged, and this scene is cheap

    def __init__(self):
        self.f = None
        self.bolts = []  # dicts: angle, length, life, max_life, hue, small, seed
        self.rng = np.random.default_rng()
        self._cooldown = 0.0
        self._scratch = {}

    def update(self, f, dt):
        self.f = f
        self._cooldown = max(0.0, self._cooldown - dt)
        for b in self.bolts:
            b["life"] -= dt
        self.bolts = [b for b in self.bolts if b["life"] > 0.0]

        if f is None:
            return
        if f.beat and self._cooldown <= 0.0:
            self._strike(f, small=False)
            self._cooldown = 0.10
        elif f.treble > 0.72 and self.rng.random() < f.treble * 0.05:
            self._strike(f, small=True)

    def _strike(self, f, small):
        life = 0.16 if small else 0.24
        self.bolts.append({
            "angle": float(self.rng.uniform(0, 2 * np.pi)),
            "length": (0.5 if small else 0.85) * (0.6 + 0.4 * f.bass),
            "life": life, "max_life": life,
            "hue": 0.56 + self.rng.uniform(-0.08, 0.08),
            "small": small,
            "seed": int(self.rng.integers(0, 1 << 30)),
        })

    def draw(self, surface):
        w, h = surface.get_size()
        s = scale(surface)
        f = self.f
        cx, cy = w / 2.0, h / 2.0

        flash = f.beat_strength if f else 0.0
        base = 4 + int(10 * flash)
        surface.fill((base, base, base + 6))
        if f is None:
            return

        layer = fx.scratch_surface(self._scratch, "layer", (w, h))
        max_r = 0.5 * min(w, h) * 1.3
        for b in self.bolts:
            if "points" not in b:
                rng = np.random.default_rng(b["seed"])
                r = b["length"] * max_r
                p1 = (cx + np.cos(b["angle"]) * r, cy + np.sin(b["angle"]) * r)
                b["points"] = fx.lightning_bolt(rng, (cx, cy), p1, roughness=0.5)
                b["branches"] = (fx.lightning_branches(rng, b["points"], n_branches=2)
                                 if not b["small"] else [])

            t = max(0.0, b["life"] / b["max_life"])
            color = hsv(b["hue"], 0.25, 1.0)
            width = max(1, round((2 if b["small"] else 4) * s))
            alpha_core = int(255 * t)
            alpha_glow = int(90 * t)
            fx.draw_bolt(layer, b["points"], color, width, alpha_core, alpha_glow)
            for branch in b["branches"]:
                fx.draw_bolt(layer, branch, color, max(1, width - 1),
                              int(alpha_core * 0.7), int(alpha_glow * 0.7))

        surface.blit(layer, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)


class NebulaScene(Scene):
    """A drifting field of glowing particles (fx.Particles). Bass pushes
    particles outward from center, treble ignites a twinkling subset each
    frame, beats throw a firework burst, and centroid shifts the palette
    cool<->warm. Rendered onto a persistent surface faded each frame
    (fx.fade) instead of cleared, for a soft long-exposure trail look."""

    name = "nebula"

    def __init__(self):
        self.f = None
        self.particles = None
        self.trail = None
        self.rng = np.random.default_rng()

    def _ensure(self, surface):
        if self.particles is not None:
            return
        w, h = surface.get_size()
        # Particles.draw() draws 2 gfxdraw circles per particle (halo + core);
        # profiling showed those calls, not allocation, dominate this scene's
        # frame time, so capacity/ambient count are kept modest rather than
        # lush -- 300/160 is comfortably under the audio thread's real-time
        # deadline where 500/220 wasn't.
        self.particles = fx.Particles(capacity=300)
        self.trail = pygame.Surface((w, h))
        self._spawn_ambient(w, h, 160, hue_base=0.6)

    def _spawn_ambient(self, w, h, n, hue_base):
        pos = self.rng.uniform([0, 0], [w, h], size=(n, 2)).astype(np.float32)
        angle = self.rng.uniform(0, 2 * np.pi, n)
        speed = self.rng.uniform(4, 18, n)
        vel = (np.stack([np.cos(angle), np.sin(angle)], axis=1)
               * speed[:, None]).astype(np.float32)
        life = self.rng.uniform(4.0, 9.0, n).astype(np.float32)
        hue = (hue_base + self.rng.uniform(-0.06, 0.06, n)).astype(np.float32)
        size = self.rng.uniform(1.5, 3.5, n).astype(np.float32)
        self.particles.spawn(n, pos, vel, life, hue, size)

    def update(self, f, dt):
        self.f = f

    def draw(self, surface):
        self._ensure(surface)
        w, h = surface.get_size()
        s = scale(surface)
        f = self.f
        p = self.particles
        cx, cy = w / 2.0, h / 2.0

        hue_base = 0.55 + 0.25 * (1.0 - (f.centroid if f else 0.5))

        if f is not None:
            alive = p.alive_mask()
            if alive.any():
                to_center = p.pos[alive] - np.array([cx, cy], dtype=np.float32)
                dist = np.linalg.norm(to_center, axis=1, keepdims=True) + 1e-3
                p.vel[alive] += (to_center / dist) * (f.bass * 60.0) * 0.016

            twinkle = np.where(alive & (self.rng.random(p.capacity) < 0.05 * f.treble))[0]
            p.ignite(twinkle, 1.0)

        # recycle dead or offscreen particles so the field stays populated
        offscreen = ((p.pos[:, 0] < -20) | (p.pos[:, 0] > w + 20)
                     | (p.pos[:, 1] < -20) | (p.pos[:, 1] > h + 20))
        need = (~p.alive_mask()) | (offscreen & p.alive_mask())
        n_need = int(need.sum())
        if n_need:
            idx = np.where(need)[0]
            pos = self.rng.uniform([0, 0], [w, h], size=(n_need, 2)).astype(np.float32)
            angle = self.rng.uniform(0, 2 * np.pi, n_need)
            speed = self.rng.uniform(4, 18, n_need)
            vel = (np.stack([np.cos(angle), np.sin(angle)], axis=1)
                   * speed[:, None]).astype(np.float32)
            life = self.rng.uniform(4.0, 9.0, n_need).astype(np.float32)
            hue = (hue_base + self.rng.uniform(-0.06, 0.06, n_need)).astype(np.float32)
            size = (self.rng.uniform(1.5, 3.5, n_need) * s).astype(np.float32)
            p.pos[idx], p.vel[idx] = pos, vel
            p.life[idx], p.max_life[idx] = life, life
            p.hue[idx], p.size[idx] = hue, size

        if f is not None and f.beat:
            n = 70
            angle = self.rng.uniform(0, 2 * np.pi, n)
            speed = (self.rng.uniform(120, 340, n) * s).astype(np.float32)
            vel = (np.stack([np.cos(angle), np.sin(angle)], axis=1)
                   * speed[:, None]).astype(np.float32)
            pos = np.tile([cx, cy], (n, 1)).astype(np.float32)
            life = self.rng.uniform(0.6, 1.4, n).astype(np.float32)
            hue = np.full(n, (hue_base + 0.5) % 1.0, dtype=np.float32)
            size = (self.rng.uniform(2.0, 4.0, n) * s).astype(np.float32)
            p.spawn(n, pos, vel, life, hue, size)

        p.update(0.016, drag=0.6)

        fx.fade(self.trail, 40)
        p.draw(self.trail, base_alpha=230, size_mul=s)
        surface.blit(self.trail, (0, 0))


# Cymatics color schemes take (field, centroid, t, np_) and return
# (hue array, saturation). Same idea as SPECTRUM_COLOR_SCHEMES above: write a
# function, list it in the registry, point CymaticsScene.COLOR_SCHEME at it.
#
# The one thing to understand: `field` is the raw interference pattern, and it
# grows with loudness -- roughly -0.5..0.5 when quiet but -3.5..3.5 on a loud
# beat. Multiplying it straight into the hue (as "spectral" does) therefore
# spreads MORE of the color wheel across the screen the louder the music gets:
# ~16% of the wheel when quiet, but over 100% on a loud beat, at which point
# the hue wraps completely and literally every color is on screen at once.
# That is the main source of "too many colors."
#
# The calm schemes below all pass field through np.tanh() first, which squashes
# it into -1..1 no matter how loud things get, so their spread is a hard,
# predictable limit rather than something loudness inflates.

def _cymatics_scheme_spectral(field, centroid, t, np_):
    """The original look: hue follows audio brightness, spreads across the
    field, and drifts over time. The most colorful and most overstimulating --
    kept so you can A/B against the calmer ones."""
    return (centroid * 0.5 + 0.15 * field + t * 0.02) % 1.0, 0.8


def _cymatics_scheme_mono(field, centroid, t, np_):
    """One fixed hue everywhere; only brightness moves. The calmest option --
    the pattern reads as pure form, with no color information at all."""
    return np.full_like(field, 0.58), 0.5


def _cymatics_scheme_duotone(field, centroid, t, np_):
    """Two neighbouring hues either side of a base. Keeps a sense of color
    without the rainbow -- the spread is capped at +-0.10 of the wheel."""
    return (0.58 + 0.10 * np.tanh(field)) % 1.0, 0.6


def _cymatics_scheme_ember(field, centroid, t, np_):
    """Warm: deep red through orange."""
    return (0.02 + 0.07 * np.tanh(field)) % 1.0, 0.85


def _cymatics_scheme_ice(field, centroid, t, np_):
    """Cool: teal through pale blue. Low saturation, easiest on the eyes."""
    return (0.50 + 0.08 * np.tanh(field)) % 1.0, 0.45


def _cymatics_scheme_slow_drift(field, centroid, t, np_):
    """Narrow duotone that slowly walks the whole wheel over ~3 minutes. Few
    colors at any instant, but the piece still changes character over a song --
    a good middle ground if a fixed palette feels static."""
    return (t * 0.006 + 0.09 * np.tanh(field)) % 1.0, 0.6


def _cymatics_scheme_album(field, centroid, t, np_):
    """Hue anchored to the cover's dominant color, with a narrow spread around
    it. Falls back to duotone when nothing is playing, so it's safe to leave
    selected -- same contract as _spectrum_scheme_album."""
    palette = np_.palette if np_ is not None else ()
    if not palette:
        return _cymatics_scheme_duotone(field, centroid, t, np_)
    r, g, b = palette[0]
    h, s, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
    return (h + 0.06 * np.tanh(field)) % 1.0, float(np.clip(s, 0.35, 0.85))


class _SpectrumClock:
    """Minimal stand-in for Features. Spectrum schemes only ever reach into
    f.t (the animated ones, e.g. "rainbow"), and the cymatics scheme contract
    carries t but no Features -- so this hands them the one field they use."""

    __slots__ = ("t",)

    def __init__(self, t):
        self.t = t


_MIRROR_STEPS = 33   # palette samples; the LUT the field is looked up in


def _make_cymatics_spectrum_mirror(name):
    """Build a cymatics scheme that wears a SPECTRUM_COLOR_SCHEMES palette.

    The two registries speak different languages: a spectrum scheme answers
    "what color is bar i at level val?" in RGB, a cymatics scheme answers
    "what hue is every pixel of this field?" So this samples the spectrum
    scheme at _MIRROR_STEPS points, sweeping the bar index and the level
    together -- which is what lets index-based ramps ("blue_pink", "rainbow")
    and level-based ones ("me1", "fire") both land on the same 0..1 axis --
    converts each sample to hue/saturation, and looks the field up in that
    table.

    The field goes through tanh first, so loudness can't inflate the spread
    past the palette's own ends (the same trick the calm schemes use), and
    then maps to 0..1: troughs take the bottom of the ramp, crests the top.
    The result is Cymatics in the same colors as SpectrumScene and
    ConstellationScene -- a bright crest is the hue of a tall bar.
    """
    fn = SPECTRUM_COLOR_SCHEMES[name]
    xs = np.linspace(0.0, 1.0, _MIRROR_STEPS, dtype=np.float32)

    def scheme(field, centroid, t, np_):
        clock = _SpectrumClock(t)
        n = _MIRROR_STEPS
        hues = np.empty(n, dtype=np.float32)
        sats = np.empty(n, dtype=np.float32)
        for i in range(n):
            r, g, b = fn(i, n, float(xs[i]), clock, np_)
            h, sat, _v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
            hues[i], sats[i] = h, sat
        # Unwrap before interpolating, so a palette that crosses the top of
        # the wheel takes the short way round instead of racing back down
        # through every other color.
        hues = np.unwrap(hues * (2.0 * np.pi)) / (2.0 * np.pi)
        lvl = 0.5 + 0.5 * np.tanh(field)
        hue = np.interp(lvl, xs, hues) % 1.0
        return hue.astype(np.float32), float(sats.mean())

    scheme.__name__ = "_cymatics_scheme_spectrum_" + name
    scheme.__doc__ = ("SpectrumScene's %r palette, mapped onto the field."
                      % (name,))
    return scheme


CYMATICS_COLOR_SCHEMES = {
    "spectral": _cymatics_scheme_spectral,   # the original, most colorful
    "mono": _cymatics_scheme_mono,           # calmest
    "duotone": _cymatics_scheme_duotone,
    "ember": _cymatics_scheme_ember,
    "ice": _cymatics_scheme_ice,
    "slow_drift": _cymatics_scheme_slow_drift,
    "album": _cymatics_scheme_album,
}

# ...plus one mirrored entry per spectrum palette, registered as
# "spectrum:<name>" (e.g. "spectrum:me2" makes Cymatics match the default
# ConstellationScene colors). Adding a scheme to SPECTRUM_COLOR_SCHEMES gets
# you the cymatics version for free.
CYMATICS_COLOR_SCHEMES.update({
    "spectrum:%s" % name: _make_cymatics_spectrum_mirror(name)
    for name in SPECTRUM_COLOR_SCHEMES
})


class CymaticsScene(Scene):
    """Nodal standing-wave interference patterns -- one mode per band, so
    louder bands make tighter/denser patterns -- plus a beat-triggered
    radial ripple term. Literally the physics of "shapes made by sound."
    All math lives in fx.draw_field()/fx.field_grid(); this scene is just
    the field function."""

    name = "cymatics"

    # ---- color -------------------------------------------------------------
    # Which palette to use; see CYMATICS_COLOR_SCHEMES above. "spectral" is
    # the original look, "slow_drift" the calm default this had before, and
    # any "spectrum:<name>" key borrows that palette from SpectrumScene, so
    # this scene, SpectrumScene and ConstellationScene can all be on one set
    # of colors.
    COLOR_SCHEME = "spectrum:me2"

    # When a Spotify track is playing, override COLOR_SCHEME with "album".
    USE_ALBUM_COLORS = False

    # Multiplier on whatever saturation the scheme asks for. Below 1.0 washes
    # the whole thing toward grey -- the single fastest way to calm it down.
    SATURATION = 1.0

    # ---- brightness --------------------------------------------------------
    # Gamma on brightness. The raw field is symmetric around 0.5, so by
    # default *every* pixel on a 1920x1080 canvas is lit to some degree and
    # there is no dark space for the eye to rest. Values >1 push the mid-tones
    # down into black, leaving bright crests on a dark ground; 1.0 is the
    # original flat-lit look.
    CONTRAST = 1.8

    # Overall ceiling, applied after CONTRAST. Lower this for a dim room.
    BRIGHTNESS = 0.9

    # ---- motion ------------------------------------------------------------
    # Multiplier on the scene clock: every wave, drift and ripple slows down
    # together. 1.0 is the original speed.
    MOTION = 0.7

    # How fast the hue-driving brightness reading follows the audio, in units
    # per second. f.centroid is the one Feature that is NOT smoothed by the
    # envelope follower (see features.py), so used raw it jitters frame to
    # frame and makes the colors visibly buzz. Lower = steadier color.
    CENTROID_SMOOTHING = 3.0

    # The field is computed at reduced resolution and smoothscaled up, because
    # its cost is purely per-pixel. This used to be a FIXED 240x135 -- an 8x
    # upscale at 1080p and 16x on a 4K TV, which is why it read as a blurry
    # smear on a big screen.
    #
    # Expressing the budget as a pixel COUNT rather than a divisor of the
    # canvas keeps frame time roughly constant no matter how big the window
    # is, while always resolving as much detail as that budget allows: ~500x330
    # at 1512p, ~550x310 at 4K. Both are 2x+ the old fixed size. Raise it for
    # more detail (cost scales linearly), lower it if you drop frames.
    FIELD_MAX_PX = 170_000

    # How many pixels led() evaluates the slice at. LedSink maps these onto
    # the real strip length, so this is just how finely the pattern is
    # sampled, not the hardware count.
    LED_PIXELS = 48

    # On screen the troughs of the pattern are meant to go black -- that is
    # what CONTRAST carves out, and it is what gives the crests their shape.
    # On a strip the same black reads as dead pixels, and the LedProfile's
    # floor can't rescue it: a black pixel has no color left to lift. So the strip
    # gets the value compressed into LED_FLOOR..1 instead of 0..1: a trough
    # rests on the dim end of the scheme's own ramp rather than going out.
    LED_FLOOR = 0.3

    def __init__(self):
        self.f = None
        self.t = 0.0
        self.centroid = 0.5    # smoothed; see CENTROID_SMOOTHING
        self.color_fn = CYMATICS_COLOR_SCHEMES[self.COLOR_SCHEME]
        self._aspect = 16.0 / 9.0   # replaced by draw() with the real canvas

    def update(self, f, dt):
        self.f = f
        self.t += dt * self.MOTION
        if f is not None:
            # low-pass the raw centroid so the palette drifts instead of buzzing
            k = min(1.0, self.CENTROID_SMOOTHING * dt)
            self.centroid += k * (f.centroid - self.centroid)

    def _active_color_fn(self, np_):
        """Album colors while something is playing, else the configured
        COLOR_SCHEME -- same rule (and same reasoning) as SpectrumScene."""
        if self.USE_ALBUM_COLORS and np_ is not None and np_.palette:
            return _cymatics_scheme_album
        return self.color_fn

    def _field(self, X, Y, f):
        """The interference pattern itself, over whatever coordinate arrays
        it's handed. Pulled out of draw() so led() can evaluate the exact same
        math along a line instead of re-deriving (and drifting from) it."""
        bass = f.bass if f else 0.3
        mid = f.mid if f else 0.3
        treble = f.treble if f else 0.3
        beat = f.beat_strength if f else 0.0
        t = self.t

        r = np.sqrt(X * X + Y * Y)
        m1 = 2.0 + bass * 7.0
        m2 = 3.0 + mid * 9.0
        m3 = 4.0 + treble * 11.0
        field = (
            bass * np.sin(m1 * X + t * 0.6) * np.sin(m1 * Y - t * 0.6)
            + mid * np.sin(m2 * Y + t * 0.9) * np.cos(m2 * X - t * 0.5)
            + treble * np.cos(m3 * (X + Y) + t * 1.3)
        )
        if beat > 0.01:
            field = field + beat * np.sin(r * 14.0 - t * 6.0)
        return field

    def _colorize(self, field, color_fn, np_):
        """Field -> (hue, value, sat), applying every look dial. The single
        place the scene's colors are decided, shared by draw() and led()."""
        # brightness: symmetric around 0.5, so raising CONTRAST is what
        # carves dark space out of an otherwise uniformly-lit canvas
        value = 0.5 + 0.5 * np.tanh(field * 0.9)
        value = self.BRIGHTNESS * value ** self.CONTRAST

        hue, sat = color_fn(field, self.centroid, self.t, np_)
        return hue, value, np.clip(sat * self.SATURATION, 0.0, 1.0)

    def draw(self, surface):
        f = self.f
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)

        def field_fn(X, Y):
            return self._colorize(self._field(X, Y, f), color_fn, np_)

        w, h = surface.get_size()
        self._aspect = w / float(h)   # led() samples the same x span
        div = max(1, int(np.ceil(np.sqrt(w * h / float(self.FIELD_MAX_PX)))))
        res = (max(2, w // div), max(2, h // div))
        fx.draw_field(surface, res, field_fn)

    def led(self, f):
        """A horizontal slice straight through the middle of the pattern,
        colorized by the very same _colorize()/_active_color_fn the pixels go
        through -- so the strip is literally a line of what's on screen, moving
        with it.

        Without this the scene fell through to led.default_led, whose hue comes
        from the raw (deliberately unsmoothed, see features.py) f.centroid and
        has nothing to do with the active color scheme. That's why the strip
        looked random next to the screen.

        LedSink resamples these LED_PIXELS onto however many LEDs are actually
        wired up, and adds the beat pulse on top -- so no beat flash here."""
        if f is None:
            return None
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)

        n = self.LED_PIXELS
        # same x span fx.field_grid uses (+/-aspect), y through the centre, so
        # a pixel at strip position p shows the color the canvas has at p
        a = self._aspect
        X = np.linspace(-a, a, n, dtype=np.float32)
        Y = np.zeros(n, dtype=np.float32)

        hue, value, sat = self._colorize(self._field(X, Y, f), color_fn, np_)
        sat = (sat if isinstance(sat, np.ndarray)
               else np.full(n, float(sat), dtype=np.float32))
        value = self.LED_FLOOR + (1.0 - self.LED_FLOOR) * np.clip(value, 0.0, 1.0)
        return fx.hsv_array(np.mod(hue, 1.0), sat, value).astype(np.float32)


class ConstellationScene(SpectrumColored, Scene):
    """A spectrum you can read, drawn as a drifting 3D point cloud.

    The two scenes it comes from fail in opposite directions: SpectrumScene is
    legible but static and flat, CymaticsScene is beautiful but has no readable
    structure. This keeps the spectrum's one great idea -- frequency runs
    left-to-right, height means loudness -- and makes it spatial:

      * X is frequency, interpolated up from f.bands for a smooth curve.
      * Y is that band's level, so the front row is exactly a spectrum
        silhouette, just drawn in dots.
      * Z is TIME. Every row behind the front one is an older spectrum, so
        loud moments become ridges that drift back toward the horizon and
        fade. That's where the organic, amorphous motion comes from -- it is
        the music's own history, not noise.

    Points shrink, dim and converge on a vanishing point with depth, which is
    what gives it air rather than the wall-to-wall glow Cymatics had.

    The history buffer is fx.SpectrumHistory and the renderer is fx.PointCloud
    -- both shared with VortexScene, ChasmScene, CartographScene and friends.
    This scene is now only the projection: _project() turns the history into
    screen coordinates, sizes and colors, and draw() hands those to the cloud.
    Subclass _project() to get a different shape for free (see ChasmScene).
    """

    name = "constellation"

    # Tune by subclassing rather than mutating an instance -- some geometry is
    # precomputed from NX/NZ in __init__:
    #     class BigConstellation(ConstellationScene): NX, NZ = 128, 64
    #
    # ---- shape -------------------------------------------------------------
    NX = 96            # points across; frequency resolution
    NZ = 52            # depth rows; how many spectra of history are visible

    # Rows pushed per second. NZ / HISTORY_HZ = seconds of history on screen
    # (52 / 20 ~= 2.6s). Lower = slower, longer drift.
    HISTORY_HZ = 20.0

    # ---- camera ------------------------------------------------------------
    FOCAL = 0.45       # smaller = wider lens = more dramatic perspective
    DEPTH = 2.2        # how far back the last row sits
    SPREAD = 0.98      # width of the front row, as a fraction of the canvas
    HORIZON = 0.20     # vanishing point, 0=top 1=bottom
    GROUND = 0.9       # where a silent front-row point sits
    HEIGHT = 0.3       # how far a full-level point rises off the ground

    # ---- look --------------------------------------------------------------
    # Reuses SPECTRUM_COLOR_SCHEMES (via SpectrumColored), so every palette you
    # have already written works here unchanged. One thing matters when picking
    # one: a scheme whose hue comes from the bar INDEX ("blue_pink", "rainbow",
    # "reactive") paints a left-to-right gradient, so color itself encodes
    # frequency and the cloud stays readable across a room. A scheme whose hue
    # comes from the LEVEL ("me1", "me2", "fire") instead colors by loudness,
    # which looks good but scatters hue across the surface.
    COLOR_SCHEME = "me2"
    USE_ALBUM_COLORS = False

    # ---- splatting ---------------------------------------------------------
    # See fx.PointCloud: MAX_SPLAT_PX is the float buffer's pixel budget,
    # KERNEL_R how many taps per side each dot writes, and DOT_RADIUS the
    # Gaussian radius of a *front-row* dot in buffer pixels (each point's sigma
    # is this times its perspective factor, so near dots are soft blobs and far
    # ones collapse toward a single crisp pixel). KERNEL_R has to comfortably
    # exceed DOT_RADIUS or near dots get clipped square.
    MAX_SPLAT_PX = 1_050_000
    DOT_RADIUS = 2.6
    KERNEL_R = 3

    # ---- glow --------------------------------------------------------------
    GLOW = 1.3
    GLOW_DOWNSCALE = 10

    BRIGHTNESS = 3.0
    DEPTH_FADE = 1.0   # exponent on the depth dimming; higher = darker distance
    BEAT_LIFT = 0.3    # how much a beat lifts the whole field

    # ---- background --------------------------------------------------------
    # The empty space around the cloud, as fractions of full brightness.
    # AMBIENT is a constant faint wash so it never sits at dead black; FLASH
    # is how far a beat lifts it, the same trick SpectrumScene uses to keep
    # its background from feeling static -- except the color here is the
    # scheme's own average hue rather than a neutral grey, so the flash reads
    # as the palette breathing rather than as a grey strobe. It follows the
    # album palette for free when USE_ALBUM_COLORS is on. Note fx.PointCloud's
    # glow pass re-adds it, so what lands on screen is about (1 + GLOW)x this.
    AMBIENT = 0.02
    FLASH = 0.1

    def __init__(self):
        self.f = None
        self.hist = fx.SpectrumHistory(self.NX, self.NZ, self.HISTORY_HZ)
        self.cloud = fx.PointCloud(self.MAX_SPLAT_PX, self.KERNEL_R)

        # Static geometry, built once: column x positions and the row fade.
        # Only the levels change per frame, so none of this is rebuilt.
        self._xn = (np.linspace(0.0, 1.0, self.NX, dtype=np.float32) - 0.5)
        self._tail = fx.depth_tail(self.NZ)

    def update(self, f, dt):
        self.f = f
        if f is None:
            return
        self.hist.push(f.bands, dt)

    def _project(self, f, W, H, np_, color_fn):
        """History -> (px, py, sigma, rgb, ambient) for fx.PointCloud.

        px/py are normalized 0..1 screen coords, sigma is in buffer pixels, and
        rgb already has each point's intensity multiplied in (the accumulation
        is additive, so brightness lives in the color, not an alpha).
        """
        # depth 0..1 for each row, offset by the fractional scroll so the field
        # drifts continuously instead of stepping once per pushed row
        z = (np.arange(self.NZ, dtype=np.float32) + self.hist.acc) / self.NZ
        persp = fx.perspective(z, self.FOCAL, self.DEPTH)[:, None]  # (NZ,1)

        lvl = self.hist.rows + self.BEAT_LIFT * f.beat_strength     # (NZ,NX)

        sx = 0.5 + self._xn[None, :] * self.SPREAD * persp
        sy = self.HORIZON + (self.GROUND - self.HORIZON
                             - lvl * self.HEIGHT) * persp

        # brightness: perspective dimming + the point's own level + the tail
        # that dissolves the furthest rows instead of ending on a back wall
        inten = ((persp ** self.DEPTH_FADE) * (0.18 + 0.82 * lvl)
                 * self._tail[:, None] * self.BRIGHTNESS)

        # color: one hue per frequency column, from the shared registry
        front = self.hist.rows[0]
        cols = np.array([color_fn(i, self.NX, float(front[i]), f, np_)
                         for i in range(self.NX)], dtype=np.float32) / 255.0
        rgb = (cols[None, :, :] * inten[:, :, None]).reshape(-1, 3)

        sigma = self.DOT_RADIUS * np.broadcast_to(persp, sx.shape).ravel()
        ambient = cols.mean(axis=0) * (self.AMBIENT
                                       + self.FLASH * f.beat_strength)
        return sx.ravel(), sy.ravel(), sigma, rgb, ambient

    def draw(self, surface):
        f = self.f
        if f is None:
            surface.fill((0, 0, 0))
            return
        W, H = surface.get_size()
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)
        px, py, sigma, rgb, ambient = self._project(f, W, H, np_, color_fn)
        self.cloud.splat(surface, px, py, sigma, rgb, ambient=ambient,
                         glow=self.GLOW, glow_downscale=self.GLOW_DOWNSCALE)

    def led(self, f):
        """The front row -- i.e. the live spectrum -- through the same palette,
        so the strip matches the near edge of the point cloud."""
        return self._spectrum_led(f)


class ChasmScene(ConstellationScene):
    """Constellation, mirrored: the ridge grows up *and* down from the horizon,
    so instead of looking at a landscape you are flying down a corridor between
    two facing walls of sound. SpectrumScene's symmetry trick, in 3D.

    The lower copy is dimmed and blurred rather than drawn identically, which
    is the whole difference between "a reflection on water" and "two walls" --
    keep REFLECT_DIM below 1 or the image reads as flat wallpaper.

    It is just a different _project(): everything else -- history, camera,
    palette, splatting, led() -- is inherited unchanged.
    """

    name = "chasm"

    # Every row is splatted twice, so the row count is halved against the
    # parent's to keep the frame cost in the same place.
    NZ = 40

    # Centred, so there is room for both halves; the parent's 0.20 horizon
    # would push the reflection off the top of the canvas.
    HORIZON = 0.5
    GROUND = 1.02
    HEIGHT = 0.34
    SPREAD = 1.15      # wider than the canvas: the walls run past the edges

    MIRROR_Y = 0.5     # the water line; normally == HORIZON
    REFLECT_DIM = 0.55
    REFLECT_BLUR = 1.7

    def _project(self, f, W, H, np_, color_fn):
        px, py, sigma, rgb, ambient = super()._project(f, W, H, np_, color_fn)
        return (np.concatenate([px, px]),
                np.concatenate([py, 2.0 * self.MIRROR_Y - py]),
                np.concatenate([sigma, sigma * self.REFLECT_BLUR]),
                np.concatenate([rgb, rgb * self.REFLECT_DIM]),
                ambient)


class VortexScene(SpectrumColored, Scene):
    """Constellation's data in polar coordinates: you are flying up a throat
    of sound.

    Each row of history is a RING rather than a line -- frequency runs around
    the circumference, the ring's radius bulges outward wherever that band is
    loud, and older rings recede toward a vanishing point dead ahead. A loud
    moment is therefore a flared mouth of light that rushes away from you, and
    the whole tunnel corkscrews because each ring is rotated a little further
    than the one in front of it (TWIST).

    Pick an index-based scheme here ("blue_pink", "rainbow"): with frequency
    mapped to angle, the tunnel wall becomes a slowly rotating color wheel,
    which is the look this scene is built around. A level-based scheme paints
    the whole tunnel one breathing color instead -- also nice, much less
    readable.
    """

    name = "vortex"

    # ---- shape -------------------------------------------------------------
    NX = 128           # points around a ring; frequency -> angle
    NZ = 64            # rings of history visible down the tunnel
    HISTORY_HZ = 26.0  # NZ / HISTORY_HZ ~= 2.5s of tunnel

    R0 = 0.42          # front ring radius, as a fraction of canvas height
    BULGE = 0.55       # how far a full-level column pushes the wall out
    TWIST = 2.2        # radians of corkscrew from the front ring to the back
    SPIN = 0.25        # rad/s the whole tunnel turns

    # ---- camera ------------------------------------------------------------
    FOCAL = 0.45
    DEPTH = 3.0

    # ---- look --------------------------------------------------------------
    COLOR_SCHEME = "me2"
    USE_ALBUM_COLORS = False

    MAX_SPLAT_PX = 1_050_000
    DOT_RADIUS = 2.4
    KERNEL_R = 3
    GLOW = 1.3
    GLOW_DOWNSCALE = 10
    BRIGHTNESS = 3.0
    DEPTH_FADE = 1.0

    BEAT_LIFT = 0.25   # how far a beat flares the wall outward
    BEAT_DOLLY = 2.5   # rows of forward lurch on a beat -- the camera kick
    AMBIENT = 0.02
    FLASH = 0.1

    def __init__(self):
        self.f = None
        self.t = 0.0
        self.hist = fx.SpectrumHistory(self.NX, self.NZ, self.HISTORY_HZ)
        self.cloud = fx.PointCloud(self.MAX_SPLAT_PX, self.KERNEL_R)
        self._theta = np.linspace(0.0, 2.0 * np.pi, self.NX, endpoint=False,
                                  dtype=np.float32)
        self._tail = fx.depth_tail(self.NZ)

    def update(self, f, dt):
        self.f = f
        self.t += dt
        if f is None:
            return
        self.hist.push(f.bands, dt)

    def draw(self, surface):
        f = self.f
        W, H = surface.get_size()
        if f is None:
            surface.fill((0, 0, 0))
            return
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)

        # depth, with the beat's forward lurch subtracted off it
        z = (np.arange(self.NZ, dtype=np.float32) + self.hist.acc
             - self.BEAT_DOLLY * f.beat_strength) / self.NZ
        z = np.maximum(0.0, z)
        persp = fx.perspective(z, self.FOCAL, self.DEPTH)[:, None]   # (NZ,1)

        lvl = self.hist.rows + self.BEAT_LIFT * f.beat_strength      # (NZ,NX)
        r = self.R0 * (1.0 + self.BULGE * lvl) * persp
        theta = (self._theta[None, :] + self.TWIST * z[:, None]
                 + self.SPIN * self.t)

        # the H/W factor is what keeps the rings circular rather than
        # elliptical -- px is normalized against the canvas WIDTH
        sx = 0.5 + r * np.cos(theta) * (H / float(W))
        sy = 0.5 + r * np.sin(theta)

        inten = ((persp ** self.DEPTH_FADE) * (0.18 + 0.82 * lvl)
                 * self._tail[:, None] * self.BRIGHTNESS)

        front = self.hist.rows[0]
        cols = np.array([color_fn(i, self.NX, float(front[i]), f, np_)
                         for i in range(self.NX)], dtype=np.float32) / 255.0
        rgb = (cols[None, :, :] * inten[:, :, None]).reshape(-1, 3)

        sigma = self.DOT_RADIUS * np.broadcast_to(persp, sx.shape).ravel()
        ambient = cols.mean(axis=0) * (self.AMBIENT
                                       + self.FLASH * f.beat_strength)
        self.cloud.splat(surface, sx.ravel(), sy.ravel(), sigma, rgb,
                         ambient=ambient, glow=self.GLOW,
                         glow_downscale=self.GLOW_DOWNSCALE)

    def led(self, f):
        """The front ring -- the live spectrum -- through the same palette, so
        the strip is the mouth of the tunnel unrolled."""
        return self._spectrum_led(f)


class ResonanceScene(SpectrumColored, Scene):
    """Cymatics, one dimension up: a globe of points whose surface is being
    driven by the music.

    CymaticsScene shows the standing waves a plate makes; this shows the ones a
    sphere makes. The displacement field is the same superposition -- one term
    per band, mode numbers rising with that band's level, plus a ripple fired
    by the beat -- evaluated on unit vectors instead of a flat grid. Crests
    bulge out of the shell and catch the light, troughs collapse toward the
    core, and the whole thing turns slowly so the pattern is never seen from
    the same angle twice.

    _field() / _colorize() are split for the same reason CymaticsScene splits
    them: led() evaluates the exact same field around the equator, so the strip
    is a great circle of what is on screen rather than something merely similar.
    """

    name = "resonance"

    # ---- shape -------------------------------------------------------------
    # Points are spread by the golden-angle (Fibonacci) spiral, which gives an
    # even covering with no pole clustering -- the thing that makes a naive
    # lat/long sphere look like a wireframe globe. Precomputed in __init__, so
    # tune by subclassing.
    N_POINTS = 6000
    R0 = 0.40          # sphere radius, as a fraction of canvas height
    AMP = 0.45         # how far a crest bulges off the shell

    SPIN = 0.22        # rad/s about the vertical axis
    TILT = 0.38        # fixed lean toward the camera, so you see the top
    MOTION = 1.0       # scales the scene clock

    # ---- camera ------------------------------------------------------------
    # The sphere spans roughly z = -0.6..0.6 in front of the camera, so a
    # perspective on (0.5 + z) makes the near face noticeably larger and softer
    # than the far one -- which is the entire depth cue here.
    FOCAL = 0.9
    DEPTH = 1.3

    # ---- look --------------------------------------------------------------
    COLOR_SCHEME = "me1"
    USE_ALBUM_COLORS = False

    # Hue is looked up by the point's own displacement, so this scene reads
    # like a level-based scheme no matter which one is selected: "me1"/"me2"
    # ramp the crests through their range, "blue_pink"/"rainbow" spread the
    # whole wheel across the surface.
    LUT_N = 64

    MAX_SPLAT_PX = 1_050_000
    DOT_RADIUS = 2.2
    KERNEL_R = 3
    GLOW = 1.4
    GLOW_DOWNSCALE = 10
    BRIGHTNESS = 2.4
    DEPTH_FADE = 1.2
    CONTRAST = 1.6     # gamma on brightness; >1 carves the troughs dark
    BEAT_LIFT = 0.25

    AMBIENT = 0.02
    FLASH = 0.1

    LED_PIXELS = 48
    LED_FLOOR = 0.25   # see CymaticsScene.LED_FLOOR -- troughs go black here

    def __init__(self):
        self.f = None
        self.t = 0.0
        self.cloud = fx.PointCloud(self.MAX_SPLAT_PX, self.KERNEL_R)

        n = self.N_POINTS
        i = np.arange(n, dtype=np.float32) + 0.5
        phi = np.arccos(1.0 - 2.0 * i / n)               # polar angle
        th = np.float32(np.pi * (1.0 + np.sqrt(5.0))) * i  # golden angle
        self._u = np.stack([np.cos(th) * np.sin(phi),
                            np.cos(phi),
                            np.sin(th) * np.sin(phi)], axis=1).astype(np.float32)

        # equator, for led() -- the same unit-vector math, one ring of it
        a = np.linspace(0.0, 2.0 * np.pi, self.LED_PIXELS, endpoint=False,
                        dtype=np.float32)
        self._u_led = np.stack([np.cos(a), np.zeros_like(a), np.sin(a)],
                               axis=1).astype(np.float32)

    def update(self, f, dt):
        self.f = f
        self.t += dt * self.MOTION

    def _field(self, u, f):
        """Displacement at each unit vector `u` (..., 3). Three superposed
        standing waves, one per band, with mode numbers that climb as that band
        gets louder -- CymaticsScene._field() promoted to 3D -- plus a ripple
        travelling pole to pole on the beat. Roughly -3..3 when loud."""
        bass = f.bass if f else 0.3
        mid = f.mid if f else 0.3
        treble = f.treble if f else 0.3
        beat = f.beat_strength if f else 0.0
        t = self.t

        X, Y, Z = u[..., 0], u[..., 1], u[..., 2]
        m1 = 2.0 + bass * 7.0
        m2 = 3.0 + mid * 9.0
        m3 = 4.0 + treble * 11.0
        field = (
            bass * np.sin(m1 * X + t * 0.6) * np.sin(m1 * Y - t * 0.6)
            + mid * np.sin(m2 * Y + t * 0.9) * np.cos(m2 * Z - t * 0.5)
            + treble * np.cos(m3 * (X + Y + Z) + t * 1.3)
        )
        if beat > 0.01:
            field = field + beat * np.sin(Y * 9.0 - t * 6.0)
        return field

    def _colorize(self, field, f):
        """Field -> a 0..1 "excitation" that drives brightness, dot size and
        the palette lookup all at once. tanh caps the spread so a loud passage
        saturates rather than running away."""
        e = 0.5 + 0.5 * np.tanh(field * 0.9)
        if f is not None:
            e = np.clip(e + self.BEAT_LIFT * f.beat_strength, 0.0, 1.0)
        return e

    def draw(self, surface):
        f = self.f
        W, H = surface.get_size()
        if f is None:
            surface.fill((0, 0, 0))
            return
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)

        e = self._colorize(self._field(self._u, f), f)
        radius = self.R0 * (1.0 + self.AMP * (2.0 * e - 1.0))
        pos = self._u * radius[:, None]

        # rotate: spin about the vertical axis, then a fixed tilt toward the
        # camera. Two 2x2 rotations rather than a matrix multiply -- at 6000
        # points the difference is noise, and this is easier to read.
        a = self.SPIN * self.t
        ca, sa = np.cos(a), np.sin(a)
        x = pos[:, 0] * ca + pos[:, 2] * sa
        zc = -pos[:, 0] * sa + pos[:, 2] * ca
        ct, st = np.cos(self.TILT), np.sin(self.TILT)
        y = pos[:, 1] * ct - zc * st
        z = pos[:, 1] * st + zc * ct

        persp = fx.perspective(0.5 + z, self.FOCAL, self.DEPTH)
        sx = 0.5 + x * persp * (H / float(W))
        sy = 0.5 + y * persp

        inten = ((persp ** self.DEPTH_FADE) * (e ** self.CONTRAST)
                 * self.BRIGHTNESS)
        lut = self._scheme_lut(color_fn, self.LUT_N, f, np_)
        rgb = self._lut_take(lut, e) * inten[:, None]

        sigma = self.DOT_RADIUS * persp
        ambient = lut.mean(axis=0) * (self.AMBIENT
                                      + self.FLASH * f.beat_strength)
        self.cloud.splat(surface, sx, sy, sigma, rgb, ambient=ambient,
                         glow=self.GLOW, glow_downscale=self.GLOW_DOWNSCALE)

    def led(self, f):
        """The equator of the globe, through the same field and the same
        palette -- the strip is a great circle of what's on screen."""
        if f is None:
            return None
        np_ = self.now_playing
        lut = self._scheme_lut(self._active_color_fn(np_), self.LUT_N, f, np_)
        e = self._colorize(self._field(self._u_led, f), f)
        # compress into LED_FLOOR..1 so a trough rests on the dim end of the
        # scheme's own ramp instead of switching the pixel off (the profile's
        # floor can't rescue a pixel that is already black -- see led.py)
        v = self.LED_FLOOR + (1.0 - self.LED_FLOOR) * e
        return self._lut_take(lut, e) * v[:, None] * 255.0


class CartographScene(SpectrumColored, Scene):
    """The same history as Constellation, drawn as ridgelines instead of dots:
    an animated *Unknown Pleasures* plot.

    Every scene in this family glows; this one deliberately doesn't. Rows are
    drawn back to front, each one filled with the background color before its
    top edge is stroked, so a near ridge hides the ones behind it -- that
    painter's-algorithm fill IS the hidden-line removal, and it is what gives
    the scene its flat, printed, cartographic look.

    Hue encodes AGE here rather than frequency: each ridge takes one color from
    the scheme at its own row index, so the front line is one end of the ramp
    and the horizon is the other, and a loud moment visibly travels back
    through the palette. Set PER_SEGMENT_COLOR to color the front rows by
    frequency instead (capped -- see the constant).
    """

    name = "cartograph"

    # Polylines and polygons are hard-edged; pygame has no AA for either, and
    # at 1:1 these ridges visibly stair-step on a TV.
    SUPERSAMPLE = 2

    # ---- shape -------------------------------------------------------------
    NX = 120
    NZ = 46
    HISTORY_HZ = 10.0

    FOCAL = 0.45
    DEPTH = 2.2
    SPREAD = 1.4
    HORIZON = 0.24
    GROUND = 0.94
    HEIGHT = 0.34

    # ---- look --------------------------------------------------------------
    COLOR_SCHEME = "me2"
    USE_ALBUM_COLORS = False

    BG = (5, 5, 9)
    BG_FLASH = 22      # how far a beat lifts the background
    LINE_W = 1.4       # stroke width of the front ridge, at fx.REF_H
    FAR_SHADE = 0.25   # brightness of the furthest ridge, as a fraction

    # A soft halo, drawn as a second wide low-alpha stroke of every ridge onto
    # one additive layer. It deliberately ignores the occlusion (a back ridge's
    # halo shows through a front one), which reads as haze in the valley.
    # Set 0 to get the flat, purely graphic version.
    GLOW_ALPHA = 28

    # Number of front rows to color segment-by-segment when PER_SEGMENT_COLOR
    # is on. This has to stay small: a segment is one pygame.draw.line call, so
    # the whole field would be NX*NZ ~= 5500 calls a frame.
    PER_SEGMENT_COLOR = False
    PER_SEGMENT_ROWS = 6

    def __init__(self):
        self.f = None
        self.hist = fx.SpectrumHistory(self.NX, self.NZ, self.HISTORY_HZ)
        self._xn = (np.linspace(0.0, 1.0, self.NX, dtype=np.float32) - 0.5)
        self._tail = fx.depth_tail(self.NZ, power=4.0)
        self._scratch = {}

    def update(self, f, dt):
        self.f = f
        if f is None:
            return
        self.hist.push(f.bands, dt)

    def draw(self, surface):
        f = self.f
        W, H = surface.get_size()
        flash = int(self.BG_FLASH * (f.beat_strength if f else 0.0))
        bg = tuple(min(255, c + flash) for c in self.BG)
        surface.fill(bg)
        if f is None:
            return

        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)
        s = fx.scale(surface)

        z = (np.arange(self.NZ, dtype=np.float32) + self.hist.acc) / self.NZ
        persp = fx.perspective(z, self.FOCAL, self.DEPTH)
        pn = persp / persp[0]                       # 1 at the front, small far
        lvl = self.hist.rows

        sx = (0.5 + self._xn[None, :] * self.SPREAD * persp[:, None]) * W
        sy = (self.HORIZON + (self.GROUND - self.HORIZON
                              - lvl * self.HEIGHT) * persp[:, None]) * H
        pts_all = np.stack([sx, sy], axis=2).astype(np.int32)

        glow = (fx.scratch_surface(self._scratch, "glow", (W, H))
                if self.GLOW_ALPHA > 0 else None)

        for r in range(self.NZ - 1, -1, -1):
            pts = pts_all[r].tolist()
            shade = self._tail[r] * (self.FAR_SHADE
                                     + (1.0 - self.FAR_SHADE) * pn[r])
            col = color_fn(r, self.NZ, float(lvl[r].mean()), f, np_)
            col = tuple(int(c * shade) for c in col)
            width = max(1, int(round(self.LINE_W * s * pn[r])))

            # fill first: this is the hidden-line removal
            pygame.draw.polygon(surface, bg,
                                pts + [[pts[-1][0], H], [pts[0][0], H]])
            if glow is not None:
                pygame.draw.lines(glow, (*col, self.GLOW_ALPHA), False, pts,
                                  width=width * 4)
            if self.PER_SEGMENT_COLOR and r < self.PER_SEGMENT_ROWS:
                for i in range(self.NX - 1):
                    c = color_fn(i, self.NX, float(lvl[r, i]), f, np_)
                    pygame.draw.line(surface, tuple(int(v * shade) for v in c),
                                     pts[i], pts[i + 1], width)
            else:
                pygame.draw.lines(surface, col, False, pts, width=width)

        if glow is not None:
            surface.blit(glow, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

    def led(self, f):
        """The front ridge, i.e. the live spectrum."""
        return self._spectrum_led(f)


class LatticeScene(SpectrumColored, Scene):
    """A crystal of points standing still in space while the music moves
    through it.

    Everything else in this family draws the music itself; here the structure
    is fixed and the music is the LIGHT travelling through it. Three plane
    waves -- one per band, their directions slowly turning, their wavelengths
    shortening as that band gets louder -- sweep through a 3D grid; a point
    near a crest brightens, swells and is nudged outward, and everything else
    stays as faint scaffolding. That scaffolding is the point: unlike a
    spectrum cloud, this scene still has something on screen during a quiet
    passage.

    The camera orbits, so the grid shears through itself and moire patterns
    surface and dissolve on their own.
    """

    name = "lattice"

    # ---- shape -------------------------------------------------------------
    # NX*NY*NZ points, precomputed in __init__ -- subclass to change, don't
    # mutate an instance. ~6000 is the budget that keeps this near
    # Constellation's ~11ms at 1080p.
    NX, NY, NZ = 22, 14, 20

    ORBIT_SPEED = 0.12   # rad/s of yaw
    PITCH = 0.22         # base lean toward the camera
    PITCH_BOB = 0.10     # how far the lean drifts, at BOB_HZ
    BOB_HZ = 0.037
    MOTION = 1.0

    FOCAL = 0.9
    DEPTH = 1.3
    EXTENT = 0.62        # half-width of the grid, fraction of canvas height

    # ---- wave --------------------------------------------------------------
    WAVE_SPEED = 1.8     # how fast crests travel through the lattice
    K_BASE = 3.0         # wavenumber at silence
    K_GAIN = 9.0         # ...and how much each band's level adds to it
    SHARPNESS = 1.6      # >1 narrows the crests into sheets rather than fog
    DISPLACE = 0.07      # how far an excited point is pushed off its lattice
    FAINT = 0.12         # brightness of an unexcited point -- the scaffolding

    # ---- look --------------------------------------------------------------
    COLOR_SCHEME = "me1"
    USE_ALBUM_COLORS = False
    LUT_N = 64

    MAX_SPLAT_PX = 1_050_000
    # Small, because an excited point also swells (see draw()); DOT_RADIUS
    # times the swell has to stay comfortably under KERNEL_R or the brightest
    # dots -- which here are isolated rather than in a dense row -- get clipped
    # into visible squares.
    DOT_RADIUS = 1.6
    KERNEL_R = 3
    GLOW = 1.2
    GLOW_DOWNSCALE = 10
    BRIGHTNESS = 3.2
    DEPTH_FADE = 1.2
    BEAT_LIFT = 0.2

    AMBIENT = 0.02
    FLASH = 0.09

    LED_PIXELS = 48
    LED_FLOOR = 0.25

    def __init__(self):
        self.f = None
        self.t = 0.0
        self.cloud = fx.PointCloud(self.MAX_SPLAT_PX, self.KERNEL_R)

        gx, gy, gz = np.meshgrid(
            np.linspace(-1.0, 1.0, self.NX, dtype=np.float32),
            np.linspace(-1.0, 1.0, self.NY, dtype=np.float32),
            np.linspace(-1.0, 1.0, self.NZ, dtype=np.float32), indexing="ij")
        self._p = np.stack([gx.ravel(), gy.ravel(), gz.ravel()], axis=1)
        # unit vector from the centre, for the outward nudge
        n = np.linalg.norm(self._p, axis=1, keepdims=True)
        self._out = (self._p / np.maximum(n, 1e-3)).astype(np.float32)

        # a line straight through the middle of the lattice, for led()
        a = np.linspace(-1.0, 1.0, self.LED_PIXELS, dtype=np.float32)
        self._p_led = np.stack([a, np.zeros_like(a), np.zeros_like(a)], axis=1)

    def update(self, f, dt):
        self.f = f
        self.t += dt * self.MOTION

    def _dirs(self):
        """Three slowly turning unit directions for the plane waves. They are
        incommensurate on purpose, so the interference pattern never repeats."""
        t = self.t
        d = np.array([
            [np.cos(t * 0.11), np.sin(t * 0.07), np.sin(t * 0.05)],
            [np.sin(t * 0.09), np.cos(t * 0.13), np.sin(t * 0.06)],
            [np.sin(t * 0.04), np.sin(t * 0.08), np.cos(t * 0.10)],
        ], dtype=np.float32)
        return d / np.linalg.norm(d, axis=1, keepdims=True)

    def _excite(self, p, f):
        """0..1 excitation at each point: three plane waves summed, rectified
        (only crests light up -- troughs are just the unlit lattice), then
        sharpened into sheets."""
        bass = f.bass if f else 0.3
        mid = f.mid if f else 0.3
        treble = f.treble if f else 0.3
        beat = f.beat_strength if f else 0.0
        t = self.t
        d = self._dirs()

        w = 0.0
        for j, lvl in enumerate((bass, mid, treble)):
            k = self.K_BASE + self.K_GAIN * lvl
            phase = p @ d[j]
            w = w + lvl * np.sin(k * phase - t * self.WAVE_SPEED * (1.0 + j * 0.4))
        if beat > 0.01:
            w = w + beat * np.sin(np.linalg.norm(p, axis=-1) * 8.0 - t * 6.0)

        # normalize by how much signal there actually is, not by a constant:
        # the three terms are each scaled by their own band, so a quiet mix
        # would otherwise never reach a crest and the lattice would sit dark
        e = np.clip(w / max(0.35, bass + mid + treble), 0.0, 1.0) ** self.SHARPNESS
        return np.clip(e + self.BEAT_LIFT * beat, 0.0, 1.0)

    def draw(self, surface):
        f = self.f
        W, H = surface.get_size()
        if f is None:
            surface.fill((0, 0, 0))
            return
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)

        e = self._excite(self._p, f)
        pos = (self._p + self._out * (self.DISPLACE * e)[:, None]) * self.EXTENT

        a = self.ORBIT_SPEED * self.t
        ca, sa = np.cos(a), np.sin(a)
        x = pos[:, 0] * ca + pos[:, 2] * sa
        zc = -pos[:, 0] * sa + pos[:, 2] * ca
        pitch = self.PITCH + self.PITCH_BOB * np.sin(self.t * self.BOB_HZ * 6.28)
        ct, st = np.cos(pitch), np.sin(pitch)
        y = pos[:, 1] * ct - zc * st
        z = pos[:, 1] * st + zc * ct

        persp = fx.perspective(0.5 + z, self.FOCAL, self.DEPTH)
        sx = 0.5 + x * persp * (H / float(W))
        sy = 0.5 + y * persp

        inten = ((persp ** self.DEPTH_FADE)
                 * (self.FAINT + (1.0 - self.FAINT) * e) * self.BRIGHTNESS)
        lut = self._scheme_lut(color_fn, self.LUT_N, f, np_)
        rgb = self._lut_take(lut, e) * inten[:, None]

        # excited points swell as well as brighten, which is what makes a
        # crest read as a sheet passing through rather than a brightness change
        sigma = self.DOT_RADIUS * persp * (0.6 + 0.5 * e)
        ambient = lut.mean(axis=0) * (self.AMBIENT
                                      + self.FLASH * f.beat_strength)
        self.cloud.splat(surface, sx, sy, sigma, rgb, ambient=ambient,
                         glow=self.GLOW, glow_downscale=self.GLOW_DOWNSCALE)

    def led(self, f):
        """The same wave, sampled along a line straight through the middle of
        the lattice -- so a crest crossing the strip is a crest crossing the
        screen."""
        if f is None:
            return None
        np_ = self.now_playing
        lut = self._scheme_lut(self._active_color_fn(np_), self.LUT_N, f, np_)
        e = self._excite(self._p_led, f)
        v = self.LED_FLOOR + (1.0 - self.LED_FLOOR) * e
        return self._lut_take(lut, e) * v[:, None] * 255.0
