"""
Mode: speech_speech
Mic input → OpenAI Realtime API (custom voice prompt) → audio output.

FLOW
----
1. Connect WebSocket directly using the API key.
2. Start event_receiver as a background task BEFORE sending anything, so that
   the server's "session.created" event is never missed.
3. Wait for session.created, then send session.update to configure voice/prompt.
4. Three async tasks run concurrently:
     • _mic_sender      — hardware mic → base64 PCM16 chunks → WebSocket
     • _event_receiver  — WebSocket events → state callbacks + audio queue
     • _speaker_player  — audio queue → hardware speaker

AUDIO
-----
Raw signed 16-bit PCM (pcm16) at 24 000 Hz, mono.
sounddevice.RawInputStream is used for capture (not pyaudio blocking reads,
which can return silence; the RawInputStream callback fires on the audio
hardware thread and is forwarded safely to asyncio via call_soon_threadsafe).
"""

import asyncio
import base64
import json
import logging
import os
import threading

import numpy as np
import sounddevice as sd
import websockets

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format="[%(levelname)s] %(name)s: %(message)s")

# ── audio constants ───────────────────────────────────────────────────────────
SAMPLE_RATE = 24_000
CHANNELS    = 1
DTYPE       = "int16"
BLOCK_MS    = 100
BLOCKSIZE   = SAMPLE_RATE * BLOCK_MS // 1000   # 2 400 samples = 100 ms

# ── OpenAI Realtime ───────────────────────────────────────────────────────────
REALTIME_WS  = "wss://api.openai.com/v1/realtime?model=gpt-realtime"
PROMPT_ID    = "pmpt_69adb36f54c481908b877132e889c5c80d6d6e9dfd2de84c"


class SpeechSpeechMode:
    """
    Manages a full-duplex speech-to-speech session with the OpenAI Realtime API.

    Designed to run inside the Sufi pygame application.  All heavy I/O runs in
    a daemon thread (started by start()) so the pygame event loop is never
    blocked.  State changes are reported back to the caller via on_state() so
    the face animation can react (listening / thinking / speaking).

    Parameters
    ----------
    on_state : callable(str)
        Called whenever the session state changes.
        Values: "idle" | "listening" | "thinking" | "speaking"
    on_error : callable(str)
        Called with a human-readable error message on any failure.
    """

    def __init__(self, on_state, on_error):
        self.on_state = on_state
        self.on_error = on_error
        self.api_key   = os.environ["OPENAI_API_KEY"]
        self._running  = False
        self._thread   = None
        self._speaking = False   # True while AI audio is playing; mic is muted

    # ── public API ────────────────────────────────────────────────────────────

    def start(self):
        """Start the session in a background daemon thread."""
        self._running = True
        self._thread  = threading.Thread(target=self._run_sync, daemon=True)
        self._thread.start()

    def cleanup(self):
        """Signal the background thread to stop gracefully."""
        self._running = False

    # ── internals ─────────────────────────────────────────────────────────────

    def _run_sync(self):
        """Entry point for the daemon thread — runs the async WS loop."""
        asyncio.run(self._ws_loop())

    async def _ws_loop(self):
        """
        Main async loop: connect WebSocket, run mic/speaker/receiver concurrently.

        Connects directly with the API key (no ephemeral token REST call).
        Waits for session.created, then sends session.update to configure the
        session before starting the mic and speaker.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta":   "realtime=v1",
        }

        log.debug("connecting WebSocket: %s", REALTIME_WS)
        try:
            async with websockets.connect(REALTIME_WS,
                                          additional_headers=headers,
                                          max_size=None) as ws:
                log.debug("WebSocket connected")

                audio_queue   = asyncio.Queue()
                session_ready = asyncio.Event()

                # Start receiver first — must not miss session.created
                receiver_task = asyncio.create_task(
                    self._event_receiver(ws, audio_queue, session_ready)
                )

                # Block until server confirms the session exists
                await session_ready.wait()
                log.debug("session ready, sending session.update")
                await self._configure_session(ws)

                self.on_state("listening")

                await asyncio.gather(
                    self._mic_sender(ws),
                    self._speaker_player(audio_queue),
                    receiver_task,
                )

        except Exception as e:
            log.exception("ws_loop error")
            self.on_error(str(e))

    async def _configure_session(self, ws: websockets.ClientConnection):
        """Send session.update to configure voice, prompt, and audio settings."""
        msg = {
            "type": "session.update",
            "session": {
                "voice":               "ballad",
                "prompt":              {"id": PROMPT_ID},
                "modalities":          ["audio", "text"],
                "input_audio_format":  "pcm16",
                "output_audio_format": "pcm16",
                "turn_detection": {
                    "type":                "server_vad",
                    "threshold":           0.4,
                    "prefix_padding_ms":   400,
                    "silence_duration_ms": 1800,
                },
            },
        }
        log.debug("session.update: %s", json.dumps(msg))
        await ws.send(json.dumps(msg))

    async def _mic_sender(self, ws: websockets.ClientConnection):
        """
        Capture microphone audio and stream it to the server.

        Uses sd.RawInputStream with a hardware callback.  The callback fires on
        the audio driver thread every BLOCK_MS milliseconds; it forwards each
        chunk to the asyncio event loop via call_soon_threadsafe so it can be
        awaited safely from this coroutine.

        Each chunk is base64-encoded and sent as an input_audio_buffer.append
        event.  Server-side VAD (configured in the session POST) automatically
        detects speech boundaries and triggers responses — no manual commit or
        response.create is needed.
        """
        loop      = asyncio.get_event_loop()
        mic_queue: asyncio.Queue = asyncio.Queue()

        # Find the USB mic automatically (falls back to system default if absent)
        usb_input = next(
            (i for i, d in enumerate(sd.query_devices())
             if d["max_input_channels"] > 0 and "USB" in d["name"]),
            None,
        )
        device_info  = sd.query_devices(usb_input, "input")
        capture_rate = int(device_info["default_samplerate"])  # e.g. 48000
        # Blocksize scaled to capture rate so each chunk = BLOCK_MS ms of audio
        capture_blocksize = SAMPLE_RATE * BLOCK_MS // 1000 * capture_rate // SAMPLE_RATE
        log.debug("mic device: %s (%s) native=%d Hz",
                  usb_input, device_info["name"], capture_rate)

        def callback(indata: bytes, frames: int, time, status):
            if status:
                pass  # overflow/underflow — not fatal, just skip
            # Resample from capture_rate → SAMPLE_RATE (e.g. 48000 → 24000)
            samples   = np.frombuffer(indata, dtype=np.int16).astype(np.float32)
            n_out     = int(len(samples) * SAMPLE_RATE / capture_rate)
            resampled = np.interp(
                np.linspace(0, len(samples) - 1, n_out),
                np.arange(len(samples)),
                samples,
            ).astype(np.int16)
            loop.call_soon_threadsafe(mic_queue.put_nowait, resampled.tobytes())

        with sd.RawInputStream(
            device=usb_input,
            samplerate=capture_rate,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=capture_blocksize,
            callback=callback,
        ):
            while self._running:
                chunk = await mic_queue.get()
                if self._speaking:
                    continue   # discard mic audio while AI is talking (prevents echo triggers)
                await ws.send(json.dumps({
                    "type":  "input_audio_buffer.append",
                    "audio": base64.b64encode(chunk).decode(),
                }))

    async def _speaker_player(self, audio_queue: asyncio.Queue):
        """
        Play audio response chunks through the default output device.

        Drains audio_queue continuously, writing each raw PCM16 chunk to a
        RawOutputStream.  The queue decouples reception from playback so that
        slow playback does not block the event receiver from processing events.
        """
        stream = sd.RawOutputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=BLOCKSIZE,
        )
        stream.start()
        try:
            while self._running:
                chunk = await audio_queue.get()
                stream.write(chunk)
        finally:
            stream.stop()
            stream.close()

    async def _event_receiver(self, ws: websockets.ClientConnection,
                               audio_queue: asyncio.Queue,
                               session_ready: asyncio.Event):
        """
        Receive and dispatch all server events.

        session.created                 → sets session_ready (unblocks _ws_loop)
        input_audio_buffer.speech_*     → state: listening / thinking
        response.output_audio.delta
        response.audio.delta            → audio bytes → audio_queue → speaker
        response.done                   → state: listening (ready for next turn)
        error                           → calls on_error with the message
        """
        async for raw in ws:
            if not self._running:
                break
            ev = json.loads(raw)
            t  = ev.get("type", "")

            # Log every event except high-frequency audio deltas
            if t not in ("response.output_audio.delta", "response.audio.delta",
                         "input_audio_buffer.append"):
                log.debug("event: %s", json.dumps(ev))

            if t == "session.created":
                log.debug("session.created — session is ready")
                session_ready.set()

            elif t == "input_audio_buffer.speech_started":
                log.debug("speech started")
                self.on_state("listening")

            elif t == "input_audio_buffer.speech_stopped":
                log.debug("speech stopped")
                self.on_state("thinking")

            elif t in ("response.output_audio.delta", "response.audio.delta"):
                delta = ev.get("delta")
                if delta:
                    self._speaking = True
                    await audio_queue.put(base64.b64decode(delta))
                    self.on_state("speaking")

            elif t == "response.done":
                log.debug("response.done")
                self._speaking = False
                self.on_state("listening")

            elif t == "error":
                log.error("server error event: %s", json.dumps(ev))
                msg = ev.get("error", {}).get("message", "unknown")
                self.on_error(msg)

            else:
                log.debug("unhandled event type: %s", t)
