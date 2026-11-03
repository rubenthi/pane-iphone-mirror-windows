# Tested devices and iOS versions

This is the verification record for **this fork**. A supported OS requirement, an upstream feature claim, or an installed Windows executable is not a successful phone test.

## Verified phone combinations

| Device model | iOS version | USB video | Mouse / keyboard | Wi-Fi video / input | Evidence |
| --- | --- | --- | --- | --- | --- |
| iPhone19,3 | 27.0.1 | Live full-frame video observed; user confirmed USB works | Coordinate math and wheel events tested synthetically; physical accuracy pending | Live Wi-Fi video decoded; cable-removal and physical input tests pending | 1.3.0 diagnostic build: 1328 × 2896 frames over USB and Wi-Fi. No five-minute rotation/reconnect acceptance record yet. |

## Reported, awaiting a hardware test

| Device model | iOS version | Status |
| --- | --- | --- |
| iPhone19,3 (device-reported identifier) | 27.0.1 (read from connected phone) | USB discovery and Developer Mode enabled were observed. Live video checks are recorded above; remaining physical acceptance is explicit. |

## What has been tested on Windows

- Windows executable build and dependency imports; local HTTP interface and request protection.
- Automatic updater download validation, waiting for exit, executable replacement, retained backup, and failure handling.
- Phone-shaped desktop shell and expandable sidebar are validated independently of an iPhone connection. Simulated display dimensions test layout behavior, not real device compatibility.
- Apple Devices and Chrome/Edge are installed on the development PC. Apple USB service availability is checked separately from phone discovery.

The release notes and automated workflow record the checks for each version. Do not interpret these desktop checks as a verified iPhone model list.

## Add a verified result

Open an issue using the **Device verification report** template. Include:

1. The marketing model name (for example, iPhone 16 Pro), model identifier if available, exact iOS version, Pane version, Windows version, and browser version.
2. USB video observed for at least five minutes, including rotation and one disconnect/reconnect.
3. Tap, drag, Home, typing, and key release tested in a harmless Notes document; record each result separately.
4. Wi-Fi pairing, cable removal, video and input tested separately, if attempted.
5. Any errors and reproducible steps. Remove serial numbers, UDIDs, pairing records, private screen content, and personal information from logs/screenshots.

Only mark a feature verified when it was actually exercised. Link the evidence in the table when adding a result; leave failed and untested features explicit.
