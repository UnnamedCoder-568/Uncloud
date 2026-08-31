use serde::{Deserialize, Serialize};
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SidecarInfo {
    pub port: u16,
    pub token: String,
}

pub struct SidecarState {
    pub info: Mutex<Option<SidecarInfo>>,
    pub child: Mutex<Option<Child>>,
}

impl SidecarState {
    pub fn new() -> Self {
        Self {
            info: Mutex::new(None),
            child: Mutex::new(None),
        }
    }
}

/// Locate the `uv` binary without relying on the inherited PATH.
fn find_uv() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = vec![
        "/opt/homebrew/bin/uv".into(),
        "/usr/local/bin/uv".into(),
    ];
    if let Some(home) = std::env::var_os("HOME") {
        let home = PathBuf::from(home);
        candidates.push(home.join(".local/bin/uv"));
        candidates.push(home.join(".cargo/bin/uv"));
    }
    if let Some(found) = candidates.into_iter().find(|p| p.is_file()) {
        return Some(found);
    }
    // Fall back to whatever PATH we did inherit.
    Command::new("which")
        .arg("uv")
        .output()
        .ok()
        .filter(|o| o.status.success())
        .and_then(|o| {
            let s = String::from_utf8_lossy(&o.stdout).trim().to_string();
            (!s.is_empty()).then(|| PathBuf::from(s))
        })
}

fn sidecar_dir() -> PathBuf {
    // Dev layout: <repo>/astro/src-tauri, sidecar lives at <repo>/sidecar.
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .parent() // astro/
        .and_then(|p| p.parent()) // repo root
        .expect("unexpected project layout")
        .join("sidecar")
}

/// Spawns the Python engine, blocks until it prints its startup handshake
/// line (`{"port": ..., "token": ...}`), and returns the parsed info.
pub fn spawn_sidecar() -> Result<(Child, SidecarInfo), String> {
    let dir = sidecar_dir();
    if !dir.join("pyproject.toml").exists() {
        return Err(format!("Sidecar project not found at {}", dir.display()));
    }

    // An app launched from Finder inherits a minimal PATH (/usr/bin:/bin:/usr/sbin:/sbin)
    // rather than the shell's, so Homebrew and friends are invisible. Resolve `uv`
    // ourselves and hand the child a PATH that includes the usual install locations —
    // otherwise `uv` starts, fails to find its toolchain, and hangs before printing
    // the handshake we're waiting on.
    let uv = find_uv().ok_or_else(|| {
        "Could not find `uv`. Install it (https://docs.astral.sh/uv/) or add it to PATH.".to_string()
    })?;

    let extra_paths = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin";
    let path_env = match std::env::var("PATH") {
        Ok(existing) if !existing.is_empty() => format!("{extra_paths}:{existing}"),
        _ => extra_paths.to_string(),
    };

    let mut child = Command::new(&uv)
        .args(["run", "python", "-m", "uncloud_engine.main"])
        .current_dir(&dir)
        .env("PATH", path_env)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|e| format!("Failed to launch sidecar via `{}`: {e}", uv.display()))?;

    let stdout = child.stdout.take().ok_or("Sidecar produced no stdout")?;
    let mut reader = BufReader::new(stdout);
    let mut first_line = String::new();
    use std::io::Read;
    let mut byte = [0u8; 1];
    loop {
        let n = reader
            .get_mut()
            .read(&mut byte)
            .map_err(|e| format!("Failed reading sidecar handshake: {e}"))?;
        if n == 0 {
            return Err("Sidecar exited before printing a handshake".into());
        }
        if byte[0] == b'\n' {
            break;
        }
        first_line.push(byte[0] as char);
    }

    let info: SidecarInfo = serde_json::from_str(first_line.trim())
        .map_err(|e| format!("Bad sidecar handshake '{first_line}': {e}"))?;

    // Drain the rest of stdout on a background thread so the child never blocks on a full pipe.
    std::thread::spawn(move || {
        let mut reader = reader;
        let mut line = String::new();
        loop {
            line.clear();
            match reader.read_line(&mut line) {
                Ok(0) | Err(_) => break,
                Ok(_) => print!("[sidecar] {line}"),
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
    Err("Timed out waiting for sidecar /health".into())
}
