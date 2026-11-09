import Foundation

struct Packetizer {
    var sequence = UInt16.random(in: .min ... .max)
    var source = UInt32.random(in: .min ... .max)

    mutating func packets(units: [Data], timestamp: UInt32) throws -> [Data] {
        var result: [Data] = []
        for (index, unit) in units.enumerated() {
            guard unit.count >= 2, unit.count <= 4 * 1024 * 1024 else {
                throw LinkError.invalid("Invalid HEVC NAL unit")
            }
            let finalUnit = index == units.count - 1
            func header(_ marker: Bool, _ sequence: UInt16, _ source: UInt32) -> Data {
                Data([0x80, marker ? 0xe0 : 0x60]) + Data.networkOrder(sequence) +
                    Data.networkOrder(timestamp) + Data.networkOrder(source)
            }
            if unit.count <= 1188 {
                result.append(header(finalUnit, sequence, source) + unit)
                sequence &+= 1
                continue
            }
            let bytes = [UInt8](unit.prefix(2))
            let type = (bytes[0] >> 1) & 0x3f
            var offset = 2
            while offset < unit.count {
                let end = min(offset + 1185, unit.count)
                let last = end == unit.count
                let flags = type | (offset == 2 ? 0x80 : 0) | (last ? 0x40 : 0)
                let fragment = Data([(bytes[0] & 0x81) | (49 << 1), bytes[1], flags])
                result.append(header(finalUnit && last, sequence, source) + fragment + unit[offset..<end])
                sequence &+= 1
                offset = end
            }
        }
        return result
    }
}
