import Foundation
import Security

struct Desktop: Codable {
    var host = ""
    var transferPort: UInt16 = 47321
    var mediaPort: UInt16 = 47322
    var secret = ""

    func validated() throws -> Data {
        guard !host.isEmpty, host.utf8.count <= 253, transferPort > 0, mediaPort > 0,
              let key = Data(secretHex: secret) else {
            throw LinkError.invalid("Enter a desktop address, valid ports and the 64-character desktop key")
        }
        return key
    }

    private static func query() throws -> [String: Any] {
        guard let group = Bundle.main.object(forInfoDictionaryKey: "PaneSharedKeychain") as? String,
              !group.isEmpty else { throw LinkError.invalid("Missing signing configuration") }
        return [kSecClass as String: kSecClassGenericPassword,
                kSecAttrService as String: "Independent Companion",
                kSecAttrAccount as String: "Desktop",
                kSecAttrAccessGroup as String: group]
    }

    static func load() throws -> Desktop {
        var search = try query()
        search[kSecReturnData as String] = true
        var result: CFTypeRef?
        let status = SecItemCopyMatching(search as CFDictionary, &result)
        if status == errSecItemNotFound { return Desktop() }
        guard status == errSecSuccess, let data = result as? Data else {
            throw LinkError.invalid("Unable to access the shared Keychain (\(status))")
        }
        return try JSONDecoder().decode(Desktop.self, from: data)
    }

    func save() throws {
        _ = try validated()
        let query = try Self.query()
        let changes: [String: Any] = [kSecValueData as String: try JSONEncoder().encode(self),
                                      kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        var status = SecItemUpdate(query as CFDictionary, changes as CFDictionary)
        if status == errSecItemNotFound {
            status = SecItemAdd(query.merging(changes) { _, value in value } as CFDictionary, nil)
        }
        guard status == errSecSuccess else { throw LinkError.invalid("Unable to save to Keychain (\(status))") }
    }
}
