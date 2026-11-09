import CryptoKit
import Combine
import Foundation

struct FileExchange {
    let channel: Channel
    let checkpoint: (UInt64, UInt64) async throws -> Void

    func upload(_ url: URL) async throws {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        let name = try FileRules.checked(url.lastPathComponent)
        let values = try url.resourceValues(forKeys: [.isRegularFileKey, .fileSizeKey])
        guard values.isRegularFile == true, let length = values.fileSize, length >= 0,
              UInt64(length) <= FileRules.limit else { throw LinkError.invalid("Choose a regular file up to 16 GiB") }
        let size = UInt64(length)
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        try await channel.send(Data([1]) + Data.networkOrder(size) + Data(name.utf8))
        try await channel.expect(3)
        var digest = SHA256()
        var sent: UInt64 = 0
        while sent < size {
            try await checkpoint(sent, size)
            let count = Int(min(65536, size - sent))
            guard let piece = try handle.read(upToCount: count), !piece.isEmpty else {
                throw LinkError.invalid("The file changed during transfer")
            }
            digest.update(data: piece)
            try await channel.send(Data([4]) + piece)
            try await channel.expect(3)
            sent += UInt64(piece.count)
        }
        guard (try handle.read(upToCount: 1) ?? Data()).isEmpty else { throw LinkError.invalid("The file grew during transfer") }
        try await checkpoint(size, size)
        try await channel.send(Data([5]) + Data(digest.finalize()))
        try await channel.expect(6)
    }

    func download() async throws -> URL {
        try await channel.send(Data([2]))
        let offer = try await channel.receive()
        guard (10...129).contains(offer.count), offer.first == 1,
              let text = String(data: offer.dropFirst(9), encoding: .utf8) else { throw LinkError.invalid("Invalid file offer") }
        let size = offer[1..<9].unsignedValue()
        let name = try FileRules.checked(text)
        guard size <= FileRules.limit else { throw LinkError.invalid("File exceeds 16 GiB") }
        let fm = FileManager.default
        let documents = try fm.url(for: .documentDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        let output = documents.appendingPathComponent(name)
        guard !fm.fileExists(atPath: output.path) else { throw LinkError.invalid("A file with that name already exists") }
        let temp = fm.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try Data().write(to: temp, options: .withoutOverwriting)
        defer { try? fm.removeItem(at: temp) }
        let handle = try FileHandle(forWritingTo: temp)
        defer { try? handle.close() }
        var digest = SHA256()
        var received: UInt64 = 0
        try await channel.send(Data([3]))
        while true {
            let record = try await channel.receive()
            if record.first == 5 {
                guard received == size, record.count == 33, Data(record.dropFirst()) == Data(digest.finalize()) else {
                    throw LinkError.invalid("File integrity check failed")
                }
                try await checkpoint(received, size)
                try handle.synchronize()
                // A hard link publishes the complete file atomically and cannot replace an existing destination.
                try fm.linkItem(at: temp, to: output)
                do { try await channel.send(Data([6])) }
                catch { throw LinkError.invalid("Saved \(name). Desktop did not receive the final confirmation.") }
                return output
            }
            let piece = record.dropFirst()
            guard record.first == 4, !piece.isEmpty, UInt64(piece.count) <= size - received else {
                throw LinkError.invalid("Invalid file data")
            }
            try handle.write(contentsOf: piece)
            digest.update(data: piece)
            received += UInt64(piece.count)
            try await checkpoint(received, size)
            try await channel.send(Data([3]))
        }
    }
}

@MainActor final class TransferState: ObservableObject {
    @Published var status = "Ready"
    @Published var active = false
    @Published var paused = false
    @Published var fraction = 0.0
    @Published var saved: URL?
    private var task: Task<Void, Never>?
    private var channel: Channel?

    func cancel() {
        task?.cancel()
        channel?.cancel()
    }

    private func checkpoint(_ bytes: UInt64, _ total: UInt64) async throws {
        fraction = total == 0 ? 1 : Double(bytes) / Double(total)
        while paused { try await Task.sleep(nanoseconds: 100_000_000) }
        try Task.checkCancellation()
    }

    func start(desktop: Desktop, upload: URL? = nil) {
        guard !active else { return }
        do {
            let secret = try desktop.validated()
            let link = try Channel(host: desktop.host, port: desktop.transferPort)
            channel = link
            active = true
            paused = false
            fraction = 0
            saved = nil
            status = upload == nil ? "Receiving file" : "Sending file"
            task = Task {
                defer { link.cancel(); channel = nil; active = false; paused = false; task = nil }
                do {
                    try await link.connect(secret: secret, protocolID: "PNFT1")
                    let exchange = FileExchange(channel: link, checkpoint: checkpoint)
                    if let upload {
                        try await exchange.upload(upload)
                        status = "Desktop confirmed receipt"
                    } else {
                        let url = try await exchange.download()
                        saved = url
                        status = "Saved \(url.lastPathComponent) in Files"
                    }
                } catch { status = Task.isCancelled ? "Cancelled" : error.localizedDescription }
            }
        } catch { status = error.localizedDescription }
    }
}
