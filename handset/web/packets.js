// Reuse a bounded buffer instead of copying the entire partial frame per read.
(function(root) {
  class PanePacketReader {
    constructor(maxPacket = 32 * 1024 * 1024) {
      this.maxPacket = maxPacket;
      this.buffer = new Uint8Array(65536);
      this.start = this.end = 0;
      this.copiedBytes = 0;
    }
    push(chunk, visit) {
      let offset = 0;
      while (offset < chunk.length) {
        if (this.end === this.buffer.length) {
          const used = this.end - this.start;
          if (this.start) {
            this.buffer.copyWithin(0, this.start, this.end);
            this.copiedBytes += used;
          } else {
            const capacity = Math.min(this.maxPacket + 4, this.buffer.length * 2);
            if (capacity <= this.buffer.length) throw Error('Stream packet exceeds limit');
            const next = new Uint8Array(capacity);
            next.set(this.buffer);
            this.copiedBytes += used;
            this.buffer = next;
          }
          this.start = 0;
          this.end = used;
        }
        const n = Math.min(chunk.length - offset, this.buffer.length - this.end);
        this.buffer.set(chunk.subarray(offset, offset + n), this.end);
        this.copiedBytes += n;
        this.end += n;
        offset += n;
        while (this.end - this.start >= 4) {
          const length = new DataView(this.buffer.buffer).getUint32(this.start);
          if (length < 1 || length > this.maxPacket) throw Error('Invalid stream packet length');
          if (this.end - this.start < length + 4) break;
          // The view is valid only during visit; WebCodecs copies on construction.
          visit(this.buffer.subarray(this.start + 4, this.start + 4 + length));
          this.start += 4 + length;
        }
        if (this.start === this.end) this.start = this.end = 0;
      }
    }
    finish() {
      if (this.start !== this.end) throw Error('Truncated stream packet');
    }
  }
  root.PanePacketReader = PanePacketReader;
  if (typeof module !== 'undefined') module.exports = PanePacketReader;
})(typeof window === 'undefined' ? globalThis : window);
