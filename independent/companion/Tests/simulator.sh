#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
# Use a disposable simulator so the build cannot replace an installed companion.
runtime=$(xcrun simctl list runtimes -j | python3 -c 'import json,sys; r=[r for r in json.load(sys.stdin)["runtimes"] if ".iOS-" in r["identifier"] and r["isAvailable"]]; print(max(r,key=lambda i:tuple(map(int,i["version"].split("."))))["identifier"])')
device_type=$(xcrun simctl list devicetypes -j | python3 -c 'import json,sys; print(next(i["identifier"] for i in json.load(sys.stdin)["devicetypes"] if i["name"] == "iPhone 16"))')
device=$(xcrun simctl create "Independent companion validation" "$device_type" "$runtime")
trap 'xcrun simctl delete "$device"' EXIT
xcrun simctl boot "$device"
xcrun simctl bootstatus "$device" -b
xcrun simctl install "$device" build/simulator/Build/Products/Release-iphonesimulator/IndependentCompanion.app
xcrun simctl launch "$device" org.panenext.independent.companion
sleep 2
xcrun simctl io "$device" screenshot build/simulator-launch.png
# terminate fails when the launched application already crashed.
xcrun simctl terminate "$device" org.panenext.independent.companion

