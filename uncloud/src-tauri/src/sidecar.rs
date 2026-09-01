use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, Manager};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarInfo {
    pub port: u16,
    pub token: String,
}

/// What the setup screen needs in order to explain itself. Every field is
/// observable state rather than a cached verdict, so the UI can re-check after
/// the user installs something without restarting the app.
#[derive(Debug, Clone, Serialize)]
pub struct RuntimeStatus {
    pub running: bool,
    /// The Python source is on disk where we expect it.
    pub source_ready: bool,
    /// `uv` was located, either bundled or already on the machine.
    pub uv_found: bool,
    /// The main environment exists, so dependencies have been installed.
    pub deps_ready: bool,
    pub engine_dir: String,
    pub error: Option<String>,
}

pub struct SidecarState {
    pub info: Mutex<Option<SidecarInfo>>,
    pub child: Mutex<Option<Child>>,
    /// Why the engine isn't running, kept so the window can open and say so
    /// instead of the process dying before it draws anything.
    pub error: Mutex<Option<String>>,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            info: Mutex::new(None),
            child: Mutex::new(None),
            error: Mutex::new(None),
        }
    }
}

fn home_dir() -> Option<PathBuf> {
    std::env::var_os("HOME")
        .or_else(|| std::env::var_os("USERPROFILE"))
        .map(PathBuf::from)
}

/// Where an installed engine lives on the user's machine.
pub fn engine_home() -> PathBuf {
    home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".uncloud")
        .join("engine")
}

/// The repo checkout, used when running from `npm run tauri dev`.
///
/// This is a compile-time constant, so it is only ever meaningful on the
/// machine that built the binary — a packaged app must not depend on it.
fn dev_sidecar_dir() -> Option<PathBuf> {
    let dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()?
        .parent()?
        .join("sidecar");
    dir.join("pyproject.toml").is_file().then_some(dir)
}

/// The read-only copy shipped inside the app bundle.
fn bundled_engine(app: &AppHandle) -> Option<PathBuf> {
    let dir = app.path().resource_dir().ok()?.join("engine");
    dir.join("pyproject.toml").is_file().then_some(dir)
}

/// Resolve the engine directory at *runtime*, preferring a live checkout during
/// development and otherwise the user's installed copy.
pub fn resolve_engine_dir(app: &AppHandle) -> Option<PathBuf> {
    if let Some(dev) = dev_sidecar_dir() {
        return Some(dev);
    }
    let installed = engine_home();
    if installed.join("pyproject.toml").is_file() {
        return Some(installed);
    }
    let _ = app;
    None
}

fn venv_python(engine_dir: &Path) -> PathBuf {
    if cfg!(windows) {
        engine_dir.join(".venv").join("Scripts").join("python.exe")
    } else {
        engine_dir.join(".venv").join("bin").join("python")
    }
}

/// Locate `uv` without relying on the inherited PATH: an app launched from
/// Finder gets a minimal one, so Homebrew and `~/.local/bin` are invisible.
pub fn find_uv(app: &AppHandle) -> Option<PathBuf> {
    // A copy shipped alongside the binary wins, so a clean machine needs nothing.
    if let Ok(dir) = app.path().resource_dir() {
        let name = if cfg!(windows) { "uv.exe" } else { "uv" };
        let bundled = dir.join(name);
        if bundled.is_file() {
            return Some(bundled);
        }
    }

    let mut candidates: Vec<PathBuf> =
        vec!["/opt/homebrew/bin/uv".into(), "/usr/local/bin/uv".into()];
    if let Some(home) = home_dir() {
        candidates.push(home.join(".local/bin/uv"));
        candidates.push(home.join(".cargo/bin/uv"));
        candidates.push(home.join(".local/bin/uv.exe"));
    }
    if let Some(found) = candidates.into_iter().find(|p| p.is_file()) {
        return Some(found);
    }

    let probe = if cfg!(windows) { "where" } else { "which" };
    Command::new(probe)
        .arg("uv")
        .output()
        .ok()
        .filter(|o| o.status.success())
        .and_then(|o| {
            let s = String::from_utf8_lossy(&o.stdout);
            let first = s.lines().next()?.trim().to_string();
            (!first.is_empty()).then(|| PathBuf::from(first))
        })
}

pub fn status(app: &AppHandle, state: &SidecarState) -> RuntimeStatus {
    let dir = resolve_engine_dir(app);
    let deps_ready = dir.as_deref().map(venv_python).is_some_and(|p| p.is_file());
    RuntimeStatus {
        running: state.info.lock().unwrap().is_some(),
        source_ready: dir.is_some(),
        uv_found: find_uv(app).is_some(),
        deps_ready,
        engine_dir: dir
            .unwrap_or_else(engine_home)
            .to_string_lossy()
            .into_owned(),
        error: state.error.lock().unwrap().clone(),
    }
}

fn copy_dir_all(src: &Path, dst: &Path) -> std::io::Result<()> {
    std::fs::create_dir_all(dst)?;
    for entry in std::fs::read_dir(src)? {
        let entry = entry?;
        let name = entry.file_name();
        // Never carry build noise into the user's copy.
        if name == "__pycache__" || name.to_string_lossy().starts_with(".venv") {
            continue;
        }
        let (from, to) = (entry.path(), dst.join(&name));
        if entry.file_type()?.is_dir() {
            copy_dir_all(&from, &to)?;
        } else {
            std::fs::copy(&from, &to)?;
        }
    }
    Ok(())
}

/// Put the engine source in place from the bundled copy. Idempotent: a newer
/// bundle overwrites an older install, which is how updates reach the engine.
pub fn ensure_engine_source(app: &AppHandle) -> Result<PathBuf, String> {
    if let Some(dev) = dev_sidecar_dir() {
        return Ok(dev);
    }
    let target = engine_home();
    let bundled = bundled_engine(app).ok_or_else(|| {
        "This build does not include the engine source. Install it manually — see INSTALL.md."
            .to_string()
    })?;
    copy_dir_all(&bundled, &target)
        .map_err(|e| format!("Could not copy the engine to {}: {e}", target.display()))?;
    Ok(target)
}

fn child_path_env() -> String {
    let extra = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    match std::env::var("PATH") {
        Ok(existing) if !existing.is_empty() => format!("{extra}:{existing}"),
        _ => extra.to_string(),
    }
}

/// Create the environment and install dependencies, streaming `uv`'s output to
/// the front end as `runtime-install-log` events so the wait is legible.
pub fn install_engine(app: &AppHandle) -> Result<(), String> {
    let dir = ensure_engine_source(app)?;
    let uv = find_uv(app).ok_or_else(|| {
        "Could not find `uv`, and this build does not bundle it. Install it from \
         https://docs.astral.sh/uv/ and try again."
            .to_string()
    })?;

    let emit = |line: &str| {
        let _ = app.emit("runtime-install-log", line.to_string());
    };
    emit(&format!("Installing into {}", dir.display()));

    let mut child = Command::new(&uv)
        .args(["sync"])
        .current_dir(&dir)
        .env("PATH", child_path_env())
        // uv installs a matching interpreter itself, so the machine needs no Python.
        .env("UV_PYTHON_DOWNLOADS", "automatic")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("Could not run `{}`: {e}", uv.display()))?;

    // uv reports progress on stderr; take both so nothing is lost.
    if let Some(out) = child.stdout.take() {
        let app = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(out).lines().map_while(Result::ok) {
                let _ = app.emit("runtime-install-log", line);
            }
        });
    }
    if let Some(err) = child.stderr.take() {
        let app = app.clone();
        std::thread::spawn(move || {
            for line in BufReader::new(err).lines().map_while(Result::ok) {
                let _ = app.emit("runtime-install-log", line);
            }
        });
    }

    let code = child
        .wait()
        .map_err(|e| format!("Install did not complete: {e}"))?;
    if !code.success() {
        return Err(format!("`uv sync` exited with status {code}"));
    }
    emit("Dependencies installed.");
    Ok(())
}

/// Spawn the engine and block until it prints its handshake line.
pub fn spawn_sidecar(app: &AppHandle) -> Result<(Child, SidecarInfo), String> {
    let dir = resolve_engine_dir(app)
        .ok_or_else(|| "The Uncloud engine is not installed yet.".to_string())?;
    let uv = find_uv(app).ok_or_else(|| {
        "Could not find `uv`. Install it (https://docs.astral.sh/uv/) or add it to PATH."
            .to_string()
    })?;

    let mut command = Command::new(&uv);
    command
        .args(["run", "python", "-m", "uncloud_engine.main"])
        .current_dir(&dir)
        .env("PATH", child_path_env())
        .env("UV_PYTHON_DOWNLOADS", "automatic")
        // A force quit or a crash never runs our exit handler. The engine
        // watches this pid and shuts itself down when it disappears.
        .env("UNCLOUD_PARENT_PID", std::process::id().to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit());

    // Own process group: the engine spawns model servers of its own, and
    // killing only the engine would leave those holding their memory.
    #[cfg(unix)]
    {
        use std::os::unix::process::CommandExt;
        command.process_group(0);
    }

    let mut child = command
        .spawn()
        .map_err(|e| format!("Failed to launch the engine via `{}`: {e}", uv.display()))?;

    let stdout = child.stdout.take().ok_or("Engine produced no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut first_line = String::new();
    if reader.read_line(&mut first_line).map_err(|e| e.to_string())? == 0 {
        return Err("Engine exited before printing a handshake".into());
    }

    let info: SidecarInfo = serde_json::from_str(first_line.trim())
        .map_err(|e| format!("Bad engine handshake '{}': {e}", first_line.trim()))?;

    // Drain the rest so a full pipe never blocks the child.
    std::thread::spawn(move || {
        let mut reader = reader;
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => print!("[engine] {line}"),
            }
        }
    });

    Ok((child, info))
}

pub async fn wait_healthy(port: u16, timeout_secs: u64) -> Result<(), String> {
    let client = reqwest::Client::new();
    let url = format!("http://127.0.0.1:{port}/health");
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(timeout_secs);
    while std::time::Instant::now() < deadline {
        if let Ok(resp) = client.get(&url).send().await {
            if resp.status().is_success() {
                return Ok(());
            }
        }
        tokio::time::sleep(std::time::Duration::from_millis(300)).await;
    }
    Err("Timed out waiting for the engine to report healthy".into())
}


/// Ask the engine and everything it started to stop, then insist.
///
/// SIGTERM first, because the engine unloads its models and closes its own
/// children on that signal; a straight kill would leave a chat server holding
/// twenty gigabytes with nothing left to reap it.
pub fn terminate(child: &mut Child) {
    #[cfg(unix)]
    {
        let pid = child.id() as i32;
        unsafe {
            // Negative pid targets the whole group.
            libc::killpg(pid, libc::SIGTERM);
        }
        for _ in 0..30 {
            match child.try_wait() {
                Ok(Some(_)) => return,
                Ok(None) => std::thread::sleep(std::time::Duration::from_millis(100)),
                Err(_) => break,
            }
        }
        unsafe {
            libc::killpg(pid, libc::SIGKILL);
        }
    }
    let _ = child.kill();
    let _ = child.wait();
}
