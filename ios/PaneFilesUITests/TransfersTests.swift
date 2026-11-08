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
        let original = toggle.value as? String
        toggle.tap()
        let changed = toggle.value as? String
        XCTAssertNotEqual(changed, original)
        app.terminate()
        app.launch()
        XCTAssertTrue(app.buttons["laptopConnection"].waitForExistence(timeout: 15))
        app.buttons["laptopConnection"].tap()
        XCTAssertTrue(toggle.waitForExistence(timeout: 5))
        XCTAssertEqual(toggle.value as? String, changed)
        toggle.tap()
        XCTAssertEqual(toggle.value as? String, original)
    }

}
