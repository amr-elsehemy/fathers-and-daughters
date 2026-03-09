"""
Mode: speech_speech
Mic input → OpenAI Realtime API → audio output.

CONNECTION LIFECYCLE
--------------------
The WebSocket is only held open during active sessions.  When the bot goes
"sleepy" (via keyword or 30-s idle) the connection is fully closed.  A local
mic-energy monitor then runs while disconnected; once sustained speech energy
is detected a brief "wake-check" session reconnects, transcribes what was
said, and resumes a normal session only if a wake word is found.

KEYWORD PRIORITY
----------------
Sleep/wake keywords are the highest-priority events.  They are checked the
instant the user transcript arrives (before any AI response is played) and
suppress or cancel responses immediately.

AUDIO
-----
Raw signed 16-bit PCM (pcm16) at 24 000 Hz, mono.
sounddevice.RawInputStream is used for capture; its callback fires on the
audio driver thread and is forwarded to asyncio via call_soon_threadsafe.
"""

import asyncio
import base64
import json
import logging
import os
import time
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
REALTIME_WS = "wss://api.openai.com/v1/realtime?model=gpt-realtime-1.5"

# Stored prompts — selected by --speaker argument
# "father"          → adult-only session
# "daughter" / "both" → child-present session (more playful, age-appropriate)
PROMPT_IDS = {
    "father":   "pmpt_69af24523e1c8194888674923c5befe702227eb588113c61",
    "daughter": "pmpt_69adb36f54c481908b877132e889c5c80d6d6e9dfd2de84c",
    "both":     "pmpt_69adb36f54c481908b877132e889c5c80d6d6e9dfd2de84c",
}

# ── session / connection tuning ───────────────────────────────────────────────
IDLE_TIMEOUT_S       = 30     # seconds of no speech before going sleepy
WAKE_CHECK_TIMEOUT_S = 10     # max seconds waiting for speech during wake-check
WAKE_ENERGY_RMS      = 600    # int16 RMS level considered possible speech
WAKE_DEBOUNCE_S      = 0.45   # sustained energy duration before triggering reconnect
MIN_RECONNECT_GAP_S  = 3.0    # minimum seconds between wake-check reconnects

# ── keyword lists (all lower-case, checked via substring match) ───────────────
WAKE_WORDS = frozenset([
    "wake up", "wake", "wakey", "hamlet",
])
SLEEP_WORDS = frozenset([
    "sleep", "sleepy", "tired", "goodnight", "good night",
    "nap", "take a nap", "rest", "bedtime", "go to sleep",
])


class SpeechSpeechMode:
    """
    Full-duplex speech session with the OpenAI Realtime API.

    All I/O runs in a background daemon thread (start()) so the pygame event
    loop is never blocked.  State transitions reported via on_state():
        idle → listening → thinking → speaking → listening …
                        ↓                              ↑
                     sleepy ←──────────────────────────
    """

    def __init__(self, on_state, on_error, profile_text: str = "",
                 speaker: str = "daughter"):
        self.on_state     = on_state
        self.on_error     = on_error
        self.profile_text = profile_text
        self.prompt_id    = PROMPT_IDS.get(speaker, PROMPT_IDS["daughter"])
        self.voice        = "ash" if speaker == "father" else "ballad"
        self.api_key      = os.environ["OPENAI_API_KEY"]
        self._running     = False
        self._thread      = None

        # session-level flags (safe to read from async tasks; written carefully)
        self._speaking      = False   # True while AI audio is being played
        self._cancel_sent   = False   # True after response.cancel sent this turn
        self._force_sleepy  = False   # True when sleep keyword detected
        self._just_woke     = False   # True on first normal session after wake
        self._last_speech_t = 0.0     # monotonic time of last detected speech

    # ── public API ────────────────────────────────────────────────────────────

    def start(self):
        self._running       = True
        self._last_speech_t = time.monotonic()
        self._thread        = threading.Thread(target=self._run_sync, daemon=True)
        self._thread.start()

    def cleanup(self):
        self._running = False

    # ── thread entry ──────────────────────────────────────────────────────────

    def _run_sync(self):
        asyncio.run(self._ws_loop())

    # ── main orchestration loop ───────────────────────────────────────────────

    async def _ws_loop(self):
        """Alternate between active sessions and disconnected sleep-listening."""
        while self._running:
            if self._force_sleepy:
                log.debug("sleeping — entering local mic monitor")
                self.on_state("sleepy")
                await self._sleep_listen_loop()
            else:
                await self._connected_session(wake_check=False)

    # ── connected session ─────────────────────────────────────────────────────

    async def _connected_session(self, *, wake_check: bool = False):
        """
        One WebSocket session.

        wake_check=True  — only looking for a wake word; AI audio is suppressed;
                           session disconnects after the first complete turn.
        wake_check=False — normal session; triggers Sufi greeting if _just_woke.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "OpenAI-Beta":   "realtime=v1",
        }
        stop_event        = asyncio.Event()
        self._cancel_sent = False
        self._speaking    = False
        audio_queue       = asyncio.Queue()

        try:
            async with websockets.connect(REALTIME_WS,
                                          additional_headers=headers,
                                          max_size=None) as ws:
                log.debug("WS connected (wake_check=%s)", wake_check)

                session_ready = asyncio.Event()
                receiver      = asyncio.create_task(
                    self._event_receiver(ws, audio_queue, session_ready,
                                         stop_event, wake_check)
                )

                try:
                    await asyncio.wait_for(session_ready.wait(), timeout=10)
                except asyncio.TimeoutError:
                    log.warning("timed out waiting for session.created")
                    return

                await self._configure_session(ws)

                # Reset speech timer; optionally trigger greeting on wake
                self._last_speech_t = time.monotonic()
                if not wake_check:
                    self.on_state("listening")
                    if self._just_woke:
                        self._just_woke = False
                        await ws.send(json.dumps({"type": "response.create"}))

                await asyncio.gather(
                    self._mic_sender(ws, stop_event),
                    self._speaker_player(audio_queue, stop_event),
                    self._session_watchdog(ws, stop_event, wake_check),
                    receiver,
                    return_exceptions=True,
                )

        except Exception as e:
            if self._running:
                log.exception("connected_session error")
                self.on_error(str(e))

    # ── sleep (disconnected) listener ─────────────────────────────────────────

    async def _sleep_listen_loop(self):
        """
        Monitor local mic energy while fully disconnected.
        When sustained speech energy is detected, attempt a brief wake-check
        reconnect.  Returns when a wake word has been confirmed.
        """
        loop           = asyncio.get_running_loop()
        high_since     = None
        last_reconnect = 0.0

        usb_idx      = self._find_usb_mic()
        dev_info     = sd.query_devices(usb_idx, "input")
        capture_rate = int(dev_info["default_samplerate"])
        cap_block    = SAMPLE_RATE * BLOCK_MS // 1000 * capture_rate // SAMPLE_RATE

        while self._running and self._force_sleepy:
            energy_q: asyncio.Queue = asyncio.Queue()

            def _cb(indata: bytes, frames: int, t, status):
                samples = np.frombuffer(indata, dtype=np.int16).astype(np.float32)
                rms = float(np.sqrt(np.mean(samples ** 2))) if len(samples) else 0.0
                loop.call_soon_threadsafe(energy_q.put_nowait, rms)

            triggered = False
            with sd.RawInputStream(device=usb_idx, samplerate=capture_rate,
                                   channels=CHANNELS, dtype=DTYPE,
                                   blocksize=cap_block, callback=_cb):
                while self._running and self._force_sleepy:
                    try:
                        rms = await asyncio.wait_for(energy_q.get(), timeout=0.2)
                    except asyncio.TimeoutError:
                        continue

                    now = time.monotonic()
                    if rms >= WAKE_ENERGY_RMS:
                        if high_since is None:
                            high_since = now
                        elif (now - high_since >= WAKE_DEBOUNCE_S
                              and now - last_reconnect >= MIN_RECONNECT_GAP_S):
                            triggered  = True
                            high_since = None
                            break   # closes the RawInputStream via with-block exit
                    else:
                        high_since = None
            # stream is now closed — safe to reconnect

            if triggered:
                log.debug("energy sustained → wake-check reconnect")
                last_reconnect = time.monotonic()
                await self._connected_session(wake_check=True)
                if not self._force_sleepy:
                    return   # wake word confirmed — exit sleep loop

    # ── session watchdog ──────────────────────────────────────────────────────

    async def _session_watchdog(self, ws, stop_event: asyncio.Event,
                                 wake_check: bool):
        """
        Close the session when:
          normal  — 30 s of no speech, or _force_sleepy set by event receiver
          wake-check — 10 s of no speech detected (probably just noise)
        """
        idle_limit = WAKE_CHECK_TIMEOUT_S if wake_check else IDLE_TIMEOUT_S
        while not stop_event.is_set() and self._running:
            await asyncio.sleep(1)
            elapsed = time.monotonic() - self._last_speech_t

            if not wake_check and not self._force_sleepy and elapsed > IDLE_TIMEOUT_S:
                log.debug("idle timeout (%ds) → sleepy", IDLE_TIMEOUT_S)
                self._force_sleepy = True
                self.on_state("sleepy")

            if self._force_sleepy or (wake_check and elapsed > idle_limit):
                stop_event.set()
                try:
                    await ws.close()
                except Exception:
                    pass
                return

    # ── mic sender ────────────────────────────────────────────────────────────

    async def _mic_sender(self, ws, stop_event: asyncio.Event):
        loop     = asyncio.get_running_loop()
        mic_q: asyncio.Queue = asyncio.Queue()

        usb_idx      = self._find_usb_mic()
        dev_info     = sd.query_devices(usb_idx, "input")
        capture_rate = int(dev_info["default_samplerate"])
        cap_block    = SAMPLE_RATE * BLOCK_MS // 1000 * capture_rate // SAMPLE_RATE
        log.debug("mic: %s @ %d Hz", dev_info["name"], capture_rate)

        def _cb(indata: bytes, frames: int, t, status):
            samples   = np.frombuffer(indata, dtype=np.int16).astype(np.float32)
            n_out     = int(len(samples) * SAMPLE_RATE / capture_rate)
            resampled = np.interp(
                np.linspace(0, len(samples) - 1, n_out),
                np.arange(len(samples)),
                samples,
            ).astype(np.int16)
            loop.call_soon_threadsafe(mic_q.put_nowait, resampled.tobytes())

        with sd.RawInputStream(device=usb_idx, samplerate=capture_rate,
                               channels=CHANNELS, dtype=DTYPE,
                               blocksize=cap_block, callback=_cb):
            while not stop_event.is_set() and self._running:
                try:
                    chunk = await asyncio.wait_for(mic_q.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                if self._speaking:
                    continue   # mute mic while AI talks (prevents echo re-triggers)
                try:
                    await ws.send(json.dumps({
                        "type":  "input_audio_buffer.append",
                        "audio": base64.b64encode(chunk).decode(),
                    }))
                except Exception:
                    break

    # ── speaker ───────────────────────────────────────────────────────────────

    async def _speaker_player(self, audio_queue: asyncio.Queue,
                               stop_event: asyncio.Event):
        stream = sd.RawOutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                    dtype=DTYPE, blocksize=BLOCKSIZE)
        stream.start()
        try:
            while not stop_event.is_set() and self._running:
                try:
                    chunk = await asyncio.wait_for(audio_queue.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                # Immediately discard buffered audio when going sleepy
                if self._force_sleepy:
                    while not audio_queue.empty():
                        audio_queue.get_nowait()
                    continue
                stream.write(chunk)
        finally:
            stream.stop()
            stream.close()

    # ── event receiver ────────────────────────────────────────────────────────

    async def _event_receiver(self, ws, audio_queue: asyncio.Queue,
                               session_ready: asyncio.Event,
                               stop_event: asyncio.Event,
                               wake_check: bool):
        """
        Dispatch all server events.  Keyword detection runs at the earliest
        possible point (transcript completion) and suppresses audio immediately.
        """
        try:
            async for raw in ws:
                if not self._running or stop_event.is_set():
                    break
                ev = json.loads(raw)
                t  = ev.get("type", "")

                if t not in ("response.output_audio.delta", "response.audio.delta",
                             "input_audio_buffer.append"):
                    log.debug("event: %s", t)

                # ── session handshake ──────────────────────────────────────────
                if t == "session.created":
                    session_ready.set()

                # ── HIGHEST PRIORITY: keyword check on completed transcript ────
                elif t == "conversation.item.input_audio_transcription.completed":
                    transcript = ev.get("transcript", "").lower().strip()
                    log.debug("heard: %r", transcript)
                    self._handle_keywords(transcript, wake_check)

                # ── speech activity (update idle timer) ───────────────────────
                elif t == "input_audio_buffer.speech_started":
                    self._last_speech_t = time.monotonic()
                    if not self._force_sleepy:
                        self.on_state("listening")

                elif t == "input_audio_buffer.speech_stopped":
                    if not self._force_sleepy:
                        self.on_state("thinking")

                # ── AI audio output ────────────────────────────────────────────
                elif t in ("response.output_audio.delta", "response.audio.delta"):
                    # Suppress and cancel: sleepy OR wake-check session
                    if self._force_sleepy or wake_check:
                        if not self._cancel_sent:
                            log.debug("suppressing AI response (sleepy=%s, wake_check=%s)",
                                      self._force_sleepy, wake_check)
                            try:
                                await ws.send(json.dumps({"type": "response.cancel"}))
                            except Exception:
                                pass
                            self._cancel_sent = True
                    else:
                        delta = ev.get("delta")
                        if delta:
                            self._speaking = True
                            await audio_queue.put(base64.b64decode(delta))
                            self.on_state("speaking")

                # ── turn complete ──────────────────────────────────────────────
                elif t == "response.done":
                    self._speaking    = False
                    self._cancel_sent = False
                    if self._force_sleepy:
                        self.on_state("sleepy")
                    else:
                        self.on_state("listening")

                    # wake-check always disconnects after one turn
                    if wake_check:
                        stop_event.set()
                        try:
                            await ws.close()
                        except Exception:
                            pass

                # ── server error ───────────────────────────────────────────────
                elif t == "error":
                    log.error("server error: %s", json.dumps(ev))
                    self.on_error(ev.get("error", {}).get("message", "unknown"))

        except websockets.exceptions.ConnectionClosed:
            log.debug("WS closed")
        except Exception as e:
            if self._running and not stop_event.is_set():
                log.exception("event_receiver error: %s", e)

    # ── keyword handler (highest priority) ────────────────────────────────────

    def _handle_keywords(self, transcript: str, wake_check: bool):
        """
        Called the instant a user transcript arrives — before any AI response
        is allowed to play.  This is the single source of truth for all
        sleep/wake transitions.
        """
        # Wake word: resume from sleep (works in both normal and wake-check sessions)
        if self._force_sleepy and any(w in transcript for w in WAKE_WORDS):
            log.debug("WAKE keyword detected → resuming")
            self._force_sleepy = False
            self._cancel_sent  = False
            self._just_woke    = True   # triggers greeting in next normal session
            # Watchdog / response.done will close this wake-check session;
            # _ws_loop will then start a fresh normal session.
            return

        # Sleep word: go to sleep immediately (suppress current response)
        if not self._force_sleepy and any(w in transcript for w in SLEEP_WORDS):
            log.debug("SLEEP keyword detected → sleeping")
            self._force_sleepy = True
            self._cancel_sent  = False
            self.on_state("sleepy")
            # Watchdog will detect _force_sleepy and close the WS.

    # ── session configuration ─────────────────────────────────────────────────

    async def _configure_session(self, ws):
        """Send session.update: voice, stored prompt, optional profile, audio format, VAD.

        PROMPT_ID drives Sufi's tone/style/persona (the "how to talk" layer).
        profile_text, when present, adds the child's personal context on top
        (the "who am I talking to" layer).  Both are independent and complement
        each other.
        """
        session: dict = {
            "voice":    self.voice,
            "prompt":   {"id": self.prompt_id},  # base persona — selected by --speaker
            "modalities": ["audio", "text"],
            "input_audio_format":        "pcm16",
            "output_audio_format":       "pcm16",
            "input_audio_transcription": {"model": "whisper-1"},
            "turn_detection": {
                "type":                "server_vad",
                "threshold":           0.4,
                "prefix_padding_ms":   400,
                "silence_duration_ms": 1800,
            },
        }
        if self.profile_text:
            # Layered on top of the stored prompt: who the child is
            session["instructions"] = self.profile_text

        log.debug("session.update sent (profile=%s)", bool(self.profile_text))
        await ws.send(json.dumps({"type": "session.update", "session": session}))

    # ── utility ───────────────────────────────────────────────────────────────

    def _find_usb_mic(self):
        """Return the index of the first USB input device, or None for default."""
        return next(
            (i for i, d in enumerate(sd.query_devices())
             if d["max_input_channels"] > 0 and "USB" in d["name"]),
            None,
        )
