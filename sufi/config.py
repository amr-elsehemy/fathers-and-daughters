# sufi — configuration

SCREEN_WIDTH  = 480
SCREEN_HEIGHT = 320
FULLSCREEN    = True

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
