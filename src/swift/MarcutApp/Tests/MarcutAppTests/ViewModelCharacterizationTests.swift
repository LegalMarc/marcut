@testable import MarcutApp
import XCTest

/// Direct-call characterization tests for `DocumentRedactionViewModel`, closing the coverage
/// gaps listed in issue #101 (`docs/design/view_controller_decomposition.md` §3.1/§3.2 items
/// 1-4 and 6, the §4 slice-4 diagnostics matrix, and the slice-9 pending-job recovery test).
/// Tests only -- no production code changes. Every test here calls the real production method
/// through `@testable import MarcutApp`; none reimplement the logic under test.
///
/// ## Formerly missing seam: progress mapping (§3.2 item 2) -- resolved by #104
///
/// `mapPhaseToStage(identifier:displayName:isEnhancedMode:)`, `extractChunkInfo(from:)`, and
/// `applyPythonKitProgress(_:to:isEnhanced:)` used to live inside a `private extension
/// DocumentRedactionViewModel` block, which Swift scopes to the declaring file -- unreachable
/// from `@testable import MarcutApp` here. #104 (`docs/design/view_controller_decomposition.md`
/// §2.1/§4 slice 3) moved them into `ProgressMonitor` as ordinary (internal) instance methods
/// as part of extracting the heartbeat/ETA collaborator, which incidentally resolves this seam
/// too -- reachable now as `viewModel.progressMonitor.mapPhaseToStage(...)` etc. No direct-call
/// tests were added here for them as part of that move (out of #104's scope); a follow-up could
/// still add coverage for item 2 now that the seam is open.
///
/// ## Missing seam (narrower): "models present" rows of the environment-status matrix (item 6)
///
/// `PythonBridgeService.isModelAvailable`/`availableModels` ultimately check a fixed, private,
/// non-injectable `modelsDirectory` (`localAppSupportURL.appendingPathComponent("models")`,
/// `PythonBridge.swift`) -- the real `~/Library/Application Support/MarcutApp/models` on
/// whatever machine runs the test. Manufacturing a "model present" fixture would mean writing
/// (and, on teardown, deleting) real Ollama manifest/blob files under that shared, real
/// directory; on a developer machine that already has real models installed there, this risks
/// corrupting or deleting that real installation. That is a materially different, worse risk
/// than the read-only/no-mutation matrix rows below, so the "models present" combinations are
/// reported as unreachable here rather than exercised, pending a seam (making `modelsDirectory`
/// injectable, the same shape as #99's `defaults` injection) that a follow-up ticket would add.
/// `installedModels` non-empty-but-unsupported *is* covered below (§6) since that only requires
/// setting the `@Published` array directly, no disk mutation.
@MainActor
final class ViewModelCharacterizationTests: XCTestCase {
    // MARK: - Shared test infrastructure (local copies -- `MarcutAppTests.swift`'s `private` helpers are file-scoped and not visible here)

    private func createTestDocumentItem(status: RedactionStatus = .completed) -> DocumentItem {
        let url = URL(fileURLWithPath: "/tmp/test.docx")
        let item = DocumentItem(url: url)
        item.status = status
        return item
    }

    /// A fresh, isolated `UserDefaults` suite, cleared on creation and tracked for teardown.
    private var suiteNamesToClean: [String] = []

    private func makeIsolatedDefaults() -> UserDefaults {
        let suiteName = "com.marcut.viewmodelcharacterization.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        suiteNamesToClean.append(suiteName)
        return defaults
    }

    override func tearDownWithError() throws {
        for suiteName in suiteNamesToClean {
            UserDefaults().removePersistentDomain(forName: suiteName)
        }
        suiteNamesToClean.removeAll()
        for key in ["MARCUT_METADATA_PRESET", "MARCUT_METADATA_ARGS", "MARCUT_METADATA_SETTINGS_JSON"] {
            unsetenv(key)
        }
    }

    // MARK: - 1. updateState() -- direct calls (§3.2 item 1)

    /// Every published flag `updateState()` derives, exercised with a direct call (not the
    /// `add(urls: [])` indirection other tests in `MarcutAppTests.swift` use because
    /// `updateState()` used to be `private`) across every `RedactionStatus`.
    func testUpdateStateFlagsForEveryStatusCombination() {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())

        // No documents at all.
        viewModel.items = []
        viewModel.updateState()
        XCTAssertFalse(viewModel.hasDocuments)
        XCTAssertFalse(viewModel.hasValidDocuments)
        XCTAssertFalse(viewModel.hasProcessingDocuments)
        XCTAssertFalse(viewModel.hasCompletedDocuments)
        XCTAssertFalse(viewModel.hasFinishedProcessing)
        XCTAssertFalse(viewModel.hasFailedDocuments)

        // A single queued (never-run) document is not "finished" -- it still needs redaction.
        let queued = createTestDocumentItem(status: .validDocument)
        viewModel.items = [queued]
        viewModel.updateState()
        XCTAssertTrue(viewModel.hasDocuments)
        XCTAssertTrue(viewModel.hasValidDocuments)
        XCTAssertFalse(viewModel.hasProcessingDocuments)
        XCTAssertFalse(viewModel.hasCompletedDocuments)
        XCTAssertFalse(viewModel.hasFinishedProcessing)
        XCTAssertFalse(viewModel.hasFailedDocuments)

        // Every in-flight status counts as "processing".
        for status: RedactionStatus in [.checking, .processing, .analyzing, .redacting] {
            viewModel.items = [createTestDocumentItem(status: status)]
            viewModel.updateState()
            XCTAssertTrue(viewModel.hasProcessingDocuments, "\(status) must count as processing")
            XCTAssertFalse(viewModel.hasFinishedProcessing, "\(status) must not be reported finished")
        }

        // A lone completed document with nothing else pending is finished.
        viewModel.items = [createTestDocumentItem(status: .completed)]
        viewModel.updateState()
        XCTAssertTrue(viewModel.hasCompletedDocuments)
        XCTAssertFalse(viewModel.hasProcessingDocuments)
        XCTAssertFalse(viewModel.hasValidDocuments)
        XCTAssertFalse(viewModel.hasFailedDocuments)
        XCTAssertTrue(viewModel.hasFinishedProcessing)

        // A failed document alongside a completed one: failed flips on, finished must not.
        viewModel.items = [createTestDocumentItem(status: .completed), createTestDocumentItem(status: .failed)]
        viewModel.updateState()
        XCTAssertTrue(viewModel.hasCompletedDocuments)
        XCTAssertTrue(viewModel.hasFailedDocuments)
        XCTAssertFalse(viewModel.hasFinishedProcessing, "An unresolved failure must block 'finished'")

        // Cancelled + invalid documents contribute to none of the six positive flags.
        viewModel.items = [
            createTestDocumentItem(status: .cancelled),
            createTestDocumentItem(status: .invalidDocument),
        ]
        viewModel.updateState()
        XCTAssertFalse(viewModel.hasValidDocuments)
        XCTAssertFalse(viewModel.hasProcessingDocuments)
        XCTAssertFalse(viewModel.hasCompletedDocuments)
        XCTAssertFalse(viewModel.hasFailedDocuments)
        XCTAssertFalse(viewModel.hasFinishedProcessing)
        XCTAssertTrue(viewModel.hasDocuments, "The list is non-empty even though nothing is actionable")
    }

    /// The B5 power-assertion begin/end edge is driven directly off `updateState()`'s
    /// not-processing <-> processing transition -- acquired exactly once on the edge into
    /// processing, released exactly once on the edge back out, with no extra churn from
    /// redundant `updateState()` calls in between.
    func testUpdateStatePowerAssertionEdgeTriggersExactlyOncePerTransition() {
        var acquireCount = 0
        var releaseCount = 0
        let powerGuard = PowerAssertionGuard(
            acquire: { _ in acquireCount += 1; return 1 },
            release: { _ in releaseCount += 1 }
        )
        let viewModel = DocumentRedactionViewModel(powerAssertion: powerGuard, defaults: makeIsolatedDefaults())

        let item = createTestDocumentItem(status: .validDocument)
        viewModel.items = [item]
        viewModel.updateState()
        XCTAssertEqual(acquireCount, 0, "A merely-valid (not yet processing) document must not acquire")

        item.status = .processing
        viewModel.updateState()
        XCTAssertEqual(acquireCount, 1, "Entering a processing state must acquire exactly once")
        XCTAssertEqual(releaseCount, 0)

        // A redundant call with nothing changed must not acquire again -- it's edge-triggered.
        viewModel.updateState()
        XCTAssertEqual(acquireCount, 1)

        item.status = .completed
        viewModel.updateState()
        XCTAssertEqual(releaseCount, 1, "Leaving the processing state must release exactly once")

        viewModel.updateState()
        XCTAssertEqual(releaseCount, 1, "A redundant call with nothing changed must not release again")
    }

    /// `updateState()` persists (or clears) the pending-batch-job record on every call, into
    /// whatever `UserDefaults` suite the view model was constructed with -- exercised here
    /// against an isolated suite rather than `.standard`.
    func testUpdateStatePersistsPendingBatchJobRecordIntoInjectedDefaults() {
        let defaults = makeIsolatedDefaults()
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        XCTAssertNil(PendingBatchJobStore.load(defaults: defaults), "Nothing pending before any documents exist")

        let queued = createTestDocumentItem(status: .validDocument)
        viewModel.items = [queued]
        viewModel.updateState()

        let record = PendingBatchJobStore.load(defaults: defaults)
        XCTAssertEqual(record?.documentPaths, [queued.url.path])

        queued.status = .completed
        viewModel.updateState()
        XCTAssertNil(
            PendingBatchJobStore.load(defaults: defaults),
            "Once nothing is pending/in-flight, the persisted record must be cleared"
        )
    }

    // MARK: - 3. Batch ETA (§3.2 item 3)

    func testDocumentSizeSignalPrefersWordCountOverFileByteSize() throws {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let fileURL = tempDir.appendingPathComponent("doc.docx")
        let payload = Data(repeating: 0x41, count: 4096)
        try payload.write(to: fileURL)

        let item = DocumentItem(url: fileURL)
        item.wordCount = 250
        XCTAssertEqual(
            viewModel.progressMonitor.documentSizeSignal(for: item), 250,
            "Word count must win over file byte size when both are available"
        )

        item.wordCount = nil
        XCTAssertEqual(
            viewModel.progressMonitor.documentSizeSignal(for: item), Int64(payload.count),
            "File byte size is the fallback once word count is unavailable"
        )

        item.wordCount = 0
        XCTAssertEqual(
            viewModel.progressMonitor.documentSizeSignal(for: item), Int64(payload.count),
            "A zero word count is not a usable signal either -- falls back the same as nil"
        )
    }

    func testDocumentSizeSignalIsZeroWhenFileIsUnreadable() {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())
        let item = DocumentItem(url: URL(fileURLWithPath: "/nonexistent/\(UUID().uuidString).docx"))
        XCTAssertEqual(viewModel.progressMonitor.documentSizeSignal(for: item), 0)
    }

    func testRecordBatchETASampleSkipsCancelledAndUntrackedItems() {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())

        // Never started (not in `batchProcessingStartTimes`) -- nothing to record.
        let neverStarted = createTestDocumentItem(status: .completed)
        viewModel.progressMonitor.recordBatchETASample(for: neverStarted)
        XCTAssertTrue(viewModel.progressMonitor.batchETASamples.isEmpty)

        // Started, but cancelled rather than completed/failed -- not a meaningful rate signal.
        let cancelled = createTestDocumentItem(status: .cancelled)
        viewModel.progressMonitor.batchProcessingStartTimes[cancelled.id] = Date().addingTimeInterval(-5)
        viewModel.progressMonitor.recordBatchETASample(for: cancelled)
        XCTAssertTrue(
            viewModel.progressMonitor.batchETASamples.isEmpty,
            "A cancelled document must not contribute a sample"
        )
        XCTAssertNil(
            viewModel.progressMonitor.batchProcessingStartTimes[cancelled.id],
            "The start time is still consumed even when no sample is recorded"
        )
    }

    func testRecordBatchETASampleAppendsDurationAndSizeForCompletedDocument() throws {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())
        let item = createTestDocumentItem(status: .completed)
        item.wordCount = 1000
        viewModel.progressMonitor.batchProcessingStartTimes[item.id] = Date().addingTimeInterval(-2)

        viewModel.progressMonitor.recordBatchETASample(for: item)

        XCTAssertEqual(viewModel.progressMonitor.batchETASamples.count, 1)
        let sample = try XCTUnwrap(viewModel.progressMonitor.batchETASamples.first)
        XCTAssertEqual(sample.size, 1000)
        XCTAssertGreaterThanOrEqual(sample.duration, 2.0)
        XCTAssertNil(viewModel.progressMonitor.batchProcessingStartTimes[item.id], "The start time must be consumed")
    }

    func testUpdateBatchETAIsNilBelowMinimumSamplesAndClearsWhenNothingIsProcessing() {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())
        let processingItem = createTestDocumentItem(status: .processing)
        viewModel.items = [processingItem]
        viewModel.updateState()
        XCTAssertTrue(viewModel.hasProcessingDocuments)

        XCTAssertLessThan(
            BatchETACalculator.minimumSamples, 2 + 1,
            "Sanity check the constant this test exercises hasn't drifted silently"
        )

        // One sample: below `BatchETACalculator.minimumSamples` (2) -- must stay nil.
        viewModel.progressMonitor.batchETASamples = [BatchETASample(duration: 10, size: 500)]
        viewModel.progressMonitor.updateBatchETA()
        XCTAssertNil(viewModel.batchETA, "A single sample is not enough data for an estimate")

        // A second sample crosses the minimum -- an estimate should now appear.
        viewModel.progressMonitor.batchETASamples.append(BatchETASample(duration: 10, size: 500))
        viewModel.progressMonitor.updateBatchETA()
        XCTAssertNotNil(viewModel.batchETA, "Two samples meets BatchETACalculator.minimumSamples")

        // Once nothing is left processing/queued, the estimate is cleared outright.
        processingItem.status = .completed
        viewModel.updateState()
        viewModel.progressMonitor.updateBatchETA()
        XCTAssertNil(viewModel.batchETA, "No processing/queued documents left means no ETA to show")
    }

    // MARK: - 4. applyOutputArtifacts (§3.2 item 4)

    private func makeTempDir() -> URL {
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        // `/var` is a symlink to `/private/var` on macOS: `FileManager.default
        // .contentsOfDirectory(at:)` (used by `findScrubReport`) returns the resolved
        // `/private/var/...` form, so resolve here too or path-equality assertions flap
        // depending on which form each side happens to produce. `URL.resolvingSymlinksInPath()`
        // does not reliably resolve this particular symlink in the `swift test` CLI sandbox
        // (confirmed empirically), so this shells out to POSIX `realpath(3)` instead.
        var buffer = [Int8](repeating: 0, count: Int(PATH_MAX))
        guard realpath(dir.path, &buffer) != nil else { return dir }
        return URL(fileURLWithPath: String(cString: buffer), isDirectory: true)
    }

    func testApplyOutputArtifactsSetsReportHTMLOnlyWhenPresentOnDisk() {
        let defaults = makeIsolatedDefaults()
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        MetadataCleaningSettings.none.save(defaults: defaults)
        let dir = makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let item = createTestDocumentItem()
        let outputPath = dir.appendingPathComponent("out.docx").path
        let reportPath = dir.appendingPathComponent("out_report.json").path
        try? Data("{}".utf8).write(to: URL(fileURLWithPath: reportPath))

        viewModel.applyOutputArtifacts(
            to: item,
            outputPath: outputPath,
            reportPath: reportPath,
            scrubReportPath: dir.appendingPathComponent("out_scrub_report.json").path
        )
        XCTAssertEqual(item.redactedOutputURL?.path, outputPath)
        XCTAssertEqual(item.reportOutputURL?.path, reportPath)
        XCTAssertNil(item.reportHTMLOutputURL, "No sibling .html file exists yet")

        let htmlPath = dir.appendingPathComponent("out_report.html").path
        try? Data("<html></html>".utf8).write(to: URL(fileURLWithPath: htmlPath))
        let item2 = createTestDocumentItem()
        viewModel.applyOutputArtifacts(
            to: item2,
            outputPath: outputPath,
            reportPath: reportPath,
            scrubReportPath: dir.appendingPathComponent("out_scrub_report.json").path
        )
        XCTAssertEqual(item2.reportHTMLOutputURL?.path, htmlPath, "A sibling .html file must be picked up")
    }

    func testApplyOutputArtifactsSkipsScrubReportLookupWhenMetadataCleaningIsNone() {
        let defaults = makeIsolatedDefaults()
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        MetadataCleaningSettings.none.save(defaults: defaults)
        let dir = makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let outputPath = dir.appendingPathComponent("out.docx").path
        let scrubReportPath = dir.appendingPathComponent("out_scrub_report.json").path
        // Present on disk at exactly the expected path -- but must still be ignored below.
        try? Data("{}".utf8).write(to: URL(fileURLWithPath: scrubReportPath))

        let item = createTestDocumentItem()
        viewModel.applyOutputArtifacts(
            to: item,
            outputPath: outputPath,
            reportPath: dir.appendingPathComponent("out_report.json").path,
            scrubReportPath: scrubReportPath
        )

        XCTAssertNil(item.scrubReportOutputURL, "MetadataCleaningSettings == .none must skip the scrub lookup entirely")
        XCTAssertNil(item.metadataReportOutputURL)
    }

    func testApplyOutputArtifactsFindsScrubReportAtExpectedPath() {
        let defaults = makeIsolatedDefaults()
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        MetadataCleaningSettings.balanced.save(defaults: defaults)
        let dir = makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let outputPath = dir.appendingPathComponent("out.docx").path
        let scrubReportPath = dir.appendingPathComponent("out_scrub_report.json").path
        try? Data("{}".utf8).write(to: URL(fileURLWithPath: scrubReportPath))
        let scrubHTMLPath = dir.appendingPathComponent("out_scrub_report.html").path
        try? Data("<html></html>".utf8).write(to: URL(fileURLWithPath: scrubHTMLPath))

        let item = createTestDocumentItem()
        viewModel.applyOutputArtifacts(
            to: item,
            outputPath: outputPath,
            reportPath: dir.appendingPathComponent("out_report.json").path,
            scrubReportPath: scrubReportPath
        )

        XCTAssertEqual(item.scrubReportOutputURL?.path, scrubReportPath)
        XCTAssertEqual(item.metadataReportOutputURL?.path, scrubReportPath)
        XCTAssertEqual(item.scrubReportHTMLOutputURL?.path, scrubHTMLPath)
        XCTAssertEqual(item.metadataReportHTMLOutputURL?.path, scrubHTMLPath)
    }

    /// When the expected scrub-report path is missing, `applyOutputArtifacts` falls back to
    /// `findScrubReport(in:matching:)`'s alternate-naming search in the output directory.
    func testApplyOutputArtifactsFallsBackToAlternateScrubReportPath() {
        let defaults = makeIsolatedDefaults()
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        MetadataCleaningSettings.balanced.save(defaults: defaults)
        let dir = makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let baseName = "MyDocument"
        let outputPath = dir.appendingPathComponent("\(baseName).docx").path
        let expectedScrubReportPath = dir.appendingPathComponent("\(baseName)_scrub_report_DOES_NOT_EXIST.json").path
        // Alternate naming convention `findScrubReport` matches: "<baseName>_scrub_report.json".
        let alternatePath = dir.appendingPathComponent("\(baseName)_scrub_report.json").path
        try? Data("{}".utf8).write(to: URL(fileURLWithPath: alternatePath))

        let item = DocumentItem(url: URL(fileURLWithPath: "/tmp/\(baseName).docx"))
        item.status = .completed
        viewModel.applyOutputArtifacts(
            to: item,
            outputPath: outputPath,
            reportPath: dir.appendingPathComponent("\(baseName)_report.json").path,
            scrubReportPath: expectedScrubReportPath
        )

        XCTAssertEqual(
            item.scrubReportOutputURL?.path, alternatePath,
            "The alternate-naming fallback must be found when the expected path is missing"
        )
        XCTAssertEqual(item.metadataReportOutputURL?.path, alternatePath)
    }

    func testApplyOutputArtifactsLeavesScrubFieldsNilWhenReportTrulyMissing() {
        let defaults = makeIsolatedDefaults()
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        MetadataCleaningSettings.balanced.save(defaults: defaults)
        let dir = makeTempDir()
        defer { try? FileManager.default.removeItem(at: dir) }

        let item = DocumentItem(url: URL(fileURLWithPath: "/tmp/NothingHere.docx"))
        item.status = .completed
        viewModel.applyOutputArtifacts(
            to: item,
            outputPath: dir.appendingPathComponent("out.docx").path,
            reportPath: dir.appendingPathComponent("out_report.json").path,
            scrubReportPath: dir.appendingPathComponent("out_scrub_report.json").path
        )

        XCTAssertNil(item.scrubReportOutputURL)
        XCTAssertNil(item.metadataReportOutputURL)
        XCTAssertNil(item.scrubReportHTMLOutputURL)
    }

    // MARK: - 5. shareFinalRedactedCopy env save/restore (§3.2 item 6)

    /// Minimal `RedactionRunning` fake for the share-copy env-restore tests -- only
    /// `scrubMetadataOnlyAsync` is exercised by `shareFinalRedactedCopy`.
    private final class ShareCopyFakeRunner: RedactionRunning {
        var result: (success: Bool, error: String?, report: [String: Any]?) = (true, nil, nil)
        var thrownError: Error?

        func runEnhancedOllamaWithProgress(
            inputPath _: String, outputPath _: String, reportPath _: String, model _: String, debug _: Bool,
            mode _: String, llmSkipConfidence _: Double, llmConcurrency _: Int, chunkTokens _: Int, overlap _: Int,
            temperature _: Double, seed _: Int, processingStepTimeout _: TimeInterval?,
            cancellationChecker _: @escaping () -> Bool
        ) -> (stream: AsyncStream<PythonRunnerProgressUpdate>, result: Task<PythonRunOutcome, Never>) {
            let stream = AsyncStream<PythonRunnerProgressUpdate> { $0.finish() }
            return (stream, Task { .success })
        }

        func scrubMetadataOnlyAsync(
            inputPath _: String,
            outputPath _: String
        ) async throws -> (success: Bool, error: String?, report: [String: Any]?) {
            if let thrownError {
                throw thrownError
            }
            return result
        }

        func metadataReportOnlyAsync(
            inputPath _: String,
            reportPath _: String
        ) async throws -> (success: Bool, error: String?, report: [String: Any]?, htmlPath: String?) {
            (success: true, error: nil, report: nil, htmlPath: nil)
        }

        func generateScrubHTML(from _: String) async -> String? {
            nil
        }

        func clearCancellationRequest() {}
        func cancelCurrentOperation(source _: String) {}
        func updateRuleFilter(_: Set<RedactionRule>) {}
    }

    private func makeShareTestViewModel(runner: ShareCopyFakeRunner) -> DocumentRedactionViewModel {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())
        viewModel.runnerProvider = { [weak runner] in runner }
        viewModel.documentShareService.sharePresenter = { _ in true }
        return viewModel
    }

    func testShareFinalRedactedCopyRestoresPriorEnvironmentValuesOnSuccess() async {
        setenv("MARCUT_METADATA_PRESET", "balanced", 1)
        setenv("MARCUT_METADATA_ARGS", "--keep-author", 1)
        setenv("MARCUT_METADATA_SETTINGS_JSON", "{\"prior\":true}", 1)

        let runner = ShareCopyFakeRunner()
        runner.result = (success: true, error: nil, report: nil)
        let viewModel = makeShareTestViewModel(runner: runner)
        let item = createTestDocumentItem(status: .completed)
        item.redactedOutputURL = makeTempDir().appendingPathComponent("input.docx")

        await viewModel.shareFinalRedactedCopy(item)

        XCTAssertEqual(String(cString: getenv("MARCUT_METADATA_PRESET")), "balanced")
        XCTAssertEqual(String(cString: getenv("MARCUT_METADATA_ARGS")), "--keep-author")
        XCTAssertEqual(String(cString: getenv("MARCUT_METADATA_SETTINGS_JSON")), "{\"prior\":true}")
    }

    func testShareFinalRedactedCopyLeavesUnsetEnvironmentValuesUnsetOnSuccess() async {
        unsetenv("MARCUT_METADATA_PRESET")
        unsetenv("MARCUT_METADATA_ARGS")
        unsetenv("MARCUT_METADATA_SETTINGS_JSON")

        let runner = ShareCopyFakeRunner()
        runner.result = (success: true, error: nil, report: nil)
        let viewModel = makeShareTestViewModel(runner: runner)
        let item = createTestDocumentItem(status: .completed)
        item.redactedOutputURL = makeTempDir().appendingPathComponent("input.docx")

        await viewModel.shareFinalRedactedCopy(item)

        XCTAssertNil(getenv("MARCUT_METADATA_PRESET"), "A previously-unset key must stay unset, not become empty")
        XCTAssertNil(getenv("MARCUT_METADATA_ARGS"))
        XCTAssertNil(getenv("MARCUT_METADATA_SETTINGS_JSON"))
    }

    func testShareFinalRedactedCopyRestoresEnvironmentOnRunnerErrorPath() async {
        setenv("MARCUT_METADATA_PRESET", "maximum", 1)
        unsetenv("MARCUT_METADATA_ARGS")
        setenv("MARCUT_METADATA_SETTINGS_JSON", "{\"prior\":true}", 1)

        let runner = ShareCopyFakeRunner()
        runner.result = (success: false, error: "boom", report: nil)
        let viewModel = makeShareTestViewModel(runner: runner)
        let item = createTestDocumentItem(status: .completed)
        item.redactedOutputURL = makeTempDir().appendingPathComponent("input.docx")

        await viewModel.shareFinalRedactedCopy(item)

        XCTAssertEqual(item.errorMessage, "boom")
        XCTAssertEqual(String(cString: getenv("MARCUT_METADATA_PRESET")), "maximum")
        XCTAssertNil(getenv("MARCUT_METADATA_ARGS"), "Still unset after a failed run")
        XCTAssertEqual(String(cString: getenv("MARCUT_METADATA_SETTINGS_JSON")), "{\"prior\":true}")
    }

    func testShareFinalRedactedCopyRestoresEnvironmentWhenRunnerThrows() async {
        setenv("MARCUT_METADATA_PRESET", "custom", 1)

        let runner = ShareCopyFakeRunner()
        runner.thrownError = NSError(domain: "test", code: 1, userInfo: [NSLocalizedDescriptionKey: "kaboom"])
        let viewModel = makeShareTestViewModel(runner: runner)
        let item = createTestDocumentItem(status: .completed)
        item.redactedOutputURL = makeTempDir().appendingPathComponent("input.docx")

        await viewModel.shareFinalRedactedCopy(item)

        XCTAssertTrue(item.errorMessage?.contains("kaboom") ?? false)
        XCTAssertEqual(
            String(cString: getenv("MARCUT_METADATA_PRESET")), "custom",
            "The defer-based restore must run even when the runner throws"
        )
    }

    // MARK: - 6. environmentStatus / isEnvironmentReady matrix (§4 slice-4 diagnostics matrix)

    private func makeEnvironmentTestViewModel() -> (DocumentRedactionViewModel, PythonBridgeService) {
        let bridge = PythonBridgeService(autoStartOllama: false, allowOllamaService: false)
        let viewModel = DocumentRedactionViewModel(pythonBridge: bridge, defaults: makeIsolatedDefaults())
        return (viewModel, bridge)
    }

    func testEnvironmentStatusFrameworkMissingOverridesEverythingElse() {
        let (viewModel, bridge) = makeEnvironmentTestViewModel()
        viewModel.frameworkAvailable = false
        bridge.isOllamaRunning = true // even a healthy Ollama must not matter
        viewModel.settings.mode = .rules

        XCTAssertFalse(viewModel.isEnvironmentReady)
        XCTAssertEqual(viewModel.environmentStatus, "❌ Python framework missing - Please reinstall MarcutApp")
    }

    func testEnvironmentStatusRulesOnlyModeIgnoresOllamaEntirely() {
        let (viewModel, bridge) = makeEnvironmentTestViewModel()
        viewModel.frameworkAvailable = true
        viewModel.settings.mode = .rules
        bridge.isOllamaRunning = false
        bridge.ollamaLaunchError = "Ollama crashed on launch"

        XCTAssertTrue(viewModel.isEnvironmentReady, "Rules Only mode needs only the framework, not Ollama")
        XCTAssertEqual(viewModel.environmentStatus, "✅ Ready (Rules Only Mode)")
    }

    func testEnvironmentStatusLLMModeOllamaNotFoundWhenNoLaunchError() {
        let (viewModel, bridge) = makeEnvironmentTestViewModel()
        viewModel.frameworkAvailable = true
        viewModel.settings.mode = .rulesOverride // usesLLM == true
        bridge.isOllamaRunning = false
        bridge.ollamaLaunchError = nil

        // `getOllamaPath()` (private) always returns nil under `swift test` -- no bundled
        // `ollama` binary and no `Bundle.main.executableURL` sibling -- so this branch, not the
        // "Starting Ollama service..." one, is what a real test run actually hits.
        XCTAssertFalse(viewModel.isEnvironmentReady)
        XCTAssertEqual(viewModel.environmentStatus, "❌ Ollama service not found - Check installation")
    }

    func testEnvironmentStatusLLMModeSurfacesOllamaLaunchError() {
        let (viewModel, bridge) = makeEnvironmentTestViewModel()
        viewModel.frameworkAvailable = true
        viewModel.settings.mode = .llmOverrides
        bridge.isOllamaRunning = false
        bridge.ollamaLaunchError = "port 11434 already in use"

        XCTAssertFalse(viewModel.isEnvironmentReady)
        XCTAssertEqual(viewModel.environmentStatus, "❌ port 11434 already in use")
    }

    func testEnvironmentStatusLLMModeNoModelsAvailableAtAllWhenNoneInstalled() {
        let (viewModel, bridge) = makeEnvironmentTestViewModel()
        viewModel.frameworkAvailable = true
        viewModel.settings.mode = .constrainedOverrides
        bridge.isOllamaRunning = true
        bridge.installedModels = []

        XCTAssertFalse(viewModel.isEnvironmentReady, "usesLLM mode requires at least one available model")
        XCTAssertEqual(viewModel.environmentStatus, "⚠️ No AI models available - Will download on first use")
    }

    func testEnvironmentStatusLLMModeInstalledButUnsupportedModels() {
        let (viewModel, bridge) = makeEnvironmentTestViewModel()
        viewModel.frameworkAvailable = true
        viewModel.settings.mode = .llmOverrides
        bridge.isOllamaRunning = true
        // Present on disk (per `installedModels`) but not one of `ModelCatalog.shared.modelIds`,
        // so `availableModels` filters it out -- this does not touch any real model directory,
        // it only sets the `@Published` array directly (see the type doc's "missing seam" note
        // for why the genuinely-on-disk-and-supported combination is not exercised here).
        bridge.installedModels = ["some-unsupported-model:1b"]

        XCTAssertFalse(viewModel.isEnvironmentReady)
        XCTAssertEqual(viewModel.environmentStatus, "⚠️ No supported models - Install qwen2.5:14b or similar")
    }

    // MARK: - 7. Pending-job recovery (§4 slice-9 pending-job recovery test)

    func testResumePendingJobRepopulatesItemsAndSettingsFromRecord() {
        let defaults = makeIsolatedDefaults()
        var resumedSettings = RedactionSettings()
        resumedSettings.model = "qwen2.5:7b"
        resumedSettings.debug = true
        let paths = ["/tmp/one.docx", "/tmp/two.docx"]
        PendingBatchJobStore.save(
            PendingBatchJobRecord(documentPaths: paths, settings: resumedSettings),
            defaults: defaults
        )

        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        XCTAssertNotNil(viewModel.pendingResumeRecord, "The record must be loaded from the injected suite at init")

        viewModel.resumePendingJob()

        XCTAssertNil(viewModel.pendingResumeRecord, "Consumed once resumed")
        XCTAssertEqual(viewModel.settings, resumedSettings, "The persisted run's settings must be restored")
        XCTAssertEqual(viewModel.items.map(\.url.path).sorted(), paths.sorted())
    }

    func testResumePendingJobIsANoOpWithoutAPendingRecord() {
        let viewModel = DocumentRedactionViewModel(defaults: makeIsolatedDefaults())
        XCTAssertNil(viewModel.pendingResumeRecord)

        viewModel.resumePendingJob()

        XCTAssertTrue(viewModel.items.isEmpty)
    }

    /// The "echo" call `discardPendingJob()` receives immediately after a genuine
    /// `resumePendingJob()` (SwiftUI writing `isPresented = false` back through the alert
    /// binding as the alert finishes dismissing) must not wipe the record `resumePendingJob()`
    /// just caused to be re-persisted for the newly-resumed, still-pending items. A second,
    /// genuine `discardPendingJob()` call afterwards must still clear it.
    func testDiscardPendingJobConsumesOneEchoCallAfterResumeThenClearsOnNextGenuineCall() {
        let defaults = makeIsolatedDefaults()
        let record = PendingBatchJobRecord(
            documentPaths: ["/tmp/resume-me.docx"],
            settings: RedactionSettings()
        )
        PendingBatchJobStore.save(record, defaults: defaults)
        let viewModel = DocumentRedactionViewModel(defaults: defaults)

        viewModel.resumePendingJob()
        XCTAssertNotNil(
            PendingBatchJobStore.load(defaults: defaults),
            "resumePendingJob's own add(urls:) -> updateState() re-persists the still-pending items"
        )

        // The echo call: must be swallowed, not wipe the just-re-persisted record.
        viewModel.discardPendingJob()
        XCTAssertNotNil(
            PendingBatchJobStore.load(defaults: defaults),
            "The echo discard immediately after resume must not clear the freshly-resumed record"
        )

        // A genuine, later discard must still work.
        viewModel.discardPendingJob()
        XCTAssertNil(
            PendingBatchJobStore.load(defaults: defaults),
            "A real discard call (not the resume echo) must clear the persisted record"
        )
    }

    func testDiscardPendingJobWithoutPriorResumeClearsImmediately() {
        let defaults = makeIsolatedDefaults()
        PendingBatchJobStore.save(
            PendingBatchJobRecord(documentPaths: ["/tmp/a.docx"], settings: RedactionSettings()),
            defaults: defaults
        )
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        XCTAssertNotNil(viewModel.pendingResumeRecord)

        viewModel.discardPendingJob()

        XCTAssertNil(viewModel.pendingResumeRecord)
        XCTAssertNil(PendingBatchJobStore.load(defaults: defaults))
    }

    /// `persistPendingBatchJobIfNeeded()` (called from every `updateState()`) skips the write
    /// when the pending path set hasn't changed since the last persist -- exercised by injecting
    /// a different value straight into the defaults suite in between two `updateState()` calls
    /// whose derived path set is identical: the dedupe guard must leave that injected value
    /// alone, and only a real path-set change on a later call must overwrite it.
    func testPersistPendingBatchJobIfNeededDedupesUnchangedPathSet() {
        let defaults = makeIsolatedDefaults()
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        let itemA = createTestDocumentItem(status: .validDocument)
        let itemB = createTestDocumentItem(status: .validDocument)
        viewModel.items = [itemA, itemB]
        viewModel.updateState()

        let firstWrite = PendingBatchJobStore.load(defaults: defaults)
        XCTAssertEqual(Set(firstWrite?.documentPaths ?? []), Set([itemA.url.path, itemB.url.path]))

        // Simulate something else having written a different record in between -- if the dedupe
        // guard is working, an unchanged-path-set `updateState()` call must leave this alone.
        let injected = PendingBatchJobRecord(
            documentPaths: ["/tmp/should-not-be-overwritten.docx"],
            settings: viewModel.settings
        )
        PendingBatchJobStore.save(injected, defaults: defaults)

        viewModel.updateState() // items/paths unchanged from the last real persist
        XCTAssertEqual(
            PendingBatchJobStore.load(defaults: defaults)?.documentPaths, injected.documentPaths,
            "An unchanged path set must dedupe -- the injected value must survive the redundant call"
        )

        // Now genuinely change the path set: this must overwrite the injected value.
        itemB.status = .completed
        viewModel.updateState()
        XCTAssertEqual(
            PendingBatchJobStore.load(defaults: defaults)?.documentPaths, [itemA.url.path],
            "A real path-set change must overwrite whatever was there, injected value included"
        )
    }
}
