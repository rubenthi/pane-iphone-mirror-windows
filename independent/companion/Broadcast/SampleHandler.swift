import CoreMedia
import ReplayKit
import VideoToolbox

// Hold one frame until its encrypted packets have drained. Dropping input before
// encoding preserves the reference chain when the desktop or network is slow.
final class SampleHandler: RPBroadcastSampleHandler {
    private let lock = NSLock()
    private var ready = false
    private var busy = false
    private var stopped = false
    private var link: Channel?
    private var desktop: Desktop?
    private var requestedSize = CGSize.zero
    private var encoder: VTCompressionSession?
    private var dimensions = CGSize.zero
    private var packetizer = Packetizer()

    override func broadcastStarted(withSetupInfo setupInfo: [String: NSObject]?) {
        do {
            let desktop = try Desktop.load()
            _ = try desktop.validated()
            self.desktop = desktop
        } catch { fail(error) }
    }

    private func connect(_ desktop: Desktop, width: Int, height: Int) {
        do {
            guard let width16 = UInt16(exactly: width), let height16 = UInt16(exactly: height) else {
                throw LinkError.invalid("Unsupported capture dimensions")
            }
            let key = try desktop.validated()
            let channel = try Channel(host: desktop.host, port: desktop.mediaPort)
            lock.withLock { link?.cancel(); link = channel }
            Task {
                do {
                    try await channel.connect(secret: key, protocolID: "PNVM1")
                    try await channel.send(Data([0x20]) + Data.networkOrder(width16) + Data.networkOrder(height16))
                    try await channel.expect(3)
                    lock.withLock { ready = true }
                } catch { fail(error) }
            }
        } catch { fail(error) }
    }

    private func fail(_ error: Error) {
        let report = lock.withLock {
            guard !stopped else { return false }
            stopped = true
            link?.cancel()
            return true
        }
        if report { finishBroadcastWithError(error) }
    }

    override func broadcastFinished() {
        lock.withLock { stopped = true; link?.cancel() }
        if let encoder { VTCompressionSessionInvalidate(encoder) }
        encoder = nil
    }

    override func processSampleBuffer(_ sampleBuffer: CMSampleBuffer, with type: RPSampleBufferType) {
        guard type == .video, let image = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }
        let width = CVPixelBufferGetWidth(image)
        let height = CVPixelBufferGetHeight(image)
        let size = CGSize(width: width, height: height)
        let reconnect = lock.withLock {
            guard !stopped, !busy, size != requestedSize, ready || requestedSize == .zero else { return false }
            ready = false
            requestedSize = size
            return true
        }
        if reconnect, let desktop {
            connect(desktop, width: width, height: height)
            return
        }
        let acquired = lock.withLock {
            guard ready, !stopped, !busy else { return false }
            busy = true
            return true
        }
        guard acquired else { return }

        do {
            if encoder == nil || size != dimensions {
                if let encoder { VTCompressionSessionInvalidate(encoder) }
                encoder = nil
                let status = VTCompressionSessionCreate(allocator: nil, width: Int32(width), height: Int32(height),
                    codecType: kCMVideoCodecType_HEVC, encoderSpecification: nil, imageBufferAttributes: nil,
                    compressedDataAllocator: nil, outputCallback: nil, refcon: nil, compressionSessionOut: &encoder)
                guard status == noErr, let encoder else { throw LinkError.invalid("HEVC encoder unavailable (\(status))") }
                for (key, value) in [(kVTCompressionPropertyKey_RealTime, kCFBooleanTrue as CFTypeRef),
                                    (kVTCompressionPropertyKey_AllowFrameReordering, kCFBooleanFalse as CFTypeRef),
                                    (kVTCompressionPropertyKey_AverageBitRate, NSNumber(value: 5_000_000) as CFTypeRef),
                                    (kVTCompressionPropertyKey_MaxKeyFrameInterval, NSNumber(value: 60) as CFTypeRef)] {
                    let result = VTSessionSetProperty(encoder, key: key, value: value)
                    guard result == noErr else { throw LinkError.invalid("HEVC configuration failed (\(result))") }
                }
                dimensions = size
            }
            guard let encoder else { throw LinkError.invalid("Missing encoder") }
            let attached = CMGetAttachment(sampleBuffer, key: RPVideoSampleOrientationKey as CFString,
                                           attachmentModeOut: nil) as? NSNumber
            let orientation = (1...8).contains(attached?.intValue ?? 0) ? attached!.uint8Value : 1
            let time = CMSampleBufferGetPresentationTimeStamp(sampleBuffer)
            let timestamp = UInt32(truncatingIfNeeded: CMTimeConvertScale(time, timescale: 90000, method: .default).value)
            let status = VTCompressionSessionEncodeFrame(encoder, imageBuffer: image, presentationTimeStamp: time,
                duration: .invalid, frameProperties: nil, infoFlagsOut: nil) { [weak self] status, flags, sample in
                guard let self else { return }
                guard status == noErr else { self.fail(LinkError.invalid("HEVC encoding failed (\(status))")); return }
                guard !flags.contains(.frameDropped), let sample else {
                    self.lock.withLock { self.busy = false }
                    return
                }
                do {
                    let units = try HEVC.units(from: sample)
                    let packets = try self.packetizer.packets(units: units, timestamp: timestamp)
                    guard let channel = self.lock.withLock({ self.link }) else { return }
                    Task {
                        defer { self.lock.withLock { self.busy = false } }
                        do {
                            try await channel.sendVideo(packets: packets, orientation: orientation)
                        } catch { self.fail(error) }
                    }
                } catch { self.fail(error) }
            }
            guard status == noErr else { throw LinkError.invalid("HEVC submission failed (\(status))") }
        } catch { fail(error) }
    }
}
