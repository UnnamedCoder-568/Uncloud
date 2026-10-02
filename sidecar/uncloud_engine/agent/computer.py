"""Desktop input tools. Every action is gated by the caller as DEVICE access.

No shell fallback, no clipboard replacement, and no unattended retry. PyAutoGUI's
corner fail-safe remains enabled so a person can interrupt physical input.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import threading

_LOCK = threading.Lock()


def availability() -> dict:
    if sys.platform.startswith("linux") and os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return {
            "ready": False,
            "detail": "Desktop input requires an X11 session; Wayland blocks this backend.",
        }
    if importlib.util.find_spec("pyautogui") is None:
        return {"ready": False, "detail": "Install Computer use in Settings → Required software."}
    return {
        "ready": True,
        "detail": (
            "macOS requires Accessibility and Screen Recording access. Move "
            "the pointer to a screen corner to interrupt."
        ),
    }


def execute(action: str, args: dict) -> str:
    status = availability()
    if not status["ready"]:
        raise RuntimeError(status["detail"])
    import pyautogui as gui

    gui.FAILSAFE = True
    gui.PAUSE = 0.1
    with _LOCK:
        if action == "computer_read":
            width, height = gui.size()
            x, y = gui.position()
            return (
                f"Screen: {width} × {height}; pointer: {x}, {y}. "
                "Capture the screen before choosing coordinates."
            )
        if action in {"computer_move", "computer_click", "computer_drag"}:
            x, y = args.get("x"), args.get("y")
            if any(
                isinstance(v, bool) or not isinstance(v, int) for v in (x, y)
            ) or not gui.onScreen(x, y):
                raise ValueError("Coordinates must be integer pixels within the current screen.")
            if action == "computer_move":
                gui.moveTo(x, y, duration=0.2)
            elif action == "computer_drag":
                gui.dragTo(x, y, duration=0.5, button="left")
            else:
                button = args.get("button", "left")
                if not isinstance(button, str) or button not in {"left", "right", "middle"}:
                    raise ValueError("Mouse button must be left, right or middle.")
                gui.click(x, y, button=button)
            return (
                f"{action.removeprefix('computer_')} at {x}, {y}. "
                "Capture the screen to verify the result."
            )
        if action == "computer_type":
            text = args.get("text", "")
            if not isinstance(text, str) or len(text) > 10000 or not text.isascii():
                raise ValueError(
                    "Desktop typing supports up to 10,000 ASCII characters. Use "
                    "browser typing for Unicode."
                )
            gui.write(text, interval=0.01)
            return "Typed into the focused application. Capture the screen to verify."
        if action == "computer_key":
            keys = args.get("keys", [])
            if isinstance(keys, str):
                keys = keys.split("+")
            if (
                not isinstance(keys, list)
                or not 1 <= len(keys) <= 4
                or any(k not in gui.KEYBOARD_KEYS for k in keys)
            ):
                raise ValueError(
                    "Provide one to four supported keyboard keys, such as ctrl+l or enter."
                )
            gui.hotkey(*keys)
            return "Pressed the requested keys. Capture the screen to verify."
        if action == "computer_scroll":
            amount = args.get("amount")
            if isinstance(amount, bool) or not isinstance(amount, int) or not -20 <= amount <= 20:
                raise ValueError("Scroll amount must be an integer between -20 and 20.")
            gui.scroll(amount)
            return "Scrolled the focused application. Capture the screen to verify."
        raise ValueError("Unknown desktop input action.")
