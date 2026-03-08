"""
face_pixel.py — pixel-art face for Sufi.

Grid-based renderer: every shape is a frozenset of (row, col) offsets.
Each offset is drawn as a (CELL-1)×(CELL-1) square so a 1 px gap between
blocks gives the classic pixel-art look.

Implements the same update() / draw() interface as Sufi in main.py, plus
set_state(state) so the AI speech mode can drive the face appearance.

States
------
idle      → happy face; right eye shows a pink heart
listening → both eyes show white pupil (heart gone); attentive
thinking  → thought bubble appears in top-right corner
speaking  → mouth alternates between smile and open shape
"""

import math
import random
import time

import pygame

import config as cfg


# ── pixel shapes ─────────────────────────────────────────────────────────────
# Each shape is a frozenset of (row, col) offsets from the shape's center.
# _draw_shape() maps (row, col) → pixel rect at (cx + col*C, cy + row*C).

# Eye outline: hollow 5×5 square with notched corners
_EYE = frozenset([
    (-2, -1), (-2,  0), (-2,  1),
    (-1, -2),                      (-1,  2),
    ( 0, -2),                      ( 0,  2),
    ( 1, -2),                      ( 1,  2),
    ( 2, -1), ( 2,  0), ( 2,  1),
])

# Closed eye: single horizontal bar (blink / wink)
_EYE_BLINK = frozenset([
    (0, -2), (0, -1), (0, 0), (0, 1), (0, 2),
])

# Pupil and specular highlight
_PUPIL     = frozenset([(0, 0)])
_HIGHLIGHT = frozenset([(-1, -1)])

# Heart (shown inside right eye when state == "idle")
_HEART = frozenset([
    (-1, -1), (-1,  1),
    ( 0, -1), ( 0,  0), ( 0,  1),
    ( 1,  0),
])

# Smile mouth: 7-wide downward arc
_MOUTH_SMILE = frozenset([
    (0, -3), (0,  3),
    (1, -2), (1,  2),
    (2, -1), (2,  0), (2,  1),
])

# Open mouth: rectangle with curved bottom (speaking state)
_MOUTH_OPEN = frozenset([
    (0, -2), (0, -1), (0,  0), (0,  1), (0,  2),
    (1, -2),                             (1,  2),
    (2, -1), (2,  0), (2,  1),
])

# Thought bubble: cloud body + 3 trailing dots (shown during "thinking")
_BUBBLE = frozenset([
    (-2, -1), (-2,  0), (-2,  1),
    (-1, -2), (-1, -1), (-1,  0), (-1,  1), (-1,  2),
    ( 0, -2), ( 0, -1), ( 0,  0), ( 0,  1), ( 0,  2),
    ( 1, -1), ( 1,  0), ( 1,  1),
    # trailing dots curving down-left toward the face
    ( 3,  0),
    ( 4, -1),
    ( 5, -2),
])


# ── drawing helper ────────────────────────────────────────────────────────────

def _draw_shape(surface: pygame.Surface, shape, cx: int, cy: int,
                cell: int, color) -> None:
    """Draw each (row, col) block as a (cell-1)×(cell-1) rect centered on (cx, cy)."""
    s = cell - 1
    for row, col in shape:
        pygame.draw.rect(surface, color,
                         (cx + col * cell, cy + row * cell, s, s))


# ── face ──────────────────────────────────────────────────────────────────────

class PixelFace:
    """
    Pixel-art face — drop-in replacement for the classic Sufi face in main.py.

    Exposes the same update() / draw() interface so sufi_ai.py can swap
    between the two face styles with no other changes.  The extra
    set_state(state) method lets the AI speech mode drive the appearance.

    Parameters
    ----------
    surface : pygame.Surface
        Surface to draw on (may be the full screen or a subsurface).
    """

    def __init__(self, surface: pygame.Surface):
        self.surface = surface
        W, H = surface.get_size()

        # Cell size: scales with screen height so the face looks right on both
        # the Pi Zero 480×320 display and the larger Windows dev screen.
        self._C = max(10, H // 20)
        C  = self._C
        cx = W // 2
        cy = H // 2

        # ── element centers ──────────────────────────────────────────────────
        self._lx = cx - 6 * C       # left eye  x
        self._rx = cx + 6 * C       # right eye x
        self._ey = cy - 2 * C       # both eyes y
        self._mx = cx               # mouth     x
        self._my = cy + 5 * C       # mouth     y
        self._bx = W - 3 * C        # thought bubble x (top-right)
        self._by = 3 * C            # thought bubble y

        # ── colors ───────────────────────────────────────────────────────────
        self._eye_c = cfg.PIXEL_EYE_COLOR
        self._pup_c = cfg.PIXEL_PUPIL_COLOR
        self._hlt_c = (200, 200, 200)         # specular highlight
        self._hrt_c = cfg.PIXEL_HEART_COLOR
        self._bbl_c = cfg.PIXEL_BUBBLE_COLOR

        # ── AI state ─────────────────────────────────────────────────────────
        self._state = "idle"

        # ── animation ────────────────────────────────────────────────────────
        self._mouth_open   = False
        self._pupil_angle  = 0.0
        self._pupil_offset = (0, 0)

        self._blink_l    = 0.0   # left  eye blink progress (0=open, 1=closed)
        self._blink_r    = 0.0   # right eye blink progress
        self._blink_start = None
        self._wink_start  = None
        self._wink_side   = None
        self._next_blink  = self._rand_blink()
        self._next_wink   = self._rand_wink()

    # ── public API ────────────────────────────────────────────────────────────

    def set_state(self, state: str) -> None:
        """Drive face appearance from AI mode: idle|listening|thinking|speaking."""
        self._state = state

    def update(self) -> None:
        """Advance all animations (call once per frame before draw())."""
        now = time.time()

        # Pupil drift — slow Lissajous wander, same as classic face
        self._pupil_angle += 0.007
        self._pupil_offset = (
            round(math.sin(self._pupil_angle * 0.7) * 1.2),
            round(math.cos(self._pupil_angle * 1.1) * 0.7),
        )

        # Speaking: toggle mouth open/closed at ~1.6 Hz
        self._mouth_open = (
            self._state == "speaking"
            and (pygame.time.get_ticks() // 300) % 2 == 0
        )

        # Blink (both eyes together)
        if self._blink_start is None and now >= self._next_blink:
            self._blink_start = now
            self._next_blink  = self._rand_blink()

        if self._blink_start is not None:
            t = (now - self._blink_start) / cfg.BLINK_DURATION
            p = t / 0.5 if t < 0.5 else (1.0 - t) / 0.5
            p = max(0.0, min(1.0, p))
            if self._wink_start is None:   # don't stomp an active wink
                self._blink_l = p
                self._blink_r = p
            if t >= 1.0:
                self._blink_l = self._blink_r = 0.0
                self._blink_start = None

        # Wink (one eye only)
        if self._wink_start is None and now >= self._next_wink:
            self._wink_start = now
            self._wink_side  = random.choice(["left", "right"])
            self._next_wink  = self._rand_wink()

        if self._wink_start is not None:
            t = (now - self._wink_start) / cfg.WINK_DURATION
            p = t / 0.5 if t < 0.5 else (1.0 - t) / 0.5
            p = max(0.0, min(1.0, p))
            if self._wink_side == "left":
                self._blink_l = p
            else:
                self._blink_r = p
            if t >= 1.0:
                self._blink_l = self._blink_r = 0.0
                self._wink_start = None

    def draw(self) -> None:
        """Render the face (call once per frame after update())."""
        self.surface.fill(cfg.BG_COLOR)
        C  = self._C
        po = self._pupil_offset

        # ── eyes ─────────────────────────────────────────────────────────────
        for side in ("left", "right"):
            ex    = self._lx if side == "left" else self._rx
            bprog = self._blink_l if side == "left" else self._blink_r

            if bprog > 0.5:
                # Closed: single horizontal bar
                _draw_shape(self.surface, _EYE_BLINK, ex, self._ey, C, self._eye_c)
            else:
                # Open: hollow square outline
                _draw_shape(self.surface, _EYE, ex, self._ey, C, self._eye_c)

                # Inner content shifts slightly with pupil drift
                pcx = ex + po[0] * C
                pcy = self._ey + po[1] * C

                if side == "right" and self._state == "idle":
                    # Pink heart in right eye when idle
                    _draw_shape(self.surface, _HEART, pcx, pcy, C, self._hrt_c)
                else:
                    # White pupil + specular highlight
                    _draw_shape(self.surface, _PUPIL,     pcx, pcy, C, self._pup_c)
                    _draw_shape(self.surface, _HIGHLIGHT, pcx, pcy, C, self._hlt_c)

        # ── mouth ─────────────────────────────────────────────────────────────
        _draw_shape(self.surface,
                    _MOUTH_OPEN if self._mouth_open else _MOUTH_SMILE,
                    self._mx, self._my, C, self._eye_c)

        # ── thought bubble (thinking state only) ─────────────────────────────
        if self._state == "thinking":
            _draw_shape(self.surface, _BUBBLE, self._bx, self._by, C, self._bbl_c)

    # ── private ───────────────────────────────────────────────────────────────

    def _rand_blink(self) -> float:
        return time.time() + random.uniform(cfg.BLINK_INTERVAL_MIN, cfg.BLINK_INTERVAL_MAX)

    def _rand_wink(self) -> float:
        return time.time() + random.uniform(cfg.WINK_INTERVAL_MIN, cfg.WINK_INTERVAL_MAX)
