"""Speech: text to voice and voice to voice, shared by both products.

BYTE-IDENTICAL IN BOTH REPOSITORIES.

Speech models pin libraries that fight with everything else — Chatterbox wants
torch 2.6 while the image stack wants a current one — so each engine runs in a
worker process on whichever interpreter satisfies it. The product decides where
that interpreter lives; Core decides what it must hold and how to talk to it.

    engines   what exists, how to recognise the weights, their preset voices
    chunks    cutting a long script into pieces one generation can say
    worker    the host side: start a worker, send it work, stop it
    runner    the worker itself, run by the engine's interpreter
    setup     building an engine's environment
"""
