"""
sufi — always-on screen companion
Raspberry Pi Zero 2 W

Expressions: blink, wink, smile, big grin, surprise, sleepy
"""

import pygame
import math
import random
import time
import sys

import config as cfg


# ---------------------------------------------------------------------------
# Expression definitions
# Each expression tweaks how eyes + smile are drawn
# ---------------------------------------------------------------------------
EXPRESSIONS = {
    "happy": {
        "smile": "normal",
        "eye_scale": 1.0,
        "squint": 0.0,
    },
    "big_grin": {
        "smile": "big",
        "eye_scale": 1.1,
        "squint": 0.3,
    },
    "surprised": {
        "smile": "open_o",
        "eye_scale": 1.35,
        "squint": 0.0,
    },
    "sleepy": {
        "smile": "small",
        "eye_scale": 0.9,
        "squint": 0.55,
    },
    "cheeky": {
        "smile": "smirk",
        "eye_scale": 1.0,
        "squint": 0.15,
    },
}

EXPRESSION_ORDER = list(EXPRESSIONS.keys())


class Eye:
    def __init__(self, cx, cy, radius):
        self.cx = cx
        self.cy = cy
        self.base_radius = radius
        self.radius = radius

        # state
        self.blink_progress = 0.0   # 0 = open, 1 = fully closed
        self.squint = 0.0           # 0 = open, 1 = half-lidded

    def draw(self, surface, pupil_offset=(0, 0)):
        r = self.radius
        # visible open fraction: 1 - blink - squint clamped
        open_frac = max(0.0, 1.0 - self.blink_progress - self.squint * 0.5)

        # --- white of the eye (ellipse) ---
        eye_rect = pygame.Rect(
            self.cx - r,
            self.cy - r * open_frac,
            r * 2,
            r * 2 * open_frac,
        )
        if open_frac > 0.05:
            pygame.draw.ellipse(surface, cfg.EYE_COLOR, eye_rect)

            # --- pupil ---
            pr = cfg.PUPIL_RADIUS
            px = self.cx + pupil_offset[0]
            py = self.cy + pupil_offset[1] * open_frac
            pygame.draw.circle(surface, cfg.PUPIL_COLOR, (int(px), int(py)), pr)

            # --- shine dot ---
            pygame.draw.circle(
                surface,
                cfg.SHINE_COLOR,
                (int(px - pr * 0.3), int(py - pr * 0.35)),
                cfg.SHINE_RADIUS,
            )

        # --- eyelid (top lid drawn over eye) ---
        lid_height = int(r * 2 * (1 - open_frac) + r * self.squint * 0.5)
        if lid_height > 0:
            lid_rect = pygame.Rect(self.cx - r - 2, self.cy - r, r * 2 + 4, lid_height)
            pygame.draw.rect(surface, cfg.BG_COLOR, lid_rect)

        # --- outline ring ---
        if open_frac > 0.05:
            pygame.draw.ellipse(surface, (180, 180, 200), eye_rect, 3)


class Sufi:
    def __init__(self, surface):
        self.surface = surface
        w, h = surface.get_size()
        cx, cy = w // 2, h // 2

        lx = cx - cfg.EYE_OFFSET_X
        rx = cx + cfg.EYE_OFFSET_X
        ey = cy + cfg.EYE_OFFSET_Y

        self.left_eye  = Eye(lx, ey, cfg.EYE_RADIUS)
        self.right_eye = Eye(rx, ey, cfg.EYE_RADIUS)
        self.smile_cx  = cx
        self.smile_cy  = cy + cfg.SMILE_Y_OFFSET

        self.expression = "happy"
        self._apply_expression("happy")

        # timers
        self._next_blink      = self._rand_blink_time()
        self._next_wink       = self._rand_wink_time()
        self._next_expression = self._rand_expr_time()

        self._blink_start  = None
        self._wink_start   = None
        self._wink_side    = None   # "left" | "right"
        self._expr_start   = None
        self._expr_pending = None

        # subtle pupil drift
        self._pupil_angle  = 0.0
        self._pupil_radius = 6

    # ------------------------------------------------------------------
    def _rand_blink_time(self):
        return time.time() + random.uniform(cfg.BLINK_INTERVAL_MIN, cfg.BLINK_INTERVAL_MAX)

    def _rand_wink_time(self):
        return time.time() + random.uniform(cfg.WINK_INTERVAL_MIN, cfg.WINK_INTERVAL_MAX)

    def _rand_expr_time(self):
        return time.time() + random.uniform(cfg.EXPRESSION_INTERVAL_MIN, cfg.EXPRESSION_INTERVAL_MAX)

    # ------------------------------------------------------------------
    def _apply_expression(self, name):
        expr = EXPRESSIONS[name]
        self.expression   = name
        self._smile_type  = expr["smile"]
        target_squint     = expr["squint"]
        scale             = expr["eye_scale"]

        for eye in (self.left_eye, self.right_eye):
            eye.radius = int(cfg.EYE_RADIUS * scale)
            eye.squint = target_squint

    # ------------------------------------------------------------------
    def update(self):
        now = time.time()

        # pupil drift (slow Lissajous wander)
        self._pupil_angle += 0.007
        px = math.sin(self._pupil_angle * 0.7) * self._pupil_radius
        py = math.cos(self._pupil_angle * 1.1) * self._pupil_radius * 0.6
        self._pupil_offset = (px, py)

        # --- blink ---
        if self._blink_start is None and now >= self._next_blink:
            self._blink_start = now
            self._next_blink  = self._rand_blink_time()

        if self._blink_start is not None:
            t = (now - self._blink_start) / cfg.BLINK_DURATION
            if t < 0.5:
                p = t / 0.5
            else:
                p = (1.0 - t) / 0.5
            p = max(0.0, min(1.0, p))
            self.left_eye.blink_progress  = p
            self.right_eye.blink_progress = p
            if t >= 1.0:
                self.left_eye.blink_progress  = 0.0
                self.right_eye.blink_progress = 0.0
                self._blink_start = None

        # --- wink ---
        if self._wink_start is None and now >= self._next_wink:
            self._wink_start = now
            self._wink_side  = random.choice(["left", "right"])
            self._next_wink  = self._rand_wink_time()

        if self._wink_start is not None:
            t = (now - self._wink_start) / cfg.WINK_DURATION
            if t < 0.5:
                p = t / 0.5
            else:
                p = (1.0 - t) / 0.5
            p = max(0.0, min(1.0, p))
            eye = self.left_eye if self._wink_side == "left" else self.right_eye
            eye.blink_progress = p
            if t >= 1.0:
                eye.blink_progress = 0.0
                self._wink_start = None

        # --- expression change ---
        if self._expr_start is None and now >= self._next_expression:
            self._expr_pending = random.choice(EXPRESSION_ORDER)
            self._expr_start   = now
            self._next_expression = self._rand_expr_time()

        if self._expr_start is not None:
            t = now - self._expr_start
            if t < 0.1:
                self._apply_expression(self._expr_pending)
            if t > cfg.EXPRESSION_DURATION:
                self._apply_expression("happy")
                self._expr_start = None

    # ------------------------------------------------------------------
    def draw(self):
        self.surface.fill(cfg.BG_COLOR)

        # cheeks (soft circles using a temp surface for alpha)
        cheek_surf = pygame.Surface(self.surface.get_size(), pygame.SRCALPHA)
        cheek_r = 28
        cheek_y = self.left_eye.cy + 30
        pygame.draw.circle(cheek_surf, cfg.CHEEK_COLOR,
                           (self.left_eye.cx,  cheek_y), cheek_r)
        pygame.draw.circle(cheek_surf, cfg.CHEEK_COLOR,
                           (self.right_eye.cx, cheek_y), cheek_r)
        self.surface.blit(cheek_surf, (0, 0))

        # eyes
        px, py = self._pupil_offset
        self.left_eye.draw(self.surface,  pupil_offset=(px, py))
        self.right_eye.draw(self.surface, pupil_offset=(px, py))

        # smile
        self._draw_smile()

    # ------------------------------------------------------------------
    def _draw_smile(self):
        cx, cy = self.smile_cx, self.smile_cy
        c = cfg.SMILE_COLOR
        t = self._smile_type

        if t == "normal":
            self._arc_smile(cx, cy, 60, 40, 30, 150, c, 5)

        elif t == "big":
            self._arc_smile(cx, cy, 75, 50, 20, 160, c, 7)
            # teeth hint
            pygame.draw.ellipse(self.surface, (240, 240, 240),
                                (cx - 30, cy - 8, 60, 22))

        elif t == "open_o":
            pygame.draw.ellipse(self.surface, c, (cx - 22, cy - 18, 44, 36), 5)

        elif t == "small":
            self._arc_smile(cx, cy, 35, 22, 30, 150, c, 4)

        elif t == "smirk":
            # only right side
            self._arc_smile(cx + 20, cy, 38, 25, 0, 90, c, 5)

    def _arc_smile(self, cx, cy, rx, ry, start_deg, end_deg, color, width):
        rect = pygame.Rect(cx - rx, cy - ry, rx * 2, ry * 2)
        pygame.draw.arc(
            self.surface, color, rect,
            math.radians(180 + start_deg),
            math.radians(180 + end_deg),
            width,
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    pygame.init()

    flags = pygame.FULLSCREEN if cfg.FULLSCREEN else 0
    screen = pygame.display.set_mode((cfg.SCREEN_WIDTH, cfg.SCREEN_HEIGHT), flags)
    pygame.display.set_caption("sufi")
    pygame.mouse.set_visible(False)

    clock = pygame.time.Clock()
    sufi  = Sufi(screen)

    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

        sufi.update()
        sufi.draw()
        pygame.display.flip()
        clock.tick(cfg.FPS)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
