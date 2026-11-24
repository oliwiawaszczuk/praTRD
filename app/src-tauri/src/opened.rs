//! Files and folders the system hands to the app (Finder, `open -a praTRD path`, praBada's
//! "Otwórz w…"). They can arrive before the page listens, so the event only says "look"
//! and the paths wait here until the frontend takes them.

use std::sync::Mutex;

use tauri::{AppHandle, Emitter, State};

#[derive(Default)]
pub struct Opened(Mutex<Vec<String>>);

#[tauri::command]
pub fn opened_take(opened: State<'_, Opened>) -> Vec<String> {
    opened.0.lock().map(|mut g| std::mem::take(&mut *g)).unwrap_or_default()
}

pub fn push(app: &AppHandle, opened: &Opened, urls: &[tauri::Url]) {
    let paths: Vec<String> = urls.iter().filter_map(|u| u.to_file_path().ok()).map(|p| p.to_string_lossy().into_owned()).collect();
    if paths.is_empty() {
        return;
    }
    if let Ok(mut g) = opened.0.lock() {
        g.extend(paths);
    }
    let _ = app.emit("files-opened", ());
}
