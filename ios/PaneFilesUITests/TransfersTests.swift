import XCTest

final class TransfersTests: XCTestCase {
    func testTransferActionsAndUSBSetup() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.navigationBars["Transfers"].waitForExistence(timeout: 15))
        XCTAssertTrue(app.buttons["Send photos and videos"].exists)
        XCTAssertTrue(app.buttons["Send files"].exists)
        let preview = XCTAttachment(screenshot: app.screenshot())
        preview.name = "Pane Transfers"
        preview.lifetime = .keepAlways
        add(preview)
        app.buttons["laptopConnection"].tap()
        XCTAssertTrue(app.buttons["Activate USB link"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.switches["keepScreenAwake"].exists)
        XCTAssertTrue(app.staticTexts["transferTransportHelp"].label.contains("files continue over Bluetooth"))
        XCTAssertTrue(app.staticTexts["2.5.1"].exists || app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Installed version")).count > 0)
        app.buttons["Done"].tap()
        XCTAssertTrue(app.buttons["Send files"].waitForExistence(timeout: 5))
    }

    func testPauseResumeCancelInBothDirections() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-transfers"]
        app.launch()
        XCTAssertTrue(app.navigationBars["Transfers"].waitForExistence(timeout: 15))
        for (id, name) in [(String(repeating: "1", count: 32), "Phone test file.txt"),
                           (String(repeating: "2", count: 32), "Laptop test file.txt")] {
            let toggle = app.buttons["transfer-toggle-\(id)"]
            XCTAssertTrue(toggle.waitForExistence(timeout: 5))
            XCTAssertEqual(toggle.label, "Pause")
            toggle.tap()
            XCTAssertEqual(toggle.label, "Resume")
            toggle.tap()
            XCTAssertEqual(toggle.label, "Pause")
            let cancel = app.buttons["transfer-cancel-\(id)"]
            XCTAssertTrue(cancel.exists)
            cancel.tap()
            XCTAssertFalse(app.staticTexts[name].exists)
            XCTAssertFalse(toggle.exists)
            XCTAssertFalse(cancel.exists)
        }
    }

    func testKeepAwakePreferencePersistsInIsolatedFixture() {
        let app = XCUIApplication()
        app.launchArguments = ["--ui-test-transfers"]
        app.launch()
        XCTAssertTrue(app.buttons["laptopConnection"].waitForExistence(timeout: 15))
        app.buttons["laptopConnection"].tap()
        let toggle = app.switches["keepScreenAwake"]
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        let original = toggle.value as? String ?? "invalid"
        XCTAssertTrue(["0", "1"].contains(original))
        let changed = original == "1" ? "0" : "1"
        // SwiftUI exposes the labeled row as a switch. Hit the trailing
        // switch control rather than the center of its multiline label.
        print("Keep-awake control: \(toggle.debugDescription)")
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        let changedValue = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", changed), object: toggle)
        XCTAssertEqual(XCTWaiter.wait(for: [changedValue], timeout: 5), .completed)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["laptopConnection"].waitForExistence(timeout: 15))
        app.buttons["laptopConnection"].tap()
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        XCTAssertEqual(toggle.value as? String, changed)
        toggle.coordinate(withNormalizedOffset: CGVector(dx: 0.9, dy: 0.5)).tap()
        let restoredValue = XCTNSPredicateExpectation(predicate: NSPredicate(format: "value == %@", original), object: toggle)
        XCTAssertEqual(XCTWaiter.wait(for: [restoredValue], timeout: 5), .completed)
    }

}
