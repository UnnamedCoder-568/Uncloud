mod sidecar;

use sidecar::{SidecarInfo, SidecarState};
use tauri::Manager;

#[tauri::command]
fn get_sidecar_info(state: tauri::State<SidecarState>) -> Option<SidecarInfo> {
    state.info.lock().unwrap().clone()
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let (child, info) = sidecar::spawn_sidecar().map_err(|e| {
                log::error!("Failed to start Uncloud engine: {e}");
                e
            })?;

            let port = info.port;
            tauri::async_runtime::block_on(sidecar::wait_healthy(port, 90))
                .map_err(|e| format!("Uncloud engine did not become healthy: {e}"))?;

            let state = SidecarState::new();
            *state.info.lock().unwrap() = Some(info);
            *state.child.lock().unwrap() = Some(child);
            app.manage(state);

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![get_sidecar_info])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::ExitRequested { .. } = event {
                let state = app_handle.state::<SidecarState>();
                let taken = state.child.lock().unwrap().take();
                if let Some(mut child) = taken {
                    let _ = child.kill();
                }
            }
        });
}
