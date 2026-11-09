#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p build
xcodegen generate --spec project.yml
swiftc Shared/Channel.swift Shared/FileRules.swift Shared/Packetizer.swift Tests/main.swift -o build/protocol-tests
build/protocol-tests
swiftc Shared/Channel.swift Shared/Packetizer.swift Shared/HEVC.swift Tests/Fixture.swift -o build/fixture-generator
build/fixture-generator
project=(-project IndependentCompanion.xcodeproj -scheme IndependentCompanion -configuration Release)
xcodebuild "${project[@]}" -destination 'generic/platform=iOS Simulator' -derivedDataPath build/simulator CODE_SIGN_IDENTITY=- build
xcodebuild "${project[@]}" -destination 'generic/platform=iOS' -derivedDataPath build/device CODE_SIGNING_ALLOWED=NO build
app=build/device/Build/Products/Release-iphoneos/IndependentCompanion.app
extension="$app/PlugIns/ScreenBroadcast.appex"
/usr/bin/plutil -lint "$app/Info.plist" "$extension/Info.plist"
test -x "$app/IndependentCompanion"
test -x "$extension/ScreenBroadcast"
for plist in "$app/Info.plist" "$extension/Info.plist"; do
  test "$(/usr/libexec/PlistBuddy -c 'Print CFBundleShortVersionString' "$plist")" = "3.0.0"
  test "$(/usr/libexec/PlistBuddy -c 'Print CFBundleVersion' "$plist")" = "7"
done
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir "$stage/Payload"
ditto "$app" "$stage/Payload/IndependentCompanion.app"
ditto -c -k --keepParent "$stage/Payload" build/IndependentCompanion-unsigned.ipa
shasum -a 256 build/IndependentCompanion-unsigned.ipa > build/SHA256SUMS

