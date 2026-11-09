import CoreMedia
import Foundation

enum HEVC {
    static func units(from sample: CMSampleBuffer) throws -> [Data] {
        guard let format = CMSampleBufferGetFormatDescription(sample),
              let block = CMSampleBufferGetDataBuffer(sample) else { throw LinkError.invalid("Missing HEVC buffer") }
        var headerWidth: Int32 = 0
        var parameterCount = 0
        let parsed = CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(format, parameterSetIndex: 0,
            parameterSetPointerOut: nil, parameterSetSizeOut: nil, parameterSetCountOut: &parameterCount,
            nalUnitHeaderLengthOut: &headerWidth)
        guard parsed == noErr, (1...4).contains(headerWidth), (1...16).contains(parameterCount) else {
            throw LinkError.invalid("Invalid HEVC format")
        }
        var units = [Data]()
        let flags = CMSampleBufferGetSampleAttachmentsArray(sample, createIfNecessary: false) as? [[CFString: Any]]
        if flags?.first?[kCMSampleAttachmentKey_NotSync] as? Bool != true {
            for i in 0..<parameterCount {
                var pointer: UnsafePointer<UInt8>?
                var count = 0
                let result = CMVideoFormatDescriptionGetHEVCParameterSetAtIndex(format, parameterSetIndex: i,
                    parameterSetPointerOut: &pointer, parameterSetSizeOut: &count,
                    parameterSetCountOut: nil, nalUnitHeaderLengthOut: nil)
                guard result == noErr, let pointer, (2...65535).contains(count) else { throw LinkError.invalid("Invalid HEVC configuration") }
                units.append(Data(bytes: pointer, count: count))
            }
        }
        let length = CMBlockBufferGetDataLength(block)
        guard (2...4_194_304).contains(length) else { throw LinkError.invalid("Invalid HEVC frame size") }
        var data = Data(count: length)
        let copied = data.withUnsafeMutableBytes { dest in
            CMBlockBufferCopyDataBytes(block, atOffset: 0, dataLength: length, destination: dest.baseAddress!)
        }
        guard copied == noErr else { throw LinkError.invalid("Unreadable HEVC frame") }
        var start = 0
        while start < length {
            let payload = start + Int(headerWidth)
            guard payload <= length else { throw LinkError.invalid("Truncated HEVC length") }
            let count = Int(data[start..<payload].unsignedValue())
            guard count >= 2, count <= length - payload, units.count < 4096 else { throw LinkError.invalid("Invalid HEVC payload") }
            units.append(data.subdata(in: payload..<(payload + count)))
            start = payload + count
        }
        return units
    }
}
