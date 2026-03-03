"""
Platform detection for sufi.

Auto-detects the running hardware, or reads SUFI_PLATFORM from .env to override.

Supported platforms:
  windows   — development machine, windowed
  pi_zero   — Raspberry Pi Zero 2 W, small fullscreen display
  pi4       — Raspberry Pi 4/5, larger fullscreen display
  linux     — generic Linux fallback, windowed
"""

import os
import sys


def detect() -> str:
    """
    Returns: 'windows' | 'pi_zero' | 'pi4' | 'linux'

    Priority:
      1. SUFI_PLATFORM env var (explicit override)
      2. sys.platform  → 'win32'  becomes 'windows'
      3. /proc/device-tree/model on Linux (Pi model detection)
      4. fallback: 'linux'
    """
    override = os.getenv("SUFI_PLATFORM", "").strip().lower()
    if override:
        return override

    if sys.platform == "win32":
        return "windows"

    if sys.platform.startswith("linux"):
        model = _read_pi_model()
        if model:
            if "zero 2" in model:
                return "pi_zero"
            if "raspberry pi 4" in model or "raspberry pi 5" in model:
                return "pi4"

    return "linux"


def _read_pi_model() -> str:
    """Read /proc/device-tree/model, return lowercase string or empty string."""
    try:
        with open("/proc/device-tree/model", "r") as f:
            return f.read().lower()
    except OSError:
        return ""
