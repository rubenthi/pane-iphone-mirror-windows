#![windows_subsystem = "windows"]

use pane_next_prototype::scale;
use windows::{
    Win32::{
        Foundation::{COLORREF, HWND, LPARAM, LRESULT, RECT, WPARAM},
        Graphics::Gdi::*,
        System::LibraryLoader::GetModuleHandleW,
        UI::{Controls::*, HiDpi::*, WindowsAndMessaging::*},
    },
    core::{Result, w},
};

const ABOUT: i32 = 101;
const BACKGROUND: COLORREF = COLORREF(0x00202020);
const SURFACE: COLORREF = COLORREF(0x00292929);
const TEXT: COLORREF = COLORREF(0x00eeeeee);
const MUTED: COLORREF = COLORREF(0x00b8b8b8);
const BLUE: COLORREF = COLORREF(0x00cf6c25);

fn main() {
    if let Err(error) = run() {
        let message: Vec<u16> = format!("The independent prototype could not start.\n{error}\0")
            .encode_utf16()
            .collect();
        unsafe {
            MessageBoxW(
                None,
                windows::core::PCWSTR(message.as_ptr()),
                w!("Pane Next — Prototype"),
                MB_OK | MB_ICONERROR,
            );
        }
    }
}

fn run() -> Result<()> {
    unsafe {
        // Set before creating any window; drawing and fonts use current window DPI.
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
            WS_OVERLAPPEDWINDOW,
            work.left + (work.right - work.left - width) / 2,
            work.top + (work.bottom - work.top - height) / 2,
            width,
            height,
            None,
            None,
            Some(instance.into()),
            None,
        )?;
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

unsafe extern "system" fn window_proc(hwnd: HWND, message: u32, wp: WPARAM, lp: LPARAM) -> LRESULT {
    // Windows invokes this callback on the window thread. HWND/GDI handles are
    // only used within their documented message or paint lifetimes.
    unsafe {
        match message {
            WM_CREATE => {
                if CreateWindowExW(
                    WINDOW_EX_STYLE::default(),
                    w!("BUTTON"),
                    w!("About this prototype"),
                    WS_CHILD | WS_VISIBLE | WS_TABSTOP | WINDOW_STYLE(BS_OWNERDRAW as u32),
                    0,
                    0,
                    0,
                    0,
                    Some(hwnd),
                    Some(HMENU(ABOUT as usize as *mut _)),
                    None,
                    None,
                )
                .is_err()
                {
                    return LRESULT(-1);
                }
                LRESULT(0)
            }
            WM_SIZE => {
                layout_button(hwnd);
                let _ = InvalidateRect(Some(hwnd), None, false);
                LRESULT(0)
            }
            WM_DPICHANGED => {
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
                layout_button(hwnd);
                let _ = InvalidateRect(Some(hwnd), None, false);
                LRESULT(0)
            }
            WM_GETMINMAXINFO => {
                let info = &mut *(lp.0 as *mut MINMAXINFO);
                let dpi = GetDpiForWindow(hwnd).max(96);
                info.ptMinTrackSize.x = scale(620, dpi);
                info.ptMinTrackSize.y = scale(440, dpi);
                LRESULT(0)
            }
            WM_ERASEBKGND => LRESULT(1),
            WM_PAINT => {
                paint(hwnd);
                LRESULT(0)
            }
            WM_DRAWITEM if wp.0 == ABOUT as usize => {
                let item = &*(lp.0 as *const DRAWITEMSTRUCT);
                fill(
                    item.hDC,
                    item.rcItem,
                    if item.itemState.0 & ODS_SELECTED.0 != 0 {
                        COLORREF(0x00944d1b)
                    } else {
                        BLUE
                    },
                );
                let dpi = GetDpiForWindow(hwnd).max(96);
                text(
                    item.hDC,
                    item.rcItem,
                    "About this prototype",
                    14,
                    TEXT,
                    dpi,
                    DT_CENTER | DT_VCENTER | DT_SINGLELINE,
                );
                if item.itemState.0 & ODS_FOCUS.0 != 0 {
                    let mut focus = item.rcItem;
                    let inset = scale(4, dpi);
                    focus.left += inset;
                    focus.top += inset;
                    focus.right -= inset;
                    focus.bottom -= inset;
                    let _ = DrawFocusRect(item.hDC, &focus);
                }
                LRESULT(1)
            }
            WM_COMMAND if wp.0 & 0xffff == ABOUT as usize => {
                MessageBoxW(
                    Some(hwnd),
                    w!(
                        "Independent prototype\n\nPhone connection not implemented.\n\nThis is a new native Windows shell and bounded frame-mailbox foundation. It does not mirror a phone, pair a device, install software, read existing Pane data, or check for updates.\n\nUnreleased. License and dependency provenance review pending."
                    ),
                    w!("About Pane Next"),
                    MB_OK | MB_ICONINFORMATION,
                );
                LRESULT(0)
            }
            WM_DESTROY => {
                PostQuitMessage(0);
                LRESULT(0)
            }
            _ => DefWindowProcW(hwnd, message, wp, lp),
        }
    }
}

unsafe fn layout_button(hwnd: HWND) {
    unsafe {
        let mut client = RECT::default();
        let _ = GetClientRect(hwnd, &mut client);
        let dpi = GetDpiForWindow(hwnd).max(96);
        if let Ok(button) = GetDlgItem(Some(hwnd), ABOUT) {
            let _ = SetWindowPos(
                button,
                None,
                scale(28, dpi),
                client.bottom - scale(70, dpi),
                scale(210, dpi),
                scale(40, dpi),
                SWP_NOZORDER | SWP_NOACTIVATE,
            );
        }
    }
}

unsafe fn paint(hwnd: HWND) {
    unsafe {
        let mut ps = PAINTSTRUCT::default();
        let dc = BeginPaint(hwnd, &mut ps);
        let mut client = RECT::default();
        let _ = GetClientRect(hwnd, &mut client);
        let dpi = GetDpiForWindow(hwnd).max(96);
        let s = |n| scale(n, dpi);
        fill(dc, client, BACKGROUND);
        let area = |l, t, r, b| RECT {
            left: s(l),
            top: s(t),
            right: r,
            bottom: b,
        };
        text(
            dc,
            area(28, 22, client.right - s(28), s(62)),
            "Pane Next",
            28,
            TEXT,
            dpi,
            DT_LEFT | DT_SINGLELINE,
        );
        text(
            dc,
            area(28, 70, client.right - s(28), s(100)),
            "Independent prototype",
            14,
            MUTED,
            dpi,
            DT_LEFT | DT_SINGLELINE,
        );
        let panel = RECT {
            left: s(28),
            top: s(118),
            right: client.right - s(28),
            bottom: client.bottom - s(96),
        };
        fill(dc, panel, SURFACE);
        let inner = panel.left + s(24);
        let heading = RECT {
            left: inner,
            top: panel.top + s(24),
            right: panel.right - s(24),
            bottom: panel.top + s(70),
        };
        text(
            dc,
            heading,
            "Phone connection not implemented",
            20,
            TEXT,
            dpi,
            DT_LEFT | DT_WORDBREAK,
        );
        text(
            dc,
            RECT {
                top: panel.top + s(92),
                bottom: panel.top + s(152),
                ..heading
            },
            "A native Windows foundation, built independently.",
            15,
            MUTED,
            dpi,
            DT_LEFT | DT_WORDBREAK,
        );
        text(
            dc,
            RECT {
                top: panel.top + s(160),
                bottom: panel.bottom - s(18),
                ..heading
            },
            "No phone session is active. This prototype has no pairing, mirroring, audio, input forwarding, or updates.",
            14,
            MUTED,
            dpi,
            DT_LEFT | DT_WORDBREAK,
        );
        text(
            dc,
            RECT {
                left: s(258),
                top: client.bottom - s(65),
                right: client.right - s(28),
                bottom: client.bottom - s(24),
            },
            "Unreleased · license review pending",
            12,
            MUTED,
            dpi,
            DT_LEFT | DT_WORDBREAK,
        );
        let _ = EndPaint(hwnd, &ps);
    }
}

unsafe fn fill(dc: HDC, rect: RECT, color: COLORREF) {
    unsafe {
        let brush = CreateSolidBrush(color);
        if !brush.is_invalid() {
            FillRect(dc, &rect, brush);
            let _ = DeleteObject(brush.into());
        }
    }
}

unsafe fn text(
    dc: HDC,
    mut rect: RECT,
    value: &str,
    size: i32,
    color: COLORREF,
    dpi: u32,
    format: DRAW_TEXT_FORMAT,
) {
    unsafe {
        let mut metrics = NONCLIENTMETRICSW {
            cbSize: std::mem::size_of::<NONCLIENTMETRICSW>() as u32,
            ..Default::default()
        };
        // Match the OS message font family, then set its logical pixel size.
        let mut font = HFONT::default();
        if SystemParametersInfoForDpi(
            SPI_GETNONCLIENTMETRICS.0,
            metrics.cbSize,
            Some((&mut metrics as *mut NONCLIENTMETRICSW).cast()),
            0,
            dpi,
        )
        .is_ok()
        {
            metrics.lfMessageFont.lfHeight = -scale(size, dpi);
            font = CreateFontIndirectW(&metrics.lfMessageFont);
        }
        let old = if !font.is_invalid() {
            Some(SelectObject(dc, font.into()))
        } else {
            None
        };
        SetBkMode(dc, TRANSPARENT);
        SetTextColor(dc, color);
        let mut utf16: Vec<u16> = value.encode_utf16().collect();
        DrawTextW(dc, &mut utf16, &mut rect, format | DT_NOPREFIX);
        if let Some(old) = old {
            SelectObject(dc, old);
            let _ = DeleteObject(font.into());
        }
    }
}
