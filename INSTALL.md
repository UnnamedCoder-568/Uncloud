# Installing Uncloud

## Normal tester installation

Testers should use a package from the
[v0.4.5 release](https://github.com/UnnamedCoder-568/Uncloud/releases/tag/v0.4.5).
Building from source is not required.

### Already running 0.4.1 or earlier? Install once by hand

Updates are signed, and the signing key was rotated during 0.4.2. A copy built
before that rotation carries the old key, so it cannot verify anything published
since — it will offer the update, download it, and refuse it with *"the signature
was created with a different key than the one provided"*. That is the check
working, not a fault.

Download the package for your platform from the release above and install it
over the old one. From 0.4.2 onwards the in-app updater works normally, and this
step is not needed again.

### Windows x64

1. Download `Uncloud-Windows-x64.exe`.
2. Run the installer.
3. If SmartScreen appears, confirm the file came from this repository, check
   its SHA-256 value against `SHA256SUMS.txt`, then choose
   **More info → Run anyway**.
4. Launch Uncloud from the Start menu.

Windows 11 includes the WebView2 runtime. On Windows 10, install the
[WebView2 Evergreen Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
only if Uncloud opens without a visible window.

### Linux x64

Download `Uncloud-Linux-x64.AppImage`, then:

```bash
chmod +x Uncloud-Linux-x64.AppImage
./Uncloud-Linux-x64.AppImage
```

The AppImage targets x86_64 distributions compatible with Ubuntu 22.04 or newer.
If the system cannot mount AppImages, use:

```bash
./Uncloud-Linux-x64.AppImage --appimage-extract-and-run
```

If the window cannot start because WebKitGTK is missing:

```bash
sudo apt-get update
sudo apt-get install libwebkit2gtk-4.1-0
```

Other distributions should install their equivalent WebKitGTK 4.1 runtime.

### First-run engine setup

Select **Install and start** in the setup screen. The application copies its
bundled engine to `~/.uncloud/engine`, then its bundled uv downloads:

- a managed CPython 3.12 runtime;
- the exact packages recorded in `sidecar/uv.lock`;
- platform-specific wheels needed by the local inference engine.

No developer tools are required. The first setup needs internet access, several
gigabytes of free disk space, and may take several minutes. Optional music,
narration, browser, and GGUF runtimes can require additional downloads.

User data is stored under `~/.uncloud/`. Models are stored in the folder chosen
during onboarding.

### Tester troubleshooting

- **Setup failed:** keep the final 30–50 lines shown in the setup screen and try
  once more after checking network access and free disk space.
- **Windows shows no window:** install WebView2 and relaunch.
- **Linux reports FUSE errors:** use `--appimage-extract-and-run`.
- **GGUF chat says llama-server is missing:** install a compatible llama.cpp
  runtime and make `llama-server` available on `PATH`.
- **Model will not load:** confirm the model supports the current platform and
  that system RAM or GPU VRAM is sufficient.

Report reproducible defects through the
[issue tracker](https://github.com/UnnamedCoder-568/Uncloud/issues).

---

## Developer/source installation

Source development requires:

- Node.js 22 and npm;
- Rust stable and Cargo;
- uv 0.12.13 or newer;
- Python 3.12, which uv can download automatically;
- the native Tauri build libraries for the host platform.

### Linux build libraries

```bash
sudo apt-get update
sudo apt-get install -y \
  libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev \
  patchelf build-essential curl file libssl-dev libxdo-dev libgtk-3-dev
```

### Development setup

```bash
git clone https://github.com/UnnamedCoder-568/Uncloud.git
cd Uncloud/sidecar
uv sync

cd ../uncloud
npm ci
npm run tauri dev
```

Run checks from the repository root:

```bash
cd uncloud
npm test
npm run lint
npm run build

cd ../sidecar
uv run pytest
uv run ruff check .

cd ../uncloud/src-tauri
cargo fmt --check
cargo test --locked
```

### Local package builds

The release workflow performs native builds on GitHub-hosted runners. Local
packaging is for development only:

```bash
# Linux x64
bash uncloud/scripts/stage_uv.sh x86_64-unknown-linux-gnu
cd uncloud
npm run tauri build -- --target x86_64-unknown-linux-gnu --bundles appimage

# Windows x64, from Git Bash or the CI shell
bash uncloud/scripts/stage_uv.sh x86_64-pc-windows-msvc
cd uncloud
npm run tauri build -- --target x86_64-pc-windows-msvc --bundles nsis
```

Pushing a version tag runs source tests, builds each native package, inspects
its installed contents, starts the packaged application and engine, creates
checksums, and publishes the GitHub release only if every platform passes.
