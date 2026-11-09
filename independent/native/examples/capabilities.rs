//! Explicit, read-only capability probe. Never prints device identifiers.
use pane_next_prototype::usbmux::{MuxTransport, list_devices};
use pane_next_prototype::{devices::scan_present_apple_usb, media::probe_hevc_decoders};

fn main() {
    match scan_present_apple_usb() {
        Ok(devices) => {
            println!("Present Apple USB nodes: {}", devices.len());
            println!(
                "Started mobile-driver nodes: {}",
                devices.iter().filter(|device| device.driver_ready).count()
            );
        }
        Err(error) => eprintln!("USB capability probe: {error}"),
    }
    match probe_hevc_decoders() {
        Ok(decoders) => {
            println!("Windows HEVC decoder candidates: {}", decoders.len());
            for decoder in decoders {
                println!(
                    "Decoder {:?}: activation={}, D3D11-aware={}, registered-hardware={}",
                    decoder.name,
                    decoder.activation_succeeded,
                    decoder.d3d11_aware,
                    decoder.registered_hardware_transform
                );
            }
            println!("Actual phone-stream decoding and GPU use are not validated by this probe.");
        }
        Err(error) => eprintln!("Media capability probe: {error}"),
    }
    match list_devices() {
        Ok(devices) => {
            println!("Apple local-service records: {}", devices.len());
            println!(
                "USB records: {}; network records: {}",
                devices
                    .iter()
                    .filter(|device| device.transport == MuxTransport::Usb)
                    .count(),
                devices
                    .iter()
                    .filter(|device| device.transport == MuxTransport::Network)
                    .count()
            );
            println!("Identifiers are omitted. Pairing and phone-session access are not checked.");
        }
        Err(error) => eprintln!("Local device-service probe: {error}"),
    }
}
