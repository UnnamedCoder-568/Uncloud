"""Physical input contract, without moving the user's pointer."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from uncloud_engine.agent import computer


@pytest.fixture
def gui(monkeypatch):
    fake = SimpleNamespace(
        FAILSAFE=False,
        PAUSE=0,
        KEYBOARD_KEYS=["ctrl", "l", "enter"],
        size=lambda: (100, 100),
        position=lambda: (10, 10),
        onScreen=lambda x, y: 0 <= x < 100 and 0 <= y < 100,
        moveTo=Mock(),
        dragTo=Mock(),
        click=Mock(),
        write=Mock(),
        hotkey=Mock(),
        scroll=Mock(),
    )
    monkeypatch.setattr(computer, "availability", lambda: {"ready": True})
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake


@pytest.mark.parametrize(
    "action,args",
    [
        ("computer_click", {"x": -1, "y": 3}),
        ("computer_move", {"x": True, "y": 3}),
        ("computer_type", {"text": "é"}),
        ("computer_key", {"keys": ["invalid"]}),
        ("computer_scroll", {"amount": 100}),
    ],
)
def test_invalid_input_does_not_reach_desktop(gui, action, args):
    with pytest.raises(ValueError):
        computer.execute(action, args)
    for name in ("moveTo", "dragTo", "click", "write", "hotkey", "scroll"):
        getattr(gui, name).assert_not_called()


@pytest.mark.parametrize(
    "action,args,method",
    [
        ("computer_click", {"x": 20, "y": 30}, "click"),
        ("computer_move", {"x": 20, "y": 30}, "moveTo"),
        ("computer_drag", {"x": 20, "y": 30}, "dragTo"),
        ("computer_type", {"text": "Hello"}, "write"),
        ("computer_key", {"keys": "ctrl+l"}, "hotkey"),
        ("computer_scroll", {"amount": -2}, "scroll"),
    ],
)
def test_action_dispatch_keeps_corner_failsafe(gui, action, args, method):
    computer.execute(action, args)
    getattr(gui, method).assert_called_once()
    assert gui.FAILSAFE is True


def test_unavailable_backend_never_imports_input(monkeypatch):
    monkeypatch.setattr(computer, "availability", lambda: {"ready": False, "detail": "Unavailable"})
    with pytest.raises(RuntimeError, match="Unavailable"):
        computer.execute("computer_click", {"x": 1, "y": 1})
