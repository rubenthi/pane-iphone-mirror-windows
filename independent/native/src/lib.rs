//! First-party bounded frame storage for an unreleased independent prototype.
//! There is no decoder, transport, or phone connection in this crate.

/// A validated, tightly packed BGRA image. Each pixel occupies four bytes.
#[derive(Debug)]
pub struct Frame {
    width: u32,
    height: u32,
    pixels: Box<[u8]>,
}

impl Frame {
    pub fn width(&self) -> u32 {
        self.width
    }

    pub fn height(&self) -> u32 {
        self.height
    }

    pub fn pixels(&self) -> &[u8] {
        &self.pixels
    }
}

#[derive(Debug, PartialEq, Eq)]
pub enum FrameError {
    EmptyDimensions,
    SizeOverflow,
    TooLarge,
    IncorrectLength,
}

/// A one-slot mailbox: a new valid frame immediately drops its obsolete predecessor.
///
/// Stored pixel memory never exceeds `max_frame_bytes`. During a submission, one
/// old and one new allocation can coexist (at most twice that pixel budget).
/// Submission transfers ownership without allocating or copying pixel bytes.
/// Producer allocations and frames returned by `take` are outside this mailbox's
/// budget. A future producer/consumer may share this
/// mailbox behind a mutex. It does not poll or create a thread by itself.
pub struct LatestFrameQueue {
    max_frame_bytes: usize,
    pending: Option<Frame>,
}

impl LatestFrameQueue {
    pub fn new(max_frame_bytes: usize) -> Self {
        Self {
            max_frame_bytes,
            pending: None,
        }
    }

    /// Move a validated image into the slot. Returns whether a frame was replaced.
    /// Rejected submissions drop the supplied buffer and leave the pending frame untouched.
    pub fn submit(
        &mut self,
        width: u32,
        height: u32,
        pixels: Box<[u8]>,
    ) -> Result<bool, FrameError> {
        if width == 0 || height == 0 {
            return Err(FrameError::EmptyDimensions);
        }
        let bytes = (width as usize)
            .checked_mul(height as usize)
            .and_then(|n| n.checked_mul(4))
            .ok_or(FrameError::SizeOverflow)?;
        if bytes > self.max_frame_bytes {
            return Err(FrameError::TooLarge);
        }
        if pixels.len() != bytes {
            return Err(FrameError::IncorrectLength);
        }
        let replacement = Frame {
            width,
            height,
            pixels,
        };
        Ok(self.pending.replace(replacement).is_some())
    }

    pub fn take(&mut self) -> Option<Frame> {
        self.pending.take()
    }

    pub fn pending_bytes(&self) -> usize {
        self.pending.as_ref().map_or(0, |frame| frame.pixels.len())
    }
}

/// Convert logical 96-DPI units into physical pixels with nearest rounding.
pub fn scale(logical: i32, dpi: u32) -> i32 {
    ((i64::from(logical) * i64::from(dpi) + 48) / 96) as i32
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keeps_only_the_latest_pending_frame() {
        let mut queue = LatestFrameQueue::new(16);
        assert!(!queue.submit(1, 1, Box::new([1; 4])).unwrap());
        assert!(queue.submit(2, 1, Box::new([2; 8])).unwrap());
        let frame = queue.take().unwrap();
        assert_eq!((frame.width(), frame.height()), (2, 1));
        assert_eq!(frame.pixels(), &[2; 8]);
        assert!(queue.take().is_none());
        assert_eq!(queue.pending_bytes(), 0);
    }

    #[test]
    fn sustained_submissions_do_not_accumulate_frames() {
        let mut queue = LatestFrameQueue::new(64);
        for n in 0..10_000 {
            queue.submit(4, 4, Box::new([n as u8; 64])).unwrap();
            assert_eq!(queue.pending_bytes(), 64);
        }
        assert_eq!(queue.take().unwrap().pixels(), &[9_999_u32 as u8; 64]);
    }

    #[test]
    fn rejects_invalid_input_without_losing_the_pending_frame() {
        let mut queue = LatestFrameQueue::new(16);
        queue.submit(1, 1, Box::new([7; 4])).unwrap();
        assert_eq!(
            queue.submit(3, 2, Box::new([0; 24])),
            Err(FrameError::TooLarge)
        );
        assert_eq!(
            queue.submit(2, 2, Box::new([0; 15])),
            Err(FrameError::IncorrectLength)
        );
        assert_eq!(
            queue.submit(0, 1, Box::new([])),
            Err(FrameError::EmptyDimensions)
        );
        assert_eq!(
            queue.submit(u32::MAX, u32::MAX, Box::new([])),
            Err(FrameError::SizeOverflow)
        );
        assert_eq!(queue.take().unwrap().pixels(), &[7; 4]);
    }

    #[test]
    fn includes_the_exact_budget_boundary() {
        let mut queue = LatestFrameQueue::new(16);
        queue.submit(2, 2, Box::new([0; 16])).unwrap();
        assert_eq!(queue.pending_bytes(), 16);
        assert_eq!(
            LatestFrameQueue::new(0).submit(1, 1, Box::new([0; 4])),
            Err(FrameError::TooLarge)
        );
    }

    #[test]
    fn transfers_the_pixel_allocation_without_a_copy() {
        let mut queue = LatestFrameQueue::new(16);
        let pixels: Box<[u8]> = Box::new([5; 16]);
        let original_pointer = pixels.as_ptr();
        queue.submit(2, 2, pixels).unwrap();
        let frame = queue.take().unwrap();
        assert_eq!(original_pointer, frame.pixels().as_ptr());
    }

    #[test]
    fn converts_100_and_200_percent_layout_units() {
        assert_eq!(scale(620, 96), 620);
        assert_eq!(scale(620, 192), 1240);
        assert_eq!(scale(15, 144), 23);
    }
}
