#![windows_subsystem = "windows"]

use pane_next_prototype::{
    devices::{DiscoveryError, UsbDevice, scan_present_apple_usb},
    scale,
    usbmux::{MuxError, MuxTransport, list_devices},
};
use std::{
    cell::{Cell, RefCell},
    io::Write,
    panic::AssertUnwindSafe,
    rc::Rc,
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
        mpsc::{self, Receiver, TryRecvError},
    },
};
use windows::{
    Win32::{
        Foundation::{COLORREF, HWND, LPARAM, LRESULT, RECT, WPARAM},
        Graphics::{
            Dwm::{DWMWA_USE_IMMERSIVE_DARK_MODE, DwmSetWindowAttribute},
            Gdi::*,
        },
        System::LibraryLoader::GetModuleHandleW,
        UI::{Controls::*, HiDpi::*, WindowsAndMessaging::*},
    },
    core::{PCWSTR, Result, w},
};

const ABOUT: i32 = 101;
const REFRESH: i32 = 102;
const TITLE: i32 = 201;
const PROTOTYPE: i32 = 202;
const CONNECTION: i32 = 203;
const SESSION: i32 = 204;
const STATUS: i32 = 205;
const DEVICES: i32 = 206;
const FOOTER: i32 = 207;
const DEVICE_LABEL: i32 = 208;
const SCAN_COMPLETE: u32 = WM_APP + 1;
const INITIAL_SCAN: u32 = WM_APP + 2;
const BACKGROUND: COLORREF = COLORREF(0x00202020);
const SURFACE: COLORREF = COLORREF(0x00292929);
const TEXT: COLORREF = COLORREF(0x00eeeeee);
const MUTED: COLORREF = COLORREF(0x00b8b8b8);
const BLUE: COLORREF = COLORREF(0x00cf6c25);

fn is_button_click(wparam: usize, button: i32) -> bool {
    wparam & 0xffff == button as usize && (wparam >> 16) & 0xffff == BN_CLICKED as usize
}

struct Font(HFONT);
impl Drop for Font {
    fn drop(&mut self) {
        unsafe {
            let _ = DeleteObject(self.0.into());
        }
    }
}

struct Brush(HBRUSH);
impl Brush {
    fn new(color: COLORREF) -> Result<Self> {
        let handle = unsafe { CreateSolidBrush(color) };
        if handle.is_invalid() {
            Err(windows::core::Error::from_thread())
        } else {
            Ok(Self(handle))
        }
    }
}
impl Drop for Brush {
    fn drop(&mut self) {
        unsafe {
            let _ = DeleteObject(self.0.into());
        }
    }
}

struct Fonts {
    title: Font,
    heading: Font,
    body: Font,
    caption: Font,
}
impl Fonts {
    fn new(dpi: u32) -> Result<Self> {
        unsafe {
            let mut metrics = NONCLIENTMETRICSW {
                cbSize: std::mem::size_of::<NONCLIENTMETRICSW>() as u32,
                ..Default::default()
            };
            SystemParametersInfoForDpi(
                SPI_GETNONCLIENTMETRICS.0,
                metrics.cbSize,
                Some((&mut metrics as *mut NONCLIENTMETRICSW).cast()),
                0,
                dpi,
            )?;
            let font = |size| -> Result<Font> {
                let mut spec = metrics.lfMessageFont;
                spec.lfHeight = -scale(size, dpi);
                let handle = CreateFontIndirectW(&spec);
                if handle.is_invalid() {
                    Err(windows::core::Error::from_thread())
                } else {
                    Ok(Font(handle))
                }
            };
            Ok(Self {
                title: font(28)?,
                heading: font(20)?,
                body: font(14)?,
                caption: font(12)?,
            })
        }
    }
}

struct UiState {
    fonts: RefCell<Rc<Fonts>>,
    background: Brush,
    surface: Brush,
    blue: Brush,
    pressed: Brush,
    scan: RefCell<Option<ScanJob>>,
    schedule: ScanSchedule,
    window_closed: Cell<bool>,
}
impl UiState {
    fn new(dpi: u32) -> Result<Self> {
        Ok(Self {
            fonts: RefCell::new(Rc::new(Fonts::new(dpi)?)),
            background: Brush::new(BACKGROUND)?,
            surface: Brush::new(SURFACE)?,
            blue: Brush::new(BLUE)?,
            pressed: Brush::new(COLORREF(0x00944d1b))?,
            scan: RefCell::new(None),
            schedule: ScanSchedule::default(),
            window_closed: Cell::new(false),
        })
    }
}

/// UI-thread-only coalescing. A burst retains one active and one pending scan.
#[derive(Default)]
struct ScanSchedule {
    active: Cell<bool>,
    pending: Cell<bool>,
}
impl ScanSchedule {
    fn request(&self) -> bool {
        if self.active.get() {
            self.pending.set(true);
            false
        } else {
            self.active.set(true);
            true
        }
    }
    fn complete(&self) -> bool {
        if !self.active.get() {
            return false;
        }
        if self.pending.replace(false) {
            true
        } else {
            self.active.set(false);
            false
        }
    }
    fn cancel(&self) {
        self.pending.set(false);
        self.active.set(false);
    }
}

enum ScanFailure {
    Unexpected,
}
struct WindowsUsbSummary {
    nodes: usize,
    ready_nodes: usize,
}
struct DiscoverySnapshot {
    windows: std::result::Result<WindowsUsbSummary, DiscoveryError>,
    // Strip opaque identifiers and routing IDs on the worker. Presentation
    // accepts transport facts only; identifiers never reach the UI queue.
    routes: std::result::Result<Vec<MuxTransport>, MuxError>,
}
type ScanResult = std::result::Result<DiscoverySnapshot, ScanFailure>;
struct ScanJob {
    receiver: Receiver<ScanResult>,
    cancelled: Arc<AtomicBool>,
}
impl Drop for ScanJob {
    fn drop(&mut self) {
        self.cancelled.store(true, Ordering::Release);
    }
}

/// Record only static event names and numeric codes, without panic payloads,
/// device names, serials, pairing material, or backend error text.
fn log_event(event: &'static str, code: Option<u32>) {
    let Some(base) = std::env::var_os("LOCALAPPDATA") else {
        return;
    };
    let directory = std::path::PathBuf::from(base)
        .join("Pane Next Prototype")
        .join("Logs");
    if std::fs::create_dir_all(&directory).is_err() {
        return;
    }
    let path = directory.join("prototype.log");
    if std::fs::metadata(&path).is_ok_and(|metadata| metadata.len() >= 65_536) {
        let previous = directory.join("prototype.previous.log");
        let _ = std::fs::remove_file(&previous);
        if std::fs::rename(&path, previous).is_err() {
            return;
        }
    }
    let seconds = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |value| value.as_secs());
    if let Ok(mut file) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
    {
        let _ = writeln!(file, "{seconds} {event} code={:08X}", code.unwrap_or(0));
    }
}

fn main() {
    std::panic::set_hook(Box::new(|_| log_event("unexpected_panic", None)));
    let result = std::panic::catch_unwind(AssertUnwindSafe(run));
    if !matches!(result, Ok(Ok(()))) {
        let code = match result {
            Ok(Err(error)) => Some(error.code().0 as u32),
            _ => None,
        };
        log_event("startup_or_message_loop_failed", code);
        unsafe {
            MessageBoxW(
                None,
                w!(
                    "The independent prototype could not start. Close it and try again. A local diagnostic code was recorded if the log folder is available."
                ),
                w!("Pane Next — Prototype"),
                MB_OK | MB_ICONERROR,
            );
        }
    }
}

fn run() -> Result<()> {
    unsafe {
        SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)?;
        let instance = GetModuleHandleW(None)?;
        let class = WNDCLASSW {
            hInstance: instance.into(),
            lpszClassName: w!("PaneNextIndependentPrototypeWindow"),
            lpfnWndProc: Some(window_proc),
            hCursor: LoadCursorW(None, IDC_ARROW)?,
            ..Default::default()
        };
        if RegisterClassW(&class) == 0 {
            return Err(windows::core::Error::from_thread());
        }
        let dpi = GetDpiForSystem();
        let mut work = RECT::default();
        SystemParametersInfoW(
            SPI_GETWORKAREA,
            0,
            Some((&mut work as *mut RECT).cast()),
            SYSTEM_PARAMETERS_INFO_UPDATE_FLAGS(0),
        )?;
        let width = scale(920, dpi).min(work.right - work.left);
        let height = scale(680, dpi).min(work.bottom - work.top);
        let hwnd = CreateWindowExW(
            WINDOW_EX_STYLE::default(),
            class.lpszClassName,
            w!("Pane Next — Prototype"),
            WS_OVERLAPPEDWINDOW | WS_CLIPCHILDREN,
            work.left + (work.right - work.left - width) / 2,
            work.top + (work.bottom - work.top - height) / 2,
            width,
            height,
            None,
            None,
            Some(instance.into()),
            None,
        )?;
        // Best effort: older Windows versions may not expose this attribute.
        // Keep the native frame usable when the request is unsupported.
        let honor_dark_mode: i32 = 1; // BOOL, as required by the DWM attribute.
        let _ = DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            (&honor_dark_mode as *const i32).cast(),
            std::mem::size_of::<i32>() as u32,
        );
        let _ = ShowWindow(hwnd, SW_SHOW);
        let mut message = MSG::default();
        loop {
            let status = GetMessageW(&mut message, None, 0, 0).0;
            if status == -1 {
                return Err(windows::core::Error::from_thread());
            }
            if status == 0 {
                break;
            }
            if !IsDialogMessageW(hwnd, &message).as_bool() {
                let _ = TranslateMessage(&message);
                DispatchMessageW(&message);
            }
        }
    }
    Ok(())
}

unsafe fn clone_raw_owner<T>(pointer: *const T) -> Option<Rc<T>> {
    if pointer.is_null() {
        return None;
    }
    // The caller guarantees a live Rc::into_raw token on this same thread.
    // Increment before reconstructing, so the token retains its own ownership.
    unsafe {
        Rc::increment_strong_count(pointer);
        Some(Rc::from_raw(pointer))
    }
}

unsafe fn state(hwnd: HWND) -> Option<Rc<UiState>> {
    // UI thread only. No callback/pumping operation occurs between retrieving
    // the window token and retaining it. Each caller owns a short-lived clone,
    // so reentrant WM_NCDESTROY cannot free resources under that caller.
    unsafe { clone_raw_owner(GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const UiState) }
}

unsafe extern "system" fn window_proc(hwnd: HWND, message: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    match std::panic::catch_unwind(AssertUnwindSafe(|| unsafe {
        handle_message(hwnd, message, wp, lp)
    })) {
        Ok(result) => result,
        Err(_) => unsafe {
            if message == WM_CREATE {
                return LRESULT(-1);
            }
            set_status(
                hwnd,
                "An unexpected error occurred. Close the prototype and reopen it.",
            );
            DefWindowProcW(hwnd, message, wp, lp)
        },
    }
}

unsafe fn handle_message(hwnd: HWND, message: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    unsafe {
        match message {
            WM_CREATE => {
                if let Err(error) = initialize_window(hwnd) {
                    log_event("window_initialization_failed", Some(error.code().0 as u32));
                    return LRESULT(-1);
                }
                LRESULT(0)
            }
            WM_SIZE => {
                layout_controls(hwnd);
                let _ = InvalidateRect(Some(hwnd), None, false);
                LRESULT(0)
            }
            WM_DPICHANGED => {
                if let Err(error) = update_fonts(hwnd) {
                    log_event("dpi_font_update_failed", Some(error.code().0 as u32));
                    set_status(
                        hwnd,
                        "Windows could not update the display font. Reopen the prototype.",
                    );
                }
                let suggested = &*(lp.0 as *const RECT);
                let _ = SetWindowPos(
                    hwnd,
                    None,
                    suggested.left,
                    suggested.top,
                    suggested.right - suggested.left,
                    suggested.bottom - suggested.top,
                    SWP_NOZORDER | SWP_NOACTIVATE,
                );
                layout_controls(hwnd);
                let _ = InvalidateRect(Some(hwnd), None, false);
                LRESULT(0)
            }
            WM_SETTINGCHANGE => {
                if let Err(error) = update_fonts(hwnd) {
                    log_event("system_font_update_failed", Some(error.code().0 as u32));
                }
                LRESULT(0)
            }
            WM_GETMINMAXINFO => {
                let info = &mut *(lp.0 as *mut MINMAXINFO);
                let dpi = GetDpiForWindow(hwnd).max(96);
                info.ptMinTrackSize.x = scale(620, dpi);
                info.ptMinTrackSize.y = scale(500, dpi);
                LRESULT(0)
            }
            WM_ERASEBKGND => LRESULT(1),
            WM_PAINT => {
                paint(hwnd);
                LRESULT(0)
            }
            WM_CTLCOLORSTATIC | WM_CTLCOLORLISTBOX => {
                if let Some(state) = state(hwnd) {
                    let dc = HDC(wp.0 as *mut _);
                    let id = GetDlgCtrlID(HWND(lp.0 as *mut _));
                    let panel =
                        matches!(id, CONNECTION | SESSION | STATUS | DEVICE_LABEL | DEVICES);
                    SetTextColor(
                        dc,
                        if matches!(id, TITLE | CONNECTION | DEVICES) {
                            TEXT
                        } else {
                            MUTED
                        },
                    );
                    SetBkColor(dc, if panel { SURFACE } else { BACKGROUND });
                    return LRESULT(if panel {
                        state.surface.0.0 as isize
                    } else {
                        state.background.0.0 as isize
                    });
                }
                DefWindowProcW(hwnd, message, wp, lp)
            }
            WM_DRAWITEM if wp.0 == ABOUT as usize || wp.0 == REFRESH as usize => {
                let item = &*(lp.0 as *const DRAWITEMSTRUCT);
                if let Some(state) = state(hwnd) {
                    let brush = if item.itemState.0 & ODS_SELECTED.0 != 0 {
                        &state.pressed
                    } else if wp.0 == REFRESH as usize {
                        &state.blue
                    } else {
                        &state.surface
                    };
                    FillRect(item.hDC, &item.rcItem, brush.0);
                    let fonts = state.fonts.borrow().clone();
                    let value = if wp.0 == REFRESH as usize {
                        "Refresh devices"
                    } else {
                        "About this prototype"
                    };
                    draw_text(
                        item.hDC,
                        item.rcItem,
                        value,
                        fonts.body.0,
                        TEXT,
                        DT_CENTER | DT_VCENTER | DT_SINGLELINE,
                    );
                    if item.itemState.0 & ODS_FOCUS.0 != 0 {
                        let inset = scale(4, GetDpiForWindow(hwnd).max(96));
                        let mut focus = item.rcItem;
                        focus.left += inset;
                        focus.top += inset;
                        focus.right -= inset;
                        focus.bottom -= inset;
                        let _ = DrawFocusRect(item.hDC, &focus);
                    }
                }
                LRESULT(1)
            }
            WM_COMMAND if is_button_click(wp.0, ABOUT) => {
                MessageBoxW(
                    Some(hwnd),
                    w!(
                        "Independent prototype\n\nPhone connection not implemented. No phone session is active.\n\nThis native Windows shell does not pair, mirror, sign, install, send input, or check for updates.\n\nLocal diagnostics use a separate Pane Next Prototype folder and contain only event names and numeric codes.\n\nUnreleased. License and provenance review pending."
                    ),
                    w!("About Pane Next"),
                    MB_OK | MB_ICONINFORMATION,
                );
                LRESULT(0)
            }
            WM_COMMAND if is_button_click(wp.0, REFRESH) => {
                refresh_devices(hwnd);
                LRESULT(0)
            }
            SCAN_COMPLETE => {
                complete_scan(hwnd);
                LRESULT(0)
            }
            INITIAL_SCAN => {
                refresh_devices(hwnd);
                LRESULT(0)
            }
            WM_DEVICECHANGE if wp.0 == DBT_DEVNODES_CHANGED as usize => {
                refresh_devices(hwnd);
                LRESULT(1)
            }
            WM_DESTROY => {
                PostQuitMessage(0);
                LRESULT(0)
            }
            WM_NCDESTROY => {
                let pointer = GetWindowLongPtrW(hwnd, GWLP_USERDATA) as *const UiState;
                SetWindowLongPtrW(hwnd, GWLP_USERDATA, 0);
                if !pointer.is_null() {
                    let owner = Rc::from_raw(pointer);
                    owner.window_closed.set(true);
                    owner.schedule.cancel();
                    // Cancel immediately, even if a reentrant caller still has
                    // a resource-lifetime clone of UiState.
                    owner.scan.take();
                    drop(owner);
                }
                DefWindowProcW(hwnd, message, wp, lp)
            }
            _ => DefWindowProcW(hwnd, message, wp, lp),
        }
    }
}

unsafe fn initialize_window(hwnd: HWND) -> Result<()> {
    unsafe {
        let resources = Rc::new(UiState::new(GetDpiForWindow(hwnd).max(96))?);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, Rc::into_raw(resources) as isize);
        for (id, value) in [
            (TITLE, "Pane Next"),
            (PROTOTYPE, "Independent prototype"),
            (CONNECTION, "Phone connection not implemented"),
            (
                SESSION,
                "No phone session is active. Device presence does not mean a connection.",
            ),
            (
                STATUS,
                "Preparing automatic device discovery… No phone session is active.",
            ),
        ] {
            // Zero selects the documented default SS_LEFT static-control style.
            create_control(hwnd, id, w!("STATIC"), value, WINDOW_STYLE(0))?;
        }
        // The native accessibility proxy uses the preceding STATIC as the
        // list's label; keep this directly before the list in creation order.
        create_control(
            hwnd,
            DEVICE_LABEL,
            w!("STATIC"),
            "Available devices",
            WINDOW_STYLE(0),
        )?;
        create_control(
            hwnd,
            DEVICES,
            w!("LISTBOX"),
            "Available devices",
            WS_TABSTOP | WS_VSCROLL | WINDOW_STYLE(LBS_NOINTEGRALHEIGHT as u32),
        )?;
        create_control(
            hwnd,
            REFRESH,
            w!("BUTTON"),
            "Refresh devices",
            WS_TABSTOP | WINDOW_STYLE(BS_OWNERDRAW as u32),
        )?;
        create_control(
            hwnd,
            ABOUT,
            w!("BUTTON"),
            "About this prototype",
            WS_TABSTOP | WINDOW_STYLE(BS_OWNERDRAW as u32),
        )?;
        create_control(
            hwnd,
            FOOTER,
            w!("STATIC"),
            "Unreleased · license review pending",
            WINDOW_STYLE(0),
        )?;
        apply_fonts(hwnd);
        layout_controls(hwnd);
        set_device_lines(hwnd, &["Waiting for the initial device snapshot."]);
        if PostMessageW(Some(hwnd), INITIAL_SCAN, WPARAM(0), LPARAM(0)).is_err() {
            refresh_devices(hwnd);
        }
        Ok(())
    }
}

unsafe fn create_control(
    hwnd: HWND,
    id: i32,
    class: PCWSTR,
    name: &str,
    style: WINDOW_STYLE,
) -> Result<HWND> {
    let wide: Vec<u16> = name.encode_utf16().chain(Some(0)).collect();
    unsafe {
        CreateWindowExW(
            WINDOW_EX_STYLE::default(),
            class,
            PCWSTR(wide.as_ptr()),
            WS_CHILD | WS_VISIBLE | style,
            0,
            0,
            0,
            0,
            Some(hwnd),
            Some(HMENU(id as usize as *mut _)),
            None,
            None,
        )
    }
}

unsafe fn update_fonts(hwnd: HWND) -> Result<()> {
    unsafe {
        if let Some(state) = state(hwnd) {
            let previous = state
                .fonts
                .replace(Rc::new(Fonts::new(GetDpiForWindow(hwnd).max(96))?));
            apply_fonts(hwnd);
            drop(previous);
        }
    }
    Ok(())
}

unsafe fn apply_fonts(hwnd: HWND) {
    unsafe {
        if let Some(state) = state(hwnd) {
            // Keep this font generation alive, without holding a RefCell borrow:
            // child messages may reenter, change DPI, or destroy the window.
            let fonts = state.fonts.borrow().clone();
            for id in [
                TITLE,
                PROTOTYPE,
                CONNECTION,
                SESSION,
                STATUS,
                DEVICE_LABEL,
                DEVICES,
                FOOTER,
                REFRESH,
                ABOUT,
            ] {
                let font = match id {
                    TITLE => fonts.title.0,
                    CONNECTION => fonts.heading.0,
                    FOOTER => fonts.caption.0,
                    _ => fonts.body.0,
                };
                if let Ok(control) = GetDlgItem(Some(hwnd), id) {
                    SendMessageW(
                        control,
                        WM_SETFONT,
                        Some(WPARAM(font.0 as usize)),
                        Some(LPARAM(1)),
                    );
                }
            }
        }
    }
}

unsafe fn layout_controls(hwnd: HWND) {
    unsafe {
        let mut client = RECT::default();
        if GetClientRect(hwnd, &mut client).is_err() {
            return;
        }
        let dpi = GetDpiForWindow(hwnd).max(96);
        let s = |value| scale(value, dpi);
        let width = client.right;
        let height = client.bottom;
        let place = |id: i32, left: i32, top: i32, right: i32, bottom: i32| {
            if let Ok(control) = GetDlgItem(Some(hwnd), id) {
                let _ = SetWindowPos(
                    control,
                    None,
                    left,
                    top,
                    (right - left).max(0),
                    (bottom - top).max(0),
                    SWP_NOZORDER | SWP_NOACTIVATE,
                );
            }
        };
        place(TITLE, s(28), s(22), width - s(28), s(62));
        place(PROTOTYPE, s(28), s(70), width - s(28), s(96));
        place(CONNECTION, s(48), s(134), width - s(48), s(188));
        place(SESSION, s(48), s(194), width - s(48), s(234));
        place(STATUS, s(48), s(242), width - s(48), s(284));
        place(DEVICE_LABEL, s(48), s(286), width - s(48), s(308));
        place(
            DEVICES,
            s(48),
            s(316),
            width - s(48),
            (height - s(112)).max(s(340)),
        );
        place(REFRESH, s(28), height - s(76), s(208), height - s(36));
        place(ABOUT, s(224), height - s(76), s(434), height - s(36));
        place(
            FOOTER,
            s(454),
            height - s(72),
            width - s(28),
            height - s(30),
        );
    }
}

unsafe fn set_status(hwnd: HWND, value: &str) {
    unsafe {
        if let Ok(control) = GetDlgItem(Some(hwnd), STATUS) {
            let wide: Vec<u16> = value.encode_utf16().chain(Some(0)).collect();
            let _ = SetWindowTextW(control, PCWSTR(wide.as_ptr()));
        }
    }
}

unsafe fn set_device_lines(hwnd: HWND, values: &[&str]) {
    unsafe {
        if let Ok(control) = GetDlgItem(Some(hwnd), DEVICES) {
            SendMessageW(control, LB_RESETCONTENT, None, None);
            for value in values {
                let wide: Vec<u16> = value.encode_utf16().chain(Some(0)).collect();
                SendMessageW(
                    control,
                    LB_ADDSTRING,
                    None,
                    Some(LPARAM(wide.as_ptr() as isize)),
                );
            }
        }
    }
}

unsafe fn refresh_devices(hwnd: HWND) {
    unsafe {
        // Also drain here if Windows could not enqueue the completion message.
        complete_scan(hwnd);
        let Some(state) = state(hwnd) else {
            return;
        };
        if state.window_closed.get() || !state.schedule.request() {
            return;
        }
        start_scan(hwnd, &state);
    }
}

unsafe fn start_scan(hwnd: HWND, state: &Rc<UiState>) {
    unsafe {
        if state.window_closed.get() {
            state.schedule.cancel();
            return;
        }
        set_status(
            hwnd,
            "Checking Windows and the local Apple service… No phone session is active.",
        );
        if state.window_closed.get() {
            state.schedule.cancel();
            return;
        }
        let (sender, receiver) = mpsc::channel();
        let cancelled = Arc::new(AtomicBool::new(false));
        state.scan.replace(Some(ScanJob {
            receiver,
            cancelled: cancelled.clone(),
        }));
        let window_token = hwnd.0 as usize;
        let spawned = std::thread::Builder::new()
            .name("pane-next-device-snapshot".into())
            .spawn(move || {
                if cancelled.load(Ordering::Acquire) {
                    return;
                }
                let result = match std::panic::catch_unwind(|| {
                    let windows = scan_present_apple_usb().map(|nodes| windows_summary(&nodes));
                    if cancelled.load(Ordering::Acquire) {
                        return None;
                    }
                    let routes = list_devices().map(|records| {
                        records.into_iter().map(|record| record.transport).collect()
                    });
                    Some(DiscoverySnapshot { windows, routes })
                }) {
                    Ok(Some(snapshot)) => Ok(snapshot),
                    Ok(None) => return,
                    Err(_) => Err(ScanFailure::Unexpected),
                };
                if cancelled.load(Ordering::Acquire) {
                    return;
                }
                if sender.send(result).is_ok() && !cancelled.load(Ordering::Acquire) {
                    // Only a notification crosses the Win32 queue. The receiver
                    // owns the result, so closing the window cannot leak a Box.
                    if let Err(error) = PostMessageW(
                        Some(HWND(window_token as *mut _)),
                        SCAN_COMPLETE,
                        WPARAM(0),
                        LPARAM(0),
                    ) {
                        log_event("scan_notification_failed", Some(error.code().0 as u32));
                    }
                }
            });
        if let Err(error) = spawned {
            state.scan.take();
            state.schedule.cancel();
            log_event(
                "scan_thread_start_failed",
                error.raw_os_error().map(|code| code as u32),
            );
            set_status(
                hwnd,
                "Windows could not start the device check. Try Refresh devices again.",
            );
        }
    }
}

unsafe fn complete_scan(hwnd: HWND) {
    unsafe {
        let Some(state) = state(hwnd) else {
            return;
        };
        let received = {
            let job = state.scan.borrow();
            let Some(job) = job.as_ref() else {
                return;
            };
            match job.receiver.try_recv() {
                Ok(result) => result,
                Err(TryRecvError::Empty) => return,
                Err(TryRecvError::Disconnected) => Err(ScanFailure::Unexpected),
            }
        };
        state.scan.take();
        match received {
            Ok(snapshot) => {
                log_snapshot_errors(&snapshot);
                let (status, lines) = device_snapshot_text(&snapshot);
                let values: Vec<&str> = lines.iter().map(String::as_str).collect();
                set_device_lines(hwnd, &values);
                set_status(hwnd, &status);
            }
            Err(ScanFailure::Unexpected) => {
                log_event("device_snapshot_unexpected_error", None);
                set_device_lines(
                    hwnd,
                    &["Device snapshot unavailable. Previous results were cleared."],
                );
                set_status(
                    hwnd,
                    "Device check failed. Open Apple Devices, then refresh. No phone session is active.",
                );
            }
        }
        if !state.window_closed.get() && state.schedule.complete() {
            start_scan(hwnd, &state);
        }
    }
}

fn windows_summary(nodes: &[UsbDevice]) -> WindowsUsbSummary {
    WindowsUsbSummary {
        nodes: nodes.len(),
        ready_nodes: nodes.iter().filter(|node| node.driver_ready).count(),
    }
}

fn log_snapshot_errors(snapshot: &DiscoverySnapshot) {
    if let Err(error) = &snapshot.windows {
        match error {
            DiscoveryError::Windows { code, .. } => {
                log_event("usb_snapshot_windows_error", Some(*code as u32))
            }
            _ => log_event("usb_snapshot_validation_failed", None),
        }
    }
    if let Err(error) = &snapshot.routes {
        match error {
            MuxError::Io { code, .. } => log_event("apple_list_io_error", Some(*code as u32)),
            MuxError::Timeout(_) => log_event("apple_list_timeout", None),
            _ => log_event("apple_list_unavailable", None),
        }
    }
}

fn windows_diagnostic(summary: &std::result::Result<WindowsUsbSummary, DiscoveryError>) -> String {
    match summary {
        Ok(summary) => format!(
            "Windows USB diagnostic: {} node(s); {} mobile driver ready.",
            summary.nodes, summary.ready_nodes
        ),
        Err(_) => "Windows USB diagnostic unavailable.".into(),
    }
}

fn transport_label(transport: MuxTransport) -> &'static str {
    match transport {
        MuxTransport::Usb => "Apple mobile device · USB · pairing not checked",
        MuxTransport::Network => "Apple mobile device · Wi-Fi · pairing not checked",
    }
}

fn device_snapshot_text(snapshot: &DiscoverySnapshot) -> (String, Vec<String>) {
    match &snapshot.routes {
        Ok(routes) if !routes.is_empty() => (
            format!("Found {} Apple service record(s). Pairing not checked; no phone session is active.", routes.len()),
            routes.iter().map(|transport| transport_label(*transport).into()).collect(),
        ),
        Ok(_) => (
            "No service records found. Open Apple Devices, then refresh. No phone session is active.".into(),
            vec!["No USB or Wi-Fi routing records in this snapshot.".into(), windows_diagnostic(&snapshot.windows)],
        ),
        Err(_) => (
            "Apple list unavailable. Open Apple Devices, then refresh. No phone session is active.".into(),
            vec!["Local Apple service unavailable. Pairing not checked.".into(), windows_diagnostic(&snapshot.windows)],
        ),
    }
}

unsafe fn paint(hwnd: HWND) {
    unsafe {
        let mut ps = PAINTSTRUCT::default();
        let dc = BeginPaint(hwnd, &mut ps);
        if let Some(state) = state(hwnd) {
            let mut client = RECT::default();
            let _ = GetClientRect(hwnd, &mut client);
            let dpi = GetDpiForWindow(hwnd).max(96);
            FillRect(dc, &client, state.background.0);
            let panel = RECT {
                left: scale(28, dpi),
                top: scale(114, dpi),
                right: client.right - scale(28, dpi),
                bottom: client.bottom - scale(98, dpi),
            };
            FillRect(dc, &panel, state.surface.0);
        }
        let _ = EndPaint(hwnd, &ps);
    }
}

unsafe fn draw_text(
    dc: HDC,
    mut rect: RECT,
    value: &str,
    font: HFONT,
    color: COLORREF,
    format: DRAW_TEXT_FORMAT,
) {
    unsafe {
        let old = SelectObject(dc, font.into());
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, color);
        let mut utf16: Vec<u16> = value.encode_utf16().collect();
        DrawTextW(dc, &mut utf16, &mut rect, format | DT_NOPREFIX);
        SelectObject(dc, old);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn button_actions_accept_only_clicked_notification_for_their_id() {
        assert!(is_button_click(REFRESH as usize, REFRESH));
        assert!(is_button_click(ABOUT as usize, ABOUT));
        assert!(!is_button_click(ABOUT as usize, REFRESH));
        for notification in [BN_SETFOCUS, BN_KILLFOCUS, BN_PAINT, BN_DOUBLECLICKED] {
            assert!(!is_button_click(
                REFRESH as usize | ((notification as usize) << 16),
                REFRESH
            ));
        }
    }

    #[test]
    fn device_status_never_exposes_instance_ids_or_claims_a_phone_session() {
        let nodes = vec![UsbDevice {
            display_name: "Apple Mobile Device (USB)".into(),
            instance_id: "USB\\PRIVATE-SERIAL-123".into(),
            driver_ready: true,
        }];
        let snapshot = DiscoverySnapshot {
            windows: Ok(windows_summary(&nodes)),
            routes: Ok(vec![MuxTransport::Usb]),
        };
        let (status, lines) = device_snapshot_text(&snapshot);
        assert!(status.contains("no phone session is active"));
        assert!(lines[0].contains("pairing not checked"));
        assert!(!status.contains("PRIVATE-SERIAL"));
        assert!(!lines.join(" ").contains("PRIVATE-SERIAL"));
    }

    #[test]
    fn empty_apple_snapshot_keeps_windows_diagnostic_separate() {
        let snapshot = DiscoverySnapshot {
            windows: Ok(WindowsUsbSummary {
                nodes: 3,
                ready_nodes: 3,
            }),
            routes: Ok(Vec::new()),
        };
        let (status, lines) = device_snapshot_text(&snapshot);
        assert!(status.contains("No service records found"));
        assert!(lines[1].contains("3 node(s)"));
        assert!(!lines[0].is_empty());
    }

    #[test]
    fn routing_records_replace_composite_windows_nodes_in_the_device_list() {
        let snapshot = DiscoverySnapshot {
            windows: Ok(WindowsUsbSummary {
                nodes: 3,
                ready_nodes: 3,
            }),
            routes: Ok(vec![MuxTransport::Usb, MuxTransport::Network]),
        };
        let (status, lines) = device_snapshot_text(&snapshot);
        assert!(status.contains("Found 2 Apple service record(s)"));
        assert_eq!(
            lines,
            [
                "Apple mobile device · USB · pairing not checked",
                "Apple mobile device · Wi-Fi · pairing not checked"
            ]
        );
        // The helper accepts transport enums only, so neither private mux
        // identifiers nor routing IDs can be incorporated into these labels.
        assert!(!lines.join(" ").contains("node(s)"));
    }

    #[test]
    fn local_apple_error_offers_action_and_only_windows_diagnostics() {
        let snapshot = DiscoverySnapshot {
            windows: Ok(WindowsUsbSummary {
                nodes: 3,
                ready_nodes: 2,
            }),
            routes: Err(MuxError::AppleRejected),
        };
        let (status, lines) = device_snapshot_text(&snapshot);
        assert!(status.contains("Open Apple Devices, then refresh."));
        assert!(status.contains("No phone session is active."));
        assert!(lines[1].contains("3 node(s); 2 mobile driver ready"));
        assert!(!status.contains("AppleRejected"));
    }

    #[test]
    fn callback_owner_survives_reentrant_window_owner_release() {
        struct DropProbe(Rc<Cell<u32>>);
        impl Drop for DropProbe {
            fn drop(&mut self) {
                self.0.set(self.0.get() + 1);
            }
        }
        let drops = Rc::new(Cell::new(0));
        let token = Rc::into_raw(Rc::new(DropProbe(drops.clone())));
        let callback = unsafe { clone_raw_owner(token) }.unwrap();
        // Models WM_NCDESTROY releasing the raw window token mid-callback.
        unsafe {
            drop(Rc::from_raw(token));
        }
        assert_eq!(drops.get(), 0);
        drop(callback);
        assert_eq!(drops.get(), 1);
    }

    #[test]
    fn closing_scan_job_cancels_delivery_and_releases_its_receiver() {
        let (sender, receiver) = mpsc::channel();
        let cancelled = Arc::new(AtomicBool::new(false));
        let job = ScanJob {
            receiver,
            cancelled: cancelled.clone(),
        };
        drop(job);
        assert!(cancelled.load(Ordering::Acquire));
        assert!(sender.send(Err(ScanFailure::Unexpected)).is_err());
    }

    #[test]
    fn device_change_burst_coalesces_to_one_pending_rescan() {
        let schedule = ScanSchedule::default();
        assert!(schedule.request());
        for _ in 0..10_000 {
            assert!(!schedule.request());
        }
        assert!(schedule.complete()); // One queued rescan starts.
        assert!(!schedule.complete()); // No further work remains.
        assert!(!schedule.complete());
        assert!(schedule.request()); // A later real event starts a new snapshot.
    }

    #[test]
    fn cancellation_discards_pending_automatic_rescan() {
        let schedule = ScanSchedule::default();
        assert!(schedule.request());
        assert!(!schedule.request());
        schedule.cancel();
        assert!(!schedule.complete());
        assert!(!schedule.active.get());
        assert!(!schedule.pending.get());
    }
}
