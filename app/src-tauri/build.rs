fn main() {
    // 섬 화면(엔진의 #/island)이 부르는 앱 명령. 권한은 capabilities/island.json 에서 섬 창에만 준다 (DESIGN.md 36.21)
    tauri_build::try_build(
        tauri_build::Attributes::new()
            .app_manifest(tauri_build::AppManifest::new().commands(&["island_mode", "open_main"])),
    )
    .expect("tauri 빌드 설정 실패");
}
