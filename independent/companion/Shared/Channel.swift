import CryptoKit
import Foundation
import Network
import Security

enum LinkError: LocalizedError {
    case invalid(String)
    var errorDescription: String? {
        switch self { case .invalid(let message): return message }
    }
}

extension Data {
    static func networkOrder<T: FixedWidthInteger>(_ number: T) -> Data {
        var value = number.bigEndian
        return Swift.withUnsafeBytes(of: &value) { Data($0) }
    }

    func unsignedValue() -> UInt64 {
        reduce(0) { ($0 << 8) | UInt64($1) }
    }

    init?(secretHex text: String) {
        let bytes = Array(text.utf8)
        guard bytes.count == 64 else { return nil }
        var decoded = Data()
        for i in stride(from: 0, to: 64, by: 2) {
            guard let value = UInt8(String(decoding: bytes[i..<(i + 2)], as: UTF8.self), radix: 16),
                  bytes[i] != 43 && bytes[i + 1] != 43 else { return nil }
            decoded.append(value)
        }
        self = decoded
    }
}

struct RecordCipher {
    private let key: SymmetricKey
    private var sequence: UInt64 = 0

    init(secret: Data, label: String, client: Data, server: Data) {
        let digest = HMAC<SHA256>.authenticationCode(for: Data(label.utf8) + client + server,
                                                       using: SymmetricKey(data: secret))
        key = SymmetricKey(data: Data(digest))
    }

    private mutating func nextNonce() throws -> AES.GCM.Nonce {
        guard sequence < UInt64.max else { throw LinkError.invalid("Session expired") }
        defer { sequence += 1 }
        return try AES.GCM.Nonce(data: Data(repeating: 0, count: 4) + Data.networkOrder(sequence))
    }

    mutating func seal(_ data: Data) throws -> Data {
        let box = try AES.GCM.seal(data, using: key, nonce: nextNonce())
        return Data.networkOrder(UInt32(data.count)) + box.ciphertext + box.tag
    }

    mutating func open(_ data: Data) throws -> Data {
        guard data.count > 16 else { throw LinkError.invalid("Invalid record") }
        let box = try AES.GCM.SealedBox(nonce: nextNonce(), ciphertext: data.dropLast(16), tag: data.suffix(16))
        return try AES.GCM.open(box, using: key)
    }
}

// One owner drives requests sequentially. cancel() may be called from another queue.
final class Channel: @unchecked Sendable {
    private let socket: NWConnection
    private let queue = DispatchQueue(label: "pane.companion.network")
    private var writer: RecordCipher?
    private var reader: RecordCipher?

    init(host: String, port: UInt16) throws {
        guard !host.isEmpty, let endpoint = NWEndpoint.Port(rawValue: port), port > 0 else {
            throw LinkError.invalid("Enter the desktop address and port")
        }
        socket = NWConnection(host: NWEndpoint.Host(host), port: endpoint, using: .tcp)
    }

    func cancel() { socket.cancel() }

    // Network.framework completes pending I/O after cancellation. Each I/O has its own deadline.
    private func bounded<T>(_ operation: (@escaping (Result<T, Error>) -> Void) -> Void) async throws -> T {
        try await withCheckedThrowingContinuation { continuation in
            let timer = DispatchSource.makeTimerSource(queue: queue)
            timer.schedule(deadline: .now() + (reader == nil ? 20 : 600))
            timer.setEventHandler { [socket] in socket.cancel() }
            timer.resume()
            operation { result in
                timer.cancel()
                continuation.resume(with: result)
            }
        }
    }

    private func write(_ data: Data) async throws {
        try await bounded { done in
            socket.send(content: data, completion: .contentProcessed { error in
                if let error { done(.failure(error)) } else { done(.success(())) }
            })
        }
    }

    private func read(_ count: Int) async throws -> Data {
        var result = Data()
        while result.count < count {
            let needed = count - result.count
            let next: Data = try await bounded { done in
                socket.receive(minimumIncompleteLength: needed, maximumLength: needed) { data, _, _, error in
                    if let error { done(.failure(error)) }
                    else if let data, !data.isEmpty { done(.success(data)) }
                    else { done(.failure(LinkError.invalid("Desktop disconnected"))) }
                }
            }
            result.append(next)
        }
        return result
    }

    func connect(secret: Data, protocolID: String) async throws {
        socket.start(queue: queue)
        let magic = Data(protocolID.utf8)
        var random = [UInt8](repeating: 0, count: 32)
        guard SecRandomCopyBytes(kSecRandomDefault, random.count, &random) == errSecSuccess else {
            throw LinkError.invalid("Random generator unavailable")
        }
        let client = Data(random)
        try await write(magic + client)
        let hello = try await read(magic.count + 32)
        guard hello.starts(with: magic) else { throw LinkError.invalid("Incompatible desktop protocol") }
        let server = Data(hello.suffix(32))
        writer = RecordCipher(secret: secret, label: protocolID + "-C", client: client, server: server)
        reader = RecordCipher(secret: secret, label: protocolID + "-S", client: client, server: server)
    }

    func send(_ data: Data) async throws {
        guard !data.isEmpty, data.count <= 65537, let sealed = try writer?.seal(data) else {
            throw LinkError.invalid("Invalid outgoing record")
        }
        try await write(sealed)
    }

    func sendVideo(packets: [Data], orientation: UInt8) async throws {
        var batch = Data()
        for packet in packets {
            guard packet.count <= 1200, let record = try writer?.seal(Data([0x21, orientation]) + packet) else {
                throw LinkError.invalid("Invalid media record")
            }
            batch.append(record)
            if batch.count >= 64 * 1024 {
                try await write(batch)
                batch.removeAll(keepingCapacity: true)
            }
        }
        if !batch.isEmpty { try await write(batch) }
    }

    func receive() async throws -> Data {
        let count = try await read(4).unsignedValue()
        guard (1...65537).contains(count) else { throw LinkError.invalid("Invalid incoming length") }
        let wire = try await read(Int(count) + 16)
        guard let plain = try reader?.open(wire) else { throw LinkError.invalid("Session unavailable") }
        return plain
    }

    func expect(_ byte: UInt8) async throws {
        guard try await receive() == Data([byte]) else { throw LinkError.invalid("Unexpected desktop response") }
    }
}
