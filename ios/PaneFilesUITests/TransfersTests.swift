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
        XCTAssertTrue(app.staticTexts["2.4.0"].exists || app.staticTexts.containing(NSPredicate(format: "label CONTAINS %@", "Installed version")).count > 0)
        app.buttons["Done"].tap()
        XCTAssertTrue(app.buttons["Send files"].waitForExistence(timeout: 5))
    }
}
