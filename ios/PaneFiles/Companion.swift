import Foundation
import CoreBluetooth
import CryptoKit
import Combine

private let commandID = CBUUID(string: "8a5d1001-7b44-4b1b-9bb6-a42e447a0001")
private let responseID = CBUUID(string: "8a5d1002-7b44-4b1b-9bb6-a42e447a0001")
private let fileLimit = 2 * 1024 * 1024 * 1024
private let paneFileManager = FileManager.default

struct Pairing: Codable {
    let version: Int
    let token: String
    let peerName: String
    let service: String
}

struct SharedFile: Codable, Identifiable {
    let id: String
    let name: String
    let size: Int
    let sha256: String
}

private struct Incoming {
    let file: SharedFile
    let url: URL
    let handle: FileHandle
    var offset: Int
    var hash = SHA256()
}

private struct TransferError: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

final class Companion: NSObject, ObservableObject, CBPeripheralManagerDelegate {
    @Published var status = "Activate the USB link to pair."
    @Published var activity = ""
    @Published var isConnected = false
    @Published var isPaired = false
    @Published var sendProgress: [String: Double] = [:]
    @Published var receiveProgress: Double?
    @Published var outgoing: [SharedFile] = []
    @Published var received: [URL] = []
    private var pairing: Pairing?
    private var manager: CBPeripheralManager!
    private var response: CBMutableCharacteristic?
    private var authorized: UUID?
    private var buffers: [UUID: Data] = [:]
    private var notifications: [(Data, CBCentral)] = []
    private var incoming: Incoming?
    private let documents = paneFileManager.urls(for: .documentDirectory, in: .userDomainMask)[0]
    private let support = paneFileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    private var sentFolder: URL { support.appendingPathComponent("Outbox") }
    private var inbox: URL { documents.appendingPathComponent("Received") }
    private var queueManifest: URL { support.appendingPathComponent("queue.json") }

    override init() {
        super.init()
        do {
            try paneFileManager.createDirectory(at: sentFolder, withIntermediateDirectories: true)
            try paneFileManager.createDirectory(at: inbox, withIntermediateDirectories: true)
            if let data = try? Data(contentsOf: queueManifest), let queue = try? JSONDecoder().decode([SharedFile].self, from: data) {
                outgoing = queue.filter { paneFileManager.fileExists(atPath: sentFolder.appendingPathComponent($0.id).path) }
            }
            if let data = try? Data(contentsOf: support.appendingPathComponent("pairing.json")) {
                pairing = try JSONDecoder().decode(Pairing.self, from: data)
                isPaired = true
            }
            refreshReceived()
        } catch { activity = error.localizedDescription }
        if isPaired { manager = CBPeripheralManager(delegate: self, queue: .main) }
    }

    func activatePendingUSB() {
        if paneFileManager.fileExists(atPath: documents.appendingPathComponent("pane-pairing.json").path) { activateUSB() }
    }

    func activateUSB() {
        do {
            let source = documents.appendingPathComponent("pane-pairing.json")
            let data = try Data(contentsOf: source)
            let newPairing = try JSONDecoder().decode(Pairing.self, from: data)
            guard newPairing.version == 1, newPairing.token.count == 64,
                  UUID(uuidString: newPairing.service) != nil,
                  newPairing.peerName.hasPrefix("Pane-"), newPairing.peerName.count <= 20 else {
                throw TransferError(message: "Invalid USB pairing. Bind again from your laptop.")
            }
            try data.write(to: support.appendingPathComponent("pairing.json"), options: [.atomic, .completeFileProtection])
            try paneFileManager.removeItem(at: source)
            pairing = newPairing
            isPaired = true
            isConnected = false
            authorized = nil
            buffers.removeAll(); notifications.removeAll()
            discardIncoming()
            if manager == nil {
                manager = CBPeripheralManager(delegate: self, queue: .main)
            } else {
                advertise()
            }
            activity = "USB pairing loaded. Connect Bluetooth from Pane on your laptop. Wi-Fi mirroring is controlled there."
        } catch {
            activity = "Keep USB connected and choose Bind USB & Wi-Fi on the laptop first. \(error.localizedDescription)"
        }
    }

    @MainActor func queueFile(_ source: URL) async throws {
        guard outgoing.count < 8 else { throw TransferError(message: "Send or remove queued files first (maximum 8).") }
        let id = UUID().uuidString
        let destination = sentFolder.appendingPathComponent(id)
        let file = try await Task.detached(priority: .userInitiated) {
            let values = try source.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
            guard values.isRegularFile == true, let size = values.fileSize, size <= fileLimit else {
                throw TransferError(message: "Choose a regular file up to 2 GB.")
            }
            do {
                try paneFileManager.copyItem(at: source, to: destination)
                return SharedFile(id: id, name: source.lastPathComponent, size: size, sha256: try Self.hashFile(destination))
            } catch {
                try? paneFileManager.removeItem(at: destination)
                throw error
            }
        }.value
        outgoing.append(file)
        do { try saveQueue() }
        catch {
            outgoing.removeAll { $0.id == id }
            try? paneFileManager.removeItem(at: destination)
            throw error
        }
        activity = "Queued \(file.name). Keep Pane open."
    }

    func removeOutgoing(at offsets: IndexSet) {
        for index in offsets.sorted(by: >) {
            let item = outgoing.remove(at: index)
            try? paneFileManager.removeItem(at: sentFolder.appendingPathComponent(item.id))
        }
        do { try saveQueue() } catch { activity = error.localizedDescription }
    }

    private func saveQueue() throws {
        try JSONEncoder().encode(outgoing).write(to: queueManifest, options: .atomic)
    }

    func refreshReceived() {
        let candidates: [URL] = (try? paneFileManager.contentsOfDirectory(at: inbox, includingPropertiesForKeys: [.isRegularFileKey])) ?? []
        let regularFiles = candidates.filter { url in
            guard !url.lastPathComponent.hasPrefix(".") else { return false }
            let values = try? url.resourceValues(forKeys: [.isRegularFileKey])
            return values?.isRegularFile == true
        }
        received = regularFiles.sorted { $0.lastPathComponent.localizedStandardCompare($1.lastPathComponent) == .orderedAscending }
    }

    private static func hashFile(_ url: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        var hash = SHA256()
        while let data = try handle.read(upToCount: 256 * 1024), !data.isEmpty { hash.update(data: data) }
        return hash.finalize().map { String(format: "%02x", $0) }.joined()
    }

    private func advertise() {
        guard manager.state == .poweredOn else { status = "Turn on Bluetooth and allow access in Settings."; return }
        manager.stopAdvertising()
        manager.removeAllServices()
        guard let pairing else { status = "Activate the USB link to pair."; return }
        let command = CBMutableCharacteristic(type: commandID, properties: [.write], value: nil, permissions: [.writeEncryptionRequired])
        let replies = CBMutableCharacteristic(type: responseID, properties: [.notify, .notifyEncryptionRequired], value: nil, permissions: [.readEncryptionRequired])
        let service = CBMutableService(type: CBUUID(string: pairing.service), primary: true)
        service.characteristics = [command, replies]
        response = replies
        manager.add(service)
        status = "Ready for \(pairing.peerName). Keep this app open."
    }

    func peripheralManagerDidUpdateState(_ peripheral: CBPeripheralManager) {
        authorized = nil; isConnected = false; buffers.removeAll(); notifications.removeAll(); discardIncoming()
        if peripheral.state == .poweredOn { advertise() }
        else { status = "Bluetooth unavailable. Enable it and allow Pane in Settings." }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        if let error { status = error.localizedDescription; return }
        guard let pairing else { return }
        peripheral.startAdvertising([CBAdvertisementDataServiceUUIDsKey: [CBUUID(string: pairing.service)], CBAdvertisementDataLocalNameKey: pairing.peerName])
    }

    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        if let error { status = error.localizedDescription }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didUnsubscribeFrom characteristic: CBCharacteristic) {
        buffers.removeValue(forKey: central.identifier)
        notifications.removeAll { $0.1.identifier == central.identifier }
        if authorized == central.identifier { authorized = nil; isConnected = false; discardIncoming(); status = "Laptop disconnected. Reconnect from Pane." }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didReceiveWrite requests: [CBATTRequest]) {
        for request in requests {
            guard request.characteristic.uuid == commandID, request.offset == 0, let value = request.value else {
                peripheral.respond(to: request, withResult: .requestNotSupported); continue
            }
            let id = request.central.identifier
            guard buffers[id] != nil || buffers.count < 4 else {
                peripheral.respond(to: request, withResult: .insufficientResources); continue
            }
            buffers[id, default: Data()].append(value)
            guard buffers[id]!.count <= 65536 else {
                buffers[id] = nil
                peripheral.respond(to: request, withResult: .invalidAttributeValueLength); continue
            }
            peripheral.respond(to: request, withResult: .success)
            while let end = buffers[id]?.firstIndex(of: 10) {
                let frame = Data(buffers[id]!.prefix(upTo: end))
                buffers[id]!.removeSubrange(...end)
                process(frame, central: request.central)
            }
        }
    }

    private func process(_ frame: Data, central: CBCentral) {
        var requestID = 0
        var reply: [String: Any]
        do {
            guard let body = try JSONSerialization.jsonObject(with: frame) as? [String: Any], let number = body["request"] as? Int else {
                throw TransferError(message: "Invalid request.")
            }
            requestID = number
            reply = try handle(body, central: central)
        } catch {
            reply = ["error": error.localizedDescription]
            activity = error.localizedDescription
        }
        reply["request"] = requestID
        guard var data = try? JSONSerialization.data(withJSONObject: reply) else { return }
        data.append(10)
        guard data.count <= 65536, notifications.count < 1024 else { return }
        let size = max(1, central.maximumUpdateValueLength)
        for start in stride(from: 0, to: data.count, by: size) {
            notifications.append((data.subdata(in: start..<min(data.count, start + size)), central))
        }
        flushNotifications()
    }

    private func flushNotifications() {
        guard let response else { return }
        while let next = notifications.first {
            guard manager.updateValue(next.0, for: response, onSubscribedCentrals: [next.1]) else { return }
            notifications.removeFirst()
        }
    }

    func peripheralManagerIsReady(toUpdateSubscribers peripheral: CBPeripheralManager) { flushNotifications() }

    private func handle(_ body: [String: Any], central: CBCentral) throws -> [String: Any] {
        let op = body["op"] as? String ?? ""
        if op == "hello" {
            guard let expected = pairing?.token, let supplied = body["token"] as? String,
                  expected.utf8.count == supplied.utf8.count,
                  zip(expected.utf8, supplied.utf8).reduce(UInt8(0), { $0 | ($1.0 ^ $1.1) }) == 0 else {
                throw TransferError(message: "USB pairing does not match. Bind again using the cable.")
            }
            if let authorized, authorized != central.identifier { throw TransferError(message: "Another laptop is connected.") }
            authorized = central.identifier
            isConnected = true
            status = "Connected to your laptop over Bluetooth."
            return ["version": 1]
        }
        guard authorized == central.identifier else { throw TransferError(message: "Pair over USB first.") }
        switch op {
        case "list":
            return ["files": try JSONSerialization.jsonObject(with: JSONEncoder().encode(outgoing))]
        case "read":
            guard let id = body["id"] as? String, let file = outgoing.first(where: { $0.id == id }),
                  let offset = body["offset"] as? Int, let length = body["length"] as? Int,
                  offset >= 0, length > 0, length <= 4096, offset <= file.size, length <= file.size - offset else {
                throw TransferError(message: "Invalid file range.")
            }
            let handle = try FileHandle(forReadingFrom: sentFolder.appendingPathComponent(file.id))
            defer { try? handle.close() }
            try handle.seek(toOffset: UInt64(offset))
            let data = try handle.read(upToCount: length) ?? Data()
            sendProgress[file.id] = file.size == 0 ? 1 : Double(offset + data.count) / Double(file.size)
            activity = "Sending \(file.name): \(file.size == 0 ? 100 : (offset + data.count) * 100 / file.size)%"
            return ["data": data.base64EncodedString()]
        case "received":
            guard let id = body["id"] as? String else { throw TransferError(message: "Missing file ID.") }
            if let index = outgoing.firstIndex(where: { $0.id == id }) {
                let file = outgoing.remove(at: index)
                sendProgress.removeValue(forKey: file.id)
                try saveQueue()
                try? paneFileManager.removeItem(at: sentFolder.appendingPathComponent(file.id))
                activity = "Saved \(file.name) to laptop Downloads."
            }
            return ["ok": true]
        case "begin":
            guard let id = body["id"] as? String, id.count == 32, id.allSatisfy({ $0.isHexDigit }),
                  let rawName = body["name"] as? String, let size = body["size"] as? Int, size >= 0, size <= fileLimit,
                  let hash = body["sha256"] as? String, hash.count == 64, hash.allSatisfy({ $0.isHexDigit }) else {
                throw TransferError(message: "Invalid incoming file.")
            }
            discardIncoming()
            let name = Self.safeName(rawName)
            let file = SharedFile(id: id, name: name, size: size, sha256: hash.lowercased())
            let target = support.appendingPathComponent("incoming.part")
            try Data().write(to: target)
            receiveProgress = 0
            incoming = Incoming(file: file, url: target, handle: try FileHandle(forWritingTo: target), offset: 0)
            return ["ok": true]
        case "write":
            guard var current = incoming, body["id"] as? String == current.file.id,
                  let offset = body["offset"] as? Int, offset == current.offset,
                  let text = body["data"] as? String, let data = Data(base64Encoded: text),
                  !data.isEmpty, data.count <= 4096, data.count <= current.file.size - current.offset else {
                throw TransferError(message: "Incoming chunk is out of order or too large.")
            }
            try current.handle.write(contentsOf: data)
            current.hash.update(data: data)
            current.offset += data.count
            incoming = current
            receiveProgress = current.file.size == 0 ? 1 : Double(current.offset) / Double(current.file.size)
            activity = "Receiving \(current.file.name): \(current.file.size == 0 ? 100 : current.offset * 100 / current.file.size)%"
            return ["offset": current.offset]
        case "finish":
            guard let current = incoming, body["id"] as? String == current.file.id, current.offset == current.file.size else {
                throw TransferError(message: "Incoming file is incomplete.")
            }
            try current.handle.synchronize(); try current.handle.close()
            let hash = current.hash.finalize().map { String(format: "%02x", $0) }.joined()
            guard hash == current.file.sha256 else { discardIncoming(); throw TransferError(message: "File verification failed. Send again.") }
            let destination = availableName(current.file.name)
            try paneFileManager.moveItem(at: current.url, to: destination)
            incoming = nil
            receiveProgress = nil
            refreshReceived()
            activity = "Received \(destination.lastPathComponent)."
            return ["ok": true]
        default:
            throw TransferError(message: "Unknown file operation.")
        }
    }

    private func discardIncoming() {
        if let incoming { try? incoming.handle.close(); try? paneFileManager.removeItem(at: incoming.url) }
        incoming = nil
        receiveProgress = nil
    }

    private static func safeName(_ name: String) -> String {
        let sanitized = name.components(separatedBy: CharacterSet(charactersIn: "/\\:\0\r\n")).joined(separator: "_")
            .trimmingCharacters(in: CharacterSet(charactersIn: ". "))
        return sanitized.isEmpty ? "File" : String(sanitized.prefix(180))
    }

    private func availableName(_ name: String) -> URL {
        var target = inbox.appendingPathComponent(name)
        let base = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        var count = 1
        while paneFileManager.fileExists(atPath: target.path) {
            target = inbox.appendingPathComponent("\(base) (\(count))" + (ext.isEmpty ? "" : ".\(ext)"))
            count += 1
        }
        return target
    }
}
