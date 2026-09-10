"""Asking the person, when the answer has to come back over a socket.

The gate decides what an answer MEANS — which session grants it creates, which
policy it rewrites, that an unrecognised answer is a no. It cannot own the
round trip, because in Uncloud the person is on the other end of a websocket
and in Studio they are not.

So this is the asynchronous half, and it is deliberately small:

    gate.check()  ->  decided already, no interruption
    ask over the wire  ->  gate.answer()  ->  gate.settle()

`settle` is the single exit. Both halves end there, so there is one place that
writes the audit line and one place that raises — rather than two paths that
could quietly disagree about either.

**A surface with no asker is not a surface that may skip the question.** When
nothing can ask, `ApprovalRequired` is raised. That is the difference between a
feature that has not been wired up yet and a hole.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..core import ApprovalRequired, Decision, Gate, Request
from .tools import current_gate

#: An asker returns "yes", "no", "always" or "never".
AsyncAsker = Callable[[Request], Awaitable[str]]

_asker: AsyncAsker | None = None


def set_asker(asker: AsyncAsker | None) -> None:
    """Install the way to reach a person. Set for the life of a connection."""
    global _asker
    _asker = asker


class _Scope:
    """Install an asker for the duration of one run, and take it away after.

    A context manager rather than a bare setter, because the failure it
    prevents is specific: a websocket that closed while an asker was still
    installed would leave the next run believing it can reach somebody, and it
    would hang waiting for an answer nobody will give.
    """

    def __init__(self, asker: AsyncAsker) -> None:
        self.asker = asker
        self.previous: AsyncAsker | None = None

    def __enter__(self) -> _Scope:
        self.previous = _asker
        set_asker(self.asker)
        return self

    def __exit__(self, *exc) -> None:
        set_asker(self.previous)


def asking(asker: AsyncAsker) -> _Scope:
    return _Scope(asker)


async def decide(request: Request, *, gate: Gate | None = None) -> Decision:
    """Settle one request, asking a person if the policy calls for it."""
    gate = gate or current_gate()
    settled = gate.check(request)
    if settled is None:
        if _asker is None:
            raise ApprovalRequired(request)
        answer = await _asker(request)
        settled = gate.answer(request, answer)
    return gate.settle(request, settled)


async def decide_or_refuse(request: Request, *, timeout: float = 300.0) -> Decision:
    """As `decide`, but a person who never answers is a refusal.

    Without this a run waits for ever on a window the user has closed, and the
    job sits in progress with nothing to show why. Timing out as a no is the
    safe direction: nothing happens, and the reason says so.
    """
    try:
        return await asyncio.wait_for(decide(request), timeout=timeout)
    except TimeoutError:
        gate = current_gate()
        refused = Decision(False, gate.mode_for(request.category),
                           "nobody answered the approval request", asked=True)
        return gate.settle(request, refused)
