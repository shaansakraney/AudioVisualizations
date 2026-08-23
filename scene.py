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

    def update(self, f: Features, dt: float):
        """Advance internal animation state. dt = seconds since the last frame."""
        pass

    def draw(self, surface):
        """Render one frame onto `surface` (size = the logical canvas)."""
        raise NotImplementedError
