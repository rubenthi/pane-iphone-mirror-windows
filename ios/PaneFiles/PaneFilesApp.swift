import SwiftUI
import PhotosUI
import UniformTypeIdentifiers

@main
struct PaneFilesApp: App {
    @StateObject private var companion = Companion()
    var body: some Scene {
        WindowGroup { ContentView(companion: companion) }
    }
}

struct PhotoFile: Transferable {
    let url: URL
    static var transferRepresentation: some TransferRepresentation {
        FileRepresentation(importedContentType: .data) { received in
            let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            let target = folder.appendingPathComponent(received.file.lastPathComponent)
            try FileManager.default.copyItem(at: received.file, to: target)
            return PhotoFile(url: target)
        }
    }
}

struct ContentView: View {
    @ObservedObject var companion: Companion
    @State private var showFiles = false
    @State private var photos: [PhotosPickerItem] = []
    @State private var importing = false
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        NavigationStack {
            List {
                Section("Connection") {
                    Label(companion.status, systemImage: "laptopcomputer.and.iphone")
                    Button("Activate USB link") { companion.activateUSB() }
                    Text("Connect by USB, choose Bind USB & Wi-Fi in Pane on your laptop, then activate here. Allow Bluetooth and keep this app open during transfers.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                Section("Send to laptop Downloads") {
                    PhotosPicker(selection: $photos, maxSelectionCount: 8, matching: .any(of: [.images, .videos]), preferredItemEncoding: .current) {
                        Label("Choose photos or videos", systemImage: "photo.on.rectangle")
                    }.disabled(importing)
                    Button { showFiles = true } label: { Label("Choose files", systemImage: "folder") }.disabled(importing)
                    if importing { ProgressView("Preparing files…") }
                    ForEach(companion.outgoing) { file in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(file.name)
                            Text("Queued · \(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))").font(.caption).foregroundStyle(.secondary)
                        }
                    }.onDelete { companion.removeOutgoing(at: $0) }
                }
                Section("Received from laptop") {
                    if companion.received.isEmpty { Text("No files received yet.").foregroundStyle(.secondary) }
                    ForEach(companion.received, id: \.self) { url in
                        ShareLink(item: url) { Label(url.lastPathComponent, systemImage: "doc") }
                    }
                    Text("Also available in Files → On My iPhone → Pane Files → Received. Tap a file to share or save it elsewhere.")
                        .font(.footnote).foregroundStyle(.secondary)
                }
                if !companion.activity.isEmpty {
                    Section("Transfer status") { Text(companion.activity).font(.footnote) }
                }
            }
            .navigationTitle("Pane Files")
            .fileImporter(isPresented: $showFiles, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
                switch result {
                case .success(let urls): importFiles(urls)
                case .failure(let error): companion.activity = error.localizedDescription
                }
            }
            .onChange(of: photos) { _, selection in
                guard !selection.isEmpty else { return }
                importing = true
                Task {
                    do {
                        for item in selection {
                            if let file = try await item.loadTransferable(type: PhotoFile.self) {
                                defer { try? FileManager.default.removeItem(at: file.url.deletingLastPathComponent()) }
                                try await companion.queueFile(file.url)
                            }
                        }
                    } catch { companion.activity = error.localizedDescription }
                    photos = []; importing = false
                }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .active { companion.refreshReceived() }
            }
        }
    }

    private func importFiles(_ urls: [URL]) {
        importing = true
        Task {
            do {
                for url in urls {
                    let access = url.startAccessingSecurityScopedResource()
                    defer { if access { url.stopAccessingSecurityScopedResource() } }
                    try await companion.queueFile(url)
                }
            } catch { companion.activity = error.localizedDescription }
            importing = false
        }
    }
}
