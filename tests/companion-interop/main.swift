import Foundation

// Drive the real Companion file state machine on its owning main queue. stdin
// replaces only the authenticated BLE command delivery in this local test.
let folder = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let phone = try Companion(testDirectory: folder)
try FileManager.default.createDirectory(at: folder.appendingPathComponent("Outbox"), withIntermediateDirectories: true)
DispatchQueue.global().async {
    while let line = readLine() {
        let finished = DispatchSemaphore(value: 0)
        Task { @MainActor in
            defer { finished.signal() }
            do {
                let object = try JSONSerialization.jsonObject(with: Data(line.utf8)) as! [String: Any]
                let response: [String: Any]
                switch object["op"] as? String {
                case "fixture-queue-received":
                    guard let name = object["name"] as? String,
                          let url = phone.received.first(where: { $0.lastPathComponent == name }) else {
                        throw CocoaError(.fileReadNoSuchFile)
                    }
                    try await phone.queueFile(url)
                    response = ["ok": true]
                case "fixture-control":
                    guard let id = object["id"] as? String, let action = object["action"] as? String else {
                        throw CocoaError(.coderInvalidValue)
                    }
                    phone.controlTransfer(id, action: action)
                    response = ["state": phone.transferState(id)]
                default:
                    response = try phone.transferOperation(object)
                }
                let encoded = try JSONSerialization.data(withJSONObject: response)
                FileHandle.standardOutput.write(encoded + Data([10]))
            } catch {
                FileHandle.standardError.write(Data("\(error)\n".utf8))
                exit(2)
            }
        }
        finished.wait()
    }
    exit(0)
}
dispatchMain()

