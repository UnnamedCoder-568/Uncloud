"""Stopping work that is already running.

One exception, in a module of its own, because three engines and a runtime all
need to agree on what "stop" looks like and none of them may import the others:
the image engine drives mflux, mflux's progress hook has to let this through,
and the video engine raises the same thing from a different loop.
"""

from __future__ import annotations


class Cancelled(RuntimeError):
    """Raised inside a running job when someone presses Stop.

    Distinct from every other failure on purpose. A render that stops because
    it was asked to is not an error, and reporting it as one puts a red message
    in front of somebody who got exactly what they wanted.
    """
