"""
fx.py
-----
Shared rendering/math infrastructure that scenes compose instead of
re-deriving. Five pieces:

- color/scale helpers   (hsv, scale, aacircle, fade)      -- used by everyone
- Particles              a vectorized particle system      -- Nebula today;
                                                               flow fields /
                                                               attractors /
                                                               sparks later
- lightning_bolt / lightning_branches / draw_bolt          -- Lightning today;
                                                               any future
                                                               "electric" motif
- field_grid / draw_field                                  -- Cymatics today;
                                                               Plasma later
- palette_from_surface / circle_masked / blurred_backdrop  -- album art in
                                                               Pulse+Spectrum;
                                                               any image-driven
                                                               visual later

Physics/geometry (particle updates, bolt paths, field math) is vectorized
with numpy; only actual pygame draw calls loop per-object, since pygame has
no vectorized drawing API. That's cheap up to a few hundred particles/bolts
at 60fps -- the field renderer sidesteps the same limit entirely by
computing color at low resolution and letting `smoothscale` do the rest.
"""

import colorsys

import numpy as np
import pygame
import pygame.gfxdraw as gfxdraw

REF_H = 320  # canvas height the small pixel-tuned constants were designed against


def scale(surface):
    """Size multiplier relative to the 320px-tall reference canvas, so
    stroke widths / gaps / radii tuned small still look right at 1080p."""
    return surface.get_height() / REF_H


def hsv(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def aacircle(surface, color, center, radius, width=0):
    """Filled anti-aliased circle (gfxdraw). Ring outlines (width > 0) use
    pygame's native thick-circle draw -- stacking gfxdraw outlines produces
    a dashed moire artifact at large radii."""
    cx, cy = int(center[0]), int(center[1])
    radius = max(1, int(radius))
    if width <= 0:
        gfxdraw.filled_circle(surface, cx, cy, radius, color)
        gfxdraw.aacircle(surface, cx, cy, radius, color)
    else:
        pygame.draw.circle(surface, color, (cx, cy), radius, width=width)


_fade_cache = {}


def fade(surface, amount):
    """Darken `surface` in place by `amount` (0..255) without a full clear
    -- the standard trick for particle/attractor motion trails: call this
    instead of surface.fill(...) each frame so previous frames fade out
    rather than vanish. The black fader surface is cached by size (module-
    level, since fade() has no per-scene state to hang it on) rather than
    allocated fresh every call."""
    size = surface.get_size()
    fader = _fade_cache.get(size)
    if fader is None:
        fader = pygame.Surface(size)
        fader.fill((0, 0, 0))
        _fade_cache[size] = fader
    fader.set_alpha(amount)
    surface.blit(fader, (0, 0))


def scratch_surface(cache, key, size):
    """Persistent SRCALPHA surface for `key`, cleared to fully transparent
    on every call. `cache` is a plain dict the caller owns (usually
    `self._scratch = {}` on a scene). Use this instead of allocating a
    fresh `pygame.Surface(size, pygame.SRCALPHA)` every frame -- at
    1920x1080 that allocation is expensive enough to measurably compete
    with the audio callback thread for CPU/GIL time. Profiling showed
    scenes doing this every frame missing the ~23ms real-time audio
    deadline on a meaningful fraction of frames, heard as crackle/dropouts."""
    surf = cache.get(key)
    if surf is None or surf.get_size() != size:
        surf = pygame.Surface(size, pygame.SRCALPHA)
        cache[key] = surf
    else:
        surf.fill((0, 0, 0, 0))
    return surf


# ---------------------------------------------------------------------------
# Particle system
# ---------------------------------------------------------------------------

class Particles:
    """Fixed-capacity particle pool. Position/velocity/life/hue/size/flash
    live in numpy arrays and are updated in a handful of vectorized ops per
    frame, regardless of how many particles are alive. `flash` is a generic
    0..1 "extra brightness" channel (decays on its own) for one-shot effects
    like a twinkle or a spark igniting, layered on top of the life-based
    fade -- reusable by anything that wants a momentary highlight."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.pos = np.zeros((capacity, 2), dtype=np.float32)
        self.vel = np.zeros((capacity, 2), dtype=np.float32)
        self.life = np.zeros(capacity, dtype=np.float32)       # <=0 means dead
        self.max_life = np.ones(capacity, dtype=np.float32)
        self.hue = np.zeros(capacity, dtype=np.float32)
        self.size = np.ones(capacity, dtype=np.float32)
        self.flash = np.zeros(capacity, dtype=np.float32)
        self._scratch = {}  # cached draw() layer -- see fx.scratch_surface

    def alive_mask(self):
        return self.life > 0.0

    def spawn(self, n, pos, vel, life, hue, size):
        """Fill up to n free slots with new particles (dead ones first,
        otherwise the particles nearest death -- a burst never silently
        drops if the pool is momentarily full). pos/vel/life/hue/size may
        be scalars/pairs (broadcast) or arrays of length n."""
        if n <= 0:
            return
        dead = np.where(~self.alive_mask())[0]
        if len(dead) < n:
            extra = np.argsort(self.life)[:n - len(dead)]
            dead = np.concatenate([dead, extra])
        idx = dead[:n]
        self.pos[idx] = pos
        self.vel[idx] = vel
        self.life[idx] = life
        self.max_life[idx] = life
        self.hue[idx] = hue
        self.size[idx] = size
        self.flash[idx] = 0.0

    def ignite(self, idx, amount=1.0):
        """Bump the flash channel for particles at `idx` (index array)."""
        if len(idx):
            self.flash[idx] = np.maximum(self.flash[idx], amount)

    def update(self, dt, drag=0.0, gravity=(0.0, 0.0), flash_decay=3.0):
        alive = self.alive_mask()
        self.pos[alive] += self.vel[alive] * dt
        if drag:
            self.vel[alive] *= max(0.0, 1.0 - drag * dt)
        if gravity[0] or gravity[1]:
            self.vel[alive] += np.array(gravity, dtype=np.float32) * dt
        self.life[alive] -= dt
        self.life[~alive] = 0.0
        self.flash = np.maximum(0.0, self.flash - flash_decay * dt)

    def draw(self, surface, base_alpha=255, size_mul=1.0, sat=0.7, glow=True,
             additive=False):
        """Anti-aliased glow circles. Drawing still loops per particle --
        pygame has no vectorized draw call -- but that's cheap for a few
        hundred particles at 60fps.

        `additive=True` composites the whole particle layer onto `surface`
        with BLEND_RGBA_ADD, which looks great for a single already-cleared
        frame (bright overlaps) but must NOT be used when `surface` is a
        persistent multi-frame trail: slow-moving particles would then add
        fresh light on top of their own barely-faded previous frame every
        tick and the trail saturates to solid white within a few dozen
        frames. Onto a persistent trail surface, leave this False (normal
        alpha blending) and let fx.fade() handle the fade-out instead."""
        idx = np.where(self.alive_mask())[0]
        if len(idx) == 0:
            return
        life_ratio = np.clip(self.life[idx] / self.max_life[idx], 0.0, 1.0)
        brightness = np.clip(life_ratio + self.flash[idx], 0.0, 1.0)

        layer = scratch_surface(self._scratch, "layer", surface.get_size())
        for k, i in enumerate(idx):
            a = int(base_alpha * brightness[k])
            if a <= 0:
                continue
            color = hsv(float(self.hue[i]), sat, 1.0)
            r = max(1.0, self.size[i] * size_mul * (1.0 + 0.6 * self.flash[i]))
            if glow:
                aacircle(layer, (*color, max(0, a // 3)), self.pos[i], r * 2.2)
            aacircle(layer, (*color, a), self.pos[i], r)
        if additive:
            surface.blit(layer, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        else:
            surface.blit(layer, (0, 0))


# ---------------------------------------------------------------------------
# Lightning geometry
# ---------------------------------------------------------------------------

def lightning_bolt(rng, p0, p1, roughness=0.5, min_seg=14, generations=6):
    """Midpoint-displacement bolt: recursively displace the midpoint of
    each segment perpendicular to it by a random amount proportional to
    the segment length, producing a jagged path from p0 to p1. Displacement
    shrinks each generation so detail gets finer without the bolt wandering
    further off its main line. Returns a list of (x, y) points."""
    points = [np.array(p0, dtype=np.float32), np.array(p1, dtype=np.float32)]
    disp = roughness

    for _ in range(generations):
        out = [points[0]]
        for a, b in zip(points, points[1:]):
            seg = b - a
            length = float(np.linalg.norm(seg))
            if length < min_seg:
                out.append(b)
                continue
            normal = np.array([-seg[1], seg[0]], dtype=np.float32)
            n_len = np.linalg.norm(normal)
            if n_len > 1e-6:
                normal /= n_len
            mid = (a + b) / 2 + normal * rng.uniform(-1, 1) * disp * length
            out.append(mid)
            out.append(b)
        points = out
        disp *= 0.55

    return [(float(x), float(y)) for x, y in points]


def lightning_branches(rng, points, n_branches, length_frac=0.35, roughness=0.5):
    """A few shorter secondary bolts forking off random points along a main
    bolt's point list. Returns a list of point-lists."""
    branches = []
    if len(points) < 3 or n_branches <= 0:
        return branches
    for _ in range(n_branches):
        i = int(rng.integers(1, len(points) - 1))
        a = np.array(points[i], dtype=np.float32)
        prev = np.array(points[i - 1], dtype=np.float32)
        direction = a - prev
        angle = rng.uniform(-1.0, 1.0) * 1.1
        cos_a, sin_a = np.cos(angle), np.sin(angle)
        rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float32)
        end = a + (rot @ direction) * length_frac * len(points)
        branches.append(lightning_bolt(rng, a, end, roughness=roughness))
    return branches


def draw_bolt(surface, points, color, width, alpha_core, alpha_glow):
    """Layered glow + colored core + white-hot center -- the standard
    "electric" look. `surface` should be an SRCALPHA layer blitted with
    BLEND_RGBA_ADD so overlapping bolts brighten instead of occlude."""
    if len(points) < 2:
        return
    pts = [(int(x), int(y)) for x, y in points]
    if alpha_glow > 0:
        pygame.draw.lines(surface, (*color, alpha_glow), False, pts, width=max(1, width * 3))
    pygame.draw.lines(surface, (*color, alpha_core), False, pts, width=max(1, width))
    hot = min(255, alpha_core + 60)
    pygame.draw.lines(surface, (255, 255, 255, hot), False, pts, width=max(1, width // 2))


# ---------------------------------------------------------------------------
# Procedural fields (plasma / cymatics style)
# ---------------------------------------------------------------------------

_grid_cache = {}


def field_grid(w, h):
    """Cached normalized coordinate grids for procedural fields. x spans
    +/-aspect, y spans +/-1, so patterns look consistent regardless of the
    field's resolution or the canvas's aspect ratio."""
    key = (w, h)
    if key not in _grid_cache:
        aspect = w / h
        xs = np.linspace(-aspect, aspect, w, dtype=np.float32)
        ys = np.linspace(-1.0, 1.0, h, dtype=np.float32)
        _grid_cache[key] = np.meshgrid(xs, ys)  # each shape (h, w)
    return _grid_cache[key]


def _hsv_array_to_rgb(h, s, v):
    """Vectorized HSV->RGB (h, s, v arrays in 0..1) -> uint8 (H, W, 3)."""
    i = (np.floor(h * 6.0).astype(np.int32)) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)

    conditions = [i == 0, i == 1, i == 2, i == 3, i == 4, i == 5]
    r = np.select(conditions, [v, q, p, p, t, v])
    g = np.select(conditions, [t, v, v, q, p, p])
    b = np.select(conditions, [p, p, t, v, v, q])

    rgb = np.stack([r, g, b], axis=-1)
    return np.clip(rgb * 255, 0, 255).astype(np.uint8)


def _rgb_array_to_hsv(rgb):
    """Vectorized RGB->HSV. `rgb` is (..., 3) in 0..1; returns h, s, v arrays
    each shaped like rgb[..., 0]. Counterpart to _hsv_array_to_rgb below --
    used by palette_from_surface to score colors by vividness."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx = np.max(rgb, axis=-1)
    mn = np.min(rgb, axis=-1)
    diff = mx - mn

    h = np.zeros_like(mx)
    mask = diff > 1e-9
    # which channel is the max decides which 60-degree sector the hue is in
    rm = mask & (mx == r)
    gm = mask & (mx == g) & ~rm
    bm = mask & (mx == b) & ~rm & ~gm
    with np.errstate(invalid="ignore", divide="ignore"):
        h[rm] = ((g[rm] - b[rm]) / diff[rm]) % 6.0
        h[gm] = ((b[gm] - r[gm]) / diff[gm]) + 2.0
        h[bm] = ((r[bm] - g[bm]) / diff[bm]) + 4.0
    h = h / 6.0

    s = np.zeros_like(mx)
    nz = mx > 1e-9
    s[nz] = diff[nz] / mx[nz]
    return h, s, mx


def draw_field(dst_surface, res, field_fn, sat=0.8):
    """Compute a procedural field at low resolution `res=(w, h)`, colorize
    it, upscale, and blit onto dst_surface. `field_fn(X, Y)` receives the
    cached coordinate grids and must return `(hue, value)` arrays shaped
    like X/Y, each roughly 0..1 (hue wraps, value is clipped).

    Doing this per-pixel in Python at full canvas resolution would be far
    too slow; computing it vectorized-with-numpy at low res and upscaling
    with smoothscale is the standard trick, and it keeps the soft/painterly
    look these fields want anyway.
    """
    w, h = res
    X, Y = field_grid(w, h)
    hue, value = field_fn(X, Y)
    sat_arr = np.full_like(hue, sat, dtype=np.float32)
    rgb = _hsv_array_to_rgb(np.mod(hue, 1.0), sat_arr, np.clip(value, 0.0, 1.0))
    field_surf = pygame.surfarray.make_surface(rgb.transpose(1, 0, 2))
    scaled = pygame.transform.smoothscale(field_surf, dst_surface.get_size())
    dst_surface.blit(scaled, (0, 0))


# ---------------------------------------------------------------------------
# Album art / palette
# ---------------------------------------------------------------------------

def palette_from_surface(surface, n=6, sample=64, min_dist=0.12):
    """Extract up to `n` prominent colors from an image (an album cover,
    typically) as a tuple of (r, g, b) ints, most prominent first.

    Downscales to `sample`x`sample` first so the clustering runs on a few
    thousand pixels instead of a few hundred thousand -- the same
    compute-small-then-use-big trick draw_field() relies on. Near-black,
    near-white and washed-out pixels are dropped before clustering, since
    cover art is usually mostly background and those colors make for a dull
    palette. Clusters are ranked by population * vividness so a small but
    saturated accent can still outrank a large muddy region.

    Colors closer together than `min_dist` (RGB euclidean, 0..1 scale) are
    merged, so a cover with only two real colors returns two entries rather
    than six near-identical ones. **That means the result can be shorter
    than `n`** -- index it with `palette[i % len(palette)]`.

    Falls back to a neutral gray if the image has no usable color.
    """
    small = pygame.transform.smoothscale(surface, (sample, sample))
    px = pygame.surfarray.array3d(small).reshape(-1, 3).astype(np.float32) / 255.0

    h, s, v = _rgb_array_to_hsv(px)
    # Filter on saturation, NOT on a value ceiling: a fully-saturated color
    # like pure orange has v == 1.0 (its red channel is maxed), so a
    # `v < 0.97` "drop near-white" test would throw away exactly the vivid
    # colors cover art is built from. White/gray are already excluded here
    # because their saturation is ~0.
    keep = (v > 0.15) & (s > 0.18)
    pts = px[keep] if keep.sum() >= n else px
    if len(pts) < n:
        return ((160, 160, 160),)

    # k-means, deterministic init: spread the seeds over the value-sorted
    # points so we don't depend on RNG state and get a stable palette for a
    # given cover every time.
    order = np.argsort(pts[:, 0] * 0.3 + pts[:, 1] * 0.6 + pts[:, 2] * 0.1)
    seeds = np.linspace(0, len(pts) - 1, n).astype(int)
    centers = pts[order[seeds]].copy()

    for _ in range(12):
        d = np.linalg.norm(pts[:, None, :] - centers[None, :, :], axis=2)
        labels = np.argmin(d, axis=1)
        for k in range(n):
            m = labels == k
            if m.any():
                centers[k] = pts[m].mean(axis=0)

    counts = np.array([(labels == k).sum() for k in range(n)], dtype=np.float32)
    _, cs, cv = _rgb_array_to_hsv(centers)
    score = (counts / max(1.0, counts.sum())) * (0.35 + cs * cv)
    ranked = centers[np.argsort(-score)]

    # merge near-duplicates, keeping the higher-ranked one -- k-means on a
    # cover with only 2-3 real colors otherwise returns several copies of
    # the same shade plus muddy midpoints between them
    out = []
    for c in ranked:
        if all(np.linalg.norm(c - k) >= min_dist for k in out):
            out.append(c)
    return tuple(
        (int(c[0] * 255), int(c[1] * 255), int(c[2] * 255)) for c in out
    )


def most_vivid(palette, fallback=(255, 255, 255)):
    """Pick the most saturated-and-bright entry of a palette -- the color you
    want for highlights (beat rings, accents) where the dominant color is
    often too dark or too muted to read against the background."""
    if not palette:
        return fallback
    arr = np.array(palette, dtype=np.float32).reshape(-1, 3) / 255.0
    _, s, v = _rgb_array_to_hsv(arr)
    return tuple(int(c) for c in palette[int(np.argmax(s * v))])


def circle_masked(cache, key, art, diameter):
    """The image `art` scaled to `diameter` and clipped to a circle, cached
    under `key` in the caller's dict so a scene redrawing the same cover at
    the same size every frame pays the scale+mask cost once.

    Callers should quantize `diameter` (e.g. round to the nearest few px)
    before calling, otherwise a smoothly-animating radius produces a cache
    miss on every single frame and this saves nothing."""
    diameter = max(2, int(diameter))
    entry = cache.get(key)
    if entry is not None and entry[0] == diameter:
        return entry[1]

    scaled = pygame.transform.smoothscale(art, (diameter, diameter))
    out = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    out.blit(scaled, (0, 0))
    # white circle in the alpha channel, then multiply -> everything outside
    # the circle becomes fully transparent
    mask = pygame.Surface((diameter, diameter), pygame.SRCALPHA)
    mask.fill((0, 0, 0, 0))
    r = diameter // 2
    gfxdraw.filled_circle(mask, r, r, max(1, r - 1), (255, 255, 255, 255))
    gfxdraw.aacircle(mask, r, r, max(1, r - 1), (255, 255, 255, 255))
    out.blit(mask, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)

    cache[key] = (diameter, out)
    return out


def blurred_backdrop(cache, key, art, size, darken=195, downscale=14):
    """A cheap blurred, darkened copy of `art` filling `size` -- for using a
    cover as a full-screen background without it fighting the foreground.

    The "blur" is just a hard downscale followed by a smooth upscale, the
    same trick draw_field() uses; it costs almost nothing compared to a real
    convolution and looks right for a soft backdrop. Cached by (size,
    darken) under `key` since the result only changes when the track does."""
    size = (int(size[0]), int(size[1]))
    entry = cache.get(key)
    if entry is not None and entry[0] == (size, darken):
        return entry[1]

    tiny = pygame.transform.smoothscale(art, (downscale, downscale))
    out = pygame.transform.smoothscale(tiny, size)
    shade = pygame.Surface(size)
    shade.fill((0, 0, 0))
    shade.set_alpha(darken)
    out.blit(shade, (0, 0))

    cache[key] = ((size, darken), out)
    return out
