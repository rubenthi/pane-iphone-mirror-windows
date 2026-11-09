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

// Persist the destination inode before publishing. After a crash between the
// rename and its acknowledgement, the same file proves that the rename ran.
private struct DeliveryReceipt: Codable {
    let file: SharedFile
    let destination: String
    let inode: UInt64
    var published: Bool
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
    @Published var laptopFiles: [SharedFile] = []
    @Published var transferStates: [String: String] = [:]
    @Published var controlsAvailable = false
    private var chunkLimit = 4096
    private var pairing: Pairing?
    private var manager: CBPeripheralManager!
    private var response: CBMutableCharacteristic?
    private var authorized: UUID?
    private var buffers: [UUID: Data] = [:]
    private var notifications: [(Data, CBCentral)] = []
    private var incoming: [String: Incoming] = [:]
    private var bulkUpload: BulkUpload?
    private var bulkUploadID: String?
    private var bulkDownload: BulkUpload?
    private var bulkDownloadID: String?
    private var downloadGeneration = UUID()
    @Published var receiveProgresses: [String: Double] = [:]
    private let documents = paneFileManager.urls(for: .documentDirectory, in: .userDomainMask)[0]
    private let support = paneFileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
    private var fixtureRoot: URL?
    private var sentFolder: URL { (fixtureRoot ?? support).appendingPathComponent("Outbox") }
    private var inbox: URL { (fixtureRoot ?? documents).appendingPathComponent("Received") }
    private var queueManifest: URL { (fixtureRoot ?? support).appendingPathComponent("queue.json") }
    private var receiptFolder: URL { (fixtureRoot ?? support).appendingPathComponent("DeliveryReceipts") }

    private func receiptURL(_ id: String) throws -> URL {
        guard id.utf8.count == 32, id.utf8.allSatisfy({ (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0) }) else {
            throw TransferError(message: "Invalid transfer ID.")
        }
        return receiptFolder.appendingPathComponent(id + ".json")
    }

    private func completed(_ id: String, matching file: SharedFile? = nil) throws -> Bool {
        let url = try receiptURL(id)
        guard paneFileManager.fileExists(atPath: url.path) else { return false }
        let receipt = try JSONDecoder().decode(DeliveryReceipt.self, from: Data(contentsOf: url))
        if let file, file.name != receipt.file.name || file.size != receipt.file.size || file.sha256 != receipt.file.sha256 {
            throw TransferError(message: "This transfer ID describes a different file.")
        }
        if receipt.published { return true }
        let destination = inbox.appendingPathComponent(receipt.destination)
        let attributes = try? paneFileManager.attributesOfItem(atPath: destination.path)
        return (attributes?[.systemFileNumber] as? NSNumber)?.uint64Value == receipt.inode &&
               (attributes?[.size] as? NSNumber)?.intValue == receipt.file.size
    }

    deinit { bulkUpload?.cancel(); bulkDownload?.cancel() }

    private func stopBulkDownload(_ id: String? = nil) {
        guard id == nil || bulkDownloadID == id else { return }
        downloadGeneration = UUID()
        bulkDownload?.cancel()
        bulkDownload = nil
        bulkDownloadID = nil
    }

    func reserveDownload(_ id: String) -> UUID {
        stopBulkDownload()
        bulkDownloadID = id
        return downloadGeneration
    }

    private func stopBulkUpload(_ id: String? = nil) {
        guard id == nil || bulkUploadID == id else { return }
        bulkUpload?.cancel()
        bulkUpload = nil
        bulkUploadID = nil
    }

    #if DEBUG
    init(testDirectory: URL) throws {
        super.init()
        fixtureRoot = testDirectory
        try paneFileManager.createDirectory(at: inbox, withIntermediateDirectories: true)
    }
    #endif

    override init() {
        super.init()
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-transfers") {
            // A separate temporary sandbox, with no pairing reads or Bluetooth
            // manager. The fixture exercises the real published state/actions.
            fixtureRoot = paneFileManager.temporaryDirectory.appendingPathComponent("PaneUITests-\(UUID().uuidString)")
            do {
                try paneFileManager.createDirectory(at: sentFolder, withIntermediateDirectories: true)
                try paneFileManager.createDirectory(at: inbox, withIntermediateDirectories: true)
                let phone = SharedFile(id: String(repeating: "1", count: 32), name: "Phone test file.txt", size: 4, sha256: "")
                let laptop = SharedFile(id: String(repeating: "2", count: 32), name: "Laptop test file.txt", size: 4, sha256: "")
                try Data("test".utf8).write(to: sentFolder.appendingPathComponent(phone.id))
                outgoing = [phone]
                laptopFiles = [laptop]
                transferStates = [phone.id: "sending", laptop.id: "receiving"]
                sendProgress[phone.id] = 0.25
                receiveProgresses[laptop.id] = 0.25
                receiveProgress = 0.25
                controlsAvailable = true
                status = "Transfer preview."
            } catch { activity = "Couldn't prepare the transfer preview. Reopen Pane." }
            return
        }
        #endif
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
            for url in (try? paneFileManager.contentsOfDirectory(at: support, includingPropertiesForKeys: nil)) ?? [] {
                if url.lastPathComponent == "incoming.part" || url.lastPathComponent.range(of: "^incoming-[a-fA-F0-9]{32}\\.part$", options: .regularExpression) != nil {
                    try? paneFileManager.removeItem(at: url)
                }
            }
            refreshReceived()
        } catch { activity = "Couldn't load your files. Reopen Pane and try again." }
        if isPaired { manager = CBPeripheralManager(delegate: self, queue: .main) }
    }

    func activatePendingUSB() {
        guard fixtureRoot == nil else { return }
        if paneFileManager.fileExists(atPath: documents.appendingPathComponent("pane-pairing.json").path) { activateUSB() }
    }

    func activateUSB() {
        guard fixtureRoot == nil else { return }
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
            stopBulkUpload()
            authorized = nil
            buffers.removeAll(); notifications.removeAll()
            discardIncoming()
            if manager == nil {
                manager = CBPeripheralManager(delegate: self, queue: .main)
            } else {
                advertise()
            }
            activity = "Linked. Keep Pane open on both devices."
        } catch {
            activity = "Phone not linked. Connect USB and retry setup on your laptop."
        }
    }

    func filePreparationFailed(_ error: Error) {
        if let failure = error as? TransferError { activity = failure.message }
        else { activity = "Couldn't prepare the file. Choose it again." }
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
        transferStates[file.id] = "queued"
        do { try saveQueue() }
        catch {
            outgoing.removeAll { $0.id == id }
            try? paneFileManager.removeItem(at: destination)
            throw error
        }
        activity = "Queued \(file.name). Keep Pane open."
    }

    func transferState(_ id: String) -> String { transferStates[id] ?? "queued" }

    func controlTransfer(_ id: String, action: String) {
        guard ["pause", "resume", "cancel"].contains(action) else { return }
        let state = action == "pause" ? "paused" : action == "cancel" ? "cancelled" : "queued"
        transferStates[id] = state
        if action == "cancel" {
            stopBulkUpload(id)
            discardIncoming(id)
            if outgoing.contains(where: { $0.id == id }) {
                outgoing.removeAll { $0.id == id }
                sendProgress.removeValue(forKey: id)
                try? paneFileManager.removeItem(at: sentFolder.appendingPathComponent(id))
                do { try saveQueue() } catch { activity = "Couldn't save the queue. Reopen Pane and try again." }
            }
            laptopFiles.removeAll { $0.id == id }
        }
    }

    func removeOutgoing(at offsets: IndexSet) {
        for index in offsets.sorted(by: >) { controlTransfer(outgoing[index].id, action: "cancel") }
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
        stopBulkUpload()
        authorized = nil; isConnected = false; buffers.removeAll(); notifications.removeAll(); discardIncoming()
        if peripheral.state == .poweredOn { advertise() }
        else { status = "Bluetooth unavailable. Enable it and allow Pane in Settings." }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, didAdd service: CBService, error: Error?) {
        if error != nil { status = "Couldn't start Bluetooth. Reopen Pane and try again."; return }
        guard let pairing else { return }
        peripheral.startAdvertising([CBAdvertisementDataServiceUUIDsKey: [CBUUID(string: pairing.service)], CBAdvertisementDataLocalNameKey: pairing.peerName])
    }

    func peripheralManagerDidStartAdvertising(_ peripheral: CBPeripheralManager, error: Error?) {
        if error != nil { status = "Couldn't connect. Keep Pane open on both devices and try again." }
    }

    func peripheralManager(_ peripheral: CBPeripheralManager, central: CBCentral, didUnsubscribeFrom characteristic: CBCharacteristic) {
        buffers.removeValue(forKey: central.identifier)
        notifications.removeAll { $0.1.identifier == central.identifier }
        if authorized == central.identifier { stopBulkUpload(); authorized = nil; isConnected = false; discardIncoming(); status = "Laptop disconnected. Reconnect from Pane." }
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
            activity = "Transfer stopped. Try sending the file again."
        }
        reply["request"] = requestID
        guard var data = try? JSONSerialization.data(withJSONObject: reply) else { return }
        data.append(10)
        guard data.count <= 65536, notifications.count < 4096 else { return }
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
            let capabilities = body["capabilities"] as? [String] ?? []
            controlsAvailable = capabilities.contains("transfer-control-v1")
            chunkLimit = capabilities.contains("chunk-32768") ? 32768 : 4096
            return ["version": 1, "capabilities": ["transfer-control-v1", "chunk-32768", "wifi-upload-v1", "wifi-download-v1"]]
        }
        guard authorized == central.identifier else { throw TransferError(message: "Pair over USB first.") }
        return try transferOperation(body)
    }

    // Called on the same main queue as Bluetooth authorization, controls and UI.
    func transferOperation(_ body: [String: Any]) throws -> [String: Any] {
        let op = body["op"] as? String ?? ""
        switch op {
        case "bulk-write", "bulk-write-stop":
            guard let id = body["id"] as? String else { throw TransferError(message: "Missing file ID.") }
            if op == "bulk-write-stop" { stopBulkDownload(id) }
            let state = transferState(id)
            if state == "cancelled" { return ["state": state, "offset": 0] }
            guard let current = incoming[id] else { throw TransferError(message: "Start this file again.") }
            if state == "paused" { return ["state": state, "offset": current.offset] }
            if op == "bulk-write-stop" { return ["ok": true, "offset": current.offset] }
            guard let raw = body["endpoint"] as? [String: Any], let endpoint = BulkUpload.Endpoint(raw) else {
                throw TransferError(message: "Invalid fast transfer endpoint.")
            }
            let generation = reserveDownload(id)
            let download = BulkUpload(endpoint: endpoint, size: current.file.size) { [weak self] offset, data, reply in
                DispatchQueue.main.async {
                    guard let self else { reply(2, 0); return }
                    let result = self.acceptBulk(id, generation: generation, offset: offset, data: data)
                    reply(result.status, result.offset)
                }
            }
            bulkDownload = download
            download.start()
            return ["ok": true, "offset": current.offset]
        case "bulk-read":
            guard let id = body["id"] as? String,
                  let file = outgoing.first(where: { $0.id == id }),
                  let rawEndpoint = body["endpoint"] as? [String: Any],
                  let endpoint = BulkUpload.Endpoint(rawEndpoint) else {
                throw TransferError(message: "Fast transfer unavailable. Try again.")
            }
            if ["paused", "cancelled"].contains(transferState(id)) { return ["state": transferState(id)] }
            stopBulkUpload()
            bulkUploadID = id
            let upload = BulkUpload(endpoint: endpoint, file: sentFolder.appendingPathComponent(file.id), size: file.size,
                state: { [weak self] complete in
                    DispatchQueue.main.async {
                        guard let self, self.bulkUploadID == id,
                              self.outgoing.contains(where: { $0.id == id }) else { complete(2); return }
                        let state = self.transferState(id)
                        complete(state == "paused" ? 1 : state == "cancelled" ? 2 : 0)
                    }
                }, progress: { [weak self] offset in
                    DispatchQueue.main.async {
                        guard let self, self.bulkUploadID == id,
                              !["paused", "cancelled"].contains(self.transferState(id)) else { return }
                        self.transferStates[id] = "sending"
                        self.sendProgress[id] = file.size == 0 ? 1 : Double(offset) / Double(file.size)
                        self.activity = "Sending \(file.name): \(file.size == 0 ? 100 : offset * 100 / file.size)%"
                    }
                })
            bulkUpload = upload
            upload.start()
            return ["ok": true]
        case "controls":
            guard controlsAvailable, let transfers = body["transfers"] as? [[String: Any]], transfers.count <= 256 else {
                throw TransferError(message: "Invalid transfer controls.")
            }
            var laptop: [SharedFile] = []
            var visible = Set(outgoing.map { $0.id })
            visible.formUnion(incoming.keys)
            for transfer in transfers {
                guard let id = transfer["id"] as? String,
                      let direction = transfer["direction"] as? String else { continue }
                let key = direction == "from-phone" ? (transfer["remoteId"] as? String ?? id) : id
                visible.insert(key)
                if let desired = transfer["control"] as? String,
                   ["queued", "sending", "receiving", "paused", "cancelled"].contains(desired) {
                    // Explicit Windows actions supersede an older local action.
                    transferStates[key] = desired
                    if desired == "cancelled" {
                        stopBulkUpload(key)
                        discardIncoming(key)
                        if outgoing.contains(where: { $0.id == key }) {
                            outgoing.removeAll { $0.id == key }
                            sendProgress.removeValue(forKey: key)
                            try? paneFileManager.removeItem(at: sentFolder.appendingPathComponent(key))
                            try saveQueue()
                        }
                    }
                }
                if direction == "to-phone", transferStates[key] != "cancelled",
                   let name = transfer["name"] as? String, let size = transfer["size"] as? Int {
                    laptop.append(SharedFile(id: id, name: name, size: size, sha256: ""))
                    if transferStates[id] == nil { transferStates[id] = transfer["state"] as? String ?? "queued" }
                }
            }
            laptopFiles = laptop
            transferStates = transferStates.filter { visible.contains($0.key) }
            let states = transferStates.map { ["id": $0.key, "state": $0.value] }
            return ["transfers": states]
        case "list":
            return ["files": try JSONSerialization.jsonObject(with: JSONEncoder().encode(outgoing))]
        case "read":
            if let id = body["id"] as? String, ["paused", "cancelled"].contains(transferState(id)) { return ["state": transferState(id)] }
            guard let id = body["id"] as? String, let file = outgoing.first(where: { $0.id == id }),
                  let offset = body["offset"] as? Int, let length = body["length"] as? Int,
                  offset >= 0, length > 0, length <= chunkLimit, offset <= file.size, length <= file.size - offset else {
                throw TransferError(message: "Invalid file range.")
            }
            if ["paused", "cancelled"].contains(transferState(id)) { return ["state": transferState(id)] }
            transferStates[id] = "sending"
            let handle = try FileHandle(forReadingFrom: sentFolder.appendingPathComponent(file.id))
            defer { try? handle.close() }
            try handle.seek(toOffset: UInt64(offset))
            let data = try handle.read(upToCount: length) ?? Data()
            sendProgress[file.id] = file.size == 0 ? 1 : Double(offset + data.count) / Double(file.size)
            activity = "Sending \(file.name): \(file.size == 0 ? 100 : (offset + data.count) * 100 / file.size)%"
            return ["data": data.base64EncodedString()]
        case "received":
            guard let id = body["id"] as? String else { throw TransferError(message: "Missing file ID.") }
            stopBulkUpload(id)
            if let index = outgoing.firstIndex(where: { $0.id == id }) {
                let file = outgoing.remove(at: index)
                sendProgress.removeValue(forKey: file.id)
                transferStates.removeValue(forKey: file.id)
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
            if transferState(id) == "cancelled" { return ["state": "cancelled"] }
            let name = Self.safeName(rawName)
            let file = SharedFile(id: id, name: name, size: size, sha256: hash.lowercased())
            if try completed(id, matching: file) { return ["ok": true, "completed": true] }
            guard incoming[id] != nil || incoming.count < 8 else { throw TransferError(message: "Finish or cancel incoming files first.") }
            discardIncoming(id)
            let target = (fixtureRoot ?? support).appendingPathComponent("incoming-\(id).part")
            try Data().write(to: target)
            if transferStates[id] != "paused" { transferStates[id] = "receiving" }
            if !laptopFiles.contains(where: { $0.id == id }) { laptopFiles.append(file) }
            receiveProgress = 0
            receiveProgresses[id] = 0
            incoming[id] = Incoming(file: file, url: target, handle: try FileHandle(forWritingTo: target), offset: 0)
            return ["ok": true]
        case "write":
            if let id = body["id"] as? String, ["paused", "cancelled"].contains(transferState(id)) { return ["state": transferState(id)] }
            guard let id = body["id"] as? String, bulkDownloadID != id,
                  let offset = body["offset"] as? Int,
                  let text = body["data"] as? String, let data = Data(base64Encoded: text),
                  data.count <= chunkLimit else {
                throw TransferError(message: "Incoming chunk is out of order or too large.")
            }
            return ["offset": try appendIncoming(id, offset: offset, data: data)]
        case "finish":
            if let id = body["id"] as? String, ["paused", "cancelled"].contains(transferState(id)) { return ["state": transferState(id)] }
            if let id = body["id"] as? String, incoming[id] == nil, try completed(id) { return ["ok": true, "completed": true] }
            guard let id = body["id"] as? String, let current = incoming[id], current.offset == current.file.size else {
                throw TransferError(message: "Incoming file is incomplete.")
            }
            stopBulkDownload(id)
            try current.handle.synchronize(); try current.handle.close()
            let hash = current.hash.finalize().map { String(format: "%02x", $0) }.joined()
            guard hash == current.file.sha256 else { discardIncoming(id); throw TransferError(message: "File verification failed. Send again.") }
            let destination = availableName(current.file.name)
            let attrs = try paneFileManager.attributesOfItem(atPath: current.url.path)
            guard let inode = attrs[.systemFileNumber] as? NSNumber else { throw TransferError(message: "Unable to identify the incoming file.") }
            var receipt = DeliveryReceipt(file: current.file, destination: destination.lastPathComponent, inode: inode.uint64Value, published: false)
            try paneFileManager.createDirectory(at: receiptFolder, withIntermediateDirectories: true)
            let url = try receiptURL(id)
            try JSONEncoder().encode(receipt).write(to: url, options: .atomic)
            try paneFileManager.moveItem(at: current.url, to: destination)
            receipt.published = true
            // The prepared receipt already proves the move when this second write fails.
            try? JSONEncoder().encode(receipt).write(to: url, options: .atomic)
            laptopFiles.removeAll { $0.id == current.file.id }
            transferStates.removeValue(forKey: current.file.id)
            incoming.removeValue(forKey: id)
            receiveProgresses.removeValue(forKey: id)
            receiveProgress = nil
            refreshReceived()
            activity = "Received \(destination.lastPathComponent)."
            return ["ok": true]
        default:
            throw TransferError(message: "Unknown file operation.")
        }
    }

    func acceptBulk(_ id: String, generation: UUID, offset: Int, data: Data) -> (status: UInt8, offset: Int) {
        let committed = incoming[id]?.offset ?? 0
        guard generation == downloadGeneration, bulkDownloadID == id else { return (3, committed) }
        switch transferState(id) {
        case "paused": return (1, committed)
        case "cancelled": return (2, committed)
        default: break
        }
        guard data.count <= 256 * 1024 else { return (3, committed) }
        do { return (0, try appendIncoming(id, offset: offset, data: data)) }
        catch { return (3, incoming[id]?.offset ?? 0) }
    }

    private func appendIncoming(_ id: String, offset: Int, data: Data) throws -> Int {
        guard var current = incoming[id], current.offset == offset,
              !data.isEmpty, data.count <= current.file.size - offset else {
            throw TransferError(message: "Incoming chunk is out of order or too large.")
        }
        do { try current.handle.write(contentsOf: data) }
        catch {
            do {
                try current.handle.truncate(atOffset: UInt64(offset))
                try current.handle.seek(toOffset: UInt64(offset))
            } catch { discardIncoming(id) }
            throw error
        }
        current.hash.update(data: data)
        current.offset += data.count
        incoming[id] = current
        receiveProgress = Double(current.offset) / Double(current.file.size)
        receiveProgresses[id] = receiveProgress
        activity = "Receiving \(current.file.name): \(current.offset * 100 / current.file.size)%"
        return current.offset
    }

    private func discardIncoming(_ id: String? = nil) {
        stopBulkDownload(id)
        let ids = id.map { [$0] } ?? Array(incoming.keys)
        for key in ids {
            if let current = incoming.removeValue(forKey: key) {
                try? current.handle.close()
                try? paneFileManager.removeItem(at: current.url)
            }
            receiveProgresses.removeValue(forKey: key)
        }
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
