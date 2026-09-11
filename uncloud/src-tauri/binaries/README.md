# The bundled `uv`

The engine is a Python application, and `uv` is what builds its environment on
first launch. It is shipped inside the app so that installing Uncloud needs
nothing preinstalled.

`uv` is a native binary, so the build must stage the one matching its target.
Getting this wrong
produces a bundle that installs cleanly, opens, and then cannot start its
engine — a failure that only appears on a customer's machine, because the
build succeeded.

`../scripts/stage_uv.sh <target-triple>` downloads the pinned official release,
checks the publisher's SHA-256 file, and writes exactly one of these ignored
build inputs:

    uv.exe   Windows x64
    uv       Linux x64 or macOS

Platform-specific Tauri configuration maps that file to the resource root where
the launcher expects it. Neither downloaded binary is committed.
