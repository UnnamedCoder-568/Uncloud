This is an early tester build of Uncloud.

The Windows x64 installer and Linux x64 AppImage are built on GitHub-hosted
runners. Before publication, CI verifies the bundled engine files and uv
runtime, installs the complete locked Python environment on each platform,
starts the engine, checks its health endpoint, and launches the packaged desktop
application.

The macOS builds remain available as the existing known-good baseline.

Please report defects through the repository's
[issue tracker](https://github.com/aswinajith96-gif/Uncloud/issues), including
your operating system, hardware, and the steps that reproduced the problem.

Unsigned test builds may trigger Windows SmartScreen or macOS Gatekeeper.
Checksums for every download are in SHA256SUMS.txt.
