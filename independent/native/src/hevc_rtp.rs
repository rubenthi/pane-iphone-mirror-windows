//! Bounded HEVC/RTP depacketization, written independently from the wire formats.
//!
//! References: RFC 3550 section 5.1 and RFC 7798 sections 4.1, 4.4, and 6:
//! <https://www.rfc-editor.org/rfc/rfc3550.html>
//! <https://www.rfc-editor.org/rfc/rfc7798.html>
//!
//! This is a single-source, no-DONL (`sprop-max-don-diff=0`) receiver. It accepts
//! single NAL units, aggregation packets, and fragmentation units. It emits one
//! Annex B access unit per RTP marker, preserving parameter sets and NAL order.
//! It does not decode video, inspect slice syntax, reorder packets, repair loss,
//! infer missing markers, or implement RTCP, SRTP, PACI, or multi-stream HEVC.
//!
//! Loss, an unseen late packet, or malformed input invalidates the partial AU.
//! Recovery waits for a new timestamp and a complete NAL or FU start. The first
//! packet after construction/reset must already be at an AU boundary; RTP has
//! no explicit AU-start flag, so an omitted prefix cannot be detected there.
//! A timestamp change drops an unfinished AU. After a marker, further packets
//! with the same timestamp are ignored. RTP timestamps may otherwise decrease
//! (for example, with picture reordering); sequence numbers establish order.
//!
//! One SSRC is configured or latched. A different SSRC is rejected; call `reset`
//! to deliberately adopt a new source or a sender whose sequence counter reset.
//! Sequence comparisons assume fewer than 32,768 packets of ambiguity. There is
//! no network I/O, dependency, unbounded queue, or parameter-set cache here.

use std::fmt;

const START_CODE: [u8; 4] = [0, 0, 0, 1];
pub const MAX_PACKET_BYTES: usize = 65_535;
pub const MAX_ACCESS_UNIT_BYTES: usize = 64 * 1024 * 1024;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RtpConfig {
    pub payload_type: u8,
    /// None latches the first accepted RTP header's SSRC until reset.
    pub expected_ssrc: Option<u32>,
    /// Negotiated SDP value. Only zero is supported; DONL cannot be autodetected.
    pub sprop_max_don_diff: u16,
    /// Complete RTP datagram, including header, extensions, and padding.
    pub max_packet_bytes: usize,
    /// Annex B output, including every four-byte start code and NAL header.
    pub max_access_unit_bytes: usize,
}

impl Default for RtpConfig {
    fn default() -> Self {
        Self {
            payload_type: 96,
            expected_ssrc: None,
            sprop_max_don_diff: 0,
            max_packet_bytes: MAX_PACKET_BYTES,
            max_access_unit_bytes: 8 * 1024 * 1024,
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct AccessUnit {
    pub annex_b: Vec<u8>,
    /// Original 90 kHz RTP timestamp; no wall-clock conversion is performed.
    pub rtp_timestamp: u32,
    pub ssrc: u32,
    /// Header classification only; this does not promise independent decoding.
    pub contains_irap: bool,
    pub contains_vps: bool,
    pub contains_sps: bool,
    pub contains_pps: bool,
    /// An incoming forbidden_zero_bit was set; bytes are preserved verbatim.
    pub has_forbidden_bit: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RtpError {
    InvalidConfig(&'static str),
    PacketTooLarge { size: usize, limit: usize },
    MalformedRtp(&'static str),
    UnexpectedPayloadType { expected: u8, actual: u8 },
    UnexpectedSsrc { expected: u32, actual: u32 },
    SequenceGap { expected: u16, actual: u16 },
    OutOfOrder { last: u16, actual: u16 },
    InvalidNal(&'static str),
    UnsupportedNalType(u8),
    MalformedAggregation(&'static str),
    MalformedFragment(&'static str),
    AccessUnitTooLarge { limit: usize },
    AllocationFailed,
}

impl fmt::Display for RtpError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "HEVC/RTP: {self:?}")
    }
}

impl std::error::Error for RtpError {}

#[derive(Debug, Default, Clone, Copy)]
struct NalFlags {
    irap: bool,
    vps: bool,
    sps: bool,
    pps: bool,
    forbidden: bool,
}

impl NalFlags {
    fn include(&mut self, header: NalHeader) {
        let ty = header.nal_type();
        self.irap |= (16..=21).contains(&ty);
        self.vps |= ty == 32;
        self.sps |= ty == 33;
        self.pps |= ty == 34;
        self.forbidden |= header.0[0] & 0x80 != 0;
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct NalHeader([u8; 2]);

impl NalHeader {
    fn parse(bytes: &[u8]) -> Result<Self, RtpError> {
        if bytes.len() < 2 {
            return Err(RtpError::InvalidNal("truncated two-byte header"));
        }
        if bytes[1] & 7 == 0 {
            return Err(RtpError::InvalidNal("temporal_id_plus1 is zero"));
        }
        Ok(Self([bytes[0], bytes[1]]))
    }

    fn nal_type(self) -> u8 {
        (self.0[0] >> 1) & 0x3f
    }

    fn layer(self) -> u8 {
        ((self.0[0] & 1) << 5) | (self.0[1] >> 3)
    }

    fn validate_nal(self) -> Result<Self, RtpError> {
        match self.nal_type() {
            0..=9 | 16..=21 | 32..=40 => Ok(self),
            ty => Err(RtpError::UnsupportedNalType(ty)),
        }
    }
}

struct RtpPacket<'a> {
    sequence: u16,
    timestamp: u32,
    ssrc: u32,
    marker: bool,
    payload: &'a [u8],
}

fn parse_rtp<'a>(bytes: &'a [u8], config: &RtpConfig) -> Result<RtpPacket<'a>, RtpError> {
    if bytes.len() > config.max_packet_bytes {
        return Err(RtpError::PacketTooLarge {
            size: bytes.len(),
            limit: config.max_packet_bytes,
        });
    }
    if bytes.len() < 12 {
        return Err(RtpError::MalformedRtp("truncated fixed header"));
    }
    if bytes[0] >> 6 != 2 {
        return Err(RtpError::MalformedRtp("version is not two"));
    }
    let pt = bytes[1] & 0x7f;
    if pt != config.payload_type {
        return Err(RtpError::UnexpectedPayloadType {
            expected: config.payload_type,
            actual: pt,
        });
    }
    let mut offset = 12 + usize::from(bytes[0] & 15) * 4;
    if offset > bytes.len() {
        return Err(RtpError::MalformedRtp("truncated CSRC list"));
    }
    if bytes[0] & 0x10 != 0 {
        if bytes.len() - offset < 4 {
            return Err(RtpError::MalformedRtp("truncated extension header"));
        }
        let words = usize::from(u16::from_be_bytes([bytes[offset + 2], bytes[offset + 3]]));
        // The wire length is u16 words, so these additions cannot overflow usize.
        offset += 4 + words * 4;
        if offset > bytes.len() {
            return Err(RtpError::MalformedRtp("truncated extension data"));
        }
    }
    let mut end = bytes.len();
    if bytes[0] & 0x20 != 0 {
        let padding = usize::from(bytes[bytes.len() - 1]);
        if padding == 0 || padding > end - offset {
            return Err(RtpError::MalformedRtp("invalid padding count"));
        }
        end -= padding;
    }
    if end - offset < 2 {
        return Err(RtpError::MalformedRtp("missing HEVC payload header"));
    }
    Ok(RtpPacket {
        sequence: u16::from_be_bytes([bytes[2], bytes[3]]),
        timestamp: u32::from_be_bytes([bytes[4], bytes[5], bytes[6], bytes[7]]),
        ssrc: u32::from_be_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]),
        marker: bytes[1] & 0x80 != 0,
        payload: &bytes[offset..end],
    })
}

enum Payload<'a> {
    Single {
        nal: &'a [u8],
        header: NalHeader,
    },
    Aggregation {
        body: &'a [u8],
        size: usize,
    },
    Fragment {
        body: &'a [u8],
        header: NalHeader,
        start: bool,
        end: bool,
    },
}

fn parse_payload(payload: &[u8], limit: usize) -> Result<Payload<'_>, RtpError> {
    let header = NalHeader::parse(payload)?;
    match header.nal_type() {
        48 => {
            let body = &payload[2..];
            let mut offset = 0;
            let mut count = 0;
            let mut size: usize = 0;
            let mut min_layer = 63;
            let mut min_tid = 7;
            let mut forbidden = false;
            // Validate the entire AP before allocating or appending any NAL.
            while offset < body.len() {
                if body.len() - offset < 2 {
                    return Err(RtpError::MalformedAggregation("truncated NAL size"));
                }
                let len = usize::from(u16::from_be_bytes([body[offset], body[offset + 1]]));
                offset += 2;
                if len < 2 || len > body.len() - offset {
                    return Err(RtpError::MalformedAggregation("invalid NAL size"));
                }
                let nal_header = NalHeader::parse(&body[offset..offset + len])?.validate_nal()?;
                min_layer = min_layer.min(nal_header.layer());
                min_tid = min_tid.min(nal_header.0[1] & 7);
                forbidden |= nal_header.0[0] & 0x80 != 0;
                size = size
                    .checked_add(4 + len)
                    .filter(|&n| n <= limit)
                    .ok_or(RtpError::AccessUnitTooLarge { limit })?;
                offset += len;
                count += 1;
            }
            if count < 2 {
                return Err(RtpError::MalformedAggregation("fewer than two NAL units"));
            }
            if header.layer() != min_layer
                || header.0[1] & 7 != min_tid
                || (header.0[0] & 0x80 != 0) != forbidden
            {
                return Err(RtpError::MalformedAggregation(
                    "inconsistent aggregate header",
                ));
            }
            Ok(Payload::Aggregation { body, size })
        }
        49 => {
            if payload.len() < 4 {
                return Err(RtpError::MalformedFragment(
                    "missing FU header or fragment data",
                ));
            }
            let fu = payload[2];
            let start = fu & 0x80 != 0;
            let end = fu & 0x40 != 0;
            if start && end {
                return Err(RtpError::MalformedFragment("start and end both set"));
            }
            let original =
                NalHeader([(payload[0] & 0x81) | ((fu & 0x3f) << 1), payload[1]]).validate_nal()?;
            Ok(Payload::Fragment {
                body: &payload[3..],
                header: original,
                start,
                end,
            })
        }
        _ => Ok(Payload::Single {
            nal: payload,
            header: header.validate_nal()?,
        }),
    }
}

/// Stateful depacketizer. Bounds apply to input length and retained/output AU
/// length; ownership of emitted AUs passes to the caller, which must bound its
/// own queues. Allocation failure is returned rather than deliberately panicked.
#[derive(Debug)]
pub struct HevcRtpDepacketizer {
    config: RtpConfig,
    ssrc: Option<u32>,
    last_sequence: Option<u16>,
    /// A 64-packet receive history distinguishes recent duplicates from late
    /// packets that were never accepted. It allocates no per-packet storage.
    sequence_history: u64,
    timestamp: Option<u32>,
    sealed: bool,
    fragment: Option<NalHeader>,
    buffer: Vec<u8>,
    flags: NalFlags,
}

impl HevcRtpDepacketizer {
    pub fn new(config: RtpConfig) -> Result<Self, RtpError> {
        if config.payload_type > 127 {
            return Err(RtpError::InvalidConfig("payload type exceeds seven bits"));
        }
        if config.sprop_max_don_diff != 0 {
            return Err(RtpError::InvalidConfig(
                "DONL/decoding-order interleaving is unsupported",
            ));
        }
        if !(14..=MAX_PACKET_BYTES).contains(&config.max_packet_bytes) {
            return Err(RtpError::InvalidConfig(
                "packet bound must be 14..=65,535 bytes",
            ));
        }
        if !(6..=MAX_ACCESS_UNIT_BYTES).contains(&config.max_access_unit_bytes) {
            return Err(RtpError::InvalidConfig(
                "access-unit bound must be 6 bytes..=64 MiB",
            ));
        }
        Ok(Self {
            ssrc: config.expected_ssrc,
            config,
            last_sequence: None,
            sequence_history: 0,
            timestamp: None,
            sealed: false,
            fragment: None,
            buffer: Vec::new(),
            flags: NalFlags::default(),
        })
    }

    /// Discard all stream state. A configured SSRC remains configured; an
    /// automatically latched SSRC will be learned again from the next packet.
    pub fn reset(&mut self) {
        self.ssrc = self.config.expected_ssrc;
        self.last_sequence = None;
        self.sequence_history = 0;
        self.timestamp = None;
        self.clear_au();
        self.sealed = false;
    }

    fn clear_au(&mut self) {
        self.buffer.clear();
        self.fragment = None;
        self.flags = NalFlags::default();
    }

    fn invalidate(&mut self) {
        self.clear_au();
        self.sealed = true;
    }

    fn reserve(&mut self, additional: usize) -> Result<(), RtpError> {
        let limit = self.config.max_access_unit_bytes;
        let new_len = self
            .buffer
            .len()
            .checked_add(additional)
            .filter(|&len| len <= limit)
            .ok_or(RtpError::AccessUnitTooLarge { limit })?;
        if new_len > self.buffer.capacity() {
            // Geometric growth avoids quadratic copying for tiny fragments.
            // Reserve against len, not capacity; cap every requested capacity
            // so a non-power-of-two budget is respected as well.
            let capacity = new_len
                .max(self.buffer.capacity().saturating_mul(2))
                .min(limit);
            self.buffer
                .try_reserve_exact(capacity - self.buffer.len())
                .map_err(|_| RtpError::AllocationFailed)?;
        }
        Ok(())
    }

    /// Process one complete RTP datagram. `Ok(None)` also covers duplicates and
    /// the remainder of an invalidated timestamp. Every error discards the
    /// partial AU; packets are never buffered for subsequent reordering.
    pub fn ingest(&mut self, bytes: &[u8]) -> Result<Option<AccessUnit>, RtpError> {
        let result = self.ingest_inner(bytes);
        if result.is_err() {
            self.invalidate();
        }
        result
    }

    fn ingest_inner(&mut self, bytes: &[u8]) -> Result<Option<AccessUnit>, RtpError> {
        let packet = parse_rtp(bytes, &self.config)?;
        if let Some(expected) = self.ssrc {
            if packet.ssrc != expected {
                return Err(RtpError::UnexpectedSsrc {
                    expected,
                    actual: packet.ssrc,
                });
            }
        } else {
            self.ssrc = Some(packet.ssrc);
        }

        if let Some(last) = self.last_sequence {
            let delta = packet.sequence.wrapping_sub(last);
            if delta == 0 {
                return Ok(None);
            }
            if delta >= 32_768 {
                let behind = usize::from(last.wrapping_sub(packet.sequence));
                if behind < 64 && self.sequence_history & (1u64 << behind) != 0 {
                    return Ok(None);
                }
                return Err(RtpError::OutOfOrder {
                    last,
                    actual: packet.sequence,
                });
            }
            self.sequence_history = if delta < 64 {
                (self.sequence_history << delta) | 1
            } else {
                1
            };
            self.last_sequence = Some(packet.sequence);
            if delta != 1 {
                // The gap may include the start of this incoming timestamp.
                // Do not treat a later intact NAL as a complete access unit.
                self.timestamp = Some(packet.timestamp);
                return Err(RtpError::SequenceGap {
                    expected: last.wrapping_add(1),
                    actual: packet.sequence,
                });
            }
        } else {
            self.last_sequence = Some(packet.sequence);
            self.sequence_history = 1;
        }

        if self.timestamp != Some(packet.timestamp) {
            self.clear_au();
            self.timestamp = Some(packet.timestamp);
            self.sealed = false;
        }
        if self.sealed {
            return Ok(None);
        }

        let payload = parse_payload(packet.payload, self.config.max_access_unit_bytes)?;
        match payload {
            Payload::Single { nal, header } => {
                if self.fragment.is_some() {
                    return Err(RtpError::MalformedFragment(
                        "NAL interrupted an unfinished FU",
                    ));
                }
                self.reserve(4 + nal.len())?;
                self.buffer.extend_from_slice(&START_CODE);
                self.buffer.extend_from_slice(nal);
                self.flags.include(header);
            }
            Payload::Aggregation { body, size } => {
                if self.fragment.is_some() {
                    return Err(RtpError::MalformedFragment(
                        "AP interrupted an unfinished FU",
                    ));
                }
                self.reserve(size)?;
                let mut offset = 0;
                while offset < body.len() {
                    // The complete AP was validated before this append pass.
                    let len = usize::from(u16::from_be_bytes([body[offset], body[offset + 1]]));
                    offset += 2;
                    let nal = &body[offset..offset + len];
                    self.buffer.extend_from_slice(&START_CODE);
                    self.buffer.extend_from_slice(nal);
                    self.flags.include(NalHeader([nal[0], nal[1]]));
                    offset += len;
                }
            }
            Payload::Fragment {
                body,
                header,
                start,
                end,
            } => {
                if start {
                    if self.fragment.is_some() {
                        return Err(RtpError::MalformedFragment(
                            "FU start interrupted an unfinished FU",
                        ));
                    }
                    self.reserve(6 + body.len())?;
                    self.buffer.extend_from_slice(&START_CODE);
                    self.buffer.extend_from_slice(&header.0);
                    self.flags.include(header);
                    self.fragment = Some(header);
                } else {
                    if self.fragment != Some(header) {
                        return Err(RtpError::MalformedFragment(
                            "missing FU start or mismatched NAL header",
                        ));
                    }
                    self.reserve(body.len())?;
                }
                self.buffer.extend_from_slice(body);
                if end {
                    self.fragment = None;
                }
            }
        }

        if !packet.marker {
            return Ok(None);
        }
        if self.fragment.is_some() {
            return Err(RtpError::MalformedFragment("marker before FU end"));
        }
        let flags = self.flags;
        let annex_b = std::mem::take(&mut self.buffer);
        self.clear_au();
        self.sealed = true;
        Ok(Some(AccessUnit {
            annex_b,
            rtp_timestamp: packet.timestamp,
            ssrc: packet.ssrc,
            contains_irap: flags.irap,
            contains_vps: flags.vps,
            contains_sps: flags.sps,
            contains_pps: flags.pps,
            has_forbidden_bit: flags.forbidden,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn packet(seq: u16, ts: u32, marker: bool, payload: &[u8]) -> Vec<u8> {
        let mut bytes = vec![0x80, 96 | if marker { 0x80 } else { 0 }];
        bytes.extend_from_slice(&seq.to_be_bytes());
        bytes.extend_from_slice(&ts.to_be_bytes());
        bytes.extend_from_slice(&123u32.to_be_bytes());
        bytes.extend_from_slice(payload);
        bytes
    }

    fn nal(ty: u8, data: &[u8]) -> Vec<u8> {
        let mut result = vec![ty << 1, 1];
        result.extend_from_slice(data);
        result
    }

    fn ap(nals: &[Vec<u8>]) -> Vec<u8> {
        let mut result = vec![48 << 1, 1];
        for nal in nals {
            result.extend_from_slice(&(nal.len() as u16).to_be_bytes());
            result.extend_from_slice(nal);
        }
        result
    }

    fn annex(nals: &[Vec<u8>]) -> Vec<u8> {
        let mut result = Vec::new();
        for nal in nals {
            result.extend_from_slice(&START_CODE);
            result.extend_from_slice(nal);
        }
        result
    }

    fn receiver() -> HevcRtpDepacketizer {
        HevcRtpDepacketizer::new(RtpConfig::default()).unwrap()
    }

    #[test]
    fn single_and_multiple_nals_keep_parameter_sets_and_irap() {
        let mut r = receiver();
        let nals = [
            nal(32, &[0x11]),
            nal(33, &[0x22]),
            nal(34, &[0x33]),
            nal(19, &[0x80, 0x44]),
        ];
        for (i, n) in nals.iter().enumerate() {
            let au = r.ingest(&packet(i as u16, 9000, i == 3, n)).unwrap();
            if i < 3 {
                assert!(au.is_none());
            } else {
                let au = au.unwrap();
                assert_eq!(au.annex_b, annex(&nals));
                assert_eq!(au.rtp_timestamp, 9000);
                assert_eq!(au.ssrc, 123);
                assert!(au.contains_irap && au.contains_vps && au.contains_sps && au.contains_pps);
                assert!(!au.has_forbidden_bit);
            }
        }
    }

    #[test]
    fn aggregation_outputs_every_nal_in_order() {
        let nals = [
            nal(32, &[1, 2]),
            nal(33, &[3]),
            nal(34, &[4]),
            nal(21, &[0x80]),
        ];
        let au = receiver()
            .ingest(&packet(42, 10, true, &ap(&nals)))
            .unwrap()
            .unwrap();
        assert_eq!(au.annex_b, annex(&nals));
        assert!(au.contains_irap && au.contains_vps && au.contains_sps && au.contains_pps);
    }

    #[test]
    fn fu_reconstructs_exact_header_and_payload_across_sequence_rollover() {
        let mut r = receiver();
        // F=1, layer=37, TID=3, type=19. Both layer-ID portions must survive.
        let indicator = [0x80 | (49 << 1) | 1, (5 << 3) | 3];
        assert!(
            r.ingest(&packet(
                65535,
                7,
                false,
                &[indicator[0], indicator[1], 0x80 | 19, 0xaa]
            ))
            .unwrap()
            .is_none()
        );
        assert!(
            r.ingest(&packet(
                0,
                7,
                false,
                &[indicator[0], indicator[1], 19, 0xbb]
            ))
            .unwrap()
            .is_none()
        );
        let au = r
            .ingest(&packet(
                1,
                7,
                true,
                &[indicator[0], indicator[1], 0x40 | 19, 0xcc],
            ))
            .unwrap()
            .unwrap();
        assert_eq!(
            au.annex_b,
            vec![
                0,
                0,
                0,
                1,
                0x80 | (19 << 1) | 1,
                (5 << 3) | 3,
                0xaa,
                0xbb,
                0xcc
            ]
        );
        assert!(au.has_forbidden_bit && au.contains_irap);
    }

    #[test]
    fn loss_drops_entire_timestamp_and_recovers_at_next() {
        let mut r = receiver();
        assert!(
            r.ingest(&packet(10, 1, false, &[98, 1, 0x81, 0xaa]))
                .unwrap()
                .is_none()
        );
        assert_eq!(
            r.ingest(&packet(12, 1, true, &[98, 1, 0x41, 0xcc])),
            Err(RtpError::SequenceGap {
                expected: 11,
                actual: 12
            })
        );
        assert!(
            r.ingest(&packet(13, 1, true, &nal(1, &[0xdd])))
                .unwrap()
                .is_none()
        );
        let au = r
            .ingest(&packet(14, 2, true, &nal(1, &[0xee])))
            .unwrap()
            .unwrap();
        assert_eq!(au.annex_b, annex(&[nal(1, &[0xee])]));
    }

    #[test]
    fn gap_at_new_timestamp_does_not_emit_a_possible_suffix() {
        let mut r = receiver();
        assert!(
            r.ingest(&packet(1, 1, true, &nal(1, &[1])))
                .unwrap()
                .is_some()
        );
        assert!(matches!(
            r.ingest(&packet(3, 2, false, &nal(1, &[2]))),
            Err(RtpError::SequenceGap { .. })
        ));
        assert!(
            r.ingest(&packet(4, 2, true, &nal(1, &[3])))
                .unwrap()
                .is_none()
        );
        assert!(
            r.ingest(&packet(5, 3, true, &nal(1, &[4])))
                .unwrap()
                .is_some()
        );
    }

    #[test]
    fn duplicate_packets_never_append_or_redeliver() {
        let mut r = receiver();
        let first = packet(10, 1, false, &nal(32, &[1]));
        let second = packet(11, 1, true, &nal(19, &[2]));
        assert!(r.ingest(&first).unwrap().is_none());
        assert!(r.ingest(&first).unwrap().is_none());
        let expected = annex(&[nal(32, &[1]), nal(19, &[2])]);
        assert_eq!(r.ingest(&second).unwrap().unwrap().annex_b, expected);
        assert!(r.ingest(&second).unwrap().is_none());
        assert!(r.ingest(&first).unwrap().is_none());
        assert!(
            r.ingest(&packet(12, 1, true, &nal(19, &[2])))
                .unwrap()
                .is_none()
        );
    }

    #[test]
    fn unseen_late_packet_invalidates_partial_au_without_rewinding_sequence() {
        let mut r = receiver();
        assert!(
            r.ingest(&packet(10, 1, false, &nal(32, &[1])))
                .unwrap()
                .is_none()
        );
        assert!(matches!(
            r.ingest(&packet(9, 1, false, &nal(33, &[2]))),
            Err(RtpError::OutOfOrder { .. })
        ));
        assert!(
            r.ingest(&packet(11, 1, true, &nal(19, &[3])))
                .unwrap()
                .is_none()
        );
        assert!(
            r.ingest(&packet(12, 2, true, &nal(19, &[4])))
                .unwrap()
                .is_some()
        );
    }

    #[test]
    fn timestamp_change_drops_unfinished_fu_and_allows_timestamp_wrap_or_decrease() {
        let mut r = receiver();
        assert!(
            r.ingest(&packet(1, u32::MAX, false, &[98, 1, 0x81, 0xaa]))
                .unwrap()
                .is_none()
        );
        let au = r
            .ingest(&packet(2, 0, true, &nal(1, &[9])))
            .unwrap()
            .unwrap();
        assert_eq!(au.annex_b, annex(&[nal(1, &[9])]));
        assert!(
            r.ingest(&packet(3, 100, true, &nal(1, &[1])))
                .unwrap()
                .is_some()
        );
        assert!(
            r.ingest(&packet(4, 90, true, &nal(1, &[2])))
                .unwrap()
                .is_some()
        );
    }

    #[test]
    fn malformed_ap_is_atomic_and_does_not_leave_a_prefix() {
        let mut r = receiver();
        let mut bad = ap(&[nal(32, &[1]), nal(33, &[2])]);
        bad.push(0);
        assert!(matches!(
            r.ingest(&packet(1, 1, false, &bad)),
            Err(RtpError::MalformedAggregation(_))
        ));
        assert!(r.buffer.is_empty());
        assert!(
            r.ingest(&packet(2, 1, true, &nal(19, &[3])))
                .unwrap()
                .is_none()
        );
        assert_eq!(
            r.ingest(&packet(3, 2, true, &nal(19, &[4])))
                .unwrap()
                .unwrap()
                .annex_b,
            annex(&[nal(19, &[4])])
        );
    }

    #[test]
    fn malformed_ap_lengths_and_nested_packetization_are_rejected() {
        for bad in [
            vec![96, 1],
            vec![96, 1, 0],
            vec![96, 1, 0, 0],
            vec![96, 1, 0, 1, 0],
            vec![96, 1, 0, 20, 64, 1],
            ap(&[nal(32, &[1])]),
            ap(&[nal(48, &[1]), nal(33, &[2])]),
            ap(&[nal(49, &[1]), nal(33, &[2])]),
        ] {
            assert!(
                receiver().ingest(&packet(1, 1, true, &bad)).is_err(),
                "{bad:?}"
            );
        }
    }

    #[test]
    fn ap_header_must_match_aggregate_layer_tid_and_forbidden_fields() {
        let nals = [vec![64 | 1, (5 << 3) | 2, 1], vec![66 | 1, (7 << 3) | 3, 2]];
        let mut payload = ap(&nals);
        payload[0] |= 1;
        payload[1] = (5 << 3) | 2;
        assert!(
            receiver()
                .ingest(&packet(1, 1, true, &payload))
                .unwrap()
                .is_some()
        );
        for (index, value) in [(0, 96), (1, 1), (0, payload[0] | 0x80)] {
            let mut bad = payload.clone();
            bad[index] = value;
            assert!(matches!(
                receiver().ingest(&packet(1, 1, true, &bad)),
                Err(RtpError::MalformedAggregation(_))
            ));
        }
    }

    #[test]
    fn fu_requires_matching_header_nonempty_data_and_complete_marker() {
        for bad in [
            vec![98, 1, 0x81],
            vec![98, 1, 0xc1, 1],
            vec![98, 1, 0x41, 1],
            vec![98, 1, 0x80 | 48, 1],
        ] {
            assert!(receiver().ingest(&packet(1, 1, true, &bad)).is_err());
        }
        for continuation in [
            vec![98, 2, 0x41, 2],
            vec![98, 1, 0x42, 2],
            nal(1, &[2]),
            ap(&[nal(32, &[1]), nal(33, &[2])]),
            vec![98, 1, 0x81, 2],
        ] {
            let mut r = receiver();
            r.ingest(&packet(1, 1, false, &[98, 1, 0x81, 1])).unwrap();
            assert!(matches!(
                r.ingest(&packet(2, 1, true, &continuation)),
                Err(RtpError::MalformedFragment(_))
            ));
            assert!(r.buffer.is_empty());
        }
        assert!(matches!(
            receiver().ingest(&packet(1, 1, true, &[98, 1, 0x81, 1])),
            Err(RtpError::MalformedFragment(_))
        ));
    }

    #[test]
    fn complete_fu_can_be_followed_by_another_nal_before_marker() {
        let mut r = receiver();
        r.ingest(&packet(1, 1, false, &[98, 1, 0x81, 1])).unwrap();
        r.ingest(&packet(2, 1, false, &[98, 1, 0x41, 2])).unwrap();
        let au = r
            .ingest(&packet(3, 1, true, &nal(40, &[3])))
            .unwrap()
            .unwrap();
        assert_eq!(au.annex_b, annex(&[nal(1, &[1, 2]), nal(40, &[3])]));
    }

    #[test]
    fn reserved_paci_and_invalid_temporal_id_are_rejected() {
        for ty in (10..=15).chain(22..=31).chain(41..=47).chain(50..=63) {
            assert_eq!(
                receiver().ingest(&packet(1, 1, true, &nal(ty, &[1]))),
                Err(RtpError::UnsupportedNalType(ty))
            );
        }
        assert!(matches!(
            receiver().ingest(&packet(1, 1, true, &[2, 0, 1])),
            Err(RtpError::InvalidNal(_))
        ));
    }

    #[test]
    fn csrc_extension_and_padding_are_not_part_of_nal() {
        let mut p = packet(1, 2, true, &[]);
        p[0] = 0x80 | 0x20 | 0x10 | 2;
        p.extend_from_slice(&[0; 8]);
        p.extend_from_slice(&[0xbe, 0xde, 0, 2]);
        p.extend_from_slice(&[0xaa; 8]);
        p.extend_from_slice(&nal(19, &[0x80, 0x55]));
        p.extend_from_slice(&[0x99, 0x99, 0x99, 4]);
        assert_eq!(
            receiver().ingest(&p).unwrap().unwrap().annex_b,
            annex(&[nal(19, &[0x80, 0x55])])
        );
        // An empty extension is also legal.
        let mut p = packet(1, 2, true, &[]);
        p[0] |= 0x10;
        p.extend_from_slice(&[0, 0, 0, 0]);
        p.extend_from_slice(&nal(1, &[1]));
        assert!(receiver().ingest(&p).unwrap().is_some());
    }

    #[test]
    fn malformed_rtp_headers_padding_and_extensions_are_rejected() {
        let base = packet(1, 2, true, &nal(1, &[1]));
        for len in 0..14 {
            assert!(receiver().ingest(&base[..len]).is_err());
        }
        for first in [0x40, 0xc0, 0x8f, 0x90, 0xa0] {
            let mut p = base.clone();
            p[0] = first;
            if first == 0xa0 {
                *p.last_mut().unwrap() = 0;
            }
            assert!(receiver().ingest(&p).is_err());
        }
        for count in [4, 255] {
            let mut p = base.clone();
            p[0] |= 0x20;
            *p.last_mut().unwrap() = count;
            assert!(receiver().ingest(&p).is_err());
        }
        let mut huge_extension = packet(1, 1, false, &[0, 0, 255, 255]);
        huge_extension[0] |= 0x10;
        assert!(receiver().ingest(&huge_extension).is_err());
    }

    #[test]
    fn packet_and_access_unit_bounds_apply_before_append() {
        let mut r = HevcRtpDepacketizer::new(RtpConfig {
            max_packet_bytes: 15,
            max_access_unit_bytes: 7,
            ..RtpConfig::default()
        })
        .unwrap();
        assert!(matches!(
            r.ingest(&packet(1, 1, true, &nal(1, &[1, 2]))),
            Err(RtpError::PacketTooLarge { .. })
        ));
        assert!(r.buffer.is_empty());
        r.reset();
        assert_eq!(
            r.ingest(&packet(1, 1, true, &nal(1, &[1])))
                .unwrap()
                .unwrap()
                .annex_b
                .len(),
            7
        );
        let mut r = HevcRtpDepacketizer::new(RtpConfig {
            max_access_unit_bytes: 13,
            ..RtpConfig::default()
        })
        .unwrap();
        r.ingest(&packet(1, 1, false, &nal(32, &[1]))).unwrap();
        assert_eq!(
            r.ingest(&packet(2, 1, true, &nal(1, &[2]))),
            Err(RtpError::AccessUnitTooLarge { limit: 13 })
        );
        assert!(r.buffer.is_empty());
        assert_eq!(
            r.ingest(&packet(3, 2, true, &ap(&[nal(32, &[1]), nal(33, &[2])]))),
            Err(RtpError::AccessUnitTooLarge { limit: 13 })
        );
        assert!(r.buffer.is_empty());
    }

    #[test]
    fn fragmented_access_unit_cannot_grow_past_bound() {
        let mut r = HevcRtpDepacketizer::new(RtpConfig {
            max_access_unit_bytes: 8,
            ..RtpConfig::default()
        })
        .unwrap();
        r.ingest(&packet(1, 1, false, &[98, 1, 0x81, 1])).unwrap();
        assert_eq!(
            r.ingest(&packet(2, 1, true, &[98, 1, 0x41, 2, 3])),
            Err(RtpError::AccessUnitTooLarge { limit: 8 })
        );
        assert!(r.buffer.is_empty());
    }

    #[test]
    fn lazy_geometric_capacity_is_capped_at_non_power_of_two_limit() {
        let limit = 19;
        let mut r = HevcRtpDepacketizer::new(RtpConfig {
            max_access_unit_bytes: limit,
            ..RtpConfig::default()
        })
        .unwrap();
        assert_eq!(r.buffer.capacity(), 0);
        for timestamp in 0..50 {
            let first = timestamp as u16 * 13;
            r.ingest(&packet(first, timestamp, false, &[98, 1, 0x81, 1]))
                .unwrap();
            for n in 1..12 {
                r.ingest(&packet(first + n, timestamp, false, &[98, 1, 1, 1]))
                    .unwrap();
                assert!(r.buffer.capacity() <= limit);
            }
            let au = r
                .ingest(&packet(first + 12, timestamp, true, &[98, 1, 0x41, 1]))
                .unwrap()
                .unwrap();
            assert_eq!(au.annex_b.len(), limit);
            assert!(au.annex_b.capacity() <= limit);
            // Completion moves the allocation rather than retaining/cloning it.
            assert_eq!(r.buffer.capacity(), 0);
            // Duplicate end fragment is ignored and performs no allocation.
            assert!(
                r.ingest(&packet(first + 12, timestamp, true, &[98, 1, 0x41, 1]))
                    .unwrap()
                    .is_none()
            );
            assert_eq!(r.buffer.capacity(), 0);
        }
    }

    #[test]
    fn source_and_payload_type_changes_reject_and_reset_is_explicit() {
        let mut r = receiver();
        r.ingest(&packet(1, 1, false, &nal(32, &[1]))).unwrap();
        let mut other = packet(2, 1, true, &nal(19, &[2]));
        other[8..12].copy_from_slice(&456u32.to_be_bytes());
        assert_eq!(
            r.ingest(&other),
            Err(RtpError::UnexpectedSsrc {
                expected: 123,
                actual: 456
            })
        );
        assert!(
            r.ingest(&packet(2, 1, true, &nal(19, &[2])))
                .unwrap()
                .is_none()
        );
        r.reset();
        assert_eq!(r.ingest(&other).unwrap().unwrap().ssrc, 456);
        let mut wrong_pt = packet(3, 2, true, &nal(1, &[1]));
        wrong_pt[1] = 0x80 | 97;
        assert_eq!(
            r.ingest(&wrong_pt),
            Err(RtpError::UnexpectedPayloadType {
                expected: 96,
                actual: 97
            })
        );
        let mut locked = HevcRtpDepacketizer::new(RtpConfig {
            expected_ssrc: Some(999),
            ..RtpConfig::default()
        })
        .unwrap();
        assert!(matches!(
            locked.ingest(&other),
            Err(RtpError::UnexpectedSsrc { .. })
        ));
        locked.reset();
        assert!(matches!(
            locked.ingest(&other),
            Err(RtpError::UnexpectedSsrc { .. })
        ));
    }

    #[test]
    fn invalid_configuration_is_rejected_without_allocation() {
        for config in [
            RtpConfig {
                payload_type: 128,
                ..RtpConfig::default()
            },
            RtpConfig {
                sprop_max_don_diff: 1,
                ..RtpConfig::default()
            },
            RtpConfig {
                max_packet_bytes: 13,
                ..RtpConfig::default()
            },
            RtpConfig {
                max_packet_bytes: usize::MAX,
                ..RtpConfig::default()
            },
            RtpConfig {
                max_access_unit_bytes: 5,
                ..RtpConfig::default()
            },
            RtpConfig {
                max_access_unit_bytes: usize::MAX,
                ..RtpConfig::default()
            },
        ] {
            assert!(matches!(
                HevcRtpDepacketizer::new(config),
                Err(RtpError::InvalidConfig(_))
            ));
        }
    }

    #[test]
    fn deterministic_malformed_datagram_corpus_stays_bounded_without_panics() {
        let limit = 257;
        let mut r = HevcRtpDepacketizer::new(RtpConfig {
            max_packet_bytes: 96,
            max_access_unit_bytes: limit,
            ..RtpConfig::default()
        })
        .unwrap();
        let mut state = 0x7a81_25c3u32;
        for case in 0..20_000u32 {
            // A reproducible, dependency-free malformed-input corpus. This is
            // parser regression coverage, not a substitute for external fuzzing.
            state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
            let len = (state as usize) % 128;
            let mut bytes = vec![0; len];
            for byte in &mut bytes {
                state = state.wrapping_mul(1_664_525).wrapping_add(1_013_904_223);
                *byte = (state >> 24) as u8;
            }
            if bytes.len() >= 12 && case % 4 != 0 {
                bytes[0] = 0x80;
                bytes[1] = 96 | if case & 1 != 0 { 0x80 } else { 0 };
                bytes[2..4].copy_from_slice(&(case as u16).to_be_bytes());
                bytes[4..8].copy_from_slice(&(case / 9).to_be_bytes());
                bytes[8..12].copy_from_slice(&123u32.to_be_bytes());
                if bytes.len() >= 14 {
                    bytes[12] = match case % 4 {
                        1 => 96,
                        2 => 98,
                        _ => bytes[12],
                    };
                    bytes[13] |= 1;
                }
            }
            // Reset every other case to exercise payload parsing independently
            // of the streaming receiver's deliberate damaged-timestamp filter.
            if case & 1 == 0 {
                r.reset();
            }
            if let Ok(Some(au)) = r.ingest(&bytes) {
                assert!(au.annex_b.len() <= limit);
                assert!(au.annex_b.capacity() <= limit);
                assert!(au.annex_b.starts_with(&START_CODE));
            }
            assert!(r.buffer.len() <= limit);
            assert!(r.buffer.capacity() <= limit);
        }
    }
}
