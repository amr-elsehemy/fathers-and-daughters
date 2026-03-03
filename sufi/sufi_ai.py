"""
sufi AI — AI-powered screen companion
--------------------------------------
Set SUFI_MODE in .env:
  text_chat      → type text, see response on screen
  text_voice     → type text, hear response as voice
  speech_speech  → speak to Sufi, hear her respond (Realtime API)

Press ESC / Q to quit.
"""

import os
import sys
import pygame
from dotenv import load_dotenv

load_dotenv()

import config as cfg

MODE = os.getenv("SUFI_MODE", "text_chat")

# ── layout ───────────────────────────────────────────────────────────────────
INPUT_H   = 42
RESP_H    = 90
PANEL_H   = INPUT_H + RESP_H + 18   # only for text modes
PAD       = 8
FONT_SIZE = 17

# ── state badge colours (speech mode) ────────────────────────────────────────
STATE_COLORS = {
    "idle":      (100, 100, 120),
    "listening": ( 80, 210, 130),
    "thinking":  (210, 165,  80),
    "speaking":  ( 80, 165, 220),
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

class TextInput:
    """Single-line text input widget."""

    PLACEHOLDER = "ask sufi something..."

    def __init__(self, rect: pygame.Rect, font: pygame.font.Font):
        self.rect  = rect
        self.font  = font
        self.text  = ""

    def handle(self, event: pygame.event.Event):
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_BACKSPACE:
            self.text = self.text[:-1]
        elif event.key not in (pygame.K_RETURN, pygame.K_ESCAPE):
            self.text += event.unicode

    def clear(self):
        self.text = ""

    def draw(self, surface: pygame.Surface):
        pygame.draw.rect(surface, (38, 38, 52), self.rect, border_radius=6)
        pygame.draw.rect(surface, (75, 75, 100), self.rect, 1, border_radius=6)

        if self.text:
            display = self.text
            color   = (220, 220, 230)
            blink   = "|" if (pygame.time.get_ticks() // 500) % 2 == 0 else ""
            surf    = self.font.render(display + blink, True, color)
        else:
            surf = self.font.render(self.PLACEHOLDER, True, (80, 80, 100))

        cy = self.rect.y + (self.rect.h - surf.get_height()) // 2
        surface.blit(surf, (self.rect.x + PAD, cy))


def draw_wrapped(surface: pygame.Surface, text: str,
                 rect: pygame.Rect, font: pygame.font.Font,
                 color=(170, 220, 170)):
    """Render word-wrapped text inside rect."""
    words  = text.split()
    lines  = []
    line   = ""
    for w in words:
        test = (line + " " + w).strip()
        if font.size(test)[0] <= rect.width - PAD * 2:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)

    y = rect.y + 4
    for ln in lines:
        if y + font.get_height() > rect.y + rect.height:
            break
        surface.blit(font.render(ln, True, color), (rect.x + PAD, y))
        y += font.get_height() + 2


# ─────────────────────────────────────────────────────────────────────────────
# Text modes (text_chat / text_voice)
# ─────────────────────────────────────────────────────────────────────────────

def run_text_mode(screen: pygame.Surface, mode_name: str):
    from main import Sufi

    W, H   = screen.get_size()
    face_h = H - PANEL_H
    face_surf = screen.subsurface(pygame.Rect(0, 0, W, face_h))
    sufi      = Sufi(face_surf)

    if mode_name == "text_chat":
        from modes.text_chat  import TextChatMode  as Mode
    else:
        from modes.text_voice import TextVoiceMode as Mode

    # shared state (written from worker thread, read by main thread)
    response = {"text": "", "busy": False}

    def on_response(text):
        response["text"] = text
        response["busy"] = False

    def on_error(err):
        response["text"] = f"[!] {err}"
        response["busy"] = False

    ai   = Mode(on_response, on_error)
    font = pygame.font.SysFont("monospace", FONT_SIZE)

    input_rect = pygame.Rect(PAD, face_h + PAD,           W - PAD * 2, INPUT_H)
    resp_rect  = pygame.Rect(PAD, face_h + INPUT_H + 14,  W - PAD * 2, RESP_H)

    text_input = TextInput(input_rect, font)
    clock      = pygame.time.Clock()
    running    = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_RETURN and not response["busy"]:
                    q = text_input.text.strip()
                    if q:
                        response["busy"] = True
                        response["text"] = "thinking..."
                        ai.submit(q)
                        text_input.clear()
                else:
                    text_input.handle(event)

        sufi.update()
        sufi.draw()

        # panel background
        pygame.draw.rect(screen, (22, 22, 32),
                         pygame.Rect(0, face_h, W, PANEL_H))
        pygame.draw.line(screen, (55, 55, 75), (0, face_h), (W, face_h), 1)

        text_input.draw(screen)

        resp_color = (100, 200, 145) \
            if not response["text"].startswith("[!]") else (220, 80, 80)
        draw_wrapped(screen, response["text"], resp_rect, font, resp_color)

        # mode badge (top-right)
        badge = font.render(mode_name.replace("_", " "), True, (60, 60, 80))
        screen.blit(badge, (W - badge.get_width() - 6, 4))

        pygame.display.flip()
        clock.tick(cfg.FPS)

    ai.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Speech-to-speech mode
# ─────────────────────────────────────────────────────────────────────────────

def run_speech_mode(screen: pygame.Surface):
    from main import Sufi
    from modes.speech_speech import SpeechSpeechMode

    sufi  = Sufi(screen)
    state = {"value": "idle"}

    def on_state(s):
        state["value"] = s

    def on_error(e):
        state["value"] = f"error: {e}"

    ai    = SpeechSpeechMode(on_state, on_error)
    font  = pygame.font.SysFont("monospace", 19)
    W, H  = screen.get_size()
    clock = pygame.time.Clock()

    ai.start()
    running = True

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and \
                    event.key in (pygame.K_ESCAPE, pygame.K_q):
                running = False

        sufi.update()
        sufi.draw()

        s     = state["value"]
        color = STATE_COLORS.get(s, (200, 80, 80))
        label = font.render(f"● {s}", True, color)
        screen.blit(label, (W - label.get_width() - 10, H - label.get_height() - 8))

        pygame.display.flip()
        clock.tick(cfg.FPS)

    ai.cleanup()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    pygame.init()
    flags  = pygame.FULLSCREEN if cfg.FULLSCREEN else 0
    screen = pygame.display.set_mode((cfg.SCREEN_WIDTH, cfg.SCREEN_HEIGHT), flags)
    pygame.display.set_caption("sufi AI")
    pygame.mouse.set_visible(cfg.CURSOR_VISIBLE)

    if MODE == "speech_speech":
        run_speech_mode(screen)
    elif MODE in ("text_chat", "text_voice"):
        run_text_mode(screen, MODE)
    else:
        print(f"Unknown SUFI_MODE: {MODE!r}")
        print("Valid options: text_chat | text_voice | speech_speech")
        sys.exit(1)

    pygame.quit()
    sys.exit()


if __name__ == "__main__":
    main()
