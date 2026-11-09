import Foundation

enum FileRules {
    static let limit: UInt64 = 16 * 1024 * 1024 * 1024

    static func checked(_ name: String) throws -> String {
        let valid = Set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._-".utf8)
        let stem = (name.components(separatedBy: ".").first ?? "").trimmingCharacters(in: .whitespaces).uppercased()
        let reserved = ["CON", "PRN", "AUX", "NUL"] + (1...9).flatMap { ["COM\($0)", "LPT\($0)"] }
        guard (1...120).contains(name.utf8.count), name.utf8.allSatisfy(valid.contains),
              !name.hasPrefix("."), !name.hasSuffix("."), !name.hasSuffix(" "), !reserved.contains(stem) else {
            throw LinkError.invalid("Choose a portable filename using letters, numbers, spaces, dots, hyphens or underscores")
        }
        return name
    }
}
