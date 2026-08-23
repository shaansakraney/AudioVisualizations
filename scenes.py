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

Add your own by subclassing Scene and dropping it into the list in run.py.
Color/scale/particle/field helpers live in fx.py -- see that module before
building something new; most scene ideas are a combination of what's there.
"""

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
        base = min(w, h) * 0.18
        radius = base + (w * 0.32) * (0.5 * f.bass + 0.5 * f.rms)
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


class BarsScene(Scene):
    name = "bars"

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
    hue = 0.67 + 0.2 * val
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

        # album colors take over while something is playing, then hand back
        # to whatever scheme was selected once it stops
        color_fn = self.color_fn
        if self.USE_ALBUM_COLORS and np_ is not None and np_.palette:
            color_fn = _spectrum_scheme_album

        bands = f.bands
        n = len(bands)
        gap = max(6, round(10 * s))
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
            pygame.draw.rect(glow, (*col, 60), pygame.Rect(rect).inflate(gap, gap),
                              border_radius=pill + gap // 2)
        surface.blit(glow, (0, 0))
        for rect, col in rects:
            pygame.draw.rect(surface, col, rect, border_radius=pill)


class LightningScene(Scene):
    """Branching electric bolts from the center. Beats fire a main strike
    with a couple of forking branches; hot treble occasionally crackles a
    smaller bolt even off-beat. Geometry comes from fx.lightning_bolt() /
    fx.lightning_branches(), rendered with fx.draw_bolt()'s glow+core+hot
    layering, additive-blended so overlapping bolts brighten."""

    name = "lightning"

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


class CymaticsScene(Scene):
    """Nodal standing-wave interference patterns -- one mode per band, so
    louder bands make tighter/denser patterns -- plus a beat-triggered
    radial ripple term. Literally the physics of "shapes made by sound."
    All math lives in fx.draw_field()/fx.field_grid(); this scene is just
    the field function."""

    name = "cymatics"

    def __init__(self):
        self.f = None
        self.t = 0.0
        self.res = (240, 135)  # low internal field resolution, upscaled to canvas

    def update(self, f, dt):
        self.f = f
        self.t += dt

    def draw(self, surface):
        f = self.f
        bass = f.bass if f else 0.3
        mid = f.mid if f else 0.3
        treble = f.treble if f else 0.3
        centroid = f.centroid if f else 0.5
        beat = f.beat_strength if f else 0.0
        t = self.t

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
            value = 0.5 + 0.5 * np.tanh(field * 0.9)
            hue = (centroid * 0.5 + 0.15 * field + t * 0.02) % 1.0
            return hue, value

        fx.draw_field(surface, self.res, field_fn)
