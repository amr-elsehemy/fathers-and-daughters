# sufi 😊

> An always-on screen companion for the Raspberry Pi Zero 2 W.

Sufi lives on a small screen and expresses herself through animated eyes and smiles. She winks, blinks, and grins — and now she can think and talk.

---

## Modes

| Script | `SUFI_MODE` | What it does |
|--------|-------------|--------------|
| `main.py` | — | Pure face animation, no AI |
| `sufi_ai.py` | `text_chat` | Type text → see response on screen |
| `sufi_ai.py` | `text_voice` | Type text → hear response as voice |
| `sufi_ai.py` | `speech_speech` | Speak to Sufi → she speaks back (Realtime API) |

---

## Hardware

- Raspberry Pi Zero 2 W
- Any HDMI or DSI display
- Speaker *(text_voice / speech_speech)*
- USB microphone *(speech_speech)*

---

## Setup

```bash
# System packages (Pi) — portaudio is needed to build pyaudio
sudo apt update
sudo apt install portaudio19-dev -y
# Note: avoid 'python3-pygame' and 'python3-pyaudio' from apt —
#       they link to the system Python, not Python 3.13.
#       Use pip instead (below).

# Python deps (against Python 3.13)
cd fathers-and-daughters/sufi
pip install -r requirements.txt

# Config
cp .env.example .env
nano .env          # add OPENAI_API_KEY and set SUFI_MODE
```

### Run

```bash
python3 main.py        # face only, no AI
python3 sufi_ai.py     # AI mode (reads SUFI_MODE from .env)
```

### Auto-start on boot

```bash
sudo cp sufi.service /etc/systemd/system/
# Edit ExecStart in the service to point to sufi_ai.py if you want AI mode
sudo systemctl enable sufi
sudo systemctl start sufi
```

Logs: `journalctl -u sufi -f`

---

## Config

- [config.py](config.py) — screen size, colors, animation timings
- [.env](.env) — API key + mode *(never committed to git)*
- [.env.example](.env.example) — safe template to copy from

---

## Project structure

```
sufi/
├── main.py              # face animation (Sufi + Eye classes)
├── sufi_ai.py           # AI launcher — all modes
├── config.py            # display + timing constants
├── modes/
│   ├── text_chat.py     # OpenAI Chat → text on screen
│   ├── text_voice.py    # OpenAI Chat + TTS → voice output
│   └── speech_speech.py # OpenAI Realtime WebSocket → speech I/O
├── .env.example         # copy to .env, never commit .env
├── requirements.txt
└── sufi.service         # systemd auto-start unit
```
