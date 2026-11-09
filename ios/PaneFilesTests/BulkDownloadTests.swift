import CryptoKit
import Foundation
import XCTest
@testable import PaneFiles

final class BulkDownloadTests: XCTestCase {
    private let id = String(repeating: "a", count: 32)
    private let second = String(repeating: "b", count: 32)
    private var folder: URL!
    private var phone: Companion!

    override func setUpWithError() throws {
        folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        phone = try Companion(testDirectory: folder)
    }
    override func tearDownWithError() throws { phone = nil; try FileManager.default.removeItem(at: folder) }

    private func begin(_ data: Data, named name: String = "sample.txt", id: String? = nil) throws -> [String: Any] {
        let hash = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        return try phone.transferOperation(["op": "begin", "id": id ?? self.id, "name": name, "size": data.count, "sha256": hash])
    }

    private func op(_ name: String, _ extra: [String: Any] = [:]) throws -> [String: Any] {
        try phone.transferOperation(["op": name, "id": id].merging(extra) { _, new in new })
    }

    func testLostAckFencesWiFiBeforeBluetoothFallbackAndDeduplicatesFinishAcrossRelaunch() throws {
        let first = Data(repeating: 0x58, count: 256 * 1024), tail = Data([1, 2, 3])
        let data = first + tail
        _ = try begin(data)
        let generation = phone.reserveDownload(id)
        XCTAssertEqual(phone.acceptBulk(id, generation: generation, offset: 0, data: first).offset, first.count)
        XCTAssertThrowsError(try op("write", ["offset": first.count, "data": tail.base64EncodedString()]))
        XCTAssertEqual(try op("bulk-write-stop")["offset"] as? Int, first.count)
        XCTAssertEqual(phone.acceptBulk(id, generation: generation, offset: first.count, data: tail).status, 3)
        XCTAssertEqual(try op("write", ["offset": first.count, "data": tail.base64EncodedString()])["offset"] as? Int, data.count)
        XCTAssertEqual(try op("finish")["ok"] as? Bool, true)
        phone = try Companion(testDirectory: folder)
        XCTAssertEqual(try op("finish")["completed"] as? Bool, true)
        XCTAssertEqual(try begin(data)["completed"] as? Bool, true)
        XCTAssertThrowsError(try begin(data, named: "different.txt"))
        let inbox = folder.appendingPathComponent("Received")
        XCTAssertEqual(try FileManager.default.contentsOfDirectory(atPath: inbox.path), ["sample.txt"])
        XCTAssertEqual(try Data(contentsOf: inbox.appendingPathComponent("sample.txt")), data)
    }

    func testGenerationPauseCancelBoundsAndHash() throws {
        let data = Data([1, 2, 3])
        _ = try begin(data)
        let old = phone.reserveDownload(id), live = phone.reserveDownload(id)
        XCTAssertEqual(phone.acceptBulk(id, generation: old, offset: 0, data: data).status, 3)
        XCTAssertEqual(phone.acceptBulk(id, generation: live, offset: 1, data: data).status, 3)
        XCTAssertEqual(phone.acceptBulk(id, generation: live, offset: 0, data: Data()).status, 3)
        XCTAssertEqual(phone.acceptBulk(id, generation: live, offset: 0, data: Data(repeating: 0, count: 262145)).status, 3)
        phone.controlTransfer(id, action: "pause")
        XCTAssertEqual(phone.acceptBulk(id, generation: live, offset: 0, data: data).status, 1)
        XCTAssertEqual(try op("bulk-write-stop")["state"] as? String, "paused")
        phone.controlTransfer(id, action: "resume")
        let next = phone.reserveDownload(id)
        XCTAssertEqual(phone.acceptBulk(id, generation: next, offset: 0, data: Data([1,2,4])).status, 0)
        XCTAssertThrowsError(try op("finish"))
        _ = try begin(data)
        let discarded = phone.reserveDownload(id)
        phone.controlTransfer(id, action: "cancel")
        XCTAssertNotEqual(phone.acceptBulk(id, generation: discarded, offset: 0, data: data).status, 0)
        XCTAssertEqual(try op("bulk-write-stop")["state"] as? String, "cancelled")
        XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: folder.appendingPathComponent("Received").path).isEmpty)
    }

    func testZeroLengthAndIndependentSameNameDeliveries() throws {
        for item in [id, second] {
            _ = try begin(Data(), id: item)
            _ = try phone.transferOperation(["op":"finish", "id":item])
        }
        XCTAssertEqual(Set(try FileManager.default.contentsOfDirectory(atPath: folder.appendingPathComponent("Received").path)),
                       Set(["sample.txt", "sample (1).txt"]))
    }
}
