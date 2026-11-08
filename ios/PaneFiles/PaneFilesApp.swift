import SwiftUI
import PhotosUI
import UniformTypeIdentifiers
import UIKit

private enum PanePreferences {
    static let store: UserDefaults = {
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ui-test-transfers") {
            return UserDefaults(suiteName: "Pane.TransferUITests")!
        }
        #endif
        return .standard
    }()
}

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
    @State private var showConnection = false
    @AppStorage("keepScreenAwake", store: PanePreferences.store) private var keepScreenAwake = true
    @Environment(\.scenePhase) private var scenePhase
    @Environment(\.dynamicTypeSize) private var typeSize

    private var linkTitle: String {
        if companion.isConnected { return "Connected to laptop" }
        return companion.isPaired ? "Laptop paired" : "Connect your laptop"
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    Button { showConnection = true } label: {
                        HStack(spacing: 14) {
                            Image(systemName: "laptopcomputer.and.iphone")
                                .font(.title).foregroundStyle(.tint).accessibilityHidden(true)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(linkTitle).font(.headline).foregroundStyle(.primary)
                                Text(companion.isConnected ? "Bluetooth file transfers" : companion.isPaired ? "Open Pane on your laptop to transfer files." : "Pair with Pane over USB.")
                                    .font(.subheadline).foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right").font(.caption.bold()).foregroundStyle(.tertiary)
                        }.padding(.vertical, 6)
                    }.accessibilityIdentifier("laptopConnection")
                }
                Section {
                    ForEach(companion.laptopFiles) { file in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(file.name).font(.headline)
                            if let progress = companion.receiveProgresses[file.id] {
                                ProgressView(value: progress)
                            }
                            transferButtons(file.id)
                        }
                    }
                    if companion.received.isEmpty && companion.receiveProgress == nil {
                        ContentUnavailableView("No received files", systemImage: "tray",
                            description: Text("Send a file from Uploads in Pane on your laptop."))
                    }
                    ForEach(companion.received, id: \.self) { url in
                        ShareLink(item: url) {
                            HStack(spacing: 12) {
                                Image(systemName: "doc").foregroundStyle(.tint)
                                Text(url.lastPathComponent).foregroundStyle(.primary).lineLimit(2).truncationMode(.middle)
                                Spacer()
                                Image(systemName: "square.and.arrow.up").foregroundStyle(.secondary)
                            }
                        }.accessibilityHint("Share or save this file")
                    }
                } header: { Text("Received") } footer: {
                    if !companion.received.isEmpty { Text("Also in Files → On My iPhone → Pane → Received.") }
                }
                if !companion.outgoing.isEmpty {
                    Section("Sending to laptop") {
                        ForEach(companion.outgoing) { file in
                            VStack(alignment: .leading, spacing: 5) {
                                Text(file.name).font(.headline).lineLimit(2).truncationMode(.middle)
                                Text(ByteCountFormatter.string(fromByteCount: Int64(file.size), countStyle: .file))
                                    .font(.caption).foregroundStyle(.secondary)
                                if let progress = companion.sendProgress[file.id] {
                                    ProgressView(value: progress).accessibilityLabel("Sending \(file.name)")
                                } else {
                                    Text(companion.transferState(file.id).capitalized).font(.caption).foregroundStyle(.secondary)
                                }
                                transferButtons(file.id)
                            }.padding(.vertical, 3)
                        }.onDelete { companion.removeOutgoing(at: $0) }
                    }
                }
                if importing { ProgressView("Preparing files…") }
                if !companion.activity.isEmpty {
                    Text(companion.activity).font(.footnote).foregroundStyle(.secondary)
                        .accessibilityAddTraits(.updatesFrequently)
                }
            }
            .navigationTitle("Transfers")
            .safeAreaInset(edge: .bottom) {
                sendControls.padding(.horizontal).padding(.vertical, 8)
            }
            .sheet(isPresented: $showConnection) {
                NavigationStack {
                    Form {
                        Section("Your laptop") {
                            Label(linkTitle, systemImage: "laptopcomputer")
                            Text(companion.status)
                            Toggle(isOn: $keepScreenAwake) {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text("Keep iPhone awake")
                                    Text("While Pane is open").font(.caption).foregroundStyle(.secondary)
                                }
                            }.accessibilityIdentifier("keepScreenAwake")
                        }
                        Section("USB pairing") {
                            Text("Connect and unlock your iPhone, then complete setup on your laptop. If needed, activate the USB link here and allow Bluetooth.")
                            Button("Activate USB link") { companion.activateUSB() }
                            if !companion.activity.isEmpty { Text(companion.activity).font(.footnote) }
                        }
                        Section("App updates") {
                            Text("To update Pane, connect by USB and follow the update prompt on your laptop. Use the same Apple Account and developer team.")
                            LabeledContent("Installed version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Unknown")
                        }
                    }
                    .navigationTitle("Laptop connection")
                    .toolbar {
                        ToolbarItem(placement: .confirmationAction) { Button("Done") { showConnection = false } }
                    }
                }.presentationDragIndicator(.visible)
            }
            .task(id: scenePhase) {
                UIApplication.shared.isIdleTimerDisabled = scenePhase == .active && keepScreenAwake
                guard scenePhase == .active else { return }
                companion.refreshReceived()
                while !Task.isCancelled {
                    companion.activatePendingUSB()
                    try? await Task.sleep(for: .seconds(2))
                }
            }
            .onChange(of: keepScreenAwake) { _, enabled in
                UIApplication.shared.isIdleTimerDisabled = scenePhase == .active && enabled
            }
            .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
            .fileImporter(isPresented: $showFiles, allowedContentTypes: [.item], allowsMultipleSelection: true) { result in
                switch result {
                case .success(let urls): importFiles(urls)
                case .failure: companion.activity = "Couldn't open that file. Choose it again."
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
                    } catch { companion.filePreparationFailed(error) }
                    photos = []; importing = false
                }
            }

        }
    }

    @ViewBuilder private func transferButtons(_ id: String) -> some View {
        HStack {
            if companion.controlsAvailable || !companion.isConnected {
                let paused = companion.transferState(id) == "paused"
                Button(paused ? "Resume" : "Pause", systemImage: paused ? "play.fill" : "pause.fill") {
                    companion.controlTransfer(id, action: paused ? "resume" : "pause")
                }.buttonStyle(.bordered)
                    .accessibilityIdentifier("transfer-toggle-\(id)")
            }
            Button("Cancel", systemImage: "xmark", role: .destructive) {
                companion.controlTransfer(id, action: "cancel")
            }.buttonStyle(.bordered)
                .accessibilityIdentifier("transfer-cancel-\(id)")
        }
        .accessibilityElement(children: .contain)
    }

    private var sendButtons: some View {
        let layout = typeSize.isAccessibilitySize ? AnyLayout(VStackLayout(spacing: 8)) : AnyLayout(HStackLayout(spacing: 10))
        return layout {
            PhotosPicker(selection: $photos, maxSelectionCount: 8, matching: .any(of: [.images, .videos]), preferredItemEncoding: .current) {
                Label("Photos", systemImage: "photo.on.rectangle").frame(maxWidth: .infinity)
            }.accessibilityLabel("Send photos and videos")
            Button { showFiles = true } label: {
                Label("Files", systemImage: "folder").frame(maxWidth: .infinity)
            }.accessibilityLabel("Send files")
        }.controlSize(.large).disabled(importing)
    }

    @ViewBuilder private var sendControls: some View {
        if #available(iOS 26.0, *) {
            GlassEffectContainer(spacing: 10) {
                sendButtons.buttonStyle(.glass)
            }
        } else {
            sendButtons.buttonStyle(.bordered).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 18))
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
            } catch { companion.filePreparationFailed(error) }
            importing = false
        }
    }
}
