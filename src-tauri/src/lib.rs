use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::process::CommandChild;
use tauri_plugin_shell::ShellExt;

struct Sidecars {
  children: Mutex<Vec<CommandChild>>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .manage(Sidecars {
      children: Mutex::new(Vec::new()),
    })
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      let shell = app.shell();
      let resource_dir = app
        .path()
        .resource_dir()
        .expect("failed to resolve resource dir");

      // Orchestrator (FastAPI/Python, PyInstaller onedir build), bundled
      // as a resource, not a Tauri "sidecar" — a onefile build works as a
      // sidecar but spawns its own child process on Windows, which
      // orphans itself if the outer process is killed before handoff
      // finishes. onedir avoids that split entirely, same as the engine.
      let orchestrator_dir = resource_dir.join("orchestrator");
      let orchestrator_exe = orchestrator_dir.join("orchestrator.exe");

      let (mut orchestrator_rx, orchestrator_child) = shell
        .command(orchestrator_exe.to_string_lossy().to_string())
        .current_dir(orchestrator_dir)
        .spawn()
        .expect("failed to spawn orchestrator");

      tauri::async_runtime::spawn(async move {
        while let Some(_event) = orchestrator_rx.recv().await {
          // Draining the channel keeps the child's stdout/stderr pipes
          // from filling up and blocking the process; we don't act on
          // individual lines here.
        }
      });

      // Engine (s2.exe), bundled as a resource next to the orchestrator,
      // not a "sidecar" in Tauri's sense since it needs its DLLs/model
      // file alongside it, not a single standalone binary.
      let engine_dir = resource_dir.join("engine");
      let engine_exe = engine_dir.join("s2.exe");

      let (mut engine_rx, engine_child) = shell
        .command(engine_exe.to_string_lossy().to_string())
        .current_dir(engine_dir)
        .args([
          "--server",
          "--host",
          "127.0.0.1",
          "--port",
          "3030",
          "-c",
          "0",
          "-m",
          "s2-pro-q8_0.gguf",
          "-t",
          "tokenizer.json",
          "--no-vram-swap",
        ])
        .spawn()
        .expect("failed to spawn engine");

      tauri::async_runtime::spawn(async move {
        while let Some(_event) = engine_rx.recv().await {
          // Same draining rationale as above.
        }
      });

      let state = app.state::<Sidecars>();
      state.children.lock().unwrap().push(orchestrator_child);
      state.children.lock().unwrap().push(engine_child);

      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building tauri application")
    .run(|app_handle, event| {
      if let tauri::RunEvent::ExitRequested { .. } = event {
        let state = app_handle.state::<Sidecars>();
        let mut children = state.children.lock().unwrap();
        for child in children.drain(..) {
          // child.kill() only signals the direct child. The orchestrator
          // sidecar (PyInstaller onefile) spawns its own child process on
          // Windows, which would otherwise survive and keep the port
          // held. Kill the whole process tree instead.
          let pid = child.pid().to_string();
          let _ = std::process::Command::new("taskkill")
            .args(["/PID", &pid, "/T", "/F"])
            .output();
        }
      }
    });
}
