//! Z Money desktop shell.
//!
//! Double-click flow: pick a port for the FastAPI backend (reuse a Z Money
//! instance already answering on 8000, else 8000 if free, else any free
//! port), spawn `<project>/.venv/bin/python -m uvicorn api.server:app` with
//! the project directory as cwd, wait for /api/health, then show the window
//! whose bundled UI asks this shell for the base URL via the `api_base`
//! command. On exit the child we spawned is killed; an instance we merely
//! reused (the dev server, or the nightly pipeline's) is left alone.
//!
//! The project directory is the one the nightly launchd job uses too —
//! same SQLite file, same config.yaml — resolved from, in order:
//! ZMONEY_HOME, ~/.config/zmoney/home, then the built-in default.

use std::fs::{self, OpenOptions};
use std::io::Write;
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{Manager, RunEvent};

const DEFAULT_PORT: u16 = 8000;
const DEFAULT_PROJECT: &str = "/Users/zoravarsingh/zmoney";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(40);

struct Backend {
    port: u16,
    reused: bool,
    child: Mutex<Option<Child>>,
}

#[tauri::command]
fn api_base(state: tauri::State<'_, Backend>) -> String {
    format!("http://127.0.0.1:{}/api", state.port)
}

#[tauri::command]
fn backend_info(state: tauri::State<'_, Backend>) -> serde_json::Value {
    serde_json::json!({ "port": state.port, "reused": state.reused, "project": project_root().to_string_lossy() })
}

fn home() -> PathBuf {
    std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"))
}

fn project_root() -> PathBuf {
    if let Ok(p) = std::env::var("ZMONEY_HOME") {
        if !p.trim().is_empty() {
            return PathBuf::from(p.trim());
        }
    }
    let marker = home().join(".config/zmoney/home");
    if let Ok(s) = fs::read_to_string(&marker) {
        let t = s.trim();
        if !t.is_empty() {
            return PathBuf::from(t);
        }
    }
    PathBuf::from(DEFAULT_PROJECT)
}

fn log_dir() -> PathBuf {
    let dir = home().join("Library/Logs/Z Money");
    let _ = fs::create_dir_all(&dir);
    dir
}

fn log(msg: &str) {
    if let Ok(mut f) = OpenOptions::new().create(true).append(true).open(log_dir().join("app.log")) {
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);
        let _ = writeln!(f, "[{ts}] {msg}");
    }
}

fn health_ok(port: u16) -> bool {
    let url = format!("http://127.0.0.1:{port}/api/health");
    match ureq::get(&url).timeout(Duration::from_millis(800)).call() {
        Ok(resp) => resp.into_string().map(|b| b.contains("\"status\"") && b.contains("\"ok\"")).unwrap_or(false),
        Err(_) => false,
    }
}

fn port_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok()
}

fn free_port() -> u16 {
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|l| l.local_addr())
        .map(|a| a.port())
        .unwrap_or(8765)
}

fn start_backend() -> Backend {
    // 1. Something already answering as Z Money on 8000: reuse it, own nothing.
    if health_ok(DEFAULT_PORT) {
        log(&format!("reusing a Z Money backend already on port {DEFAULT_PORT}"));
        return Backend { port: DEFAULT_PORT, reused: true, child: Mutex::new(None) };
    }
    // 2. Otherwise 8000 if free, any free port if some other program holds it.
    let port = if port_free(DEFAULT_PORT) { DEFAULT_PORT } else { free_port() };
    let root = project_root();
    let python = root.join(".venv/bin/python");
    log(&format!("starting backend: {} -m uvicorn api.server:app on port {port} (cwd {})", python.display(), root.display()));

    let backend_log = log_dir().join("backend.log");
    let out = OpenOptions::new().create(true).append(true).open(&backend_log).ok();
    let err = OpenOptions::new().create(true).append(true).open(&backend_log).ok();
    let spawned = Command::new(&python)
        .args(["-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", &port.to_string()])
        .current_dir(&root)
        .stdin(Stdio::null())
        .stdout(out.map(Stdio::from).unwrap_or_else(Stdio::null))
        .stderr(err.map(Stdio::from).unwrap_or_else(Stdio::null))
        .spawn();

    let child = match spawned {
        Ok(c) => Some(c),
        Err(e) => {
            log(&format!("FAILED to spawn backend: {e}. Is the venv at {}?", python.display()));
            None
        }
    };

    if child.is_some() {
        let started = Instant::now();
        while started.elapsed() < HEALTH_TIMEOUT {
            if health_ok(port) {
                log(&format!("backend healthy on port {port} after {:.1}s", started.elapsed().as_secs_f32()));
                break;
            }
            std::thread::sleep(Duration::from_millis(250));
        }
        if !health_ok(port) {
            log(&format!("backend did not become healthy within {HEALTH_TIMEOUT:?}; see {}", backend_log.display()));
        }
    }
    Backend { port, reused: false, child: Mutex::new(child) }
}

fn stop_backend(backend: &Backend) {
    if backend.reused {
        return;
    }
    if let Ok(mut guard) = backend.child.lock() {
        if let Some(child) = guard.as_mut() {
            log(&format!("stopping backend pid {}", child.id()));
            let _ = child.kill();
            let _ = child.wait();
        }
        *guard = None;
    }
}

pub fn run() {
    let backend = start_backend();
    let app = tauri::Builder::default()
        .manage(backend)
        .invoke_handler(tauri::generate_handler![api_base, backend_info])
        .setup(|app| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Z Money");

    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_backend(&handle.state::<Backend>());
            log("app exit");
        }
    });
}
