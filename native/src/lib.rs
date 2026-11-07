use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, PartialEq, Eq, Deserialize, Serialize)]
#[serde(default)]
pub struct Preferences {
    pub background_enabled: bool,
    pub notifications_enabled: bool,
    pub show_previews: bool,
    pub audio_enabled: bool,
    pub audio_device_id: String,
    pub notification_device_id: String,
    pub categories: Vec<String>,
    pub tour_complete: bool,
}
impl Default for Preferences {
    fn default() -> Self {
        Self {
            background_enabled: false,
            notifications_enabled: false,
            show_previews: false,
            audio_enabled: true,
            audio_device_id: String::new(),
            notification_device_id: String::new(),
            categories: vec!["calls".into(), "messages".into()],
            tour_complete: false,
        }
    }
}
impl Preferences {
    pub fn accepts(&self, category: u8) -> bool {
        self.notifications_enabled && self.categories.iter().any(|x| x == category_key(category))
    }
}
pub fn category_key(category: u8) -> &'static str {
    match category {
        1 | 2 => "calls",
        4 => "messages",
        5 => "calendar",
        6 => "mail",
        _ => "other",
    }
}
pub fn category_label(category: u8) -> &'static str {
    match category {
        1 => "Incoming call",
        2 => "Missed call",
        4 => "Message or social notification",
        5 => "Calendar notification",
        6 => "Mail notification",
        _ => "iPhone notification",
    }
}
#[derive(Debug, Clone, Copy)]
pub struct Notice {
    pub uid: u32,
    pub category: u8,
    pub removed: bool,
}
pub fn parse_notice(bytes: &[u8]) -> Option<Notice> {
    if bytes.len() != 8 || bytes[0] > 2 || (bytes[1] & 0x10) != 0 {
        return None;
    }
    Some(Notice {
        uid: u32::from_le_bytes(bytes[4..8].try_into().ok()?),
        category: bytes[2],
        removed: bytes[0] == 2,
    })
}
pub fn request_attributes(uid: u32) -> Vec<u8> {
    let mut b = vec![0];
    b.extend(uid.to_le_bytes());
    b.extend([1, 128, 0, 3, 0, 2]);
    b
}
/// ANCS Data Source fragments are NOT complete messages. Bound every length,
/// correlate the UID, and wait for both requested attributes before displaying.
#[derive(Default)]
pub struct AttributeBuffer {
    bytes: Vec<u8>,
}
impl AttributeBuffer {
    pub fn push(
        &mut self,
        data: &[u8],
        uid: u32,
    ) -> Result<Option<(String, String)>, &'static str> {
        if self.bytes.len() + data.len() > 2048 {
            self.bytes.clear();
            return Err("Notification exceeds limit");
        }
        self.bytes.extend(data);
        if self.bytes.len() < 5 {
            return Ok(None);
        }
        if self.bytes[0] != 0 || self.bytes[1..5] != uid.to_le_bytes() {
            self.bytes.clear();
            return Err("Unexpected notification response");
        }
        let mut pos = 5;
        let (mut title, mut body) = (None, None);
        while pos < self.bytes.len() {
            if pos + 3 > self.bytes.len() {
                return Ok(None);
            }
            let kind = self.bytes[pos];
            let len = u16::from_le_bytes([self.bytes[pos + 1], self.bytes[pos + 2]]) as usize;
            if ![1, 3].contains(&kind) || len > 512 || (kind == 1 && len > 128) {
                self.bytes.clear();
                return Err("Invalid notification attribute");
            }
            pos += 3;
            if pos + len > self.bytes.len() {
                return Ok(None);
            }
            let value = String::from_utf8_lossy(&self.bytes[pos..pos + len]).into_owned();
            match kind {
                1 => title = Some(value),
                3 => body = Some(value),
                _ => unreachable!(),
            };
            pos += len;
        }
        if let (Some(title), Some(body)) = (title, body) {
            self.bytes.clear();
            Ok(Some((title, body)))
        } else {
            Ok(None)
        }
    }
}
pub fn xml_escape(s: &str) -> String {
    s.chars()
        .filter(|c| {
            *c == '\n'
                || *c == '\r'
                || *c == '\t'
                || (*c >= ' ' && *c != '\u{fffe}' && *c != '\u{ffff}')
        })
        .map(|c| match c {
            '&' => "&amp;".into(),
            '<' => "&lt;".into(),
            '>' => "&gt;".into(),
            '"' => "&quot;".into(),
            '\'' => "&apos;".into(),
            _ => c.to_string(),
        })
        .collect()
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn defaults_are_opt_in() {
        let p = Preferences::default();
        assert!(!p.background_enabled);
        assert!(!p.notifications_enabled);
        assert!(!p.show_previews);
        assert!(!p.accepts(1));
    }
    #[test]
    fn categories_and_preexisting_are_filtered() {
        let mut p = Preferences::default();
        p.notifications_enabled = true;
        assert!(p.accepts(1));
        assert!(p.accepts(2));
        assert!(p.accepts(4));
        assert!(!p.accepts(6));
        assert!(parse_notice(&[0, 16, 4, 1, 0, 0, 0, 0]).is_none());
        assert!(parse_notice(&[0; 7]).is_none());
    }
    #[test]
    fn every_fragment_boundary_is_supported() {
        let mut b = vec![0, 7, 0, 0, 0, 1, 3, 0];
        b.extend(b"Ada");
        b.extend([3, 5, 0]);
        b.extend(b"Hello");
        for split in 1..b.len() {
            let mut a = AttributeBuffer::default();
            assert!(a.push(&b[..split], 7).unwrap().is_none());
            assert_eq!(
                a.push(&b[split..], 7).unwrap(),
                Some(("Ada".into(), "Hello".into()))
            );
        }
    }
    #[test]
    fn wrong_uid_and_oversized_attributes_are_rejected() {
        let mut a = AttributeBuffer::default();
        assert!(a.push(&[0, 8, 0, 0, 0], 7).is_err());
        assert!(a.push(&[0, 7, 0, 0, 0, 3, 255, 255], 7).is_err());
        assert!(a.push(&[0; 2049], 7).is_err());
    }
    #[test]
    fn phone_text_cannot_become_toast_markup() {
        assert_eq!(xml_escape("a<&\"\u{0}"), "a&lt;&amp;&quot;");
    }
}
