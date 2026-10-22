use std::fs::File;
use std::net::TcpListener;
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use tauri::menu::{Menu, SubmenuBuilder};
use tauri::{Emitter, Manager, RunEvent, WindowEvent};

struct Sidecar(Mutex<Option<Child>>);

/// Port picked at launch. No fixed port means no clash with another app (or a second
/// praTRD instance) and nothing to kill on startup; orphaned sidecars exit on their own
/// (PRATRD_PARENT_PID watchdog in the sidecar).
struct SidecarPort(u16);

#[tauri::command]
fn sidecar_port(port: tauri::State<'_, SidecarPort>) -> u16 {
    port.0
}

/// Ask the OS for a free loopback port. The tiny window between closing this listener
/// and uvicorn binding is acceptable: the frontend would show its error screen.
fn pick_port() -> u16 {
    TcpListener::bind("127.0.0.1:0")
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(7433)
}

/// Set after the first close request, so a hung frontend can never trap the window:
/// the second click on the close button always closes.
struct CloseRequested(AtomicBool);

/// Where workspaces/ and app_settings.json live.
/// Release: per-user OS app-data dir. Dev: the project root baked in by build.rs.
fn data_root(app: &tauri::AppHandle) -> PathBuf {
    #[cfg(feature = "pyinstaller-sidecar")]
    {
        app.path().app_data_dir().expect("no app data dir")
    }
    #[cfg(not(feature = "pyinstaller-sidecar"))]
    {
        let _ = app;
        PathBuf::from(env!("PRATRD_ROOT"))
    }
}

fn sidecar_command(app: &tauri::AppHandle, root: &Path) -> Command {
    #[cfg(feature = "pyinstaller-sidecar")]
    {
        let _ = root;
        let exe = if cfg!(windows) {
            "sidecar.exe"
        } else {
            "sidecar"
        };
        // PyInstaller --onedir output is bundled as resources/sidecar/{exe,_internal/}.
        let bin = app
            .path()
            .resource_dir()
            .expect("no resource dir")
            .join("sidecar")
            .join(exe);
        // Only touch permissions if the exec bit is really missing. Writing into our own
        // signed bundle on macOS trips "App Management" protection: an unconditional
        // chmod blocked the main thread forever when launched from Finder / `open`.
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            if let Ok(meta) = std::fs::metadata(&bin) {
                let mode = meta.permissions().mode();
                if mode & 0o111 == 0 {
                    let _ = std::fs::set_permissions(
                        &bin,
                        std::fs::Permissions::from_mode(mode | 0o755),
                    );
                }
            }
        }
        Command::new(bin)
    }
    #[cfg(not(feature = "pyinstaller-sidecar"))]
    {
        let _ = app;
        // GUI apps on macOS don't inherit the shell PATH — probe the usual uv locations.
        let home = std::env::var_os("HOME")
            .map(PathBuf::from)
            .unwrap_or_default();
        let uv = [
            PathBuf::from("/opt/homebrew/bin/uv"),
            PathBuf::from("/usr/local/bin/uv"),
            home.join(".local/bin/uv"),
            home.join(".cargo/bin/uv"),
        ]
        .into_iter()
        .find(|p| p.exists())
        .unwrap_or_else(|| PathBuf::from("uv"));
        let mut cmd = Command::new(uv);
        cmd.current_dir(root)
            .args(["run", "--frozen", "python", "-m", "pratrd"]);
        cmd
    }
}

fn spawn_sidecar(app: &tauri::AppHandle, port: u16) -> std::io::Result<Child> {
    let root = data_root(app);
    std::fs::create_dir_all(&root)?;
    // One log per run: startup tracebacks (e.g. a missing module in a frozen build)
    // would otherwise vanish, since a GUI app has no console.
    let log = File::create(root.join("sidecar.log"))?;
    let mut cmd = sidecar_command(app, &root);
    cmd.env("PRATRD_ROOT", &root)
        .env("PRATRD_PORT", port.to_string())
        .env("PRATRD_PARENT_PID", std::process::id().to_string())
        .env("PYTHONUNBUFFERED", "1")
        .stdin(Stdio::null())
        .stdout(log.try_clone()?)
        .stderr(log);
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    cmd.spawn()
}

fn stop_sidecar(app: &tauri::AppHandle) {
    if let Some(mut child) = app.state::<Sidecar>().0.lock().unwrap().take() {
        let _ = child.kill();
        let _ = child.wait();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Sidecar(Mutex::new(None)))
        .manage(SidecarPort(pick_port()))
        .manage(CloseRequested(AtomicBool::new(false)))
        .invoke_handler(tauri::generate_handler![sidecar_port])
        .setup(|app| {
            let port = app.state::<SidecarPort>().0;
            match spawn_sidecar(app.handle(), port) {
                Ok(child) => *app.state::<Sidecar>().0.lock().unwrap() = Some(child),
                // The frontend shows its own error screen when /health never answers.
                Err(e) => eprintln!("[praTRD] cannot start sidecar: {e}"),
            }

            // Keep the default menu: WKWebView implements Cmd+C/V/X/Z/A in text fields
            // through the Edit menu items — removing them breaks copy/paste app-wide.
            let menu = Menu::default(app.handle())?;
            let workspace = SubmenuBuilder::new(app, "Workspace")
                .text("ws_new", "Nowy workspace…")
                .text("ws_open", "Przełącz…")
                .separator()
                .text("ws_import", "Importuj…")
                .text("ws_export", "Eksportuj aktywny…")
                .build()?;
            menu.append(&workspace)?;
            app.set_menu(menu)?;
            app.on_menu_event(|app, event| {
                let action = match event.id().as_ref() {
                    "ws_new" => "new",
                    "ws_open" => "open",
                    "ws_import" => "import",
                    "ws_export" => "export",
                    _ => return,
                };
                let _ = app.emit("workspace-menu", action);
            });
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let flag = &window.state::<CloseRequested>().0;
                if !flag.swap(true, Ordering::SeqCst) {
                    // Let the frontend flush debounced saves; it destroys the window itself.
                    api.prevent_close();
                    let _ = window.emit("close-requested", ());
                }
            }
        })
        .build(tauri::generate_context!())
        .expect("error while building praTRD");

    app.run(|app, event| match event {
        // Cmd+Q / app-menu Quit bypasses the window's CloseRequested: route it through
        // the same flush-then-destroy handshake. code == None means user-initiated.
        RunEvent::ExitRequested {
            api, code: None, ..
        } => {
            if !app.state::<CloseRequested>().0.swap(true, Ordering::SeqCst) {
                api.prevent_exit();
                let _ = app.emit("close-requested", ());
            }
        }
        RunEvent::Exit => stop_sidecar(app),
        _ => {}
    });
}
