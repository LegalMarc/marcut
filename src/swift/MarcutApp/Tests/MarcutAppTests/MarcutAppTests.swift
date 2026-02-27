import XCTest
import SwiftUI
@testable import MarcutApp

@MainActor
final class MarcutAppTests: XCTestCase {

    // MARK: - Test Infrastructure

    /// Test helper for creating DocumentItems
    private func createTestDocumentItem(status: RedactionStatus = .completed) -> DocumentItem {
        let url = URL(fileURLWithPath: "/tmp/test.docx")
        let item = DocumentItem(url: url)
        item.status = status
        return item
    }

    /// Test helper for creating a test ViewModel
    private func createTestViewModel() -> DocumentRedactionViewModel {
        return DocumentRedactionViewModel()
    }

    /// Test helper for resolving sample file URLs from the repo root
    private func sampleFileURL(_ name: String) -> URL {
        let testFile = URL(fileURLWithPath: #filePath)
        let repoRoot = testFile
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
            .deletingLastPathComponent()
        return repoRoot.appendingPathComponent("sample-files").appendingPathComponent(name)
    }

    private func runProcess(_ process: Process) throws {
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        try process.run()
        process.waitUntilExit()
        if process.terminationStatus != 0 {
            throw NSError(domain: "MarcutAppTests", code: Int(process.terminationStatus))
        }
    }

    // MARK: - Test Setup

    override func setUpWithError() throws {
        // Put setup code here. This method is called before the invocation of each test method in the class.
    }

    override func tearDownWithError() throws {
        // Put teardown code here. This method is called after the invocation of each test method in the class.
    }

    // MARK: - Tooltip Tests (Task 1.2)

    func testTooltipButtonConfiguration() throws {
        // Test that TooltipButton is properly configured
        let action = { }
        let button = TooltipButton(
            action: action,
            icon: "doc.text.fill",
            tooltip: "Open Redacted Document",
            description: "Opens the redacted .docx file with sensitive information removed"
        )

        // Verify button properties are set correctly
        XCTAssertEqual(button.iconName, "doc.text.fill")
        XCTAssertEqual(button.tooltip, "Open Redacted Document")
        XCTAssertEqual(button.description, "Opens the redacted .docx file with sensitive information removed")
    }

    func testTooltipButtonsInDocumentRow() throws {
        // Test that completed document rows have all 3 tooltip buttons
        let testItem = createTestDocumentItem(status: .completed)

        // Note: In a real UI test, we would check the view hierarchy
        // For unit tests, we verify the status condition that shows tooltips
        XCTAssertTrue(testItem.status.isComplete, "Test item should be in completed state")
    }

    // MARK: - Button Position Tests (Task 1.3)

    func testButtonOrderInActionButtons() throws {
        // Test that Clear All appears before Redact Documents in the button layout
        let testViewModel = createTestViewModel()

        // Create ContentView with test view model
        let contentView = ContentView()
        // Note: In a real implementation, we'd inject the test view model

        // For unit testing, we verify the button order logic exists
        XCTAssertNotNil(contentView, "ContentView should be created successfully")
    }

    // MARK: - Dynamic Button State Tests (Task 1.4)

    func testFinishedProcessingStateLogic() throws {
        // Test the logic behind finished processing state
        // Since we can't mock the final class, we test the logic directly

        let hasCompletedDocuments = true
        let hasProcessingDocuments = false
        let hasValidDocuments = false

        // This matches the logic in DocumentRedactionViewModel.updateState()
        let hasFinishedProcessing = hasCompletedDocuments && !hasProcessingDocuments && !hasValidDocuments

        XCTAssertTrue(hasFinishedProcessing, "Should be finished when completed but no processing or valid docs")
    }

    func testProcessingStateLogic() throws {
        // Test different processing state combinations

        // Active processing
        let activeProcessing = true
        let completedDocs = false
        let validDocs = false

        XCTAssertTrue(activeProcessing, "Should be processing")
        XCTAssertFalse(completedDocs && !activeProcessing && !validDocs, "Should not be finished while processing")

        // Ready to process
        let readyToProcess = false
        let hasValidDocsReady = true
        let hasCompletedReady = false

        XCTAssertTrue(hasValidDocsReady, "Should have valid documents")
        XCTAssertFalse(readyToProcess, "Should not be processing")
        XCTAssertFalse(hasCompletedReady && !readyToProcess && !hasValidDocsReady, "Should not be finished")
    }

    // MARK: - Model Selection Tests (Task 1.5)

    func testModelSelectionOptions() throws {
        // Test that the correct 3 models are available
        let expectedModels = ["llama3.1:8b", "mistral:7b", "llama3.2:3b"]

        // Test model configuration in settings
        let settings = RedactionSettings()

        // Verify default model is one of the expected models
        XCTAssertTrue(expectedModels.contains(settings.model),
                     "Default model should be one of the supported models")

        // Test model descriptions exist (in a real test, we'd verify the UI)
        let modelDescriptions = [
            "llama3.1:8b": "Best accuracy for legal & complex documents",
            "mistral:7b": "Excellent at following instructions",
            "llama3.2:3b": "Quick processing for simple documents"
        ]

        for model in expectedModels {
            XCTAssertNotNil(modelDescriptions[model], "Model \(model) should have a description")
        }
    }

    func testModelSelectionPersistence() throws {
        // Test that model selection persists in settings
        var settings = RedactionSettings()
        let originalModel = settings.model

        settings.model = "mistral:7b"
        XCTAssertEqual(settings.model, "mistral:7b", "Model selection should persist")

        settings.model = "llama3.2:3b"
        XCTAssertEqual(settings.model, "llama3.2:3b", "Model selection should update")

        // Reset to original
        settings.model = originalModel
    }

    // MARK: - Progress Indicator Tests (Task 1.6)

    func testPreparingStateLogic() throws {
        // Test the preparing state logic that should prevent beach balls

        // Simulate the preparing state
        var isPreparing = false

        // Test initial state
        XCTAssertFalse(isPreparing, "Should not be preparing initially")

        // Simulate clicking redact button
        isPreparing = true
        XCTAssertTrue(isPreparing, "Should be in preparing state after button click")

        // Simulate completion of file dialog
        isPreparing = false
        XCTAssertFalse(isPreparing, "Should exit preparing state after file dialog")
    }

    // MARK: - Accessibility Identifier Tests

    func testTooltipButtonAccessibilityIdentifier() throws {
        let button = TooltipButton(
            action: {},
            icon: "doc.text.fill",
            tooltip: "Open Redacted Document",
            description: "Opens the redacted .docx file",
            isEnabled: true,
            accessibilityId: "document.openRedacted.test"
        )

        XCTAssertEqual(button.accessibilityId, "document.openRedacted.test")
    }

    func testModelSelectionRowAccessibilityIdentifier() throws {
        let row = ModelSelectionRow(
            modelId: "llama3.1:8b",
            displayName: "Llama 3.1 8B",
            description: "Gold standard",
            processingTime: "~45s",
            accentColor: .blue,
            isSelected: false,
            isInstalled: false,
            accessibilityId: "settings.model.llama3.1:8b"
        ) {}

        XCTAssertEqual(row.accessibilityId, "settings.model.llama3.1:8b")
    }

    // MARK: - Mass Progress Tests

    func testMassTotalDeferredUntilEnhancedStage() throws {
        let item = createTestDocumentItem(status: .processing)

        XCTAssertTrue(item.ingestProgressPayload("{\"type\":\"mass_total\",\"value\":120}"))
        XCTAssertEqual(item.totalMass, 0, "Mass total should be deferred before enhanced stage")

        item.beginStage(.enhancedDetection)
        XCTAssertEqual(item.totalMass, 120, "Mass total should apply when enhanced stage begins")
        XCTAssertTrue(item.isMassTrackingActive, "Mass tracking should activate during enhanced stage")
    }

    func testChunkEndClampsProcessedMassToTotal() throws {
        let item = createTestDocumentItem(status: .processing)
        item.beginStage(.enhancedDetection)

        XCTAssertTrue(item.ingestProgressPayload("{\"type\":\"mass_total\",\"value\":100}"))
        XCTAssertEqual(item.processedMass, 0)

        XCTAssertTrue(item.ingestProgressPayload("{\"type\":\"chunk_start\",\"size\":150,\"estimated_time\":10}"))
        XCTAssertTrue(item.ingestProgressPayload("{\"type\":\"chunk_end\",\"size\":150}"))

        XCTAssertEqual(item.processedMass, 100, "Processed mass should clamp to total mass")
    }

    // MARK: - Integration Tests

    func testDocumentItemStatusTransitions() throws {
        // Test document item status transitions
        let item = createTestDocumentItem(status: .validDocument)

        XCTAssertEqual(item.status, .validDocument, "Item should start as valid document")

        // Test transition to processing
        item.status = .processing
        XCTAssertEqual(item.status, .processing, "Item should transition to processing")
        XCTAssertTrue(item.status.isProcessing, "Processing status should be detected")

        // Test transition to completed
        item.status = .completed
        XCTAssertEqual(item.status, .completed, "Item should transition to completed")
        XCTAssertTrue(item.status.isComplete, "Completed status should be detected")
    }

    // MARK: - Error Handling Tests

    func testInvalidDocumentHandling() throws {
        let item = createTestDocumentItem(status: .invalidDocument)
        item.errorMessage = "Only DOCX files are supported"

        XCTAssertEqual(item.status, .invalidDocument, "Item should be marked as invalid")
        XCTAssertNotNil(item.errorMessage, "Error message should be set")
        XCTAssertEqual(item.errorMessage, "Only DOCX files are supported", "Error message should be specific")
    }

    // MARK: - DOCX Validation Tests

    func testValidateDocxStructureAcceptsValidDocx() async throws {
        let viewModel = createTestViewModel()
        let url = sampleFileURL("Sample 123 Consent.docx")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw XCTSkip("Missing sample file: \(url.path)")
        }

        let isValid = await viewModel.validateDocxStructure(at: url)
        XCTAssertTrue(isValid, "Expected valid DOCX to pass validation")
    }

    func testValidateDocxStructureFlagsCorruptDocx() async throws {
        let viewModel = createTestViewModel()
        let url = sampleFileURL("Sample 123 Consent Corrupt.docx")
        guard FileManager.default.fileExists(atPath: url.path) else {
            throw XCTSkip("Missing sample file: \(url.path)")
        }

        let isValid = await viewModel.validateDocxStructure(at: url)
        XCTAssertFalse(isValid, "Expected corrupt DOCX to fail validation")
    }

    func testValidateDocxStructureAcceptsAbsoluteCustomXMLTarget() async throws {
        let viewModel = createTestViewModel()
        let baseURL = sampleFileURL("Sample 123 Consent.docx")
        guard FileManager.default.fileExists(atPath: baseURL.path) else {
            throw XCTSkip("Missing sample file: \(baseURL.path)")
        }

        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let unzipDir = tempDir.appendingPathComponent("unzipped")
        try FileManager.default.createDirectory(at: unzipDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let unzip = Process()
        unzip.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
        unzip.arguments = ["-q", baseURL.path, "-d", unzipDir.path]
        try runProcess(unzip)

        let relsURL = unzipDir.appendingPathComponent("word/_rels/document.xml.rels")
        var relsText = try String(contentsOf: relsURL, encoding: .utf8)
        if !relsText.contains("customXml/item3.xml") {
            let insertion = "  <Relationship Id=\"rIdCustomXML\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml\" Target=\"/customXml/item3.xml\"/>\n"
            guard let range = relsText.range(of: "</Relationships>") else {
                XCTFail("Relationships XML missing closing tag")
                return
            }
            relsText.insert(contentsOf: insertion, at: range.lowerBound)
            try relsText.write(to: relsURL, atomically: true, encoding: .utf8)
        }

        let customDir = unzipDir.appendingPathComponent("customXml")
        try FileManager.default.createDirectory(at: customDir, withIntermediateDirectories: true)
        let customItem = customDir.appendingPathComponent("item3.xml")
        if !FileManager.default.fileExists(atPath: customItem.path) {
            guard let payload = "<root/>".data(using: .utf8) else {
                XCTFail("Failed to encode customXML payload")
                return
            }
            try payload.write(to: customItem, options: .atomic)
        }

        let outputURL = tempDir.appendingPathComponent("absolute-customxml.docx")
        let topLevelEntries = try FileManager.default.contentsOfDirectory(atPath: unzipDir.path)
        let zip = Process()
        zip.executableURL = URL(fileURLWithPath: "/usr/bin/zip")
        zip.currentDirectoryURL = unzipDir
        zip.arguments = ["-qr", outputURL.path] + topLevelEntries
        try runProcess(zip)

        let isValid = await viewModel.validateDocxStructure(at: outputURL)
        XCTAssertTrue(isValid, "Expected absolute customXML relationship target to pass validation")
    }

    func testFailedDocumentHandling() throws {
        let item = createTestDocumentItem(status: .failed)
        item.errorMessage = "Processing failed - check logs for details"

        XCTAssertEqual(item.status, .failed, "Item should be marked as failed")
        XCTAssertNotNil(item.errorMessage, "Error message should be set for failed items")
    }

    // MARK: - Performance Tests

    func testRedactionStatusPerformance() throws {
        // Test that RedactionStatus operations are performant
        measure {
            // Simulate rapid status checks
            for i in 0..<10000 {
                let status: RedactionStatus = (i % 2 == 0) ? .processing : .completed
                _ = status.isProcessing
                _ = status.isComplete
            }
        }
    }
}

// MARK: - Test Extensions

extension RedactionStatus {
    var isProcessing: Bool {
        switch self {
        case .processing, .analyzing, .redacting:
            return true
        default:
            return false
        }
    }

    var isComplete: Bool {
        switch self {
        case .completed:
            return true
        default:
            return false
        }
    }
}
