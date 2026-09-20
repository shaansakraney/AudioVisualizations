"""
app.py
------
The render loop. Everything is drawn onto a fixed logical canvas
(CANVAS_W x CANVAS_H), then scaled onto whatever the window happens to be.

Resolution, in the order it matters for image quality:

1. By default the canvas is sized to the WINDOW, not to a fixed 1920x1080, so
   there is no rescale between canvas and screen at all -- every canvas pixel
   is a screen pixel. Pass --canvas WxH to pin a fixed logical resolution
   instead (the MCU-portability mode: effects then behave identically no
   matter how big the window is, at the cost of being resampled to fit).
2. SUPERSAMPLE renders that canvas at NxN the pixels and averages down. This
   is what anti-aliases everything at once -- pygame's rect/circle drawing
   has no AA of its own, so a "2" here is the difference between crisp and
   jagged on a big screen.
3. Whatever scaling is left keeps the canvas aspect ratio and letterboxes the
   remainder, so the image is never stretched or cropped.

Scaling uses smoothscale, NOT transform.scale. transform.scale point-samples,
which is fine upscaling pixel art but destroys an image on the way down: a
1px checker downscaled 2x came out solid white (mean 255) instead of mean 64,
because it happened to sample only the lit pixels. Every one of these scenes
is a smooth gradient rather than pixel art, so area-averaging is correct in
both directions.

Controls:  1-9 switch scene   h toggle HUD   l LED panel   f fullscreen
           esc/quit close

The LED panel is the one piece of interactive UI here. The strip is a light in
a room rather than an image on a screen, so it has to be tuned against the
actual wall, live, with the music playing -- which is what LedProfile and the
panel below exist for. Its edits are global: they hold across every scene.
"""

import pygame

from features import Features
from led import default_led
from ledprofile import LedProfile

CANVAS_W, CANVAS_H = 1920, 1080   # only used for --canvas / the window aspect
SCALE = 0.5          # initial window size is CANVAS * SCALE
FPS = 60

# Global multiplier on each scene's own Scene.SUPERSAMPLE. 1 keeps the
# per-scene defaults (which already say what each scene needs); raise it only
# if you have frames to spare.
SUPERSAMPLE = 1

# Cap on the supersampled canvas, so a 4K fullscreen at SUPERSAMPLE=2 doesn't
# quietly ask for a 7680x4320 render target.
MAX_CANVAS_PX = 3840 * 2160


class App:
    def __init__(self, source, scenes, now_playing=None, led_sink=None,
                 scale=SCALE, fullscreen=False, display=0,
                 canvas=None, supersample=SUPERSAMPLE):
        self.source = source
        self.scenes = scenes
        self.now_playing = now_playing  # NowPlayingProvider or None
        self.led_sink = led_sink        # LedSink; None-safe via NullTransport
        self.scene_idx = 0
        self.show_hud = True
        # The LED profile, and the panel that edits it. The profile is the
        # sink's, so the panel mutates exactly the object the sender thread
        # reads -- there is no copy to keep in sync.
        self.led_profile = (led_sink.profile if led_sink is not None
                            else LedProfile())
        self.show_led_panel = False
        self.led_cursor = 0
        self._led_msg = ""      # transient "saved"/"reset" note for the panel

        self.display = display
        self.fullscreen = fullscreen
        self.canvas_size = canvas          # None = match the window
        self.supersample = max(1, int(supersample))
        self._canvas = None
        # Remembered so leaving fullscreen restores the size you had, rather
        # than snapping back to the default.
        self._windowed_size = (int(CANVAS_W * scale), int(CANVAS_H * scale))
        self._win = None
        self._view = None   # cached scratch surface at the current blit size
        self._font = None
        self._font_px = 0

    # -- display ------------------------------------------------------------

    def _open_window(self):
        """(Re)create the display surface for the current windowed/fullscreen
        state. Called on startup and on every fullscreen toggle."""
        if self.fullscreen:
            # (0, 0) asks for the desktop resolution of the chosen display,
            # which is what you want on a TV -- no mode switch, no guessing.
            self._win = pygame.display.set_mode(
                (0, 0), pygame.FULLSCREEN, display=self.display)
        else:
            self._win = pygame.display.set_mode(
                self._windowed_size, pygame.RESIZABLE, display=self.display)
        return self._win

    def _dest_rect(self, win):
        """The largest CANVAS-aspect rect that fits in the window, centered.
        Everything outside it is a letterbox bar."""
        ww, wh = win.get_size()
        k = min(ww / CANVAS_W, wh / CANVAS_H)
        w, h = max(1, int(CANVAS_W * k)), max(1, int(CANVAS_H * k))
        return pygame.Rect((ww - w) // 2, (wh - h) // 2, w, h)

    def _canvas_for(self, win, scene):
        """The render target. By default it matches the on-screen rect exactly
        (times the scene's supersample factor), so nothing is ever resampled
        except the deliberate supersample averaging."""
        if self.canvas_size is not None:
            w, h = self.canvas_size
        else:
            w, h = self._dest_rect(win).size
        ss = max(1, getattr(scene, "SUPERSAMPLE", 1)) * self.supersample
        w, h = w * ss, h * ss
        if w * h > MAX_CANVAS_PX:                    # clamp, keeping aspect
            k = (MAX_CANVAS_PX / float(w * h)) ** 0.5
            w, h = max(1, int(w * k)), max(1, int(h * k))
        if self._canvas is None or self._canvas.get_size() != (w, h):
            self._canvas = pygame.Surface((w, h))
        return self._canvas

    def _blit_canvas(self, win, canvas):
        rect = self._dest_rect(win)
        if canvas.get_size() == rect.size:
            # the common path: canvas is exactly the on-screen rect, so the
            # pixels go straight to the window untouched
            if rect.size != win.get_size():
                win.fill((0, 0, 0))
            win.blit(canvas, rect.topleft)
            return
        # Reuse one scratch surface; a fresh 1080p allocation every frame is
        # pure garbage-collector churn. Only rebuilt when the size changes.
        if self._view is None or self._view.get_size() != rect.size:
            self._view = pygame.Surface(rect.size)
        # smoothscale, not scale -- see the module docstring
        pygame.transform.smoothscale(canvas, rect.size, self._view)
        if rect.size != win.get_size():
            win.fill((0, 0, 0))          # letterbox bars
        win.blit(self._view, rect.topleft)

    def _hud_font(self, win):
        """Font sized as a fraction of window height, so the HUD stays
        readable in a small window and doesn't balloon in fullscreen."""
        px = max(12, int(win.get_height() * 0.030))
        if self._font is None or px != self._font_px:
            self._font = pygame.font.SysFont("menlo,consolas,monospace", px)
            self._font_px = px
        return self._font

    # -- main loop ----------------------------------------------------------

    def run(self):
        pygame.init()
        pygame.display.set_caption("audioviz")
        win = self._open_window()
        clock = pygame.time.Clock()

        self.source.start()
        if self.now_playing is not None:
            self.now_playing.start()
        if self.led_sink is not None:
            self.led_sink.start()
        running = True
        while running:
            dt = clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.VIDEORESIZE and not self.fullscreen:
                    self._windowed_size = (event.w, event.h)
                elif event.type == pygame.KEYDOWN and not self._on_key(event):
                    running = False
            win = pygame.display.get_surface()
            scene = self.scenes[self.scene_idx]
            canvas = self._canvas_for(win, scene)

            f = self.source.read(dt)
            # read() is a cheap snapshot read -- the provider does all its
            # network work on its own thread (see nowplaying.py)
            np_ = self.now_playing.read() if self.now_playing is not None else None
            scene.now_playing = np_
            scene.update(f, dt)
            scene.draw(canvas)
            # second output, same Features: the scene's own LED frame if it
            # defines one, else a sane default. submit() is a non-blocking
            # handoff -- the sending happens on the sink's own thread.
            if self.led_sink is not None:
                px = scene.led(f)          # `is None`, not `or`: a numpy
                if px is None:             # array has no truth value
                    px = default_led(f, np_)
                self.led_sink.submit(px, f, np_)

            self._blit_canvas(win, canvas)
            if self.show_hud or self.show_led_panel:
                self._draw_hud(win, self._hud_font(win), f, clock, np_)
            pygame.display.flip()

        if self.now_playing is not None:
            self.now_playing.stop()
        if self.led_sink is not None:
            self.led_sink.stop()
        self.source.stop()
        pygame.quit()

    def _on_key(self, event):
        """Return False to quit, True otherwise."""
        k = event.key
        if k == pygame.K_ESCAPE:
            # In fullscreen, esc drops back to a window rather than quitting --
            # otherwise a fullscreen app with no visible chrome is a trap.
            if self.fullscreen:
                self.fullscreen = False
                self._open_window()
                return True
            return False
        # The number keys stay live while the panel is open on purpose: the
        # whole point of a global profile is checking one setting across
        # several scenes without losing your place in the list.
        if pygame.K_1 <= k <= pygame.K_9:
            idx = k - pygame.K_1
            if idx < len(self.scenes):
                self.scene_idx = idx
            return True
        if k == pygame.K_l:
            self.show_led_panel = not self.show_led_panel
            self._led_msg = ""
            return True
        if self.show_led_panel and self._on_led_key(event):
            return True
        if k == pygame.K_h:
            self.show_hud = not self.show_hud
        elif k == pygame.K_f:
            self.fullscreen = not self.fullscreen
            self._open_window()
        return True

    def _on_led_key(self, event):
        """Panel keys, swallowed only while the panel is open so h and f keep
        their usual meaning the rest of the time. Returns True if handled."""
        k = event.key
        params = LedProfile.PARAMS
        if k in (pygame.K_UP, pygame.K_DOWN):
            step = -1 if k == pygame.K_UP else 1
            self.led_cursor = (self.led_cursor + step) % len(params)
        elif k in (pygame.K_LEFT, pygame.K_RIGHT):
            coarse = bool(event.mod & pygame.KMOD_SHIFT)
            self.led_profile.adjust(params[self.led_cursor].name,
                                    1 if k == pygame.K_RIGHT else -1, coarse)
            self._led_msg = ""
        elif k == pygame.K_s:
            try:
                self._led_msg = f"saved {self.led_profile.save()}"
            except OSError as e:
                self._led_msg = f"save failed: {e}"
        elif k == pygame.K_r:
            self.led_profile.reset()
            self._led_msg = "reset to defaults (not saved)"
        else:
            return False
        return True

    def _draw_hud(self, win, font, f: Features, clock, np_=None):
        """The debug readout, the LED panel, or both -- h and l toggle them
        independently, and each starts where the last one left off."""
        # margins and line spacing follow the font, so the block stays
        # proportional at any window size
        pad = self._font_px
        y = pad // 2
        if self.show_hud:
            y = self._draw_hud_lines(win, font, f, clock, np_, pad, y)
        if self.show_led_panel:
            self._draw_led_panel(win, font, y)

    def _draw_hud_lines(self, win, font, f: Features, clock, np_, pad, y):
        lines = [
            f"fps {clock.get_fps():4.0f}   source {self.source.name}   "
            f"scene {self.scenes[self.scene_idx].name}   "
            f"render {self._canvas.get_width()}x{self._canvas.get_height()}"
            f"{'' if self.supersample == 1 else f' (ss{self.supersample})'}",
            f"rms {f.rms:.2f}  bass {f.bass:.2f}  mid {f.mid:.2f}  "
            f"treble {f.treble:.2f}  centroid {f.centroid:.2f}",
        ]
        # The auto-gain's own state, so it's visible whether a passage reads
        # quiet because it *is* quiet or because the reference has drifted.
        dbg = getattr(getattr(self.source, "extractor", None), "last_debug", None)
        if dbg:
            lines.append("agc  " + "   ".join(
                f"{k} {dbg['raw'][k]:.3f}/{dbg['ref'][k]:.3f}->{dbg['norm'][k]:.2f}"
                for k in ("rms", "bass")))
        if np_ is not None and np_.label():
            state = "" if np_.playing else " (paused)"
            lines.append(f"{np_.label()}{state}")
        if self.led_sink is not None and self.led_sink.name != "none":
            lines.append(f"leds {self.led_sink.stats()}")
        lines.append("keys: 1-9 scene   h hud   l leds   f fullscreen   esc quit")
        y = self._text_block(win, font, [(ln, (255, 255, 255)) for ln in lines],
                             pad, y)
        if f.beat_strength > 0:
            r = int((0.45 + 0.8 * f.beat_strength) * self._font_px)
            pygame.draw.circle(win, (255, 80, 80),
                               (win.get_width() - 2 * pad, pad + r // 2), r)
        return y

    def _draw_led_panel(self, win, font, y):
        """The LED profile, one knob per line, cursor on the selected one.
        Generated straight from LedProfile.PARAMS, so a knob added there shows
        up here with no edits."""
        pad = self._font_px
        note = (150, 220, 255)
        entries = [("LED profile   up/down pick   left/right adjust (shift=x5)"
                    "   s save   r reset", note)]
        for i, p in enumerate(LedProfile.PARAMS):
            sel = i == self.led_cursor
            entries.append((
                f"{'>' if sel else ' '} {p.label:<11} "
                f"{self.led_profile.display(p.name)}",
                (255, 255, 160) if sel else (215, 215, 215)))
        if self._led_msg:
            entries.append((self._led_msg, note))
        self._text_block(win, font, entries, pad,
                         y + int(self._font_px * 1.28) // 2)

    def _text_block(self, win, font, entries, x, y):
        """Blit a run of (text, color) lines onto a translucent dark plate,
        and return the y just past them.

        The plate is not decoration. The HUD sits on top of whatever the scene
        is drawing, and most of these scenes spend a lot of their time bright
        -- white text on Pulse's orb or Resonance's globe is unreadable, which
        is fatal for the LED panel specifically, since its entire job is being
        read while you turn a knob. One alpha blit per block fixes every scene
        at once, rather than each scene worrying about contrast."""
        if not entries:
            return y
        step = int(self._font_px * 1.28)
        surfaces = [font.render(t, True, c) for t, c in entries]
        m = max(2, self._font_px // 3)          # plate margin around the text
        w = max(s.get_width() for s in surfaces)
        h = step * (len(surfaces) - 1) + surfaces[-1].get_height()
        plate = pygame.Surface((w + 2 * m, h + 2 * m), pygame.SRCALPHA)
        plate.fill((0, 0, 0, 165))
        win.blit(plate, (x - m, y - m))
        for s in surfaces:
            win.blit(s, (x, y))
            y += step
        return y
