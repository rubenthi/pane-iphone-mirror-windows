import Foundation

func require(_ result: Bool, _ message: String) {
    guard result else { fatalError(message) }
}

let zeroKey = Data(repeating: 0, count: 32)
let client = Data(0..<32)
let server = Data(32..<64)
func cipher(_ label: String = "PNFT1-C") -> RecordCipher {
    RecordCipher(secret: zeroKey, label: label, client: client, server: server)
}
var writer = cipher()
var reader = cipher()
let sealed = try writer.seal(Data([2]))
let hex = sealed.map { String(format: "%02x", $0) }.joined()
require(hex == "000000014ecbe012323e578ece0ad58876a60db536", "Windows peer cipher vector")
let opened = try reader.open(Data(sealed.dropFirst(4)))
require(opened == Data([2]), "record decrypt")
require((try? reader.open(Data(sealed.dropFirst(4)))) == nil, "reject sequence replay")
var wrongDomain = cipher("PNVM1-C")
require((try? wrongDomain.open(Data(sealed.dropFirst(4)))) == nil, "reject cross-protocol replay")
for name in ["../x", "a/b", "CON.txt", "com9", "a.", "a ", ".hidden", "À", "LPT1 .x"] {
    require((try? FileRules.checked(name)) == nil, "unsafe name accepted: \(name)")
}
require((try? FileRules.checked("File 21_A-7.txt")) == "File 21_A-7.txt", "portable name")
require(Data(secretHex: String(repeating: "aF", count: 32))?.count == 32, "key parser")
require(Data(secretHex: String(repeating: "g1", count: 32)) == nil, "non-hex key")
var rtp = Packetizer(sequence: 65534, source: 3)
let large = Data([0x26, 1]) + Data(repeating: 0xab, count: 1900)
let packets = try rtp.packets(units: [Data([0x40, 1, 0]), large], timestamp: 90000)
require(packets.count == 3 && packets.allSatisfy { $0.count <= 1200 }, "RTP fragmentation")
require(packets[0][1] == 96 && packets[1][1] == 96 && packets[2][1] == 224, "RTP marker")
require(packets[1][14] == 0x93 && packets[2][14] == 0x53, "FU start/end")
require(packets[2][2..<4].unsignedValue() == 0, "RTP rollover")
require(Data(packets[1].dropFirst(15)) + Data(packets[2].dropFirst(15)) == large.dropFirst(2), "RTP payload")
print("Independent companion protocol tests passed")

