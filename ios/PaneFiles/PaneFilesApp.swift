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
    @State private var showConnectionSetup = true
    @Environment(\.scenePhase) private var scenePhase

    private let accent = Color(red: 0.39, green: 0.47, blue: 0.82)

    var body: some View {
        NavigationStack {
            List {
                Section {
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(spacing: 12) {
                            Image(systemName: "laptopcomputer.and.iphone")
                                .font(.system(size: 24, weight: .light))
                                .foregroundStyle(accent)
                                .frame(width: 42, height: 42)
                                .background(accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                            VStack(alignment: .leading, spacing: 4) {
                                Text("Your laptop").font(.subheadline.weight(.semibold))
                                HStack(spacing: 5) {
                                    Circle().fill(companion.isConnected ? Color.green : Color.secondary.opacity(0.5)).frame(width: 5, height: 5)
                                    Text(companion.isConnected ? "Connected over Bluetooth" : companion.isPaired ? "Ready to connect" : "Set up a connection")
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                            Spacer(minLength: 0)
                        }
                        if !companion.isConnected {
                            Text(companion.status).font(.footnote).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                        }
                        DisclosureGroup("USB setup", isExpanded: $showConnectionSetup) {
                            VStack(alignment: .leading, spacing: 12) {
                                Text("Connect the cable and choose Bind USB & Wi-Fi in Pane on your laptop. Then activate here and allow Bluetooth.")
                                    .font(.footnote).foregroundStyle(.secondary)
                                Button("Activate USB link") { companion.activateUSB() }
                                    .buttonStyle(.borderedProminent).controlSize(.regular)
                            }.padding(.top, 8)
                        }.font(.footnote.weight(.medium))
                    }.padding(.vertical, 6)
                }
                Section {
                    HStack(spacing: 12) {
                        PhotosPicker(selection: $photos, maxSelectionCount: 8, matching: .any(of: [.images, .videos]), preferredItemEncoding: .current) {
                            VStack(spacing: 9) {
                                Image(systemName: "photo.on.rectangle").font(.system(size: 21, weight: .regular))
                                Text("Photos & videos").font(.caption.weight(.medium))
                            }.frame(maxWidth: .infinity, minHeight: 72)
                        }.disabled(importing).buttonStyle(.borderless)
                        Divider().frame(height: 40)
                        Button { showFiles = true } label: {
                            VStack(spacing: 9) {
                                Image(systemName: "folder").font(.system(size: 21, weight: .regular))
                                Text("Browse files").font(.caption.weight(.medium))
                            }.frame(maxWidth: .infinity, minHeight: 72)
                        }.disabled(importing).buttonStyle(.borderless)
                    }
                    if importing { ProgressView("Preparing files…").font(.footnote) }
                } header: { Text("Send to laptop") } footer: {
                    Text("Files arrive in your laptop's Downloads folder. Keep Pane open during transfers.")
                }
                if !companion.outgoing.isEmpty {
                    Section("Sending") {
                        ForEach(companion.outgoing) { file in
                            VStack(alignment: .leading, spacing: 8) {
                                HStack(spacing: 10) {
                                    Image(systemName: "doc").font(.title3).foregroundStyle(.secondary)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(file.name).font(.subheadline).lineLimit(1).truncationMode(.middle)
                                        Text(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))
                                            .font(.caption).foregroundStyle(.secondary).monospacedDigit()
                                    }
                                    Spacer(minLength: 8)
                                    Text(companion.sendProgress[file.id] == nil ? "Queued" : "Sending").font(.caption2).foregroundStyle(.secondary)
                                }
                                if let progress = companion.sendProgress[file.id] {
                                    ProgressView(value: progress).tint(accent)
                                        .accessibilityLabel("Sending \(file.name)")
                                }
                            }.padding(.vertical, 4)
                        }.onDelete { companion.removeOutgoing(at: $0) }
                    }
                }
                Section {
                    if companion.received.isEmpty {
                        VStack(spacing: 8) {
                            Image(systemName: "tray").font(.system(size: 26, weight: .light)).foregroundStyle(.tertiary)
                            Text("No received files yet").font(.subheadline.weight(.medium))
                            Text("Send a file from the Uploads tab on your laptop.").font(.footnote).foregroundStyle(.secondary).multilineTextAlignment(.center)
                        }.frame(maxWidth: .infinity).padding(.vertical, 18)
                    }
                    ForEach(companion.received, id: \.self) { url in
                        ShareLink(item: url) {
                            HStack(spacing: 12) {
                                Image(systemName: "doc").foregroundStyle(.secondary)
                                Text(url.lastPathComponent).font(.subheadline).foregroundStyle(.primary).lineLimit(1).truncationMode(.middle)
                                Spacer(minLength: 8)
                                Image(systemName: "square.and.arrow.up").font(.footnote).foregroundStyle(.secondary)
                            }.padding(.vertical, 4)
                        }
                    }
                    if let progress = companion.receiveProgress {
                        ProgressView("Receiving from laptop", value: progress).font(.footnote).tint(accent)
                    }
                } header: { Text("Received") } footer: {
                    Text("Also in Files → On My iPhone → Pane → Received. Tap a file to share or save it elsewhere.")
                }
                if !companion.activity.isEmpty {
                    Section {
                        Label(companion.activity, systemImage: "arrow.left.arrow.right")
                            .font(.footnote).foregroundStyle(.secondary)
                            .accessibilityAddTraits(.updatesFrequently)
                    }
                }
            }
            .task {
                while !Task.isCancelled {
                    companion.activatePendingUSB()
                    try? await Task.sleep(for: .seconds(2))
                }
            }
            .listStyle(.insetGrouped)
            .navigationTitle("Pane")
            .navigationBarTitleDisplayMode(.inline)
            .tint(accent)
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
