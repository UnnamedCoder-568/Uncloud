//! Replacing the installed application with a newer, signed one.
//!
//! The update is found at the release endpoint, its signature is checked
//! against the public key compiled into this build, and only then is anything
//! installed. A build made without a key does not look for updates at all: an
//! updater that cannot verify what it downloads is the one thing worse than no
//! updater.
//!
//! Uncloud's policy is CONTINUOUS — every newer version is offered, majors
//! included. Uncloud Studio uses the same module with WITHIN_MAJOR, which is
//! why the policy is a value and not an assumption.
//!
//! Notices that are not new versions — announcements, known problems — come
//! from the engine's manifest check, not from here.

use serde::Serialize;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter};
use tauri_plugin_updater::{Update, UpdaterExt};

/// The public half of the update signing key. Empty until one is generated;
/// see docs/UPDATES.md. Public by nature — the private half never enters the
/// repository.
const PUBKEY: &str = include_str!("../updater-pubkey.txt");

/// Where releases publish their signed `latest.json`. GitHub's `latest` points
/// at the newest release that is not marked as a pre-release.
const ENDPOINT: &str =
    "https://github.com/UnnamedCoder-568/Uncloud/releases/latest/download/latest.json";

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Policy {
    Continuous,
    #[allow(dead_code)]
    WithinMajor,
}

pub const POLICY: Policy = Policy::Continuous;

/// Whether `candidate` may replace `current` under `policy`.
pub fn accepts(policy: Policy, current: &semver::Version, candidate: &semver::Version) -> bool {
    candidate > current && (policy == Policy::Continuous || candidate.major == current.major)
}

#[derive(Default)]
pub struct UpdateState {
    pending: Mutex<Option<Update>>,
}

#[derive(Serialize, Clone)]
pub struct Available {
    version: String,
    notes: String,
    date: String,
}

#[derive(Serialize)]
pub struct Status {
    /// False when this build cannot verify updates, and so never checks.
    configured: bool,
    reason: String,
    current: String,
    available: Option<Available>,
}

#[tauri::command]
pub async fn app_update_check(
    app: AppHandle,
    state: tauri::State<'_, UpdateState>,
) -> Result<Status, String> {
    let current = app.package_info().version.to_string();
    let pubkey = PUBKEY.trim();
    if pubkey.is_empty() {
        return Ok(Status {
            configured: false,
            reason: "This build was made without an update signing key, so it cannot verify \
                     an update and does not look for one."
                .into(),
            current,
            available: None,
        });
    }

    let endpoint = tauri::Url::parse(ENDPOINT).map_err(|e| e.to_string())?;
    let updater = app
        .updater_builder()
        .pubkey(pubkey)
        .endpoints(vec![endpoint])
        .map_err(|e| e.to_string())?
        .version_comparator(|current, remote| accepts(POLICY, &current, &remote.version))
        .build()
        .map_err(|e| e.to_string())?;

    match updater.check().await {
        Ok(Some(update)) => {
            let available = Available {
                version: update.version.clone(),
                notes: update.body.clone().unwrap_or_default(),
                date: update.date.map(|d| d.to_string()).unwrap_or_default(),
            };
            *state.pending.lock().unwrap() = Some(update);
            Ok(Status {
                configured: true,
                reason: String::new(),
                current,
                available: Some(available),
            })
        }
        Ok(None) => {
            *state.pending.lock().unwrap() = None;
            Ok(Status {
                configured: true,
                reason: String::new(),
                current,
                available: None,
            })
        }
        // Offline, rate-limited, no release yet: nothing to report is not a
        // fault in the application, and is never shown as one.
        Err(error) => Ok(Status {
            configured: true,
            reason: format!("Could not check for updates: {error}"),
            current,
            available: None,
        }),
    }
}

/// Download, verify and install the update found by the last check, then
/// restart into it. Progress arrives as `app-update-progress` events.
#[tauri::command]
pub async fn app_update_install(
    app: AppHandle,
    state: tauri::State<'_, UpdateState>,
) -> Result<(), String> {
    let update = state
        .pending
        .lock()
        .unwrap()
        .take()
        .ok_or("No update has been found to install. Check again first.")?;
    let events = app.clone();
    let mut received: u64 = 0;
    update
        .download_and_install(
            |chunk, total| {
                received += chunk as u64;
                let _ = events.emit("app-update-progress", (received, total));
            },
            || {},
        )
        .await
        .map_err(|e| format!("The update could not be installed: {e}"))?;
    // Restarting runs the exit handler, which stops the engine first.
    app.restart();
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v(text: &str) -> semver::Version {
        semver::Version::parse(text).unwrap()
    }

    #[test]
    fn continuous_accepts_every_newer_version() {
        assert!(accepts(Policy::Continuous, &v("0.3.0"), &v("0.3.1")));
        assert!(accepts(Policy::Continuous, &v("1.9.0"), &v("2.0.0")));
        assert!(!accepts(Policy::Continuous, &v("0.3.0"), &v("0.3.0")));
        assert!(!accepts(Policy::Continuous, &v("0.3.1"), &v("0.3.0")));
    }

    #[test]
    fn within_major_never_crosses_into_the_next_version() {
        assert!(accepts(Policy::WithinMajor, &v("1.0.0"), &v("1.4.2")));
        assert!(!accepts(Policy::WithinMajor, &v("1.9.9"), &v("2.0.0")));
    }

    #[test]
    fn a_prerelease_is_older_than_its_release() {
        assert!(accepts(Policy::Continuous, &v("0.3.0-test.2"), &v("0.3.0")));
    }

    #[test]
    fn this_build_can_verify_an_update() {
        // The key landed. An empty one here means every installed copy stops
        // looking for updates, silently — which is the failure this catches.
        let key = PUBKEY.trim();
        assert!(!key.is_empty(), "updater-pubkey.txt is empty");
        assert!(key.len() > 40 && !key.contains('\n'),
                "the public key should be one line of base64");
    }
}
