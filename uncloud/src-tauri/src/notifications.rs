//! Native delivery runs in Rust, independently of a suspended/hidden webview.
//! Clicks only foreground the app and emit a record ID. No execution grants.
use crate::sidecar::{SidecarInfo, SidecarState};
use serde::{Deserialize, Serialize};
use std::sync::{
    atomic::{AtomicBool, AtomicUsize, Ordering},
    Mutex,
};
use tauri::{AppHandle, Emitter, Manager};

#[derive(Default)]
pub struct DesktopState {
    pub background: AtomicBool,
    last_click: Mutex<Option<String>>,
}

static ACTIVE_ALERTS: AtomicUsize = AtomicUsize::new(0);

#[tauri::command]
pub async fn notification_permission(request: bool) -> Result<String, String> {
    #[cfg(target_os = "macos")]
    {
        if request {
            let granted = notify_rust::request_auth()
                .await
                .map_err(|e| e.to_string())?;
            if !granted {
                return Ok("Not authorized. Review Uncloud in macOS System Settings → Notifications. Your requests remain in the bell inbox.".into());
            }
        }
        let settings = notify_rust::get_notification_settings()
            .await
            .map_err(|e| e.to_string())?;
        Ok(format!(
            "{:?}; alerts: {:?}; sound: {:?}",
            settings.authorization_status, settings.alert_enabled, settings.sound_enabled
        ))
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = request;
        Ok("Managed by your operating system. Use the test alert to check delivery.".into())
    }
}

#[derive(Clone, Deserialize)]
struct Event {
    id: String,
    title: String,
    body: String,
    category: String,
    source: String,
}
#[derive(Deserialize)]
struct Preferences {
    enabled: bool,
    sound: bool,
    system_sound: bool,
    background: bool,
    quiet: bool,
}
#[derive(Deserialize)]
struct Batch {
    events: Vec<Event>,
    preferences: Preferences,
}

#[derive(Serialize)]
pub struct DesktopPreferences {
    background: bool,
    last_click: Option<String>,
}

#[tauri::command]
pub fn desktop_preferences(app: AppHandle, consume: Option<bool>) -> DesktopPreferences {
    let state = app.state::<DesktopState>();
    let last_click = if consume.unwrap_or(false) {
        state.last_click.lock().unwrap().take()
    } else {
        state.last_click.lock().unwrap().clone()
    };
    DesktopPreferences {
        background: state.background.load(Ordering::Relaxed),
        last_click,
    }
}

#[tauri::command]
pub fn set_background_running(app: AppHandle, enabled: bool) -> Result<(), String> {
    let directory = app.path().app_config_dir().map_err(|e| e.to_string())?;
    std::fs::create_dir_all(&directory).map_err(|e| e.to_string())?;
    let temp = directory.join("desktop-preferences.tmp");
    std::fs::write(
        &temp,
        serde_json::json!({"background": enabled}).to_string(),
    )
    .map_err(|e| e.to_string())?;
    std::fs::rename(temp, directory.join("desktop-preferences.json")).map_err(|e| e.to_string())?;
    app.state::<DesktopState>()
        .background
        .store(enabled, Ordering::Relaxed);
    Ok(())
}

fn clicked(app: &AppHandle, id: &str) {
    *app.state::<DesktopState>().last_click.lock().unwrap() = Some(id.to_string());
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
    let _ = app.emit("notification-open", id);
}

fn valid_id(id: &str) -> bool {
    id.len() == 32 && id.bytes().all(|b| b.is_ascii_hexdigit())
}

fn present(app: AppHandle, event: Event, sound: bool) -> Result<(), String> {
    if !valid_id(&event.id) {
        return Err("Invalid notification identifier".into());
    }
    let mut notification = notify_rust::Notification::new();
    notification
        .summary(&event.title)
        .body(&event.body)
        .appname("Uncloud");
    // Normal OS priority: never time-sensitive/critical, never app-level audio.
    #[cfg(target_os = "windows")]
    {
        notification.app_id("com.uncloud.app");
        if !sound {
            notification.sound_name("silent");
        }
    }
    #[cfg(target_os = "macos")]
    if sound {
        notification.sound_name("");
    }
    #[cfg(all(unix, not(target_os = "macos")))]
    {
        notification
            .icon("uncloud")
            .action("default", "Open Uncloud");
        notification.hint(notify_rust::Hint::SuppressSound(!sound));
    }
    notification.timeout(notify_rust::Timeout::Milliseconds(600_000));
    if ACTIVE_ALERTS
        .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |n| {
            (n < 16).then_some(n + 1)
        })
        .is_err()
    {
        return Err("Notification queue is full; the request remains in the inbox".into());
    }
    let handle = match notification.show() {
        Ok(handle) => handle,
        Err(error) => {
            ACTIVE_ALERTS.fetch_sub(1, Ordering::Relaxed);
            return Err(error.to_string());
        }
    };
    // The handle receives activation/dismissal from the native OS API.
    std::thread::spawn(move || {
        handle.wait_for_action(move |action| {
            if action == "default" {
                clicked(&app, &event.id);
            }
        });
        ACTIVE_ALERTS.fetch_sub(1, Ordering::Relaxed);
    });
    Ok(())
}

pub fn start(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    use tauri::menu::{Menu, MenuItem};
    use tauri::tray::TrayIconBuilder;
    if let Ok(directory) = app.path().app_config_dir() {
        if let Ok(text) = std::fs::read_to_string(directory.join("desktop-preferences.json")) {
            if let Ok(data) = serde_json::from_str::<serde_json::Value>(&text) {
                app.state::<DesktopState>()
                    .background
                    .store(data["background"] == true, Ordering::Relaxed);
            }
        }
    }
    let show = MenuItem::with_id(app, "show", "Open Uncloud", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, "stop", "Stop active tasks", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Uncloud", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show, &stop, &quit])?;
    let mut tray = TrayIconBuilder::with_id("uncloud-background")
        .tooltip("Uncloud")
        .menu(&menu)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "show" => {
                if let Some(w) = app.get_webview_window("main") {
                    let _ = w.show();
                    let _ = w.set_focus();
                }
            }
            "stop" => {
                let app = app.clone();
                tauri::async_runtime::spawn(async move {
                    let info = app.state::<SidecarState>().info.lock().unwrap().clone();
                    if let Some(info) = info {
                        let _ = client()
                            .post(format!("http://127.0.0.1:{}/api/tasks/stop", info.port))
                            .bearer_auth(info.token)
                            .send()
                            .await;
                    }
                });
            }
            "quit" => app.exit(0),
            _ => {}
        });
    if let Some(icon) = app.default_window_icon() {
        tray = tray.icon(icon.clone());
    }
    tray.build(app)?;
    let app = app.clone();
    tauri::async_runtime::spawn(async move {
        let client = client();
        loop {
            tokio::time::sleep(std::time::Duration::from_secs(2)).await;
            let info = app.state::<SidecarState>().info.lock().unwrap().clone();
            let Some(info) = info else { continue };
            let response = client
                .get(format!(
                    "http://127.0.0.1:{}/api/notifications/native",
                    info.port
                ))
                .bearer_auth(&info.token)
                .send()
                .await;
            let Ok(response) = response else { continue };
            if !response.status().is_success() {
                continue;
            }
            let Ok(batch) = response.json::<Batch>().await else {
                continue;
            };
            for event in batch.events {
                let focused = app
                    .get_webview_window("main")
                    .and_then(|w| w.is_focused().ok())
                    .unwrap_or(false);
                let eligible = batch.preferences.enabled
                    && (!focused
                        || event.source == "notification_test"
                        || matches!(event.category.as_str(), "permission" | "question"))
                    && (focused || batch.preferences.background);
                let status = if !eligible {
                    "suppressed"
                } else {
                    let result = present(
                        app.clone(),
                        event.clone(),
                        batch.preferences.sound
                            && batch.preferences.system_sound
                            && !batch.preferences.quiet,
                    );
                    if result.is_ok() {
                        "submitted"
                    } else {
                        "unavailable"
                    }
                };
                delivery(&client, &info, &event.id, status).await;
            }
        }
    });
    Ok(())
}

fn client() -> reqwest::Client {
    reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .unwrap()
}
async fn delivery(client: &reqwest::Client, info: &SidecarInfo, id: &str, status: &str) {
    let _ = client
        .post(format!(
            "http://127.0.0.1:{}/api/notifications/delivery",
            info.port
        ))
        .bearer_auth(&info.token)
        .json(&serde_json::json!({"id": id, "status": status}))
        .send()
        .await;
}

#[cfg(test)]
mod tests {
    #[test]
    fn notification_ids_are_navigation_only() {
        assert!(super::valid_id("0123456789abcdef0123456789abcdef"));
        assert!(!super::valid_id("yes"));
        assert!(!super::valid_id("../../approve"));
    }
}
