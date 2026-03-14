# sufi — configuration

import os
import platform_detect as _pd

# ── platform profiles ─────────────────────────────────────────────────────────
# Override by setting SUFI_PLATFORM in .env:
#   windows | pi_zero | pi4 | linux
_PROFILES = {
    "windows": dict(SCREEN_WIDTH=800,  SCREEN_HEIGHT=520,  FULLSCREEN=False, CURSOR_VISIBLE=True),
    "pi_zero": dict(SCREEN_WIDTH=480,  SCREEN_HEIGHT=320,  FULLSCREEN=True,  CURSOR_VISIBLE=False),
    "pi4":     dict(SCREEN_WIDTH=1280, SCREEN_HEIGHT=720,  FULLSCREEN=True,  CURSOR_VISIBLE=False),
    "linux":   dict(SCREEN_WIDTH=800,  SCREEN_HEIGHT=520,  FULLSCREEN=False, CURSOR_VISIBLE=True),
}

PLATFORM      = _pd.detect()
_profile      = _PROFILES.get(PLATFORM, _PROFILES["linux"])

SCREEN_WIDTH   = _profile["SCREEN_WIDTH"]
SCREEN_HEIGHT  = _profile["SCREEN_HEIGHT"]
FULLSCREEN     = _profile["FULLSCREEN"]
CURSOR_VISIBLE = _profile["CURSOR_VISIBLE"]

# Colors
BG_COLOR      = (20, 20, 30)       # dark background
EYE_COLOR     = (255, 255, 255)    # white eyes
PUPIL_COLOR   = (30, 30, 30)       # dark pupils
SHINE_COLOR   = (255, 255, 255)    # pupil shine
CHEEK_COLOR   = (255, 100, 120, 80)  # rosy cheeks (with alpha)
SMILE_COLOR   = (255, 200, 80)     # smile line

# Eye geometry (relative to screen center)
EYE_OFFSET_X  = 90    # horizontal distance from center to each eye
EYE_OFFSET_Y  = -20   # vertical offset from center (negative = up)
EYE_RADIUS    = 55
PUPIL_RADIUS  = 22
SHINE_RADIUS  = 8

# Smile
SMILE_Y_OFFSET = 70   # below center

# Timing (seconds)
BLINK_INTERVAL_MIN = 2.5
BLINK_INTERVAL_MAX = 5.0
BLINK_DURATION     = 0.12

WINK_INTERVAL_MIN  = 6.0
WINK_INTERVAL_MAX  = 14.0
WINK_DURATION      = 0.25

EXPRESSION_INTERVAL_MIN = 8.0
EXPRESSION_INTERVAL_MAX = 20.0
EXPRESSION_DURATION     = 3.0

FPS = 60

# ── face style ────────────────────────────────────────────────────────────────
# Set SUFI_FACE=pixel in .env to use the pixel-art face; default is classic.
FACE_STYLE = os.getenv("SUFI_FACE", "classic").strip().lower()

# ── speech_speech options ─────────────────────────────────────────────────────
BARGE_IN_ENABLED = False    # set False to disable barge-in (user speech never interrupts AI)
SLEEP_MODE_ENABLED = False  # set True to enable sleep/wake keyword detection

# ── pixel face colors ─────────────────────────────────────────────────────────
PIXEL_EYE_COLOR    = (0,   220, 220)   # cyan — eye outlines and mouth
PIXEL_PUPIL_COLOR  = (255, 255, 255)   # white pupil dot
PIXEL_HEART_COLOR  = (230,  80, 170)   # pink heart (right eye, idle state)
PIXEL_BUBBLE_COLOR = (230, 235, 255)   # soft white thought bubble
