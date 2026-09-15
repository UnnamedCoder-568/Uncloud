"""The Quality narration engine reads only lines labelled with a speaker.

Its processor drops every other line without an error. Only the first line was
labelled, so a script with a title or paragraph breaks produced its first line
and stopped: about five seconds of a long read.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

RUNNER = Path(__file__).resolve().parent.parent / "scripts" / "vibevoice_hq_runner.py"


def _runner():
    spec = importlib.util.spec_from_file_location("vibevoice_hq_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_line_of_plain_text_is_read():
    script = _runner().as_script("The Keeper\n\nThe lighthouse stood.\nEvery night he climbed.\n")
    assert script.splitlines() == [
        "Speaker 1: The Keeper",
        "Speaker 1: The lighthouse stood.",
        "Speaker 1: Every night he climbed.",
    ]


def test_a_line_without_a_label_continues_the_last_speaker():
    script = _runner().as_script("Speaker 2: Hello there.\nHow are you?\nspeaker 1: Fine.")
    assert script.splitlines() == [
        "Speaker 2: Hello there.",
        "Speaker 2: How are you?",
        "speaker 1: Fine.",
    ]


def test_the_runner_raises_the_length_budget_above_the_library_default():
    # The library stops at twice the input length; English narration needs more.
    assert _runner().MAX_LENGTH_TIMES > 2
