import Foundation
import VideoToolbox

@main struct Fixture {
    static func main() throws {
        let width = 320, height = 240
        var session: VTCompressionSession?
        try check(VTCompressionSessionCreate(allocator: nil, width: Int32(width), height: Int32(height),
            codecType: kCMVideoCodecType_HEVC, encoderSpecification: nil, imageBufferAttributes: nil,
            compressedDataAllocator: nil, outputCallback: nil, refcon: nil, compressionSessionOut: &session))
        guard let session else { throw LinkError.invalid("No HEVC encoder") }
        defer { VTCompressionSessionInvalidate(session) }
        try check(VTSessionSetProperty(session, key: kVTCompressionPropertyKey_AllowFrameReordering, value: kCFBooleanFalse))
        try check(VTSessionSetProperty(session, key: kVTCompressionPropertyKey_MaxKeyFrameInterval, value: NSNumber(value: 10)))
        var packetizer = Packetizer(sequence: 0, source: 12345)
        var output = Data()
        // Each entry is a big-endian u32 length and one plaintext PNVM1 record.
        func append(_ record: Data) { output.append(Data.networkOrder(UInt32(record.count))); output.append(record) }
        append(Data([0x20]) + Data.networkOrder(UInt16(width)) + Data.networkOrder(UInt16(height)))
        for index in 0..<30 {
            var buffer: CVPixelBuffer?
            try check(CVPixelBufferCreate(nil, width, height, kCVPixelFormatType_32BGRA,
                [kCVPixelBufferIOSurfacePropertiesKey: [:]] as CFDictionary, &buffer))
            guard let buffer else { throw LinkError.invalid("No pixel buffer") }
            try check(CVPixelBufferLockBaseAddress(buffer, []))
            let stride = CVPixelBufferGetBytesPerRow(buffer) / 4
            let pixels = CVPixelBufferGetBaseAddress(buffer)!.assumingMemoryBound(to: UInt32.self)
            let color: UInt32 = [0xffff0000, 0xff00ff00, 0xff0000ff][index / 10]
            for y in 0..<height { for x in 0..<width { pixels[y * stride + x] = color } }
            CVPixelBufferUnlockBaseAddress(buffer, [])
            let time = CMTime(value: Int64(index), timescale: 10)
            var result: Result<[Data], Error>?
            try check(VTCompressionSessionEncodeFrame(session, imageBuffer: buffer, presentationTimeStamp: time,
                duration: CMTime(value: 1, timescale: 10), frameProperties: nil, infoFlagsOut: nil) { status, _, sample in
                result = Result {
                    try check(status)
                    guard let sample else { throw LinkError.invalid("No encoded sample") }
                    return try HEVC.units(from: sample)
                }
            })
            try check(VTCompressionSessionCompleteFrames(session, untilPresentationTimeStamp: time))
            guard let result else { throw LinkError.invalid("Missing fixture frame") }
            for packet in try packetizer.packets(units: result.get(), timestamp: UInt32(index * 9000)) {
                append(Data([0x21, 1]) + packet)
            }
        }
        try output.write(to: URL(fileURLWithPath: "build/colors.pnvm"), options: .atomic)
    }

    static func check(_ status: OSStatus) throws {
        if status != noErr { throw LinkError.invalid("VideoToolbox fixture failed (\(status))") }
    }
}
