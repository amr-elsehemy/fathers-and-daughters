"""
Mode: text_chat
User types text → OpenAI Chat API → text response displayed on screen.
"""

import threading
from openai import OpenAI


class TextChatMode:
    def __init__(self, on_response, on_error, profile_text: str = ""):
        self.client      = OpenAI()   # reads OPENAI_API_KEY from env
        self.on_response = on_response
        self.on_error    = on_error
        self.profile_text = profile_text
        self.busy        = False

    def submit(self, text: str):
        if self.busy or not text.strip():
            return
        self.busy = True
        threading.Thread(target=self._call, args=(text,), daemon=True).start()

    def _call(self, text: str):
        try:
            messages = []
            if self.profile_text:
                messages.append({"role": "system", "content": self.profile_text})
            messages.append({"role": "user", "content": text})
            resp = self.client.chat.completions.create(
                model="gpt-4o",
                messages=messages,
                max_tokens=200,
            )
            self.on_response(resp.choices[0].message.content.strip())
        except Exception as e:
            self.on_error(str(e))
        finally:
            self.busy = False

    def cleanup(self):
        pass
