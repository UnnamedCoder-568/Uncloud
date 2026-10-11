"""A tool question waits for its authenticated user, independently of the viewer."""

from contextlib import contextmanager
from contextvars import ContextVar

_asker = ContextVar("chisel_questions", default=None)


@contextmanager
def asking(asker):
    token = _asker.set(asker)
    try:
        yield
    finally:
        _asker.reset(token)


async def ask(question: str, options: list | None = None) -> str:
    if not isinstance(question, str) or not question.strip() or len(question) > 4000:
        raise ValueError("A short, nonempty question is required.")
    options = options or []
    if (
        not isinstance(options, list)
        or len(options) > 8
        or any(not isinstance(o, str) or len(o) > 200 for o in options)
    ):
        raise ValueError("Use at most eight short answer options.")
    asker = _asker.get()
    if asker is None:
        raise RuntimeError("No user interaction channel is available; the task cannot continue.")
    answer = await asker({"question": question, "options": options})
    if not answer:
        raise RuntimeError("No answer was received; no dependent actions were taken.")
    return answer
