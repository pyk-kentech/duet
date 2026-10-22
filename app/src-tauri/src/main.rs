// tenure 데스크톱 셸 (DESIGN.md 36.20·36.21).
// 창에는 먼저 앱에 든 시작 화면을 띄우고, 엔진(tenure-engine, 얼린 파이썬)을 켠 뒤 엔진이 주는 화면으로 옮긴다.
// 엔진이 준비되면 화면 위 가운데에 '섬'(작은 알약 창)을 띄운다. 섬 화면은 엔진의 #/island 이고, 셸은 창 크기·위치만 바꾼다.
// 창을 닫으면 엔진도 끝낸다. 엔진은 --parent-pid 로 이 프로세스를 지켜보다가 셸이 죽어도 스스로 끝난다.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, PhysicalPosition, PhysicalSize, RunEvent, Url, WebviewUrl, WebviewWindowBuilder};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, ShortcutState};
use tauri_plugin_updater::UpdaterExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

// 섬 펼치기 단축키: 앞에서부터 처음 등록되는 것 하나만 쓴다
// (Ctrl+Alt+Space 는 다른 앱이 흔히 차지하고 있어서 뺐다, DESIGN.md 36.21)
const ISLAND_SHORTCUTS: [&str; 2] = ["ctrl+alt+t", "ctrl+shift+space"];

struct Engine(Mutex<Option<Child>>);

fn engine_exe(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().resource_dir().map_err(|e| format!("앱 폴더를 찾지 못했습니다: {e}"))?;
    let name = if cfg!(windows) { "tenure-engine.exe" } else { "tenure-engine" };
    let exe = dir.join("engine").join(name);
    if exe.is_file() {
        Ok(exe)
    } else {
        Err(format!("엔진 실행 파일이 없습니다: {}", exe.display()))
    }
}

/// 엔진을 띄우고 `TENURE_READY {"url": ...}` 줄을 기다린다. (프로세스, 화면 주소)
fn spawn_engine(app: &AppHandle) -> Result<(Child, String), String> {
    let exe = engine_exe(app)?;
    let mut cmd = Command::new(&exe);
    cmd.args(["ui", "--no-browser", "--port", "0", "--ready-line", "--parent-pid"])
        .arg(std::process::id().to_string())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    #[cfg(windows)]
    cmd.creation_flags(CREATE_NO_WINDOW);
    let mut child = cmd.spawn().map_err(|e| format!("엔진을 켜지 못했습니다: {e}"))?;
    let stdout = child.stdout.take().ok_or("엔진 출력을 읽을 수 없습니다")?;
    let mut lines = BufReader::new(stdout).lines();
    let mut url = None;
    for line in lines.by_ref() {
        let Ok(line) = line else { break };
        if let Some(rest) = line.strip_prefix("TENURE_READY ") {
            let v: serde_json::Value = serde_json::from_str(rest).map_err(|e| format!("엔진 응답을 읽지 못했습니다: {e}"))?;
            url = v.get("url").and_then(|u| u.as_str()).map(str::to_string);
            break;
        }
    }
    // 남은 출력을 계속 비워 엔진이 쓰기에서 막히지 않게
    std::thread::spawn(move || for _ in lines {});
    match url {
        Some(u) => Ok((child, u)),
        None => {
            let _ = child.kill();
            Err("엔진이 준비 신호 없이 끝났습니다. 다시 열어 보세요.".into())
        }
    }
}

fn show_error(app: &AppHandle, msg: &str) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.eval(&format!("window.showError && window.showError({})", serde_json::json!(msg)));
    }
}

// ---------------------------------------------------------------- 섬 (36.21)
/// 섬 창 크기: 알약 · 배너 · 펼친 판 (논리 픽셀)
fn island_size(mode: &str) -> (f64, f64) {
    match mode {
        "panel" => (460.0, 560.0),
        "banner" => (460.0, 84.0),
        _ => (380.0, 40.0),
    }
}

/// 섬을 그 모니터의 위 가운데에 두고 크기를 맞춘다.
fn place_island(win: &tauri::WebviewWindow, mode: &str) {
    let (w, h) = island_size(mode);
    let Ok(Some(mon)) = win.current_monitor().or_else(|_| win.primary_monitor()) else { return };
    let scale = mon.scale_factor();
    let (pw, ph) = ((w * scale) as u32, (h * scale) as u32);
    let mpos = mon.position();
    let msize = mon.size();
    let x = mpos.x + ((msize.width as i32 - pw as i32) / 2);
    let y = mpos.y + (6.0 * scale) as i32;
    let _ = win.set_size(PhysicalSize::new(pw, ph));
    let _ = win.set_position(PhysicalPosition::new(x, y));
}

/// 섬 화면이 부른다: 알약(pill)·배너(banner)·펼친 판(panel)·숨기기(hide).
#[tauri::command]
fn island_mode(app: AppHandle, mode: String) {
    let Some(win) = app.get_webview_window("island") else { return };
    if mode == "hide" {
        let _ = win.hide();
        return;
    }
    place_island(&win, &mode);
    let _ = win.show();
    if mode == "panel" {
        let _ = win.set_focus();
    }
}

/// 섬 화면이 부른다: 메인 창을 앞으로 가져와 그 작업(해시 주소)을 연다.
#[tauri::command]
fn open_main(app: AppHandle, hash: String) {
    if let Some(w) = app.get_webview_window("main") {
        let _ = w.show();
        let _ = w.unminimize();
        let _ = w.set_focus();
        if hash.starts_with('#') {
            let _ = w.eval(&format!("location.hash = {}", serde_json::json!(hash)));
        }
    }
}

fn open_island(app: &AppHandle, engine_url: &str) {
    let mut url = match Url::parse(engine_url) {
        Ok(u) => u,
        Err(_) => return,
    };
    url.set_fragment(Some("/island"));
    let built = WebviewWindowBuilder::new(app, "island", WebviewUrl::External(url))
        .title("tenure 섬")
        .decorations(false)
        .transparent(true)
        .always_on_top(true)
        .skip_taskbar(true)
        .resizable(false)
        .shadow(false)
        .focused(false)
        .inner_size(380.0, 40.0)
        .build();
    if let Ok(win) = built {
        place_island(&win, "pill");
    }
}

fn toggle_island(app: &AppHandle) {
    if let Some(win) = app.get_webview_window("island") {
        let _ = win.show();
        let _ = win.eval("window.islandToggle && window.islandToggle()");
    }
}

// ---------------------------------------------------------------- 업데이트
/// 시작할 때 한 번: GitHub 릴리스의 latest.json 을 보고 새 버전이 있으면 묻는다. 오프라인·릴리스 없음은 조용히 넘어간다.
async fn check_update(app: AppHandle) {
    tokio_sleep(Duration::from_secs(5)).await;
    let Ok(updater) = app.updater() else { return };
    let Ok(Some(update)) = updater.check().await else { return };
    let question = format!("새 버전 {} 이 있습니다 (지금 {}).\n설치하고 다시 시작할까요?", update.version, update.current_version);
    let ok = app
        .dialog()
        .message(question)
        .title("tenure 업데이트")
        .kind(MessageDialogKind::Info)
        .buttons(MessageDialogButtons::OkCancelCustom("설치".into(), "나중에".into()))
        .blocking_show();
    if !ok {
        return;
    }
    if update.download_and_install(|_, _| {}, || {}).await.is_ok() {
        stop_engine(&app);
        app.restart();
    }
}

async fn tokio_sleep(d: Duration) {
    let _ = tauri::async_runtime::spawn_blocking(move || std::thread::sleep(d)).await;
}

fn stop_engine(app: &AppHandle) {
    if let Some(state) = app.try_state::<Engine>() {
        if let Some(mut child) = state.0.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

fn main() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            // 두 번째로 열면 새로 띄우지 않고 기존 창을 앞으로
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.show();
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state() == ShortcutState::Pressed {
                        toggle_island(app);
                    }
                })
                .build(),
        )
        .manage(Engine(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![island_mode, open_main])
        .setup(|app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || match spawn_engine(&handle) {
                Ok((child, url)) => {
                    handle.state::<Engine>().0.lock().unwrap().replace(child);
                    match (Url::parse(&url), handle.get_webview_window("main")) {
                        (Ok(u), Some(w)) => {
                            let _ = w.navigate(u);
                        }
                        _ => show_error(&handle, "엔진 주소가 잘못되었습니다."),
                    }
                    let h2 = handle.clone();
                    let _ = handle.run_on_main_thread(move || open_island(&h2, &url));
                }
                Err(e) => show_error(&handle, &e),
            });
            for key in ISLAND_SHORTCUTS {
                if app.global_shortcut().register(key).is_ok() {
                    break;
                }
            }
            tauri::async_runtime::spawn(check_update(app.handle().clone()));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tenure 앱을 시작하지 못했습니다");
    app.run(|handle, event| match event {
        // 메인 창을 닫으면 앱을 끝낸다(섬만 남지 않게)
        RunEvent::WindowEvent { label, event: tauri::WindowEvent::CloseRequested { .. }, .. } if label == "main" => {
            stop_engine(handle);
            handle.exit(0);
        }
        RunEvent::Exit => stop_engine(handle),
        _ => {}
    });
}
