mod listener;
mod sidecar;
mod updates;

use sidecar::{RuntimeStatus, SidecarInfo, SidecarState};
use tauri::{AppHandle, Manager};

#[tauri::command]
fn get_sidecar_info(state: tauri::State<SidecarState>) -> Option<SidecarInfo> {
    state.info.lock().unwrap().clone()
}

#[tauri::command]
fn runtime_status(app: AppHandle, state: tauri::State<SidecarState>) -> RuntimeStatus {
    sidecar::status(&app, &state)
}

/// Create the engine environment. Long-running; progress arrives separately as
/// `runtime-install-log` events.
#[tauri::command]
async fn install_runtime(app: AppHandle) -> Result<(), String> {
    tauri::async_runtime::spawn_blocking(move || sidecar::install_engine(&app))
        .await
        .map_err(|e| format!("Install task failed: {e}"))?
}

/// Start the engine and wait for it to report healthy. Safe to call repeatedly:
/// if it is already up, the existing handshake is returned.
#[tauri::command]
async fn start_runtime(
    app: AppHandle,
    state: tauri::State<'_, SidecarState>,
) -> Result<SidecarInfo, String> {
    let existing = state.info.lock().unwrap().clone();
    if let Some(info) = existing {
        return Ok(info);
    }

    let spawn_app = app.clone();
    let (mut child, info) =
        tauri::async_runtime::spawn_blocking(move || sidecar::spawn_sidecar(&spawn_app))
            .await
            .map_err(|e| format!("Start task failed: {e}"))??;

    if let Err(e) = sidecar::wait_healthy(info.port, 120).await {
        sidecar::terminate(&mut child);
        *state.error.lock().unwrap() = Some(e.clone());
        return Err(e);
    }

    *state.info.lock().unwrap() = Some(info.clone());
    *state.child.lock().unwrap() = Some(child);
    *state.error.lock().unwrap() = None;
    Ok(info)
}

#[tauri::command]
fn network_access(app: AppHandle) -> bool {
    sidecar::network_access_enabled(&app)
}

/// Turn "available on this network" on or off, and restart the engine so the
/// change takes effect. The port and token change with the restart, so the
/// window reloads afterwards rather than trusting what it had cached.
#[tauri::command]
async fn set_network_access(
    app: AppHandle,
    state: tauri::State<'_, SidecarState>,
    enabled: bool,
) -> Result<SidecarInfo, String> {
    sidecar::set_network_access(&app, enabled)?;

    let taken = state.child.lock().unwrap().take();
    if let Some(mut child) = taken {
        sidecar::terminate(&mut child);
    }
    *state.info.lock().unwrap() = None;

    let spawn_app = app.clone();
    let (mut child, info) =
        tauri::async_runtime::spawn_blocking(move || sidecar::spawn_sidecar(&spawn_app))
            .await
            .map_err(|e| format!("Restart task failed: {e}"))??;
    if let Err(e) = sidecar::wait_healthy(info.port, 120).await {
        sidecar::terminate(&mut child);
        *state.error.lock().unwrap() = Some(e.clone());
        return Err(e);
    }
    *state.info.lock().unwrap() = Some(info.clone());
    *state.child.lock().unwrap() = Some(child);
    *state.error.lock().unwrap() = None;
    Ok(info)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        // Without this nothing could leave the application: every link in a
        // reply, a release note or the model catalogue was inert, because
        // the webview has nowhere to send a request for a new window.
        .plugin(tauri_plugin_opener::init())
        .manage(updates::UpdateState::default())
        .manage(listener::Listening::default())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            // Starting the engine must never prevent the window from opening:
            // when it is missing the front end shows a setup screen, and it
            // cannot do that if this closure returns Err.
            let state = SidecarState::new();
            match sidecar::spawn_sidecar(app.handle()) {
                Ok((mut child, info)) => {
                    let port = info.port;
                    match tauri::async_runtime::block_on(sidecar::wait_healthy(port, 90)) {
                        Ok(()) => {
                            *state.info.lock().unwrap() = Some(info);
                            *state.child.lock().unwrap() = Some(child);
                        }
                        Err(e) => {
                            sidecar::terminate(&mut child);
                            log::warn!("Engine did not become healthy: {e}");
                            *state.error.lock().unwrap() = Some(e);
                        }
                    }
                }
                Err(e) => {
                    log::warn!("Engine not started: {e}");
                    *state.error.lock().unwrap() = Some(e);
                }
            }
            app.manage(state);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            get_sidecar_info,
            runtime_status,
            install_runtime,
            start_runtime,
            network_access,
            set_network_access,
            updates::app_update_check,
            updates::app_update_install,
            listener::listener_available,
            listener::listener_start,
            listener::listener_end_turn,
            listener::listener_stop
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            // Both events, because they cover different exits. Closing the
            // last window raises ExitRequested; Cmd-Q and the Quit menu item
            // go straight to Exit, which is how people actually quit on macOS
            // — handling only the first left the engine running with its
            // models still resident. `take()` makes the second call a no-op.
            if matches!(
                event,
                tauri::RunEvent::ExitRequested { .. } | tauri::RunEvent::Exit
            ) {
                let state = app_handle.state::<SidecarState>();
                let taken = state.child.lock().unwrap().take();
                if let Some(mut child) = taken {
                    sidecar::terminate(&mut child);
                }
            }
        });
}
