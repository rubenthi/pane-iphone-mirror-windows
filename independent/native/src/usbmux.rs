//! Small, independent, read-only client for the local Apple USB multiplexing service.
//!
//! This module sends only `ListDevices`. It never pairs, reads pairing records,
//! starts a phone service, or opens a connection to a phone. Wire constants are
//! protocol facts, not copied implementation. Public API references:
//! https://docs.rs/idevice/latest/idevice/usbmuxd/index.html
//! https://docs.rs/idevice/latest/idevice/usbmuxd/enum.UsbmuxdAddr.html
//! Property lists use the pure Rust `plist` crate's documented Value API:
//! https://docs.rs/plist/1.10.3/plist/enum.Value.html
//! Bounded XML preflight uses documented borrowed events:
//! https://docs.rs/quick-xml/0.42.0/quick_xml/reader/struct.Reader.html

use plist::Value;
use quick_xml::events::Event;
use quick_xml::reader::Reader;
use std::fmt;
use std::io::{self, Read, Write};
use std::net::{Ipv4Addr, SocketAddr, SocketAddrV4, TcpStream};
use std::time::{Duration, Instant};

const HEADER_BYTES: usize = 16;
const MAX_PACKET_BYTES: usize = 1024 * 1024;
const MAX_DEVICES: usize = 256;
const MAX_IDENTIFIER_BYTES: usize = 256;
const MAX_XML_DEPTH: usize = 32;
const MAX_XML_EVENTS: usize = 8192;
const APPLE_PUBLIC_DTD: &str = r#"plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd""#;
const PROTOCOL_VERSION: u32 = 1;
const PLIST_MESSAGE: u32 = 8;
const REQUEST_TAG: u32 = 1;
const LOCAL_PORT: u16 = 27015;
const REQUEST: &[u8] = br#"<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>MessageType</key><string>ListDevices</string>
<key>ClientVersionString</key><string>PaneNextPrototype0.1</string>
<key>ProgName</key><string>PaneNextPrototype</string>
<key>kLibUSBMuxVersion</key><integer>3</integer>
</dict></plist>"#;

/// Device identifiers are opaque. Diagnostics must not expose their contents.
#[derive(Clone, PartialEq, Eq)]
pub struct DeviceIdentifier(String);

impl DeviceIdentifier {
    /// Explicit access for matching devices; do not include this value in logs.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for DeviceIdentifier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str("DeviceIdentifier([redacted])")
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MuxTransport {
    Usb,
    Network,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MuxDevice {
    pub identifier: DeviceIdentifier,
    /// Local service-assigned routing ID, not the phone's serial number.
    pub id: u32,
    pub transport: MuxTransport,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MuxStage {
    Connect,
    Configure,
    WriteRequest,
    ReadHeader,
    ReadBody,
}

impl fmt::Display for MuxStage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::Connect => "connecting to the local Apple service",
            Self::Configure => "configuring the local Apple connection",
            Self::WriteRequest => "sending the device-list request",
            Self::ReadHeader => "reading the device-list header",
            Self::ReadBody => "reading the device list",
        })
    }
}

/// Errors intentionally retain no service payloads, identifiers, or OS messages.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MuxError {
    Io { stage: MuxStage, code: i32 },
    Timeout(MuxStage),
    NonLoopback,
    Truncated(MuxStage),
    InvalidLength,
    InvalidHeader,
    InvalidPlist,
    InvalidDeviceList,
    TooManyDevices,
    InvalidIdentifier,
    UnknownTransport,
    ConflictingDeviceId,
    AppleRejected,
}

impl fmt::Display for MuxError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io { stage, code } => write!(f, "Failed while {stage} (system error {code})."),
            Self::Timeout(stage) => write!(f, "Timed out while {stage}."),
            Self::Truncated(stage) => {
                write!(f, "The local Apple service disconnected while {stage}.")
            }
            _ => f.write_str(match self {
                Self::NonLoopback => "Device discovery requires a local loopback connection.",
                Self::InvalidLength => "The local Apple service returned an invalid packet length.",
                Self::InvalidHeader => {
                    "The local Apple service returned an unexpected packet header."
                }
                Self::InvalidPlist => "The local Apple service returned an unreadable device list.",
                Self::InvalidDeviceList => {
                    "The local Apple service returned an invalid device list."
                }
                Self::TooManyDevices => "The local Apple service returned too many devices.",
                Self::InvalidIdentifier => {
                    "The local Apple service returned an invalid device identifier."
                }
                Self::UnknownTransport => {
                    "The local Apple service returned an unsupported transport."
                }
                Self::ConflictingDeviceId => {
                    "The local Apple service returned conflicting device records."
                }
                Self::AppleRejected => "The local Apple service rejected device discovery.",
                Self::Io { .. } | Self::Timeout(_) | Self::Truncated(_) => unreachable!(),
            }),
        }
    }
}

impl std::error::Error for MuxError {}

#[derive(Clone, Copy)]
struct Limits {
    operation_timeout: Duration,
    total_timeout: Duration,
}

const DEFAULT_LIMITS: Limits = Limits {
    operation_timeout: Duration::from_secs(1),
    total_timeout: Duration::from_secs(3),
};

/// List USB and network device records through 127.0.0.1:27015 only.
///
/// No environment variable, hostname resolution, remote address, or phone
/// connection is used. A network record is metadata returned by the local
/// service; listing it does not contact that device. All socket operations have
/// individual timeouts and share one overall deadline.
pub fn list_devices() -> Result<Vec<MuxDevice>, MuxError> {
    let deadline = Instant::now() + DEFAULT_LIMITS.total_timeout;
    let address = SocketAddr::V4(SocketAddrV4::new(Ipv4Addr::LOCALHOST, LOCAL_PORT));
    let timeout = remaining(deadline, DEFAULT_LIMITS, MuxStage::Connect)?;
    let stream = TcpStream::connect_timeout(&address, timeout)
        .map_err(|error| io_error(MuxStage::Connect, error))?;
    exchange(stream, deadline, DEFAULT_LIMITS)
}

fn io_error(stage: MuxStage, error: io::Error) -> MuxError {
    if matches!(
        error.kind(),
        io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock
    ) {
        MuxError::Timeout(stage)
    } else {
        MuxError::Io {
            stage,
            code: error.raw_os_error().unwrap_or(0),
        }
    }
}

fn remaining(deadline: Instant, limits: Limits, stage: MuxStage) -> Result<Duration, MuxError> {
    let remaining = deadline.saturating_duration_since(Instant::now());
    if remaining.is_zero() || limits.operation_timeout.is_zero() {
        return Err(MuxError::Timeout(stage));
    }
    Ok(remaining.min(limits.operation_timeout))
}

fn read_bounded(
    stream: &mut TcpStream,
    mut target: &mut [u8],
    deadline: Instant,
    limits: Limits,
    stage: MuxStage,
) -> Result<(), MuxError> {
    while !target.is_empty() {
        let timeout = remaining(deadline, limits, stage)?;
        stream
            .set_read_timeout(Some(timeout))
            .map_err(|e| io_error(MuxStage::Configure, e))?;
        match stream.read(target) {
            Ok(0) => return Err(MuxError::Truncated(stage)),
            Ok(count) => target = &mut target[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(io_error(stage, error)),
        }
    }
    remaining(deadline, limits, stage)?;
    Ok(())
}

fn write_bounded(
    stream: &mut TcpStream,
    mut source: &[u8],
    deadline: Instant,
    limits: Limits,
) -> Result<(), MuxError> {
    let stage = MuxStage::WriteRequest;
    while !source.is_empty() {
        let timeout = remaining(deadline, limits, stage)?;
        stream
            .set_write_timeout(Some(timeout))
            .map_err(|e| io_error(MuxStage::Configure, e))?;
        match stream.write(source) {
            Ok(0) => return Err(MuxError::Truncated(stage)),
            Ok(count) => source = &source[count..],
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(error) => return Err(io_error(stage, error)),
        }
    }
    remaining(deadline, limits, stage)?;
    Ok(())
}

fn header(length: u32, version: u32, message: u32, tag: u32) -> [u8; HEADER_BYTES] {
    let mut bytes = [0; HEADER_BYTES];
    for (slot, number) in bytes
        .as_chunks_mut::<4>()
        .0
        .iter_mut()
        .zip([length, version, message, tag])
    {
        slot.copy_from_slice(&number.to_le_bytes());
    }
    bytes
}

fn exchange(
    mut stream: TcpStream,
    deadline: Instant,
    limits: Limits,
) -> Result<Vec<MuxDevice>, MuxError> {
    if !stream
        .peer_addr()
        .map_err(|e| io_error(MuxStage::Configure, e))?
        .ip()
        .is_loopback()
    {
        return Err(MuxError::NonLoopback);
    }
    // This finite request cannot be influenced by server-provided device data.
    let request_header = header(
        (HEADER_BYTES + REQUEST.len()) as u32,
        PROTOCOL_VERSION,
        PLIST_MESSAGE,
        REQUEST_TAG,
    );
    write_bounded(&mut stream, &request_header, deadline, limits)?;
    write_bounded(&mut stream, REQUEST, deadline, limits)?;
    let mut response_header = [0; HEADER_BYTES];
    read_bounded(
        &mut stream,
        &mut response_header,
        deadline,
        limits,
        MuxStage::ReadHeader,
    )?;
    let mut words = [0; 4];
    for (word, bytes) in words
        .iter_mut()
        .zip(response_header.as_chunks::<4>().0.iter())
    {
        *word = u32::from_le_bytes(*bytes);
    }
    let length = words[0] as usize;
    // Validate before allocating or reading the service-controlled body length.
    if !(HEADER_BYTES..=MAX_PACKET_BYTES).contains(&length) {
        return Err(MuxError::InvalidLength);
    }
    if words[1..] != [PROTOCOL_VERSION, PLIST_MESSAGE, REQUEST_TAG] {
        return Err(MuxError::InvalidHeader);
    }
    let mut body = vec![0; length - HEADER_BYTES];
    read_bounded(&mut stream, &mut body, deadline, limits, MuxStage::ReadBody)?;
    let devices = decode_devices(&body)?;
    remaining(deadline, limits, MuxStage::ReadBody)?;
    Ok(devices)
}

fn preflight_xml(body: &[u8]) -> Result<(), MuxError> {
    // Scan borrowed XML events before constructing a recursive plist::Value.
    // This bounds tree depth and node count even for a malformed local service.
    // Neither this reader nor the following Value parser resolves DTD URLs.
    if body.len() > MAX_PACKET_BYTES - HEADER_BYTES {
        return Err(MuxError::InvalidPlist);
    }
    let mut reader = Reader::from_reader(body);
    reader.config_mut().enable_all_checks(true);
    let mut depth = 0usize;
    let mut events = 0usize;
    let mut seen_root = false;
    let mut seen_doctype = false;
    let mut seen_declaration = false;
    loop {
        let event = reader.read_event().map_err(|_| MuxError::InvalidPlist)?;
        // Whitespace contributes no Value nodes. Keep the cap independent of
        // pretty-printing while still bounding the complete input byte count.
        if matches!(&event, Event::Text(text) if text.trim_ascii().is_empty()) {
            continue;
        }
        events += 1;
        if events > MAX_XML_EVENTS {
            return Err(MuxError::InvalidPlist);
        }
        match event {
            Event::Start(tag) => {
                if depth == 0 {
                    if seen_root || tag.name().as_ref() != "plist" {
                        return Err(MuxError::InvalidPlist);
                    }
                    seen_root = true;
                }
                depth += 1;
                if depth > MAX_XML_DEPTH {
                    return Err(MuxError::InvalidPlist);
                }
            }
            Event::Empty(_) => {
                if depth == 0 || depth == MAX_XML_DEPTH {
                    return Err(MuxError::InvalidPlist);
                }
            }
            Event::End(_) => {
                depth = depth.checked_sub(1).ok_or(MuxError::InvalidPlist)?;
            }
            Event::DocType(declaration) => {
                // Accept only Apple's conventional public declaration. In
                // particular, internal subsets and ENTITY declarations fail
                // this equality test and are never passed to the Value parser.
                if seen_root || seen_doctype || declaration.trim_ascii() != APPLE_PUBLIC_DTD {
                    return Err(MuxError::InvalidPlist);
                }
                seen_doctype = true;
            }
            Event::GeneralRef(reference) => {
                if depth == 0 {
                    return Err(MuxError::InvalidPlist);
                }
                let builtin = matches!(reference.as_ref(), "amp" | "lt" | "gt" | "apos" | "quot");
                let character = reference
                    .resolve_char_ref()
                    .map_err(|_| MuxError::InvalidPlist)?;
                if !builtin && character.is_none() {
                    return Err(MuxError::InvalidPlist);
                }
            }
            Event::Text(_) | Event::CData(_) if depth == 0 => return Err(MuxError::InvalidPlist),
            Event::Decl(_) => {
                if seen_root || seen_doctype || seen_declaration {
                    return Err(MuxError::InvalidPlist);
                }
                seen_declaration = true;
            }
            Event::PI(_) => return Err(MuxError::InvalidPlist),
            Event::Eof => {
                return if seen_root && depth == 0 {
                    Ok(())
                } else {
                    Err(MuxError::InvalidPlist)
                };
            }
            _ => {}
        }
    }
}

fn decode_devices(body: &[u8]) -> Result<Vec<MuxDevice>, MuxError> {
    preflight_xml(body)?;
    // XML only: accepting other formats is unnecessary for this request.
    // Parser errors are deliberately discarded because they can contain data.
    let root = Value::from_reader_xml(body).map_err(|_| MuxError::InvalidPlist)?;
    let dictionary = root.as_dictionary().ok_or(MuxError::InvalidDeviceList)?;
    if let Some(kind) = dictionary.get("MessageType") {
        match kind.as_string() {
            Some("Result") => {
                let number = dictionary
                    .get("Number")
                    .and_then(Value::as_unsigned_integer)
                    .ok_or(MuxError::InvalidDeviceList)?;
                return Err(if number != 0 {
                    MuxError::AppleRejected
                } else {
                    MuxError::InvalidDeviceList
                });
            }
            Some("ListDevices") => {}
            _ => return Err(MuxError::InvalidDeviceList),
        }
    }
    let records = dictionary
        .get("DeviceList")
        .and_then(Value::as_array)
        .ok_or(MuxError::InvalidDeviceList)?;
    if records.len() > MAX_DEVICES {
        return Err(MuxError::TooManyDevices);
    }
    let mut devices: Vec<MuxDevice> = Vec::with_capacity(records.len());
    for record in records {
        let record = record.as_dictionary().ok_or(MuxError::InvalidDeviceList)?;
        let id = record
            .get("DeviceID")
            .and_then(Value::as_unsigned_integer)
            .and_then(|id| u32::try_from(id).ok())
            .ok_or(MuxError::InvalidDeviceList)?;
        let properties = record
            .get("Properties")
            .and_then(Value::as_dictionary)
            .ok_or(MuxError::InvalidDeviceList)?;
        let transport = match properties.get("ConnectionType").and_then(Value::as_string) {
            Some("USB") => MuxTransport::Usb,
            Some("Network") => MuxTransport::Network,
            // Reject the complete response rather than silently hiding records.
            Some(_) => return Err(MuxError::UnknownTransport),
            None => return Err(MuxError::InvalidDeviceList),
        };
        let identifier = properties
            .get("SerialNumber")
            .and_then(Value::as_string)
            .ok_or(MuxError::InvalidIdentifier)?;
        if identifier.is_empty()
            || identifier.len() > MAX_IDENTIFIER_BYTES
            || identifier.chars().any(char::is_control)
        {
            return Err(MuxError::InvalidIdentifier);
        }
        let device = MuxDevice {
            identifier: DeviceIdentifier(identifier.to_owned()),
            id,
            transport,
        };
        // Exact repeats coalesce in first-seen order. Reuse of a routing ID for
        // different data is rejected. The same opaque identifier with distinct
        // IDs remains separate, preserving USB and network transport records.
        if let Some(existing) = devices.iter().find(|existing| existing.id == device.id) {
            if existing != &device {
                return Err(MuxError::ConflictingDeviceId);
            }
        } else {
            devices.push(device);
        }
    }
    Ok(devices)
}

#[cfg(test)]
mod tests {
    use super::*;
    use plist::Dictionary;
    use std::net::TcpListener;
    use std::thread;

    fn record(id: u64, transport: &str, identifier: &str) -> Value {
        let mut properties = Dictionary::new();
        properties.insert("ConnectionType".into(), Value::from(transport));
        properties.insert("SerialNumber".into(), Value::from(identifier));
        let mut device = Dictionary::new();
        device.insert("DeviceID".into(), Value::from(id));
        device.insert("Properties".into(), Value::Dictionary(properties));
        Value::Dictionary(device)
    }

    fn body(records: Vec<Value>) -> Vec<u8> {
        let mut dictionary = Dictionary::new();
        dictionary.insert("DeviceList".into(), Value::Array(records));
        xml(Value::Dictionary(dictionary))
    }

    fn xml(value: Value) -> Vec<u8> {
        let mut bytes = Vec::new();
        value.to_writer_xml(&mut bytes).unwrap();
        bytes
    }

    fn packet(body: &[u8]) -> Vec<u8> {
        let mut bytes = header(
            (HEADER_BYTES + body.len()) as u32,
            PROTOCOL_VERSION,
            PLIST_MESSAGE,
            REQUEST_TAG,
        )
        .to_vec();
        bytes.extend_from_slice(body);
        bytes
    }

    // All fixtures bind an ephemeral loopback port. Never invoke list_devices()
    // here, as it would access the actual Apple service or attached hardware.
    fn fixture<F>(limits: Limits, server: F) -> Result<Vec<MuxDevice>, MuxError>
    where
        F: FnOnce(TcpStream) + Send + 'static,
    {
        let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let worker = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            stream
                .set_read_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            stream
                .set_write_timeout(Some(Duration::from_secs(2)))
                .unwrap();
            let mut request_header = [0; HEADER_BYTES];
            stream.read_exact(&mut request_header).unwrap();
            assert_eq!(
                request_header,
                header((HEADER_BYTES + REQUEST.len()) as u32, 1, 8, 1)
            );
            let mut request_body = vec![0; REQUEST.len()];
            stream.read_exact(&mut request_body).unwrap();
            assert_eq!(request_body, REQUEST);
            let request = Value::from_reader_xml(request_body.as_slice()).unwrap();
            let request = request.as_dictionary().unwrap();
            assert_eq!(
                request.get("MessageType").and_then(Value::as_string),
                Some("ListDevices")
            );
            assert_eq!(request.len(), 4);
            server(stream);
        });
        let stream = TcpStream::connect_timeout(&address, Duration::from_secs(1)).unwrap();
        let result = exchange(stream, Instant::now() + limits.total_timeout, limits);
        worker.join().unwrap();
        result
    }

    fn response(bytes: Vec<u8>) -> Result<Vec<MuxDevice>, MuxError> {
        fixture(DEFAULT_LIMITS, move |mut stream| {
            stream.write_all(&bytes).unwrap()
        })
    }

    #[test]
    fn lists_usb_and_network_without_merging_transports() {
        let records = body(vec![
            record(1, "USB", "opaque fixture"),
            record(2, "Network", "opaque fixture"),
        ]);
        let devices = response(packet(&records)).unwrap();
        assert_eq!(devices.len(), 2);
        assert_eq!(devices[0].transport, MuxTransport::Usb);
        assert_eq!(devices[1].transport, MuxTransport::Network);
        assert_eq!(devices[0].identifier.as_str(), "opaque fixture");
    }

    #[test]
    fn handles_partial_header_and_body_reads() {
        let bytes = packet(&body(vec![record(7, "USB", "partial fixture")]));
        let result = fixture(DEFAULT_LIMITS, move |mut stream| {
            for chunk in bytes.chunks(3) {
                stream.write_all(chunk).unwrap();
                thread::yield_now();
            }
        })
        .unwrap();
        assert_eq!(result[0].id, 7);
    }

    #[test]
    fn accepts_empty_device_list() {
        assert!(response(packet(&body(Vec::new()))).unwrap().is_empty());
    }

    #[test]
    fn rejects_bad_lengths_before_body_read_or_allocation() {
        for length in [0, 15, MAX_PACKET_BYTES as u32 + 1, u32::MAX] {
            assert_eq!(
                response(header(length, 1, 8, 1).to_vec()),
                Err(MuxError::InvalidLength)
            );
        }
    }

    #[test]
    fn rejects_header_version_message_and_tag() {
        for (version, message, tag) in [(2, 8, 1), (1, 7, 1), (1, 8, 2)] {
            assert_eq!(
                response(header(16, version, message, tag).to_vec()),
                Err(MuxError::InvalidHeader)
            );
        }
    }

    #[test]
    fn rejects_truncated_header_and_body() {
        assert_eq!(
            response(vec![0; 7]),
            Err(MuxError::Truncated(MuxStage::ReadHeader))
        );
        assert_eq!(
            response(header(100, 1, 8, 1).to_vec()),
            Err(MuxError::Truncated(MuxStage::ReadBody))
        );
    }

    #[test]
    fn idle_response_times_out() {
        let limits = Limits {
            operation_timeout: Duration::from_millis(40),
            total_timeout: Duration::from_millis(300),
        };
        assert_eq!(
            fixture(limits, |_stream| thread::sleep(Duration::from_millis(150))),
            Err(MuxError::Timeout(MuxStage::ReadHeader))
        );
    }

    #[test]
    fn slow_progress_does_not_reset_overall_deadline() {
        let limits = Limits {
            operation_timeout: Duration::from_millis(200),
            total_timeout: Duration::from_millis(90),
        };
        let bytes = packet(&body(Vec::new()));
        let result = fixture(limits, move |mut stream| {
            for byte in bytes.iter().take(5) {
                if stream.write_all(&[*byte]).is_err() {
                    break;
                }
                thread::sleep(Duration::from_millis(35));
            }
        });
        assert_eq!(result, Err(MuxError::Timeout(MuxStage::ReadHeader)));
    }

    #[test]
    fn rejects_result_errors_without_exposing_payload() {
        let mut dictionary = Dictionary::new();
        dictionary.insert("MessageType".into(), Value::from("Result"));
        dictionary.insert("Number".into(), Value::from(5u64));
        dictionary.insert(
            "UntrustedText".into(),
            Value::from("private identifier from server"),
        );
        let error = response(packet(&xml(Value::Dictionary(dictionary)))).unwrap_err();
        assert_eq!(error, MuxError::AppleRejected);
        assert!(!format!("{error:?} {error}").contains("private identifier"));
    }

    #[test]
    fn zero_result_is_not_a_device_list() {
        let mut dictionary = Dictionary::new();
        dictionary.insert("MessageType".into(), Value::from("Result"));
        dictionary.insert("Number".into(), Value::from(0u64));
        assert_eq!(
            response(packet(&xml(Value::Dictionary(dictionary)))),
            Err(MuxError::InvalidDeviceList)
        );
    }

    #[test]
    fn rejects_malformed_and_wrong_shape_plists() {
        assert_eq!(
            response(packet(b"<plist>private malformed fixture")),
            Err(MuxError::InvalidPlist)
        );
        assert_eq!(
            response(packet(&xml(Value::Array(Vec::new())))),
            Err(MuxError::InvalidDeviceList)
        );
        assert_eq!(
            response(packet(&xml(Value::Dictionary(Dictionary::new())))),
            Err(MuxError::InvalidDeviceList)
        );
    }

    #[test]
    fn rejects_wrong_types_and_missing_required_properties() {
        assert_eq!(
            decode_devices(&body(vec![Value::from("not a record")])),
            Err(MuxError::InvalidDeviceList)
        );
        for field in ["DeviceID", "Properties"] {
            let mut device = record(1, "USB", "fixture");
            device.as_dictionary_mut().unwrap().remove(field);
            assert_eq!(
                decode_devices(&body(vec![device])),
                Err(MuxError::InvalidDeviceList)
            );
        }
        for field in ["ConnectionType", "SerialNumber"] {
            let mut device = record(1, "USB", "fixture");
            device
                .as_dictionary_mut()
                .unwrap()
                .get_mut("Properties")
                .unwrap()
                .as_dictionary_mut()
                .unwrap()
                .remove(field);
            let expected = if field == "SerialNumber" {
                MuxError::InvalidIdentifier
            } else {
                MuxError::InvalidDeviceList
            };
            assert_eq!(decode_devices(&body(vec![device])), Err(expected));
        }
        let mut device = record(1, "USB", "fixture");
        device
            .as_dictionary_mut()
            .unwrap()
            .insert("DeviceID".into(), Value::from(-1i64));
        assert_eq!(
            decode_devices(&body(vec![device])),
            Err(MuxError::InvalidDeviceList)
        );
    }

    #[test]
    fn exact_duplicate_coalesces_but_conflicting_id_rejects() {
        let duplicate = record(4, "USB", "fixture");
        assert_eq!(
            response(packet(&body(vec![duplicate.clone(), duplicate.clone()])))
                .unwrap()
                .len(),
            1
        );
        for conflicting in [
            record(4, "USB", "other fixture"),
            record(4, "Network", "fixture"),
        ] {
            assert_eq!(
                response(packet(&body(vec![duplicate.clone(), conflicting]))),
                Err(MuxError::ConflictingDeviceId)
            );
        }
    }

    #[test]
    fn unknown_transport_is_rejected() {
        assert_eq!(
            response(packet(&body(vec![record(
                1,
                "unexpected private text",
                "fixture"
            )]))),
            Err(MuxError::UnknownTransport)
        );
    }

    #[test]
    fn bounds_record_count_identifiers_and_routing_ids() {
        assert_eq!(
            decode_devices(&body(
                (0..256).map(|id| record(id, "USB", "fixture")).collect()
            ))
            .unwrap()
            .len(),
            256
        );
        assert_eq!(
            decode_devices(&body(
                (0..257).map(|id| record(id, "USB", "fixture")).collect()
            )),
            Err(MuxError::TooManyDevices)
        );
        for identifier in [String::new(), "x".repeat(257), "line\nbreak".to_owned()] {
            assert_eq!(
                decode_devices(&body(vec![record(1, "USB", &identifier)])),
                Err(MuxError::InvalidIdentifier)
            );
        }
        assert_eq!(
            decode_devices(&body(vec![record(
                u64::from(u32::MAX) + 1,
                "USB",
                "fixture"
            )])),
            Err(MuxError::InvalidDeviceList)
        );
    }

    #[test]
    fn identifiers_are_redacted_from_derived_diagnostics() {
        let devices =
            decode_devices(&body(vec![record(9, "USB", "secret fixture identifier")])).unwrap();
        let diagnostic = format!("{devices:?} {:?}", devices[0].identifier);
        assert!(!diagnostic.contains("secret fixture identifier"));
        assert!(diagnostic.contains("redacted"));
        let error = io_error(
            MuxStage::ReadBody,
            io::Error::other("private error payload"),
        );
        assert!(!format!("{error:?} {error}").contains("private error payload"));
    }

    #[test]
    fn rejects_deep_xml_before_building_recursive_values() {
        let deep = format!(
            "<plist>{}{} </plist>",
            "<array>".repeat(2000),
            "</array>".repeat(2000)
        );
        assert_eq!(preflight_xml(deep.as_bytes()), Err(MuxError::InvalidPlist));
        assert_eq!(decode_devices(deep.as_bytes()), Err(MuxError::InvalidPlist));
    }

    #[test]
    fn rejects_wide_xml_before_building_values() {
        let wide = format!(
            "<plist><array>{}</array></plist>",
            "<string/>".repeat(MAX_XML_EVENTS)
        );
        assert_eq!(preflight_xml(wide.as_bytes()), Err(MuxError::InvalidPlist));
        assert_eq!(decode_devices(wide.as_bytes()), Err(MuxError::InvalidPlist));
    }

    #[test]
    fn rejects_internal_entity_and_unrecognized_external_dtds() {
        for declaration in [
            r#"<!DOCTYPE plist [<!ENTITY private "fixture">]>"#,
            r#"<!DOCTYPE plist SYSTEM "file:///private-fixture.dtd">"#,
            r#"<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd" [<!ENTITY private "fixture">]>"#,
        ] {
            let payload = format!("{declaration}<plist><dict/></plist>");
            assert_eq!(
                preflight_xml(payload.as_bytes()),
                Err(MuxError::InvalidPlist)
            );
            assert_eq!(
                decode_devices(payload.as_bytes()),
                Err(MuxError::InvalidPlist)
            );
        }
        assert_eq!(
            preflight_xml(b"<plist><string>&private;</string></plist>"),
            Err(MuxError::InvalidPlist)
        );
    }

    #[test]
    fn accepts_standard_apple_doctype_and_builtin_character_references() {
        let payload = body(vec![record(1, "USB", "opaque & <fixture>")]);
        assert_eq!(preflight_xml(&payload), Ok(()));
        assert_eq!(
            decode_devices(&payload).unwrap()[0].identifier.as_str(),
            "opaque & <fixture>"
        );
        assert_eq!(
            preflight_xml(b"<plist><string>&#65;&#x42;</string></plist>"),
            Ok(())
        );
    }

    #[test]
    fn rejects_empty_malformed_and_multiple_xml_roots() {
        for payload in [
            "",
            "  ",
            "<!-- fixture -->",
            "<plist><dict></plist>",
            "<plist><dict/></plist><plist><dict/></plist>",
            "<plist><dict/></plist>trailing text",
            "<plist><dict/>",
            "<plist><dict/></plist><?xml version=\"1.0\"?>",
        ] {
            assert_eq!(
                preflight_xml(payload.as_bytes()),
                Err(MuxError::InvalidPlist)
            );
        }
    }
}
