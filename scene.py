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

    def update(self, f: Features, dt: float):
        """Advance internal animation state. dt = seconds since the last frame."""
        pass

    def draw(self, surface):
        """Render one frame onto `surface` (size = the logical canvas)."""
        raise NotImplementedError
