"""
Mode: text_voice
User types text → OpenAI Chat API → OpenAI TTS → voice output.
"""

import os
import tempfile
import threading

import pygame
from openai import OpenAI


class TextVoiceMode:
    def __init__(self, on_response, on_error):
        self.client      = OpenAI()   # reads OPENAI_API_KEY from env
        self.on_response = on_response
        self.on_error    = on_error
        self.busy        = False
        pygame.mixer.init()

    def submit(self, text: str):
        if self.busy or not text.strip():
            return
        self.busy = True
        threading.Thread(target=self._call, args=(text,), daemon=True).start()

    def _call(self, text: str):
        tmp = None
        try:
            # 1. Chat response
            resp = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": text}],
                max_tokens=200,
            )
            reply = resp.choices[0].message.content.strip()
            self.on_response(reply)

            # 2. TTS → temp mp3 → play
            speech = self.client.audio.speech.create(
                model="tts-1",
                voice="nova",
                input=reply,
            )
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                f.write(speech.read())
                tmp = f.name

            pygame.mixer.music.load(tmp)
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                pygame.time.wait(50)

        except Exception as e:
            self.on_error(str(e))
        finally:
            self.busy = False
            if tmp and os.path.exists(tmp):
                try:
                    pygame.mixer.music.unload()
                    os.unlink(tmp)
                except OSError:
                    pass

    def cleanup(self):
        if pygame.mixer.get_init():
            pygame.mixer.music.stop()
            pygame.mixer.quit()
