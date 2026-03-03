"""
Mode: speech_speech
Mic input → OpenAI Realtime API (with custom voice prompt) → audio output.

Flow:
  1. POST /v1/realtime/sessions  → ephemeral token
  2. WebSocket to Realtime API
  3. Stream mic audio in, play response audio out (server VAD handles turn detection)
"""

import asyncio
import base64
import json
import os
import threading

import pyaudio
import requests
import websockets

# ── audio settings ──────────────────────────────────────────────────────────
SAMPLE_RATE  = 24_000
CHANNELS     = 1
CHUNK        = 4_096
PA_FORMAT    = pyaudio.paInt16

# ── OpenAI Realtime ──────────────────────────────────────────────────────────
SESSION_URL  = "https://api.openai.com/v1/realtime/sessions"
REALTIME_WS  = "wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview"
PROMPT_ID    = "pmpt_6976bad9d9348194929c127dcd7c260501624896e429830b"
PROMPT_VER   = "6"


class SpeechSpeechMode:
    def __init__(self, on_state, on_error):
        """
        on_state(str) → called with: "idle" | "listening" | "thinking" | "speaking"
        on_error(str) → called on any error
        """
        self.on_state = on_state
        self.on_error = on_error
        self.api_key  = os.environ["OPENAI_API_KEY"]
        self._running = False
        self._thread  = None

    # ── public ───────────────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._thread  = threading.Thread(target=self._run_sync, daemon=True)
        self._thread.start()

    def cleanup(self):
        self._running = False

    # ── internals ─────────────────────────────────────────────────────────────

    def _run_sync(self):
        """Create Realtime session (sync HTTP), then hand off to asyncio."""
        try:
            resp = requests.post(
                SESSION_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "gpt-4o-realtime-preview",
                    "prompt": {"id": PROMPT_ID, "version": PROMPT_VER},
                },
                timeout=10,
            )
            resp.raise_for_status()
            token = resp.json()["client_secret"]["value"]
        except Exception as e:
            self.on_error(f"session error: {e}")
            return

        asyncio.run(self._ws_loop(token))

    async def _ws_loop(self, token: str):
        headers = {
            "Authorization": f"Bearer {token}",
            "OpenAI-Beta":   "realtime=v1",
        }

        pa  = pyaudio.PyAudio()
        mic = pa.open(format=PA_FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
                      input=True,  frames_per_buffer=CHUNK)
        spk = pa.open(format=PA_FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
                      output=True, frames_per_buffer=CHUNK)

        try:
            async with websockets.connect(REALTIME_WS, additional_headers=headers) as ws:

                # Enable server-side Voice Activity Detection
                await ws.send(json.dumps({
                    "type": "session.update",
                    "session": {
                        "turn_detection":      {"type": "server_vad"},
                        "input_audio_format":  "pcm16",
                        "output_audio_format": "pcm16",
                    },
                }))

                self.on_state("listening")
                loop = asyncio.get_event_loop()

                async def mic_sender():
                    while self._running:
                        chunk = await loop.run_in_executor(None, mic.read, CHUNK)
                        await ws.send(json.dumps({
                            "type":  "input_audio_buffer.append",
                            "audio": base64.b64encode(chunk).decode(),
                        }))

                async def event_receiver():
                    async for raw in ws:
                        if not self._running:
                            break
                        ev = json.loads(raw)
                        t  = ev.get("type", "")

                        if t == "input_audio_buffer.speech_started":
                            self.on_state("listening")
                        elif t == "input_audio_buffer.speech_stopped":
                            self.on_state("thinking")
                        elif t == "response.audio.delta":
                            audio = base64.b64decode(ev["delta"])
                            await loop.run_in_executor(None, spk.write, audio)
                            self.on_state("speaking")
                        elif t == "response.done":
                            self.on_state("listening")
                        elif t == "error":
                            msg = ev.get("error", {}).get("message", "unknown")
                            self.on_error(msg)

                await asyncio.gather(mic_sender(), event_receiver())

        except Exception as e:
            self.on_error(str(e))
        finally:
            mic.stop_stream();  mic.close()
            spk.stop_stream();  spk.close()
            pa.terminate()
