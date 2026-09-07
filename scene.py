"""
scene.py
--------
The contract for a visual. A scene reads `Features` and paints one frame onto a
fixed-size surface (the logical TFT resolution). Keeping time-based state in
update() and pure drawing in draw() makes scenes easy to reason about and swap.
"""

from features import Features


class Scene:
    name = "scene"

    # Set by App every frame to the current NowPlaying (see nowplaying.py),
    # or left None when Spotify integration is off. This rides alongside
    # Features rather than inside it on purpose: Features is the audio
    # contract meant to be reimplemented on a microcontroller, and album art
    # has no place in it. Scenes that don't care simply never read this.
    now_playing = None

    # How many times the output resolution this scene wants to be rendered at
    # before being averaged down (SSAA). It is per-scene because the right
    # answer varies enormously: pygame's rect/polygon drawing has no
    # anti-aliasing, so scenes built from hard-edged geometry look jagged on a
    # big screen and want 2 -- while scenes that are already smooth fields or
    # anti-aliased circles gain nothing from it and simply cost 4x the pixels.
    # app.py multiplies this by the global --supersample.
    SUPERSAMPLE = 1

    def update(self, f: Features, dt: float):
        """Advance internal animation state. dt = seconds since the last frame."""
        pass

    def draw(self, surface):
        """Render one frame onto `surface` (size = the logical canvas)."""
        raise NotImplementedError

    def led(self, f: Features):
        """Optional second output: one frame for the physical LED strip.

        Return a sequence of (r, g, b) 0..255 -- any length. LedSink resamples
        it onto however many LEDs are actually connected, so a scene never
        needs to know the strip's length (or whether it's a 1-color analog
        strip at all). Return None to get led.default_led(), which derives a
        reasonable color from Features alone.

        Don't add a beat flash here: LedSink pulses every frame it sends with
        f.beat_strength, so the strip throbs on the beat in every scene."""
        return None
