@testable import MarcutApp
import XCTest

/// Golden bridge-call characterization suite for `DocumentRedactionViewModel` (issue #100).
/// See `RedactionCharacterizationHarness.swift`'s header doc-comment for what every golden
/// snapshots, the environment allowlist, the normalizer, and how to re-baseline.
///
/// This is the prerequisite gate for every extraction slice in
/// `docs/design/view_controller_decomposition.md` (#103-#111): every slice must run
///
///     swift test --package-path src/swift/MarcutApp --filter RedactionCharacterizationTests
///
/// before and after its change and get zero diffs.
@MainActor
final class RedactionCharacterizationTests: XCTestCase {
    override func setUpWithError() throws {
        RedactionCharacterizationHarness.unsetAllowlistedEnv()
    }

    override func tearDownWithError() throws {
        RedactionCharacterizationHarness.unsetAllowlistedEnv()
        // `generateMetadataReportsInPlace` writes through `FileAccessCoordinator`'s real,
        // non-injectable metadata-report cache under Application Support (see the harness type
        // doc: no new seam is added here per the ticket's "no production code moves" scope) --
        // clear it so scenario runs don't leave files behind in the real user's app data.
        FileAccessCoordinator.shared.clearMetadataReportCache()
    }

    // MARK: - Scenario harness

    /// Runs one scenario end-to-end against a fresh, isolated view model + `UserDefaults` suite
    /// + temp directory, then asserts the resulting `CharacterizationSnapshot` against
    /// `Golden/<name>.json` (or writes it, under `MARCUT_GOLDEN_UPDATE=1`).
    private func runScenario(
        name: String,
        metadataSettings: MetadataCleaningSettings = .none,
        preflightResult: Bool = true,
        modelReadyResult: Bool = true,
        sharePresenterResult: Bool = true,
        runnerAvailable: Bool = true,
        configureRunner: (RecordingRedactionRunner) -> Void = { _ in },
        configureViewModel: (DocumentRedactionViewModel) -> Void = { _ in },
        items: (URL) -> [DocumentItem],
        operation: (
            DocumentRedactionViewModel,
            [DocumentItem],
            URL,
            RecordingRedactionRunner,
            EventRecorder
        ) async -> Void
    ) async throws {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: tempDir) }

        let defaults = RedactionCharacterizationHarness.makeDefaults()
        metadataSettings.save(defaults: defaults)

        let viewModel = RedactionCharacterizationHarness.makeViewModel(defaults: defaults)
        let recorder = EventRecorder()
        let runner = RecordingRedactionRunner(recorder: recorder)
        configureRunner(runner)

        if runnerAvailable {
            viewModel.runnerProvider = { [runner] in runner }
        } else {
            viewModel.runnerProvider = { nil }
        }
        viewModel.llmPreflightCheck = { model in
            recorder.record("llmPreflightCheck", [model])
            return preflightResult
        }
        viewModel.modelReadinessCheck = { model in
            recorder.record("modelReadinessCheck", [model])
            return modelReadyResult
        }
        viewModel.documentShareService.sharePresenter = { url in
            recorder.record("sharePresenter", [url.path])
            return sharePresenterResult
        }
        configureViewModel(viewModel)

        let envBefore = RedactionCharacterizationHarness.currentEnvSnapshot()
        let docItems = items(tempDir)
        viewModel.items = docItems
        viewModel.updateState()

        await operation(viewModel, docItems, tempDir, runner, recorder)

        // Bounded quiescence poll: wait for the view model to leave "processing" and for the
        // scrub-report-path env var (unset by processDocumentWithPythonKit's completion task
        // `defer`, which runs on a detached task) to clear. See the harness type doc.
        var iterations = 0
        while viewModel.hasProcessingDocuments || getenv("MARCUT_SCRUB_REPORT_PATH") != nil, iterations < 400 {
            try? await Task.sleep(nanoseconds: 5_000_000)
            iterations += 1
        }

        let snapshot = CharacterizationSnapshot(
            scenario: name,
            envBefore: envBefore,
            events: recorder.events,
            itemsAfter: docItems.map(ItemSnapshot.init),
            flagsAfter: FlagsSnapshot(viewModel),
            envAfter: RedactionCharacterizationHarness.currentEnvSnapshot()
        )
        try GoldenStore.assertMatchesGolden(name: name, snapshot: snapshot, tempDir: tempDir)
    }

    /// A `.validDocument` item pointing at the real `sample-files/Consent.docx` fixture --
    /// nothing in this harness reads its bytes for real processing, only its path.
    private func makeValidItem() -> DocumentItem {
        let item = DocumentItem(url: URL(fileURLWithPath: RedactionCharacterizationHarness.fixturePath(.validDocx)))
        item.status = .validDocument
        return item
    }

    /// Writes a redacted-DOCX + audit-report pair at the exact paths the view model computed,
    /// optionally alongside a scrub report at the exact expected path (`atExpectedScrubPath`) or
    /// at an alternate-naming path in the same directory (exercising the `findScrubReport`
    /// fallback `applyOutputArtifacts` uses).
    private func successRunScript(writeScrubReport: ScrubReportPlacement) -> RecordingRedactionRunner.RunScript {
        .init(outcome: .success, writeArtifacts: { outputPath, reportPath, scrubReportPathAtCall in
            try? FileManager.default.copyItem(
                atPath: RedactionCharacterizationHarness.fixturePath(.validDocx),
                toPath: outputPath
            )
            try? "{}".write(toFile: reportPath, atomically: true, encoding: .utf8)
            switch writeScrubReport {
            case .none:
                break
            case .atExpectedPath:
                guard let scrubReportPathAtCall else { break }
                try? "{\"summary\":{}}".write(toFile: scrubReportPathAtCall, atomically: true, encoding: .utf8)
                let html = (scrubReportPathAtCall as NSString).deletingPathExtension + ".html"
                try? "<html></html>".write(toFile: html, atomically: true, encoding: .utf8)
            case .alternateNaming:
                let dir = (outputPath as NSString).deletingLastPathComponent
                let alt = (dir as NSString).appendingPathComponent("Consent (scrub-report alt).json")
                try? "{\"summary\":{}}".write(toFile: alt, atomically: true, encoding: .utf8)
            }
        })
    }

    private enum ScrubReportPlacement {
        case none
        case atExpectedPath
        case alternateNaming
    }

    // MARK: - 1. rules_only_success / rules_only_success_no_scrub_report

    func testRulesOnlySuccess() async throws {
        try await runScenario(
            name: "rules_only_success",
            metadataSettings: .balanced,
            configureRunner: { runner in
                runner.runEnhancedScript = self.successRunScript(writeScrubReport: .atExpectedPath)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rules
            await vm.processAllDocuments(to: dir)
        }
    }

    func testRulesOnlySuccessNoScrubReport() async throws {
        try await runScenario(
            name: "rules_only_success_no_scrub_report",
            metadataSettings: .balanced,
            configureRunner: { runner in
                runner.runEnhancedScript = self.successRunScript(writeScrubReport: .alternateNaming)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rules
            await vm.processAllDocuments(to: dir)
        }
    }

    // MARK: - 2. llm_mode_debug_on / llm_mode_debug_off

    func testLLMModeDebugOn() async throws {
        try await runScenario(
            name: "llm_mode_debug_on",
            configureRunner: { runner in
                runner.runEnhancedScript = self.successRunScript(writeScrubReport: .none)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rulesOverride
            vm.settings.debug = true
            await vm.processAllDocuments(to: dir)
        }
    }

    func testLLMModeDebugOff() async throws {
        try await runScenario(
            name: "llm_mode_debug_off",
            configureRunner: { runner in
                runner.runEnhancedScript = self.successRunScript(writeScrubReport: .none)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rulesOverride
            vm.settings.debug = false
            await vm.processAllDocuments(to: dir)
        }
    }

    // MARK: - 3. llm_mode_preflight_fails

    func testLLMModePreflightFails() async throws {
        try await runScenario(
            name: "llm_mode_preflight_fails",
            preflightResult: false,
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rulesOverride
            await vm.processAllDocuments(to: dir)
        }
    }

    // MARK: - 4. redaction_failure_with_report / _no_report / _stalled

    func testRedactionFailureWithReport() async throws {
        try await runScenario(
            name: "redaction_failure_with_report",
            configureRunner: { runner in
                runner.runEnhancedScript = .init(outcome: .failure, writeArtifacts: { _, reportPath, _ in
                    let payload: [String: Any] = [
                        "status": "failed",
                        "input_file": "Consent.docx",
                        "error_code": "AI_PROCESSING_TIMEOUT",
                        "message": "Processing exceeded the deadline",
                        "technical_details": "deadline exceeded after 300s",
                    ]
                    if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) {
                        try? data.write(to: URL(fileURLWithPath: reportPath))
                    }
                })
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rules
            await vm.processAllDocuments(to: dir)
        }
    }

    func testRedactionFailureNoReport() async throws {
        try await runScenario(
            name: "redaction_failure_no_report",
            configureRunner: { runner in
                runner.runEnhancedScript = .init(outcome: .failure)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rules
            await vm.processAllDocuments(to: dir)
        }
    }

    func testRedactionStalled() async throws {
        try await runScenario(
            name: "redaction_stalled",
            configureRunner: { runner in
                runner.runEnhancedScript = .init(outcome: .stalled)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            vm.settings.mode = .rules
            await vm.processAllDocuments(to: dir)
        }
    }

    // MARK: - 5. metadata_scrub_success / _corrupt_output / _runner_error

    func testMetadataScrubSuccess() async throws {
        try await runScenario(
            name: "metadata_scrub_success",
            configureRunner: { runner in
                runner.scrubScript = .init(
                    success: true,
                    report: ["summary": ["total_cleaned": 5, "total_preserved": 2], "embedded_docs_found": []],
                    outputFixture: .validDocx
                )
                runner.generateScrubHTMLContent = "<html>scrub report</html>"
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            await vm.scrubMetadataOnly(to: dir)
        }
    }

    func testMetadataScrubCorruptOutput() async throws {
        try await runScenario(
            name: "metadata_scrub_corrupt_output",
            configureRunner: { runner in
                runner.scrubScript = .init(success: true, outputFixture: .corruptDocx)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            await vm.scrubMetadataOnly(to: dir)
        }
    }

    func testMetadataScrubRunnerError() async throws {
        struct ScrubError: Error, LocalizedError {
            var errorDescription: String? {
                "Python error: worker crashed"
            }
        }
        try await runScenario(
            name: "metadata_scrub_runner_error",
            configureRunner: { runner in
                runner.scrubScript = .init(throwsError: ScrubError())
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            await vm.scrubMetadataOnly(to: dir)
        }
    }

    // MARK: - 6. metadata_report_in_place_html_present / _html_fallback

    func testMetadataReportInPlaceHTMLPresent() async throws {
        try await runScenario(
            name: "metadata_report_in_place_html_present",
            configureRunner: { runner in
                runner.reportScript = .init(
                    success: true,
                    report: ["summary": ["file_name": "Consent.docx"]],
                    htmlPath: "/tmp/does-not-need-to-exist-report.html",
                    writeReportFile: true,
                    writeHTMLSibling: false
                )
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            await vm.generateMetadataReportsInPlace(destination: dir)
        }
    }

    func testMetadataReportInPlaceHTMLFallback() async throws {
        try await runScenario(
            name: "metadata_report_in_place_html_fallback",
            configureRunner: { runner in
                runner.reportScript = .init(
                    success: true,
                    report: ["summary": ["file_name": "Consent.docx"]],
                    htmlPath: nil,
                    writeReportFile: true,
                    writeHTMLSibling: true
                )
                // Bridge-side on-demand generation is unavailable; the code must fall back to
                // the sibling HTML file `writeHTMLSibling` above already placed on disk.
                runner.generateScrubHTMLContent = nil
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, _ in
            await vm.generateMetadataReportsInPlace(destination: dir)
        }
    }

    // MARK: - 7. share_final_copy_*

    /// A `.completed` item with a real file at `redactedOutputURL`, as `shareFinalRedactedCopy`
    /// requires (it reads `item.redactedOutputURL ?? item.scrubOutputURL`, then computes
    /// `finalRedactedCopyURL` relative to it).
    private func makeShareableItem(in dir: URL) -> DocumentItem {
        let sourcePath = dir.appendingPathComponent("Consent.docx")
        try? FileManager.default.copyItem(
            atPath: RedactionCharacterizationHarness.fixturePath(.validDocx),
            toPath: sourcePath.path
        )
        let item = DocumentItem(url: sourcePath)
        item.status = .completed
        item.redactedOutputURL = sourcePath
        return item
    }

    func testShareFinalCopyEnvUnsetSuccess() async throws {
        try await runScenario(
            name: "share_final_copy_env_unset_success",
            configureRunner: { runner in
                runner.scrubScript = .init(success: true, outputFixture: .validDocx)
            },
            items: { dir in [makeShareableItem(in: dir)] }
        ) { vm, items, _, _, _ in
            unsetenv("MARCUT_METADATA_PRESET")
            unsetenv("MARCUT_METADATA_ARGS")
            unsetenv("MARCUT_METADATA_SETTINGS_JSON")
            await vm.shareFinalRedactedCopy(items[0])
        }
    }

    func testShareFinalCopyEnvPresetSuccess() async throws {
        try await runScenario(
            name: "share_final_copy_env_preset_success",
            configureRunner: { runner in
                runner.scrubScript = .init(success: true, outputFixture: .validDocx)
            },
            items: { dir in [makeShareableItem(in: dir)] }
        ) { vm, items, _, _, _ in
            setenv("MARCUT_METADATA_PRESET", "custom", 1)
            setenv("MARCUT_METADATA_ARGS", "--no-clean-author", 1)
            setenv("MARCUT_METADATA_SETTINGS_JSON", "{\"cleanAuthor\":false}", 1)
            await vm.shareFinalRedactedCopy(items[0])
        }
    }

    func testShareFinalCopyRunnerError() async throws {
        struct ShareError: Error, LocalizedError {
            var errorDescription: String? {
                "Python error: bridge unavailable"
            }
        }
        try await runScenario(
            name: "share_final_copy_runner_error",
            configureRunner: { runner in
                runner.scrubScript = .init(throwsError: ShareError())
            },
            items: { dir in [makeShareableItem(in: dir)] }
        ) { vm, items, _, _, _ in
            await vm.shareFinalRedactedCopy(items[0])
        }
    }

    func testShareFinalCopyResultFailure() async throws {
        try await runScenario(
            name: "share_final_copy_result_failure",
            configureRunner: { runner in
                runner.scrubScript = .init(success: false, error: "Unable to finalize.", outputFixture: .none)
            },
            items: { dir in [makeShareableItem(in: dir)] }
        ) { vm, items, _, _, _ in
            await vm.shareFinalRedactedCopy(items[0])
        }
    }

    // MARK: - 8. stop_mid_run

    func testStopMidRun() async throws {
        let gate = RunGate()
        try await runScenario(
            name: "stop_mid_run",
            configureRunner: { runner in
                runner.runEnhancedScript = .init(outcome: .cancelled, gate: gate)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, _, dir, _, recorder in
            vm.settings.mode = .rules
            let runTask = Task { await vm.processAllDocuments(to: dir) }

            var iterations = 0
            while !recorder.events.contains(where: { $0.method == "runEnhancedOllamaWithProgress" }),
                  iterations < 400
            {
                try? await Task.sleep(nanoseconds: 5_000_000)
                iterations += 1
            }

            vm.stopProcessing()
            await gate.open()
            await runTask.value
        }
    }

    // MARK: - 9. retry_after_failure

    func testRetryAfterFailure() async throws {
        try await runScenario(
            name: "retry_after_failure",
            configureRunner: { runner in
                runner.runEnhancedScript = .init(outcome: .failure)
            },
            items: { _ in [makeValidItem()] }
        ) { vm, items, dir, runner, _ in
            vm.settings.mode = .rules
            await vm.processAllDocuments(to: dir)

            runner.runEnhancedScript = self.successRunScript(writeScrubReport: .none)
            vm.retryFailedDocuments(destination: dir)

            var iterations = 0
            while items[0].status == .failed, iterations < 400 {
                try? await Task.sleep(nanoseconds: 5_000_000)
                iterations += 1
            }
            iterations = 0
            while vm.hasProcessingDocuments, iterations < 400 {
                try? await Task.sleep(nanoseconds: 5_000_000)
                iterations += 1
            }
            // Grace period for retryDocument's follow-on `processAllDocuments` call.
            try? await Task.sleep(nanoseconds: 50_000_000)
        }
    }

    // MARK: - 10. runner_unavailable

    func testRunnerUnavailable() async throws {
        try await runScenario(
            name: "runner_unavailable",
            metadataSettings: .balanced,
            runnerAvailable: false,
            items: { _ in
                let redactionItem = makeValidItem()
                let scrubItem = makeValidItem()
                let reportItem = makeValidItem()
                return [redactionItem, scrubItem, reportItem]
            }
        ) { vm, items, dir, _, _ in
            vm.settings.mode = .rules

            // Drive each entry point against exactly the one item meant for it -- `vm.items`
            // is swapped per phase so `scrubMetadataOnly`/`generateMetadataReportsInPlace`'s own
            // eligibility filtering doesn't also pick up an earlier phase's now-`.failed` item.
            vm.items = [items[0]]
            await vm.processDocument(items[0], destination: dir)

            vm.items = [items[1]]
            await vm.scrubMetadataOnly(to: dir)

            vm.items = [items[2]]
            await vm.generateMetadataReportsInPlace(destination: dir)

            vm.items = items
            vm.updateState()
        }
    }
}
