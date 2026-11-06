# Pane signing helper

Built from the pinned isideload source revision in Cargo.toml, with Cargo.lock checked in. `cargo build --release --locked --manifest-path signer/Cargo.toml` builds the worker. Windows packaging bundles it automatically. No separate iloader or AltStore application is needed.

The host supplies one JSON request through stdin (email/password, selected UDID, validated Pane IPA path). The helper emits JSON-line status, verification/team prompts, encrypted-storage requests and a terminal completion/error. Credentials never appear in command-line arguments. No tracing subscriber is installed and stderr is discarded by the host. Upstream errors are replaced with a generic recovery message to avoid leaking authentication responses.

The Python host stores opaque values with current-user Windows DPAPI, keyed by hashed account and storage-key names. This includes certificates and anisette state, not account passwords. Files are inside the reset-owned `signing` directory. The selected USB device is verified before starting. Certificate exhaustion fails rather than silently revoking certificates. Initial install and manual renewal use the same flow and original unsigned IPA. Reusing an already re-signed IPA is not recommended because upstream appends the team ID to the bundle identifier.

The current upstream signer lists entitlement handling as unfinished. Pane uses standard sandbox, Bluetooth and document sharing APIs, but real-device signing/install and renewal must still be tested with a user's account. Apple authentication and remote anisette availability are external dependencies. Upstream is MIT licensed; retain ISIDELOAD-LICENSE and dependency notices when distributing. Cargo.lock records all transitive dependencies.
