# The bundled `uv`

The engine is a Python application, and `uv` is what builds its environment on
first launch. It is shipped inside the app so that installing Uncloud needs
nothing preinstalled.

`uv` is a native binary, so there is one per architecture and the build must
stage the one matching the machine it is building for. Getting this wrong
produces a bundle that installs cleanly, opens, and then cannot start its
engine — a failure that only appears on a customer's machine, because the
build succeeded.

    uv-aarch64   Apple Silicon
    uv-x86_64    Intel
    uv           whichever of the two this build stages; not committed

Copy the right one to `uv` before `tauri build`. `scripts/stage_uv.sh` does it
and refuses if the result does not match.

Only `uv` is bundled. `binaries/*` would have shipped every architecture at once
— an extra 110 MB in the installer, of which the customer's machine can run
exactly one.
