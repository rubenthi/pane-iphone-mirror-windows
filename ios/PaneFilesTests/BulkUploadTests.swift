import Foundation
import XCTest
@testable import PaneFiles

final class BulkUploadTests: XCTestCase {
    func testCertificatePinAcceptsOnlyExactSHA256OfCertificateBytes() {
        // SHA-256 known-answer vector, independent of the implementation.
        let pin = Data([0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea,
                        0x41, 0x41, 0x40, 0xde, 0x5d, 0xae, 0x22, 0x23,
                        0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
                        0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad])
        XCTAssertTrue(BulkUpload.verifiesCertificate(der: Data("abc".utf8), expected: pin))
        XCTAssertFalse(BulkUpload.verifiesCertificate(der: Data("abd".utf8), expected: pin))
        var wrongPin = pin
        wrongPin[0] ^= 1
        XCTAssertFalse(BulkUpload.verifiesCertificate(der: Data("abc".utf8), expected: wrongPin))
        XCTAssertFalse(BulkUpload.verifiesCertificate(der: Data("abc".utf8), expected: Data()))
        XCTAssertFalse(BulkUpload.verifiesCertificate(der: Data("abc".utf8), expected: Data(pin.prefix(31))))
    }

    private var valid: [String: Any] {
        ["hosts": ["192.168.1.20"], "port": 49152,
         "fingerprint": String(repeating: "ab", count: 32),
         "secret": String(repeating: "01", count: 32)]
    }

    func testEndpointDecodesExactPinSecretAndPrivateAddresses() throws {
        for host in ["10.0.0.1", "172.16.0.1", "172.31.255.254", "192.168.1.20", "169.254.2.3"] {
            var value = valid
            value["hosts"] = [host]
            let endpoint = try XCTUnwrap(BulkUpload.Endpoint(value))
            XCTAssertEqual(endpoint.hosts, [host])
            XCTAssertEqual(endpoint.port.rawValue, 49152)
            XCTAssertEqual(endpoint.fingerprint, Data(repeating: 0xab, count: 32))
            XCTAssertEqual(endpoint.secret, Data(repeating: 1, count: 32))
        }
        var value = valid
        value["fingerprint"] = String(repeating: "AB", count: 32)
        XCTAssertNotNil(BulkUpload.Endpoint(value))
    }

    func testRejectsUntrustedAndAmbiguousHosts() {
        let rejected = ["8.8.8.8", "127.0.0.1", "0.0.0.0", "224.0.0.1", "255.255.255.255",
                        "172.15.0.1", "172.32.0.1", "169.253.1.2", "192.167.1.2", "localhost",
                        "::1", "fe80::1", "10.0.0.256", "10.0.0", "10..0.1", "10.0.0.1:80",
                        "010.0.0.1", "+10.0.0.1", "10.0.0.01", "10.0.0.1 ", "１０.0.0.1"]
        for host in rejected {
            var value = valid
            value["hosts"] = [host]
            XCTAssertNil(BulkUpload.Endpoint(value), "Unexpectedly accepted \(host)")
        }
        for hosts in [[], [String](repeating: "10.0.0.1", count: 9), ["10.0.0.1", "8.8.8.8"]] {
            var value = valid
            value["hosts"] = hosts
            XCTAssertNil(BulkUpload.Endpoint(value))
        }
    }

    func testRejectsMalformedPinAndSecret() {
        for key in ["fingerprint", "secret"] {
            for text in ["", String(repeating: "a", count: 63), String(repeating: "a", count: 65),
                         String(repeating: "gg", count: 32), "+1" + String(repeating: "ab", count: 31),
                         String(repeating: "ab", count: 31) + " 1", String(repeating: "é", count: 64)] {
                var value = valid
                value[key] = text
                XCTAssertNil(BulkUpload.Endpoint(value), "Unexpectedly accepted malformed \(key)")
            }
            var value = valid
            value.removeValue(forKey: key)
            XCTAssertNil(BulkUpload.Endpoint(value))
            value[key] = Data(repeating: 1, count: 32)
            XCTAssertNil(BulkUpload.Endpoint(value))
        }
    }

    func testPortAndFieldTypesAreBounded() {
        for port in [0, -1, 65536, Int.max] {
            var value = valid
            value["port"] = port
            XCTAssertNil(BulkUpload.Endpoint(value))
        }
        for port in [1, 65535] {
            var value = valid
            value["port"] = port
            XCTAssertNotNil(BulkUpload.Endpoint(value))
        }
        var value = valid
        value["port"] = "49152"
        XCTAssertNil(BulkUpload.Endpoint(value))
        value = valid
        value["hosts"] = "192.168.1.20"
        XCTAssertNil(BulkUpload.Endpoint(value))
        XCTAssertNil(BulkUpload.Endpoint([:]))
    }
}
