# Pane 2.0.0 — clean setup and file sharing

- Reset Pane's stored preferences, browser profiles, logs and app pairing state once on first launch. Personal files and shared Apple system trust are preserved.
- Remove automatic volume reduction when mirroring starts. Keep the volume buttons for direct iPhone control; no audio is streamed or played on Windows.
- Guide USB trust, Developer Mode reveal, signed companion installation, on-device enable/restart/confirmation, and USB/Wi-Fi binding.
- Add Pane for iPhone: select photos/files and exchange them over encrypted Bluetooth Low Energy after USB provisioning.
- Add Uploads as the second sidebar tab, with progress/history and laptop-to-phone sending. Verified incoming files go to Windows Downloads without overwriting existing files.

The iPhone artifact is unsigned and requires AltStore or Xcode signing. Pane can install a device-signed IPA but does not sign it or collect Apple credentials. File transfers require a BLE-capable adapter and the companion in the foreground. Physical installation, pairing and transfers require device acceptance testing; automated checks do not establish hardware compatibility.
