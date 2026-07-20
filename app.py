"""
app.py
------
The render loop. Everything is drawn onto a logical canvas, then scaled
(nearest-neighbour) onto the desktop window. SCALE is normally 1 for a
1920x1080 display; bump it only if you want to render at a lower internal
resolution and let the window upscale it.

Controls:  1-9 switch scene   h toggle HUD   esc/quit close
"""

import pygame

from features import Features

CANVAS_W, CANVAS_H = 1920, 1080
SCALE = 0.5          # window is CANVAS * SCALE
FPS = 60


class App:
    def __init__(self, source, scenes):
        self.source = source
        self.scenes = scenes
        self.scene_idx = 0
        self.show_hud = True

    def run(self):
        pygame.init()
        pygame.display.set_caption("audioviz")
        win = pygame.display.set_mode((CANVAS_W * SCALE, CANVAS_H * SCALE))
        canvas = pygame.Surface((CANVAS_W, CANVAS_H))
        clock = pygame.time.Clock()
        font = pygame.font.SysFont("menlo,consolas,monospace", 22)

        self.source.start()
        running = True
        while running:
            dt = clock.tick(FPS) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and not self._on_key(event):
                    running = False

            f = self.source.read(dt)
            scene = self.scenes[self.scene_idx]
            scene.update(f, dt)
            scene.draw(canvas)

            pygame.transform.scale(canvas, win.get_size(), win)  # upscale onto window
            if self.show_hud:
                self._draw_hud(win, font, f, clock)
            pygame.display.flip()

        self.source.stop()
        pygame.quit()

    def _on_key(self, event):
        """Return False to quit, True otherwise."""
        k = event.key
        if k == pygame.K_ESCAPE:
            return False
        if k == pygame.K_h:
            self.show_hud = not self.show_hud
        elif pygame.K_1 <= k <= pygame.K_9:
            idx = k - pygame.K_1
            if idx < len(self.scenes):
                self.scene_idx = idx
        return True

    def _draw_hud(self, win, font, f: Features, clock):
        lines = [
            f"fps {clock.get_fps():4.0f}   source {self.source.name}   "
            f"scene {self.scenes[self.scene_idx].name}",
            f"rms {f.rms:.2f}  bass {f.bass:.2f}  mid {f.mid:.2f}  "
            f"treble {f.treble:.2f}  centroid {f.centroid:.2f}",
            "keys: 1-9 scene   h hud   esc quit",
        ]
        y = 12
        for ln in lines:
            win.blit(font.render(ln, True, (255, 255, 255)), (16, y))
            y += 28
        if f.beat_strength > 0:
            r = int(10 + 18 * f.beat_strength)
            pygame.draw.circle(win, (255, 80, 80), (win.get_width() - 40, 34), r)
