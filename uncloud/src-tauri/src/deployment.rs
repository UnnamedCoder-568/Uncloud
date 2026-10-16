//! First-run planning uses locked archive sizes, never invented download progress.
use serde_json::{json, Value};
use std::path::Path;
use std::sync::OnceLock;

pub fn plan(destination: &Path) -> Value {
    static MANIFEST: OnceLock<Value> = OnceLock::new();
    let manifest = MANIFEST.get_or_init(|| {
        serde_json::from_str(include_str!("../../../sidecar/setup-manifest.json"))
            .expect("validated setup manifest")
    });
    let target = match (std::env::consts::OS, std::env::consts::ARCH) {
        ("macos", "aarch64") => "macos-arm64",
        ("windows", "x86_64") => "windows-x64",
        ("linux", "x86_64") => "linux-x64",
        _ => "unsupported",
    };
    let mut profile = manifest["profiles"][target].clone();
    if let Some(object) = profile.as_object_mut() {
        object.insert(
            "available_bytes".into(),
            json!(available_space(destination)),
        );
        object.insert("platform".into(), json!(target));
    }
    profile
}

fn existing_parent(path: &Path) -> Option<&Path> {
    path.ancestors().find(|candidate| candidate.is_dir())
}

#[cfg(unix)]
fn available_space(path: &Path) -> Option<u64> {
    use std::ffi::CString;
    use std::os::unix::ffi::OsStrExt;
    let path = CString::new(existing_parent(path)?.as_os_str().as_bytes()).ok()?;
    let mut info = std::mem::MaybeUninit::<libc::statvfs>::uninit();
    if unsafe { libc::statvfs(path.as_ptr(), info.as_mut_ptr()) } != 0 {
        return None;
    }
    let info = unsafe { info.assume_init() };
    Some((info.f_bavail as u64).saturating_mul(info.f_frsize as u64))
}

#[cfg(windows)]
fn available_space(path: &Path) -> Option<u64> {
    use std::os::windows::ffi::OsStrExt;
    #[link(name = "kernel32")]
    extern "system" {
        fn GetDiskFreeSpaceExW(
            directory: *const u16,
            available: *mut u64,
            total: *mut u64,
            free: *mut u64,
        ) -> i32;
    }
    let path: Vec<u16> = existing_parent(path)?
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect();
    let mut available = 0;
    let ok = unsafe {
        GetDiskFreeSpaceExW(
            path.as_ptr(),
            &mut available,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    (ok != 0).then_some(available)
}

#[cfg(not(any(unix, windows)))]
fn available_space(_: &Path) -> Option<u64> {
    None
}

#[cfg(test)]
mod tests {
    #[test]
    fn plan_exposes_archive_totals_and_free_space_for_the_destination() {
        let plan = super::plan(&std::env::temp_dir());
        if !plan.is_null() {
            let files = plan["files"].as_array().unwrap();
            let total: u64 = files.iter().filter_map(|file| file["bytes"].as_u64()).sum();
            assert_eq!(plan["download_bytes"], total);
            assert_eq!(plan["package_count"], files.len());
            assert!(plan["available_bytes"].as_u64().is_some());
        }
    }
}
