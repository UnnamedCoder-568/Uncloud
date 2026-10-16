"""Stop exact, sustained reasoning cycles without changing prompts or samplers."""

from __future__ import annotations


class ReasoningLoop:
    def __init__(self) -> None:
        self.tail = ''
        self.pending = 0

    def push(self, text: str) -> None:
        self.tail = (self.tail + text)[-24000:]
        self.pending += len(text)
        if self.pending < 512 or len(self.tail) < 1024:
            return
        self.pending = 0
        end = len(self.tail)
        needle = self.tail[-256:]
        previous = self.tail.rfind(needle, 0, end - 256)
        while previous >= 0:
            period = end - 256 - previous
            if period > 6000:
                break
            if period * 4 <= end:
                block = self.tail[-period:]
                if len(block.split()) >= 20 and self.tail.endswith(block * 4):
                    raise RuntimeError(
                        'The model repeated the same thinking without an answer. '
                        'Generation was stopped and your conversation is preserved.')
            previous = self.tail.rfind(needle, 0, previous)
