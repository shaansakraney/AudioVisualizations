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
    """Breathing orb. With Spotify connected (self.now_playing), the album
    cover becomes the orb itself -- circle-masked and scaled by the same
    bass+rms radius -- and the glow/rings/background take their colors from
    the cover's palette. Without it, everything falls back to the original
    centroid-driven hue, so resting mode looks exactly as it always did."""

    name = "pulse"

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

    def update(self, f, dt):
        self.f = f
        if f.beat:
            self.rings.append([0.0, 1.0])
        for r in self.rings:
            r[0] += dt * 260.0   # expand outward
            r[1] -= dt * 1.6     # fade out
        self.rings = [r for r in self.rings if r[1] > 0.0]

    def draw(self, surface):
        w, h = surface.get_size()
        s = scale(surface)
        f = self.f
        np_ = self.now_playing
        art = np_.art if np_ is not None else None
        palette = np_.palette if np_ is not None else ()

        # background: near-black. Tinted by the cover's dominant color when
        # there's a track, else by the original brightness+treble hue.
        if palette:
            dom = palette[0]
            surface.fill((int(dom[0] * 0.10), int(dom[1] * 0.10), int(dom[2] * 0.10)))
        else:
            surface.fill(hsv(f.centroid if f else 0.6, 0.5,
                             0.05 + 0.06 * (f.treble if f else 0.0)))
        if f is None:
            return

        cx, cy = w // 2, h // 2
        base = min(w, h) * 0.1
        radius = base + (w * 0.2) * (0.5 * f.bass + 0.5 * f.rms)
        radius += (w * 0.05) * f.beat_strength
        hue = f.centroid
        glow_col = palette[0] if palette else hsv(hue, 0.7, 1.0)
        core_col = palette[0] if palette else hsv(hue, 0.5, 1.0)
        ring_col = np_.accent if np_ is not None and palette else hsv(hue + 0.1, 0.6, 1.0)

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
        """A single color: the orb's own glow color, brightened by the same
        bass+rms mix that drives its radius. With a track playing that's the
        cover's dominant palette entry, so the strip washes the room in the
        album's colors; without one it's the centroid hue, exactly like the
        orb on screen. Returns one pixel -- LedSink spreads it across the
        whole strip, and pulses it on the beat."""
        if f is None:
            return None
        palette = self.now_playing.palette if self.now_playing is not None else ()
        col = palette[0] if palette else hsv(f.centroid, 0.7, 1.0)
        k = 0.2 + 0.8 * (0.5 * f.bass + 0.5 * f.rms)
        return [tuple(c * k for c in col)]


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
    hue = 0.62 + 0.3 * (i / (n - 1))
    return hsv(hue, 1, 1.0)


def _spectrum_scheme_rainbow_cycle(i, n, val, f, np_):
    """Full rainbow across the bars, slowly cycling over time."""
    hue = (i / n + f.t * 0.05) % 1.0
    return hsv(hue, 1, 1.0)


def _spectrum_scheme_reactive(i, n, val, f, np_):
    """Blue-pink ramp, but each bar's brightness pulses with its own level."""
    hue = 0.4 + 0.4 * (i / (n - 1))
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
    "album": _spectrum_scheme_album,
}


class SpectrumScene(Scene):
    """Apple-Music-style 6-bin spectrum: bars laid out left-to-right, each
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
    USE_ALBUM_COLORS = True

    # Draw the cover blurred + darkened behind the bars.
    SHOW_ALBUM_BACKDROP = True

    # Fraction of each bin's slot width the bar actually fills (0..1).
    # Lower = narrower bars with more gap between them; the bin's center
    # position doesn't move since it's computed from the slot, not the bar.
    BAR_WIDTH_FRAC = 0.9

    def __init__(self):
        self.f = None
        self._scratch = {}
        self._art_cache = {}
        self.color_fn = SPECTRUM_COLOR_SCHEMES[self.COLOR_SCHEME]

    def update(self, f, dt):
        self.f = f

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
        the bars are drawn with -- so the strip reads as a physical extension
        of the on-screen spectrum. LedSink stretches these len(f.bands) pixels
        across however many LEDs are wired up (or averages them down to one
        for an analog strip), and adds the beat pulse on top."""
        if f is None:
            return None
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)
        bands = f.bands
        n = len(bands)
        # brightness tracks each bin's own level, so the strip has the same
        # quiet-bins-go-dark shape the bars do
        return [tuple(c * (0.15 + 0.85 * val)
                      for c in color_fn(i, n, val, f, np_))
                for i, val in enumerate(bands)]


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


CYMATICS_COLOR_SCHEMES = {
    "spectral": _cymatics_scheme_spectral,   # the original, most colorful
    "mono": _cymatics_scheme_mono,           # calmest
    "duotone": _cymatics_scheme_duotone,
    "ember": _cymatics_scheme_ember,
    "ice": _cymatics_scheme_ice,
    "slow_drift": _cymatics_scheme_slow_drift,
    "album": _cymatics_scheme_album,
}


class CymaticsScene(Scene):
    """Nodal standing-wave interference patterns -- one mode per band, so
    louder bands make tighter/denser patterns -- plus a beat-triggered
    radial ripple term. Literally the physics of "shapes made by sound."
    All math lives in fx.draw_field()/fx.field_grid(); this scene is just
    the field function."""

    name = "cymatics"

    # ---- color -------------------------------------------------------------
    # Which palette to use; see CYMATICS_COLOR_SCHEMES above. "spectral" is
    # the original look.
    COLOR_SCHEME = "slow_drift"

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

    def __init__(self):
        self.f = None
        self.t = 0.0
        self.centroid = 0.5    # smoothed; see CENTROID_SMOOTHING
        self.color_fn = CYMATICS_COLOR_SCHEMES[self.COLOR_SCHEME]

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

    def draw(self, surface):
        f = self.f
        bass = f.bass if f else 0.3
        mid = f.mid if f else 0.3
        treble = f.treble if f else 0.3
        centroid = self.centroid
        beat = f.beat_strength if f else 0.0
        t = self.t
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)

        def field_fn(X, Y):
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

            # brightness: symmetric around 0.5, so raising CONTRAST is what
            # carves dark space out of an otherwise uniformly-lit canvas
            value = 0.5 + 0.5 * np.tanh(field * 0.9)
            value = self.BRIGHTNESS * value ** self.CONTRAST

            hue, sat = color_fn(field, centroid, t, np_)
            return hue, value, np.clip(sat * self.SATURATION, 0.0, 1.0)

        w, h = surface.get_size()
        div = max(1, int(np.ceil(np.sqrt(w * h / float(self.FIELD_MAX_PX)))))
        res = (max(2, w // div), max(2, h // div))
        fx.draw_field(surface, res, field_fn)


class ConstellationScene(Scene):
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

    Rendering is the same compute-small-then-upscale trick as fx.draw_field:
    ~3.2k points are splatted into a 480x270 float buffer with np.add.at
    (additive, so overlapping points bloom) and smoothscaled up, which both
    costs almost nothing (~3ms/frame at 1080p) and gives the soft glow for
    free. There is no per-point pygame call anywhere.
    """

    name = "constellation"

    # Tune by subclassing rather than mutating an instance -- some geometry is
    # precomputed from NX/NZ in __init__:
    #     class BigConstellation(ConstellationScene): NX, NZ = 128, 64
    #
    # ---- shape -------------------------------------------------------------
    NX = 96            # points across; frequency resolution
    NZ = 52            # depth rows; how many spectra of history are visible
    RES = (480, 270)   # internal buffer, upscaled to the canvas

    # Rows pushed per second. NZ / HISTORY_HZ = seconds of history on screen
    # (44 / 26 ~= 1.7s). Lower = slower, longer drift.
    HISTORY_HZ = 20.0

    # ---- camera ------------------------------------------------------------
    FOCAL = 0.55       # smaller = wider lens = more dramatic perspective
    DEPTH = 2.2        # how far back the last row sits
    SPREAD = 0.98      # width of the front row, as a fraction of the canvas
    HORIZON = 0.30     # vanishing point, 0=top 1=bottom
    GROUND = 0.85      # where a silent front-row point sits
    HEIGHT = 0.3      # how far a full-level point rises off the ground

    # ---- look --------------------------------------------------------------
    # Reuses SPECTRUM_COLOR_SCHEMES, so every palette you have already written
    # works here unchanged. One thing matters when picking one: a scheme whose
    # hue comes from the bar INDEX ("blue_pink", "rainbow", "reactive") paints
    # a left-to-right gradient, so color itself encodes frequency and the
    # cloud stays readable across a room. A scheme whose hue comes from the
    # LEVEL ("me1", "me2", "fire") instead colors by loudness, which looks
    # good but scatters hue across the surface. Hence the index-based default.
    COLOR_SCHEME = "me2"
    USE_ALBUM_COLORS = False
    
    # The soft glow is rendered at 1/GLOW_DOWNSCALE resolution and upscaled.
    # gfxdraw.filled_circle is O(radius^2), so this is a real speed dial --
    # but at 3 the falloff visibly bands on a big screen. 2 is the compromise;
    # 1 is exact and costs ~4x the glow time.
    GLOW_DOWNSCALE = 2

    BRIGHTNESS = 2.2
    DEPTH_FADE = 1.2   # exponent on the depth dimming; higher = darker distance
    DOT_SPREAD = 0.3  # weight of a point's 4 neighbours; higher = softer dots
    BEAT_LIFT = 0.25   # how much a beat lifts the whole field

    def __init__(self):
        self.f = None
        self.hist = np.zeros((self.NZ, self.NX), dtype=np.float32)
        self._acc = 0.0        # fractional row progress, for continuous drift
        self._scratch = {}
        self.color_fn = SPECTRUM_COLOR_SCHEMES[self.COLOR_SCHEME]

        # Static geometry, built once: column x positions and the per-row depth
        # ramp. Only the levels change per frame, so none of this is rebuilt.
        self._xn = (np.linspace(0.0, 1.0, self.NX, dtype=np.float32) - 0.5)
        self._src = np.linspace(0.0, 1.0, 1, dtype=np.float32)  # replaced below

    def update(self, f, dt):
        self.f = f
        if f is None:
            return
        bands = np.asarray(f.bands, dtype=np.float32)
        if len(self._src) != len(bands):
            self._src = np.linspace(0.0, 1.0, len(bands), dtype=np.float32)
        # smooth the 16 coarse bins up to NX columns so the ridge line is a
        # curve rather than a staircase
        dst = np.linspace(0.0, 1.0, self.NX, dtype=np.float32)
        row = np.interp(dst, self._src, bands).astype(np.float32)

        # Push history at a fixed rate independent of frame rate, keeping the
        # leftover as a fractional offset so the field drifts continuously
        # instead of stepping once per pushed row.
        self._acc += dt * self.HISTORY_HZ
        while self._acc >= 1.0:
            self._acc -= 1.0
            self.hist = np.roll(self.hist, 1, axis=0)
            self.hist[0] = row
        self.hist[0] = row   # keep the front row live between pushes

    def _active_color_fn(self, np_):
        if self.USE_ALBUM_COLORS and np_ is not None and np_.palette:
            return _spectrum_scheme_album
        return self.color_fn

    def draw(self, surface):
        f = self.f
        rw, rh = self.RES
        buf = np.zeros((rh, rw, 3), dtype=np.float32)
        if f is None:
            surface.fill((0, 0, 0))
            return

        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)

        # --- geometry, fully vectorized over (NZ, NX) ------------------------
        # depth 0..1 for each row, offset by the fractional scroll
        z = (np.arange(self.NZ, dtype=np.float32) + self._acc) / self.NZ
        persp = self.FOCAL / (self.FOCAL + z * self.DEPTH)      # (NZ,)
        persp = persp[:, None]                                   # (NZ,1)

        lift = self.BEAT_LIFT * f.beat_strength
        lvl = self.hist + lift                                   # (NZ,NX)

        sx = 0.5 + self._xn[None, :] * self.SPREAD * persp
        sy = self.HORIZON + (self.GROUND - self.HORIZON - lvl * self.HEIGHT) * persp

        # --- brightness: perspective dimming + the point's own level ---------
        tail = 1.0 - (np.arange(self.NZ, dtype=np.float32) / self.NZ) ** 3
        inten = (persp ** self.DEPTH_FADE) * (0.18 + 0.82 * lvl) * tail[:, None]
        inten *= self.BRIGHTNESS

        # --- color: one hue per frequency column, from the shared registry ---
        front = self.hist[0]
        cols = np.array([color_fn(i, self.NX, float(front[i]), f, np_)
                         for i in range(self.NX)], dtype=np.float32) / 255.0
        rgb = cols[None, :, :] * inten[:, :, None]               # (NZ,NX,3)

        # --- splat into the low-res buffer -----------------------------------
        xi = np.clip((sx * rw).astype(np.int32), 1, rw - 2)
        yi = np.clip((sy * rh).astype(np.int32), 1, rh - 2)
        xi, yi, rgb = xi.ravel(), yi.ravel(), rgb.reshape(-1, 3)
        w = self.DOT_SPREAD
        for dx, dy, wt in ((0, 0, 1.0), (1, 0, w), (-1, 0, w),
                           (0, 1, w), (0, -1, w)):
            np.add.at(buf, (yi + dy, xi + dx), rgb * wt)

        # additive accumulation means overlaps bloom; clip and upscale
        out = (np.clip(buf, 0.0, 1.0) * 255.0).astype(np.uint8)
        small = pygame.surfarray.make_surface(out.transpose(1, 0, 2))
        pygame.transform.smoothscale(small, surface.get_size(), surface)

    def led(self, f):
        """The front row -- i.e. the live spectrum -- through the same palette,
        so the strip matches the near edge of the point cloud."""
        if f is None:
            return None
        np_ = self.now_playing
        color_fn = self._active_color_fn(np_)
        bands = f.bands
        n = len(bands)
        return [tuple(c * (0.15 + 0.85 * val)
                      for c in color_fn(i, n, val, f, np_))
                for i, val in enumerate(bands)]
