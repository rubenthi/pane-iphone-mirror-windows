import ReplayKit
import SwiftUI
import UniformTypeIdentifiers

struct BroadcastButton: UIViewRepresentable {
    func makeUIView(context: Context) -> RPSystemBroadcastPickerView {
        let picker = RPSystemBroadcastPickerView(frame: CGRect(x: 0, y: 0, width: 48, height: 48))
        picker.preferredExtension = Bundle.main.bundleIdentifier.map { $0 + ".broadcast" }
        picker.showsMicrophoneButton = false
        picker.accessibilityLabel = "Start or stop screen broadcast"
        return picker
    }
    func updateUIView(_ uiView: RPSystemBroadcastPickerView, context: Context) {}
}

struct CompanionView: View {
    @State private var desktop = Desktop()
    @State private var savedDesktop: Desktop?
    @State private var message = ""
    @State private var importer = false
    @State private var testing = false
    @StateObject private var transfers = TransferState()

    var body: some View {
        NavigationStack {
            Form {
                Section("Desktop connection") {
                    TextField("Desktop address", text: $desktop.host)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    HStack {
                        Text("File port")
                        TextField("File port", value: $desktop.transferPort, format: .number.grouping(.never))
                            .keyboardType(.numberPad).multilineTextAlignment(.trailing)
                    }
                    HStack {
                        Text("Screen port")
                        TextField("Screen port", value: $desktop.mediaPort, format: .number.grouping(.never))
                            .keyboardType(.numberPad).multilineTextAlignment(.trailing)
                    }
                    SecureField("64-character desktop key", text: $desktop.secret)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Button("Save connection") {
                        do {
                            desktop.host = desktop.host.trimmingCharacters(in: .whitespacesAndNewlines)
                            desktop.secret = desktop.secret.trimmingCharacters(in: .whitespacesAndNewlines)
                            try desktop.save()
                            savedDesktop = desktop
                            message = "Connection saved"
                        } catch { message = error.localizedDescription }
                    }
                    if !message.isEmpty { Text(message) }
                }
                if let savedDesktop {
                    Section("Screen broadcast") {
                        Button("Test screen connection") {
                            testing = true
                            Task {
                                defer { testing = false }
                                do {
                                    let key = try savedDesktop.validated()
                                    let link = try Channel(host: savedDesktop.host, port: savedDesktop.mediaPort)
                                    defer { link.cancel() }
                                    try await link.connect(secret: key, protocolID: "PNVM1")
                                    try await link.send(Data([7]))
                                    try await link.expect(6)
                                    message = "Desktop authenticated. Screen sharing is ready."
                                } catch { message = error.localizedDescription }
                            }
                        }.disabled(testing)
                        HStack {
                            Text("Share the screen with \(savedDesktop.host)")
                            Spacer()
                            BroadcastButton().frame(width: 48, height: 48)
                        }
                    }
                    Section("Files") {
                        Button("Send a file") { importer = true }.disabled(transfers.active)
                        Button("Receive desktop’s offered file") { transfers.start(desktop: savedDesktop) }
                            .disabled(transfers.active)
                        if transfers.active {
                            ProgressView(value: transfers.fraction)
                            Button(transfers.paused ? "Resume" : "Pause") { transfers.paused.toggle() }
                            Button("Cancel", role: .destructive) { transfers.cancel() }
                        }
                        Text(transfers.status)
                        if let url = transfers.saved { ShareLink(item: url) { Label("Share saved file", systemImage: "square.and.arrow.up") } }
                    }
                }
            }
            .navigationTitle("Pane Companion")
            .onAppear {
                do {
                    desktop = try Desktop.load()
                    if (try? desktop.validated()) != nil { savedDesktop = desktop }
                } catch { message = error.localizedDescription }
            }
            .fileImporter(isPresented: $importer, allowedContentTypes: [.item]) { result in
                do {
                    let file = try result.get()
                    if let savedDesktop { transfers.start(desktop: savedDesktop, upload: file) }
                } catch { transfers.status = error.localizedDescription }
            }
        }
    }
}

@main struct IndependentCompanion: App {
    var body: some Scene { WindowGroup { CompanionView() } }
}
