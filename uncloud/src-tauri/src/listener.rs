//! The native listener: Apple's on-device recogniser, transcribing as you talk.
//!
//! The browser can only hand over a finished recording, which means every turn
//! in a conversation pays for an upload and a model load after the person has
//! stopped speaking. This runs a small helper inside the bundle that listens,
//! transcribes while the words arrive, and says when a turn has ended — so the
//! text is ready the moment there is a silence to act on.
//!
//! macOS only, and offered rather than assumed: `listener_available` is what
//! the interface asks before it uses this instead of Whisper, and everything
//! else keeps working where the answer is no.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Manager, State};

/// What the helper says, forwarded to the interface untouched.
#[derive(Clone, Serialize, Deserialize)]
pub struct ListenerEvent {
    pub event: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub text: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Default)]
pub struct Listening {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
}

/// The helper, beside the app's other resources. Absent on every platform but
/// macOS, which is exactly how `listener_available` answers.
fn helper(app: &AppHandle) -> Option<PathBuf> {
    let path = app.path().resource_dir().ok()?.join("uncloud-listen");
    path.is_file().then_some(path)
}

#[tauri::command]
pub fn listener_available(app: AppHandle) -> bool {
    cfg!(target_os = "macos") && helper(&app).is_some()
}

/// Start listening. Events arrive on the `listener` channel until `stop`.
#[tauri::command]
pub fn listener_start(
    app: AppHandle,
    state: State<'_, Listening>,
    locale: Option<String>,
) -> Result<(), String> {
    stop_now(&state);
    let path = helper(&app).ok_or("This build has no native listener.")?;

    let mut command = Command::new(path);
    if let Some(locale) = locale.filter(|l| !l.is_empty()) {
        command.args(["--locale", &locale]);
    }
    let mut child = command
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .map_err(|e| format!("The listener would not start: {e}"))?;

    let stdout = child
        .stdout
        .take()
        .ok_or("The listener produced no output.")?;
    *state.stdin.lock().unwrap() = child.stdin.take();
    *state.child.lock().unwrap() = Some(child);

    let handle = app.clone();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            // One JSON object per line, and nothing else is on that stream.
            // A line that is not one is the helper's business, not the app's.
            if let Ok(event) = serde_json::from_str::<ListenerEvent>(&line) {
                let _ = handle.emit("listener", event);
            }
        }
        // The helper ending is itself news: without this the interface waits
        // for a turn that can never arrive.
        let _ = handle.emit(
            "listener",
            ListenerEvent {
                event: "ended".into(),
                text: None,
                message: None,
            },
        );
    });
    Ok(())
}

/// End the current turn now, without waiting for a silence.
#[tauri::command]
pub fn listener_end_turn(state: State<'_, Listening>) -> Result<(), String> {
    if let Some(stdin) = state.stdin.lock().unwrap().as_mut() {
        stdin.write_all(b"stop\n").map_err(|e| e.to_string())?;
        stdin.flush().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
pub fn listener_stop(state: State<'_, Listening>) -> Result<(), String> {
    stop_now(&state);
    Ok(())
}

/// Ends the helper. Asked to leave first, so the microphone is released the
/// moment the person stops talking rather than whenever the process dies.
fn stop_now(state: &Listening) {
    if let Some(mut stdin) = state.stdin.lock().unwrap().take() {
        let _ = stdin.write_all(b"quit\n");
        let _ = stdin.flush();
    }
    if let Some(mut child) = state.child.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}
