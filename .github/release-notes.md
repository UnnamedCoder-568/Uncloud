Uncloud 0.4.0 adds live speech, voice-to-voice conversations, speech studio,
multi-image generation, local-network access, model import, a refreshed model
catalogue, and signed in-app update support.

The Windows x64 installer, Linux x64 AppImage, and Apple-silicon macOS DMG are
freshly built on GitHub-hosted native runners. Before publication, CI tests the
frontend, Python engine, and Rust desktop shell; verifies the bundled engine and
uv runtime; and inspects each packaged application.

Intel Macs are not supported because the engine's current PyTorch dependency no
longer provides macOS x86_64 packages.

Please report defects through the repository's
[issue tracker](https://github.com/UnnamedCoder-568/Uncloud/issues), including
your operating system, hardware, and the steps that reproduced the problem.

The installers are not OS code-signed or notarised, so Windows SmartScreen or
macOS Gatekeeper may display a warning. Checksums for every download are in
`SHA256SUMS.txt`.
