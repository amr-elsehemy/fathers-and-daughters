# sufi 😊

> An always-on screen companion for the Raspberry Pi Zero 2 W.

Sufi lives on a small screen and expresses herself through animated eyes and smiles. She winks, blinks, and grins — just vibing.

---

## Hardware

- Raspberry Pi Zero 2 W
- Any HDMI display (or DSI ribbon display)

## What it does now

- Animated blinking eyes
- Random winks (left or right)
- Rotating smiley expressions

## What's coming

- Voice output (speakers)
- Voice input (microphone)
- Reactive expressions based on what she hears

---

## Setup

```bash
# On the Pi
sudo apt update
sudo apt install python3-pygame -y

# Clone and run
git clone <this-repo>
cd fathers-and-daughters/sufi
python3 main.py
```

### Auto-start on boot

```bash
# Add to /etc/rc.local before exit 0:
cd /home/pi/fathers-and-daughters/sufi && python3 main.py &
```

Or use the provided systemd service:

```bash
sudo cp sufi.service /etc/systemd/system/
sudo systemctl enable sufi
sudo systemctl start sufi
```

---

## Config

Edit [config.py](config.py) to tweak colors, screen size, animation speed, and expression timings.
