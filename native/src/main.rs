#![cfg_attr(windows, windows_subsystem = "windows")]
#[cfg(windows)]
mod windows;
fn main() {
    #[cfg(windows)]
    if let Err(e) = windows::run() {
        eprintln!("Pane companion: {e}");
        std::process::exit(1);
    }
    #[cfg(not(windows))]
    println!(
        "{}",
        serde_json::json!({"audio":[],"notifications":[],"error":"Bluetooth integration requires Windows 10 2004 or later."})
    );
}
