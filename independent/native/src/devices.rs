//! Independently authored, read-only Windows device discovery.
//!
//! Sources: Microsoft Learn documentation for SetupDiGetClassDevsW,
//! SetupDiEnumDeviceInfo, SetupDiGetDeviceRegistryPropertyW,
//! SetupDiGetDeviceInstanceIdW, SetupDiDestroyDeviceInfoList and
//! CM_Get_DevNode_Status. This module never opens a device or changes its state.

use std::{fmt, mem::size_of};
use windows::{
    Win32::{
        Devices::DeviceAndDriverInstallation::{
            CM_DEVNODE_STATUS_FLAGS, CM_Get_DevNode_Status, CM_PROB, CR_SUCCESS, DIGCF_ALLCLASSES,
            DIGCF_PRESENT, DN_HAS_PROBLEM, DN_STARTED, HDEVINFO, SETUP_DI_REGISTRY_PROPERTY,
            SP_DEVINFO_DATA, SPDRP_HARDWAREID, SPDRP_SERVICE, SetupDiDestroyDeviceInfoList,
            SetupDiEnumDeviceInfo, SetupDiGetClassDevsW, SetupDiGetDeviceInstanceIdW,
            SetupDiGetDeviceRegistryPropertyW,
        },
        Foundation::{ERROR_INSUFFICIENT_BUFFER, ERROR_INVALID_DATA, ERROR_NO_MORE_ITEMS},
        System::Registry::{REG_MULTI_SZ, REG_SZ, REG_VALUE_TYPE},
    },
    core::{HRESULT, w},
};

const MAX_USB_NODES: u32 = 4096;
const MAX_PROPERTY_BYTES: usize = 16 * 1024;
const MAX_INSTANCE_UNITS: usize = 1024;

/// A present USB device node, not proof of pairing or a usable phone connection.
/// Composite devices may expose several nodes. Instance IDs can contain serial
/// numbers: use only in memory and never put them in logs or error messages.
#[derive(Clone, PartialEq, Eq)]
pub struct UsbDevice {
    pub display_name: String,
    pub instance_id: String,
    /// True only for a recognized Apple mobile driver whose node is started and
    /// has no reported problem. It does not assert trust, pairing, or transport access.
    pub driver_ready: bool,
}

impl fmt::Debug for UsbDevice {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("UsbDevice")
            .field("display_name", &self.display_name)
            .field("instance_id", &"[redacted]")
            .field("driver_ready", &self.driver_ready)
            .finish()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DiscoveryError {
    Windows { operation: &'static str, code: i32 },
    TooManyDevices,
    PropertyTooLarge,
    InvalidProperty,
}

impl fmt::Display for DiscoveryError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Windows { operation, code } => {
                write!(f, "{operation} failed (0x{:08X})", *code as u32)
            }
            Self::TooManyDevices => f.write_str("USB discovery exceeded its device limit"),
            Self::PropertyTooLarge => f.write_str("A USB property exceeded its size limit"),
            Self::InvalidProperty => f.write_str("A USB property had an invalid format"),
        }
    }
}

impl std::error::Error for DiscoveryError {}

struct DeviceSet(HDEVINFO);

impl Drop for DeviceSet {
    fn drop(&mut self) {
        // SAFETY: this wrapper exclusively owns the valid information-set handle.
        unsafe {
            let _ = SetupDiDestroyDeviceInfoList(self.0);
        }
    }
}

fn windows_error(operation: &'static str, error: windows::core::Error) -> DiscoveryError {
    DiscoveryError::Windows {
        operation,
        code: error.code().0,
    }
}

/// Take a bounded one-shot snapshot of present Apple USB hardware. Call this on
/// a worker selected by the UI; this function creates no thread, poller or timer.
/// The snapshot can become stale immediately after return if USB is unplugged.
pub fn scan_present_apple_usb() -> Result<Vec<UsbDevice>, DiscoveryError> {
    // SAFETY: no class pointer or parent window; the literal enumerator is terminated.
    let set = DeviceSet(
        unsafe { SetupDiGetClassDevsW(None, w!("USB"), None, DIGCF_PRESENT | DIGCF_ALLCLASSES) }
            .map_err(|e| windows_error("USB enumeration", e))?,
    );
    let mut devices = Vec::new();
    // One extra lookup distinguishes exactly-at-limit from a truncated snapshot.
    for index in 0..=MAX_USB_NODES {
        let mut info = SP_DEVINFO_DATA {
            cbSize: size_of::<SP_DEVINFO_DATA>() as u32,
            ..Default::default()
        };
        // SAFETY: the set remains alive and info has its required size initialized.
        match unsafe { SetupDiEnumDeviceInfo(set.0, index, &mut info) } {
            Err(e) if e.code() == HRESULT::from_win32(ERROR_NO_MORE_ITEMS.0) => return Ok(devices),
            Err(e) => return Err(windows_error("USB enumeration", e)),
            Ok(()) => {}
        }
        if index == MAX_USB_NODES {
            return Err(DiscoveryError::TooManyDevices);
        }
        let Some(ids) = read_property(&set, &info, SPDRP_HARDWAREID, REG_MULTI_SZ)? else {
            continue;
        };
        if !ids.iter().any(|id| is_apple_usb_id(id)) {
            continue;
        }
        let service = read_property(&set, &info, SPDRP_SERVICE, REG_SZ)?;
        let mobile = service
            .as_ref()
            .and_then(|s| s.first())
            .is_some_and(|s| has_mobile_driver(&ids, s));
        let mut status = CM_DEVNODE_STATUS_FLAGS::default();
        let mut problem = CM_PROB::default();
        // SAFETY: the two outputs are valid and DevInst comes from the same snapshot.
        // Failure is conservative: a disappearing/unqueryable node is not ready.
        let ready = mobile
            && unsafe {
                CM_Get_DevNode_Status(&mut status, &mut problem, info.DevInst, 0) == CR_SUCCESS
            }
            && node_ready(status.0);
        devices.push(UsbDevice {
            display_name: if mobile {
                "Apple Mobile Device (USB)"
            } else {
                "Apple USB device"
            }
            .into(),
            instance_id: read_instance_id(&set, &info)?,
            driver_ready: ready,
        });
    }
    unreachable!("bounded enumeration always returns at the limit")
}

fn read_property(
    set: &DeviceSet,
    info: &SP_DEVINFO_DATA,
    property: SETUP_DI_REGISTRY_PROPERTY,
    expected_type: REG_VALUE_TYPE,
) -> Result<Option<Vec<String>>, DiscoveryError> {
    let mut bytes = vec![0; MAX_PROPERTY_BYTES];
    let mut required = 0;
    let mut kind = 0_u32;
    // SAFETY: the owned output slice supplies its own length; all pointers are valid.
    match unsafe {
        SetupDiGetDeviceRegistryPropertyW(
            set.0,
            info,
            property,
            Some(&mut kind),
            Some(&mut bytes),
            Some(&mut required),
        )
    } {
        Err(e) if e.code() == HRESULT::from_win32(ERROR_INVALID_DATA.0) => return Ok(None),
        Err(e) if e.code() == HRESULT::from_win32(ERROR_INSUFFICIENT_BUFFER.0) => {
            return Err(DiscoveryError::PropertyTooLarge);
        }
        Err(e) => return Err(windows_error("USB property query", e)),
        Ok(()) => {}
    }
    if kind != expected_type.0 {
        return Err(DiscoveryError::InvalidProperty);
    }
    decode_property(&bytes, required as usize, kind == REG_MULTI_SZ.0).map(Some)
}

fn read_instance_id(set: &DeviceSet, info: &SP_DEVINFO_DATA) -> Result<String, DiscoveryError> {
    let mut units = vec![0_u16; MAX_INSTANCE_UNITS];
    let mut required = 0;
    // SAFETY: the owned output slice supplies its own length and info is initialized.
    unsafe { SetupDiGetDeviceInstanceIdW(set.0, info, Some(&mut units), Some(&mut required)) }
        .map_err(|e| {
            if e.code() == HRESULT::from_win32(ERROR_INSUFFICIENT_BUFFER.0) {
                DiscoveryError::PropertyTooLarge
            } else {
                windows_error("USB instance query", e)
            }
        })?;
    let length = required as usize;
    if length == 0 || length > units.len() {
        return Err(DiscoveryError::InvalidProperty);
    }
    let text = decode_units(&units[..length], false)?;
    text.into_iter()
        .next()
        .filter(|s| !s.is_empty())
        .ok_or(DiscoveryError::InvalidProperty)
}

fn decode_property(
    bytes: &[u8],
    required: usize,
    multi: bool,
) -> Result<Vec<String>, DiscoveryError> {
    if required > MAX_PROPERTY_BYTES {
        return Err(DiscoveryError::PropertyTooLarge);
    }
    if required == 0 || required > bytes.len() || !required.is_multiple_of(2) {
        return Err(DiscoveryError::InvalidProperty);
    }
    let units: Vec<u16> = bytes[..required]
        .as_chunks::<2>()
        .0
        .iter()
        .map(|v| u16::from_le_bytes([v[0], v[1]]))
        .collect();
    decode_units(&units, multi)
}

fn decode_units(units: &[u16], multi: bool) -> Result<Vec<String>, DiscoveryError> {
    let ending = if multi { 2 } else { 1 };
    if units.len() < ending || units[units.len() - ending..].iter().any(|u| *u != 0) {
        return Err(DiscoveryError::InvalidProperty);
    }
    let contents = &units[..units.len() - ending];
    if !multi && contents.contains(&0) {
        return Err(DiscoveryError::InvalidProperty);
    }
    if contents.is_empty() {
        return Ok(Vec::new());
    }
    contents
        .split(|u| *u == 0)
        .map(|s| {
            if s.is_empty() {
                return Err(DiscoveryError::InvalidProperty);
            }
            String::from_utf16(s).map_err(|_| DiscoveryError::InvalidProperty)
        })
        .collect()
}

fn is_apple_usb_id(id: &str) -> bool {
    let upper = id.to_ascii_uppercase();
    // Hardware IDs only, never a substring in a serial or an unrelated bus ID.
    upper
        .strip_prefix("USB\\")
        .is_some_and(|parts| parts.split('&').any(|part| part == "VID_05AC"))
}

fn is_mobile_service(service: &str) -> bool {
    service.eq_ignore_ascii_case("usbaapl") || service.eq_ignore_ascii_case("usbaapl64")
}

fn has_mobile_driver(ids: &[String], service: &str) -> bool {
    ids.iter().filter(|id| is_apple_usb_id(id)).any(|id| {
        is_mobile_service(service)
            || (service.eq_ignore_ascii_case("WinUSB") && is_observed_mobile_usb_id(id))
    })
}

fn is_observed_mobile_usb_id(id: &str) -> bool {
    // The user's connected iPhone was observed on Windows with a healthy WinUSB
    // node at this exact vendor/product pair. This narrow compatibility rule is
    // based on that observation, not a universal Apple product-ID catalogue.
    // Its MTP/composite siblings do not qualify: the caller also requires WinUSB.
    let upper = id.to_ascii_uppercase();
    upper.strip_prefix("USB\\").is_some_and(|parts| {
        let mut tokens = parts.split('&');
        tokens.next() == Some("VID_05AC") && tokens.any(|token| token == "PID_12A8")
    })
}

fn node_ready(status: u32) -> bool {
    status & DN_STARTED.0 != 0 && status & DN_HAS_PROBLEM.0 == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn bytes(units: &[u16]) -> Vec<u8> {
        units.iter().flat_map(|u| u.to_le_bytes()).collect()
    }

    #[test]
    fn vendor_is_exact_and_usb_only() {
        assert!(is_apple_usb_id(r"USB\VID_05AC&PID_0000"));
        assert!(is_apple_usb_id(r"usb\vid_05ac&pid_0000&mi_00"));
        for id in [
            r"USB\VID_05AC0&PID_0000",
            r"HID\VID_05AC&PID_0000",
            r"USB\OTHER_VID_05AC",
            r"USB\VID_0000&PID_05AC",
        ] {
            assert!(!is_apple_usb_id(id));
        }
    }

    #[test]
    fn vendor_alone_does_not_prove_mobile_driver() {
        for service in ["", "usbccgp", "HidUsb", "usbaapl64-other"] {
            assert!(!is_mobile_service(service));
        }
        assert!(is_mobile_service("usbaapl"));
        assert!(is_mobile_service("USBAAPL64"));
        assert!(!node_ready(0));
        assert!(node_ready(DN_STARTED.0));
        assert!(!node_ready(DN_STARTED.0 | DN_HAS_PROBLEM.0));
    }

    #[test]
    fn observed_winusb_interface_is_narrowly_recognized() {
        let observed = vec![r"USB\VID_05AC&PID_12A8".into()];
        assert!(has_mobile_driver(&observed, "WinUSB"));
        let interface = vec![r"usb\vid_05ac&pid_12a8&mi_00".into()];
        assert!(has_mobile_driver(&interface, "wInUsB"));
        for service in ["WUDFWpdMtp", "usbccgp", "", "WinUSB-other"] {
            assert!(!has_mobile_driver(&observed, service));
        }
        for id in [
            r"USB\VID_0000&PID_12A8",
            r"USB\VID_05AC&PID_0000",
            r"USB\VID_05AC0&PID_12A8",
            r"USB\VID_05AC&PID_12A80",
            r"USB\VID_05AC&OTHER_PID_12A8",
            r"HID\VID_05AC&PID_12A8",
        ] {
            assert!(!has_mobile_driver(&[id.into()], "WinUSB"));
        }
        // Existing Apple mobile drivers remain supported independently of PID.
        assert!(has_mobile_driver(
            &[r"USB\VID_05AC&PID_0000".into()],
            "usbaapl64"
        ));
        assert!(!has_mobile_driver(
            &[r"USB\VID_0000&PID_12A8".into()],
            "usbaapl"
        ));
    }

    #[test]
    fn strict_utf16_and_termination() {
        assert_eq!(decode_units(&[65, 0], false).unwrap(), ["A"]);
        assert_eq!(decode_units(&[65, 0, 66, 0, 0], true).unwrap(), ["A", "B"]);
        assert!(decode_units(&[0, 0], true).unwrap().is_empty());
        for units in [&[0xD800, 0][..], &[65][..], &[65, 0, 66, 0][..]] {
            assert_eq!(
                decode_units(units, false),
                Err(DiscoveryError::InvalidProperty)
            );
        }
        assert_eq!(
            decode_units(&[65, 0], true),
            Err(DiscoveryError::InvalidProperty)
        );
    }

    #[test]
    fn property_lengths_are_bounded_and_even() {
        let data = bytes(&[65, 0]);
        assert_eq!(decode_property(&data, data.len(), false).unwrap(), ["A"]);
        for length in [0, 3, 6] {
            assert_eq!(
                decode_property(&data, length, false),
                Err(DiscoveryError::InvalidProperty)
            );
        }
        assert_eq!(
            decode_property(&[], MAX_PROPERTY_BYTES + 2, false),
            Err(DiscoveryError::PropertyTooLarge)
        );
        let mut boundary_units = vec![65; MAX_PROPERTY_BYTES / 2];
        *boundary_units.last_mut().unwrap() = 0;
        let boundary = bytes(&boundary_units);
        assert_eq!(
            decode_property(&boundary, MAX_PROPERTY_BYTES, false).unwrap()[0].len(),
            MAX_PROPERTY_BYTES / 2 - 1
        );
    }

    #[test]
    fn debug_does_not_reveal_identifier() {
        let device = UsbDevice {
            display_name: "Apple USB device".into(),
            instance_id: "synthetic-private-value".into(),
            driver_ready: false,
        };
        let debug = format!("{device:?}");
        assert!(!debug.contains("synthetic-private-value"));
        assert!(debug.contains("[redacted]"));
    }
}
