//! Read-only Windows HEVC transform discovery, not a decoding pipeline.
//!
//! References: Microsoft Learn, "H.265 / HEVC Video Decoder", "MFTEnumEx",
//! "Initializing Media Foundation", and "Media Foundation and COM".
//! A listed transform or D3D11-aware attribute does not prove that a particular
//! phone stream can be decoded in hardware. That requires actual decode tests.

use std::fmt;
use windows::{
    Win32::{
        Media::MediaFoundation::*,
        System::Com::{COINIT_MULTITHREADED, CoInitializeEx, CoTaskMemFree, CoUninitialize},
    },
    core::GUID,
};

const MAX_DECODERS: usize = 256;
const MAX_NAME_UNITS: usize = 256;

#[derive(Debug, Clone)]
pub struct HevcDecoderInfo {
    pub name: String,
    pub class_id: Option<GUID>,
    pub registered_hardware_transform: bool,
    pub d3d11_aware: bool,
    pub activation_succeeded: bool,
}

#[derive(Debug)]
pub struct MediaProbeError {
    pub operation: &'static str,
    pub code: i32,
}

impl fmt::Display for MediaProbeError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{} failed ({:#x})", self.operation, self.code)
    }
}
impl std::error::Error for MediaProbeError {}

fn failure(operation: &'static str, error: windows::core::Error) -> MediaProbeError {
    MediaProbeError {
        operation,
        code: error.code().0,
    }
}

struct ComApartment;
impl Drop for ComApartment {
    fn drop(&mut self) {
        unsafe { CoUninitialize() };
    }
}
struct MediaFoundation;
impl Drop for MediaFoundation {
    fn drop(&mut self) {
        unsafe {
            let _ = MFShutdown();
        }
    }
}

struct Activations {
    pointer: *mut Option<IMFActivate>,
    count: u32,
}
impl Drop for Activations {
    fn drop(&mut self) {
        if !self.pointer.is_null() {
            // MFTEnumEx owns allocation sizing; release each returned COM ref
            // before freeing its array, including on a later validation error.
            unsafe {
                for index in 0..self.count as usize {
                    std::ptr::drop_in_place(self.pointer.add(index));
                }
                CoTaskMemFree(Some(self.pointer.cast()));
            }
        }
    }
}

fn activations(flags: MFT_ENUM_FLAG) -> Result<Activations, MediaProbeError> {
    let input = MFT_REGISTER_TYPE_INFO {
        guidMajorType: MFMediaType_Video,
        guidSubtype: MFVideoFormat_HEVC,
    };
    let mut list = Activations {
        pointer: std::ptr::null_mut(),
        count: 0,
    };
    unsafe {
        MFTEnumEx(
            MFT_CATEGORY_VIDEO_DECODER,
            flags,
            Some(&input),
            None,
            &mut list.pointer,
            &mut list.count,
        )
    }
    .map_err(|error| failure("HEVC transform enumeration", error))?;
    if list.count as usize > MAX_DECODERS || (list.count > 0 && list.pointer.is_null()) {
        return Err(MediaProbeError {
            operation: "HEVC transform result validation",
            code: -1,
        });
    }
    Ok(list)
}

fn name(activation: &IMFActivate) -> String {
    unsafe {
        let Ok(length) = activation.GetStringLength(&MFT_FRIENDLY_NAME_Attribute) else {
            return "System HEVC decoder".into();
        };
        if length as usize > MAX_NAME_UNITS {
            return "System HEVC decoder".into();
        }
        let mut text = vec![0u16; length as usize + 1];
        if activation
            .GetString(&MFT_FRIENDLY_NAME_Attribute, &mut text, None)
            .is_err()
        {
            return "System HEVC decoder".into();
        }
        String::from_utf16_lossy(&text[..length as usize])
    }
}

/// Enumerate installed Windows decoders on the caller's MTA-compatible thread.
/// Call once from a worker or explicit diagnostic, never from a render loop.
/// No transform processes samples or opens a phone/network connection here.
pub fn probe_hevc_decoders() -> Result<Vec<HevcDecoderInfo>, MediaProbeError> {
    unsafe { CoInitializeEx(None, COINIT_MULTITHREADED).ok() }
        .map_err(|error| failure("Media COM initialization", error))?;
    let _com = ComApartment;
    unsafe { MFStartup(MF_VERSION, MFSTARTUP_FULL) }
        .map_err(|error| failure("Media Foundation startup", error))?;
    let _media = MediaFoundation;
    let hardware = activations(MFT_ENUM_FLAG_HARDWARE | MFT_ENUM_FLAG_SORTANDFILTER)?;
    let mut hardware_ids = Vec::new();
    for index in 0..hardware.count as usize {
        if let Some(activation) = unsafe { &*hardware.pointer.add(index) }
            && let Ok(id) = unsafe { activation.GetGUID(&MFT_TRANSFORM_CLSID_Attribute) }
        {
            hardware_ids.push(id);
        }
    }
    let all = activations(
        MFT_ENUM_FLAG_SYNCMFT
            | MFT_ENUM_FLAG_ASYNCMFT
            | MFT_ENUM_FLAG_LOCALMFT
            | MFT_ENUM_FLAG_HARDWARE
            | MFT_ENUM_FLAG_SORTANDFILTER,
    )?;
    let mut decoders = Vec::with_capacity(all.count as usize);
    for index in 0..all.count as usize {
        let Some(activation) = (unsafe { &*all.pointer.add(index) }) else {
            continue;
        };
        let class_id = unsafe { activation.GetGUID(&MFT_TRANSFORM_CLSID_Attribute) }.ok();
        let transform = unsafe { activation.ActivateObject::<IMFTransform>() };
        let d3d11_aware = transform
            .as_ref()
            .ok()
            .and_then(|transform| unsafe { transform.GetAttributes() }.ok())
            .and_then(|attributes| unsafe { attributes.GetUINT32(&MF_SA_D3D11_AWARE) }.ok())
            .is_some_and(|value| value != 0);
        decoders.push(HevcDecoderInfo {
            name: name(activation),
            class_id,
            registered_hardware_transform: class_id.is_some_and(|id| hardware_ids.contains(&id)),
            d3d11_aware,
            activation_succeeded: transform.is_ok(),
        });
        // Drop the transform before Media Foundation/COM shutdown.
        drop(transform);
        unsafe {
            let _ = activation.ShutdownObject();
        }
    }
    Ok(decoders)
}
