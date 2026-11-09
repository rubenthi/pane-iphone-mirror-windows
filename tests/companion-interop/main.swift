import Foundation

// Drive the real Companion file state machine on its owning main queue. stdin
// replaces only the authenticated BLE command delivery in this local test.
let phone = try Companion(testDirectory: URL(fileURLWithPath: CommandLine.arguments[1]))
DispatchQueue.global().async {
    while let line = readLine() {
        DispatchQueue.main.sync {
            do {
                let object = try JSONSerialization.jsonObject(with: Data(line.utf8)) as! [String: Any]
                let response = try phone.transferOperation(object)
                let encoded = try JSONSerialization.data(withJSONObject: response)
                FileHandle.standardOutput.write(encoded + Data([10]))
            } catch {
                FileHandle.standardError.write(Data("\(error)\n".utf8))
                exit(2)
            }
        }
    }
    exit(0)
}
dispatchMain()

