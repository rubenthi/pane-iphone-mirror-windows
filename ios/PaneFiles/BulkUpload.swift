import Foundation
import Network
import Security
import CryptoKit

/// A bounded, certificate-pinned local TLS transfer. Endpoint credentials arrive
/// only through the authenticated, encrypted Bluetooth connection.
final class BulkUpload {
    static func verifiesCertificate(der: Data, expected: Data) -> Bool {
        expected.count == 32 && Data(SHA256.hash(data: der)) == expected
    }

    struct Endpoint {
        let hosts: [String]
        let port: NWEndpoint.Port
        let fingerprint: Data
        let secret: Data

        init?(_ value: [String: Any]) {
            guard let hosts = value["hosts"] as? [String], !hosts.isEmpty, hosts.count <= 8,
                  hosts.allSatisfy(Self.isLocalIPv4),
                  let port = value["port"] as? Int, (1...65535).contains(port),
                  let fingerprint = Self.hex(value["fingerprint"]),
                  let secret = Self.hex(value["secret"]) else { return nil }
            self.hosts = hosts
            self.port = NWEndpoint.Port(rawValue: UInt16(port))!
            self.fingerprint = fingerprint
            self.secret = secret
        }

        private static func hex(_ value: Any?) -> Data? {
            guard let text = value as? String, text.utf8.count == 64,
                  text.utf8.allSatisfy({ (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0) }) else { return nil }
            var result = Data()
            var start = text.startIndex
            for _ in 0..<32 {
                let end = text.index(start, offsetBy: 2)
                guard let byte = UInt8(text[start..<end], radix: 16) else { return nil }
                result.append(byte)
                start = end
            }
            return result
        }

        private static func isLocalIPv4(_ host: String) -> Bool {
            let parts = host.split(separator: ".", omittingEmptySubsequences: false)
            guard parts.count == 4 else { return false }
            let octets = parts.compactMap { UInt8($0) }
            // Reject alternate IP spellings (octal-looking leading zeros,
            // signs and whitespace) before Network resolves the address.
            guard octets.count == 4, zip(parts, octets).allSatisfy({ String($0.0) == String($0.1) }) else { return false }
            return octets[0] == 10 || (octets[0] == 172 && (16...31).contains(octets[1]))
                || (octets[0] == 192 && octets[1] == 168)
                || (octets[0] == 169 && octets[1] == 254)
        }
    }

    private let endpoint: Endpoint
    typealias WriteBlock = (Int, Data, @escaping (UInt8, Int) -> Void) -> Void
    private enum Direction {
        case upload(URL, (@escaping (UInt8) -> Void) -> Void, (Int) -> Void)
        case download(WriteBlock)
    }
    private let direction: Direction
    private let size: Int
    private let queue = DispatchQueue(label: "pane.bulk-upload", qos: .userInitiated)
    private var connection: NWConnection?
    private var stopped = false
    private var timer: DispatchSourceTimer?

    init(endpoint: Endpoint, file: URL, size: Int,
         state: @escaping (@escaping (UInt8) -> Void) -> Void,
         progress: @escaping (Int) -> Void) {
        self.endpoint = endpoint
        self.direction = .upload(file, state, progress)
        self.size = size
    }

    init(endpoint: Endpoint, size: Int, write: @escaping WriteBlock) {
        self.endpoint = endpoint
        self.size = size
        self.direction = .download(write)
    }

    func start() { queue.async { self.connect(index: 0) } }
    func cancel() { queue.async { self.stop() } }

    private func stop() {
        stopped = true
        timer?.cancel()
        timer = nil
        connection?.stateUpdateHandler = nil
        connection?.cancel()
        connection = nil
    }

    private func connect(index: Int) {
        guard !stopped, index < endpoint.hosts.count else { stop(); return }
        let options = NWProtocolTLS.Options()
        sec_protocol_options_set_min_tls_protocol_version(options.securityProtocolOptions, .TLSv12)
        let expected = endpoint.fingerprint
        sec_protocol_options_set_verify_block(options.securityProtocolOptions, { _, trust, complete in
            let reference = sec_trust_copy_ref(trust).takeRetainedValue()
            guard let certificates = SecTrustCopyCertificateChain(reference) as? [SecCertificate],
                  let leaf = certificates.first else { complete(false); return }
            // Exact pinning deliberately replaces public-CA/hostname trust for
            // this ephemeral local identity; no other certificate is accepted.
            complete(Self.verifiesCertificate(der: SecCertificateCopyData(leaf) as Data, expected: expected))
        }, queue)
        let candidate = NWConnection(host: NWEndpoint.Host(endpoint.hosts[index]), port: endpoint.port,
                                     using: NWParameters(tls: options, tcp: NWProtocolTCP.Options()))
        connection = candidate
        candidate.stateUpdateHandler = { [weak self, weak candidate] state in
            guard let self, let candidate, self.connection === candidate, !self.stopped else { return }
            switch state {
            case .ready:
                candidate.stateUpdateHandler = nil
                self.armTimeout()
                candidate.send(content: self.endpoint.secret, completion: .contentProcessed { [weak self] error in
                    guard let self else { return }
                    if error != nil { self.stop() } else { self.readRequest() }
                })
            case .failed, .cancelled:
                candidate.stateUpdateHandler = nil
                candidate.cancel()
                self.connection = nil
                self.connect(index: index + 1)
            default: break
            }
        }
        candidate.start(queue: queue)
        queue.asyncAfter(deadline: .now() + 3) { [weak self, weak candidate] in
            guard let self, let candidate, self.connection === candidate,
                  candidate.stateUpdateHandler != nil, !self.stopped else { return }
            candidate.stateUpdateHandler = nil
            candidate.cancel()
            self.connection = nil
            self.connect(index: index + 1)
        }
    }

    private func armTimeout() {
        timer?.cancel()
        let timer = DispatchSource.makeTimerSource(queue: queue)
        timer.schedule(deadline: .now() + 30)
        timer.setEventHandler { [weak self] in self?.stop() }
        self.timer = timer
        timer.resume()
    }

    private func receive(_ count: Int, accumulated: Data = Data(), completion: @escaping (Data) -> Void) {
        guard !stopped, let connection else { return }
        let remaining = count - accumulated.count
        connection.receive(minimumIncompleteLength: remaining, maximumLength: remaining) { [weak self] data, _, complete, error in
            guard let self, !self.stopped else { return }
            var result = accumulated
            if let data { result.append(data) }
            guard error == nil, result.count <= count else { self.stop(); return }
            if result.count == count { completion(result) }
            else if complete || data?.isEmpty != false { self.stop() }
            else { self.receive(count, accumulated: result, completion: completion) }
        }
    }

    private func readRequest() {
        armTimeout()
        receive(12) { [weak self] header in
            guard let self else { return }
            let offset = header.prefix(8).reduce(UInt64(0)) { ($0 << 8) | UInt64($1) }
            let length = header.suffix(4).reduce(UInt32(0)) { ($0 << 8) | UInt32($1) }
            guard offset <= UInt64(self.size), length > 0, length <= 256 * 1024,
                  UInt64(length) <= UInt64(self.size) - offset else { self.stop(); return }
            if case .download(let write) = self.direction {
                self.receive(Int(length)) { data in
                    write(Int(offset), data) { [weak self] status, next in
                        self?.queue.async { [weak self] in self?.acknowledge(status, next: next) }
                    }
                }
                return
            }
            guard case let .upload(file, state, _) = self.direction else { return }
            state { [weak self] status in
                guard let self else { return }
                self.queue.async {
                    guard !self.stopped else { return }
                    if status != 0 { self.reply(status: status, data: Data(), offset: Int(offset)); return }
                    do {
                        let handle = try FileHandle(forReadingFrom: file)
                        defer { try? handle.close() }
                        try handle.seek(toOffset: offset)
                        let data = try handle.read(upToCount: Int(length)) ?? Data()
                        guard data.count == Int(length) else { self.stop(); return }
                        self.reply(status: 0, data: data, offset: Int(offset))
                    } catch { self.reply(status: 3, data: Data(), offset: Int(offset)) }
                }
            }
        }
    }

    private func acknowledge(_ status: UInt8, next: Int) {
        guard !stopped, let connection, next >= 0, next <= size else { stop(); return }
        var offset = UInt64(next).bigEndian
        var packet = Data([status])
        withUnsafeBytes(of: &offset) { packet.append(contentsOf: $0) }
        connection.send(content: packet, completion: .contentProcessed { [weak self] error in
            guard let self, !self.stopped else { return }
            if error == nil && status == 0 && next < self.size { self.readRequest() }
            else { self.stop() }
        })
    }

    private func reply(status: UInt8, data: Data, offset: Int) {
        guard let connection, !stopped else { return }
        var length = UInt32(data.count).bigEndian
        var packet = Data([status])
        withUnsafeBytes(of: &length) { packet.append(contentsOf: $0) }
        packet.append(data)
        connection.send(content: packet, completion: .contentProcessed { [weak self] error in
            guard let self else { return }
            if error != nil { self.stop(); return }
            if status == 0, case .upload(_, _, let progress) = self.direction { progress(offset + data.count) }
            if status == 2 || status == 3 { self.stop() } else { self.readRequest() }
        })
    }
}
