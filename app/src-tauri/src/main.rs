// tenure 데스크톱 셸 (DESIGN.md 36.20).
// 창에는 먼저 앱에 든 시작 화면을 띄우고, 엔진(tenure-engine, 얼린 파이썬)을 켠 뒤 엔진이 주는 화면으로 옮긴다.
// 창을 닫으면 엔진도 끝낸다. 엔진은 --parent-pid 로 이 프로세스를 지켜보다가 셸이 죽어도 스스로 끝난다.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::time::Duration;

use tauri::{AppHandle, Manager, RunEvent, Url};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};
use tauri_plugin_updater::UpdaterExt;

#[cfg(windows)]
use std::os::windows::process::CommandExt;
#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

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
                let _ = w.unminimize();
                let _ = w.set_focus();
            }
        }))
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .manage(Engine(Mutex::new(None)))
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
                }
                Err(e) => show_error(&handle, &e),
            });
            tauri::async_runtime::spawn(check_update(app.handle().clone()));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("tenure 앱을 시작하지 못했습니다");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            stop_engine(handle);
        }
    });
}
