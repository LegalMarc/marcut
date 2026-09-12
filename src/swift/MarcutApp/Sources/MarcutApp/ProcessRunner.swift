import Foundation

/// Single-document execution collaborator extracted from `DocumentRedactionViewModel`
/// (`docs/design/view_controller_decomposition.md` §2.1, slice 8; issue #110). This is the direct
/// PythonKit call boundary: owns `processDocument`, `processDocumentWithPythonKit`,
/// `applyAdvancedSettingsEnvironment`, `applyMetadataSettingsEnvironment`,
/// `logAdvancedSettingsSnapshot`, `awaitPythonOutcome`, and the metadata counterpart
/// `scrubDocumentMetadataOnly`/`generateMetadataReport`.
///
/// `processingTasks`/`activeAttemptTokens` stay owned by the view model until #111's
/// `BatchCoordinator` extraction (out of scope for this slice), so this collaborator reaches back
/// through `mintAttemptToken`/`isAttemptCurrent`/`registerProcessingTask`/`isProcessingCancelled`
/// rather than holding them itself. `finalizeProcessing`, `assignFailureMessageIfNeeded`,
/// `loadFailureReport`, `validateDocxStructure`, and `updateState` also stay on the view model
/// per `docs/design/view_controller_decomposition.md` §2.1's explicit "stays" list -- the first
/// three are additionally called directly by name from `@testable import MarcutApp` tests, so
/// moving them would change a tested surface -- and are reached through constructor closures the
/// same way `ProgressMonitor.failItem` reaches back into the view model. `outputArtifactManager`/
/// `progressMonitor` are held directly (like `EnvironmentDiagnosticsService` holds `pythonBridge`
/// directly): both are themselves already-extracted collaborators with no reach back into this
/// one, so a direct reference is simpler than re-deriving their surface as closures.
///
/// The environment-variable order the goldens pin is preserved exactly: `clearCancellationRequest`
/// -> `MARCUT_LOG_PATH` -> `MARCUT_ADVANCED_*` -> `MARCUT_METADATA_*` -> model readiness (LLM
/// only) -> `MARCUT_SCRUB_REPORT_PATH` -> runner; and for scrub: `MARCUT_METADATA_*` ->
/// `MARCUT_METADATA_ONLY` -> runner, `MARCUT_METADATA_ONLY` unset on return.
@MainActor
final class ProcessRunner {
    private let defaults: UserDefaults
    private let pythonBridge: PythonBridgeService
    private let outputArtifactManager: OutputArtifactManager
    private let progressMonitor: ProgressMonitor

    private let runnerProvider: () -> (any RedactionRunning)?
    private let settingsProvider: () -> RedactionSettings
    private let itemsProvider: () -> [DocumentItem]
    private let llmPreflightCheck: (String) async -> Bool
    private let modelReadinessCheck: (String) async -> Bool
    private let markMetadataScrubUsed: () -> Void
    private let updateState: () -> Void
    private let validateDocxStructure: (URL) async -> Bool
    private let finalizeProcessing: (DocumentItem) -> Void
    private let assignFailureMessageIfNeeded: (DocumentItem) -> Void
    private let loadFailureReport: (String) -> (code: String, message: String, details: String)?
    /// Mints and stores a fresh attempt token for `itemId` in the view model's
    /// `activeAttemptTokens`, returning it. See `DocumentRedactionViewModel.activeAttemptTokens`.
    private let mintAttemptToken: (UUID) -> UUID
    /// Whether `token` is still the current attempt for `itemId` in the view model's
    /// `activeAttemptTokens` -- false means a newer attempt (or an explicit abandon) superseded it.
    private let isAttemptCurrent: (UUID, UUID) -> Bool
    /// Cancels any existing processing task for `itemId` and stores `task` as the new one, in the
    /// view model's `processingTasks`.
    private let registerProcessingTask: (UUID, Task<Void, Never>) -> Void
    /// Whether the view model's `processingTasks` entry for `itemId` has been cancelled.
    private let isProcessingCancelled: (UUID) -> Bool

    init(
        defaults: UserDefaults,
        pythonBridge: PythonBridgeService,
        outputArtifactManager: OutputArtifactManager,
        progressMonitor: ProgressMonitor,
        runnerProvider: @escaping () -> (any RedactionRunning)?,
        settingsProvider: @escaping () -> RedactionSettings,
        itemsProvider: @escaping () -> [DocumentItem],
        llmPreflightCheck: @escaping (String) async -> Bool,
        modelReadinessCheck: @escaping (String) async -> Bool,
        markMetadataScrubUsed: @escaping () -> Void,
        updateState: @escaping () -> Void,
        validateDocxStructure: @escaping (URL) async -> Bool,
        finalizeProcessing: @escaping (DocumentItem) -> Void,
        assignFailureMessageIfNeeded: @escaping (DocumentItem) -> Void,
        loadFailureReport: @escaping (String) -> (code: String, message: String, details: String)?,
        mintAttemptToken: @escaping (UUID) -> UUID,
        isAttemptCurrent: @escaping (UUID, UUID) -> Bool,
        registerProcessingTask: @escaping (UUID, Task<Void, Never>) -> Void,
        isProcessingCancelled: @escaping (UUID) -> Bool
    ) {
        self.defaults = defaults
        self.pythonBridge = pythonBridge
        self.outputArtifactManager = outputArtifactManager
        self.progressMonitor = progressMonitor
        self.runnerProvider = runnerProvider
        self.settingsProvider = settingsProvider
        self.itemsProvider = itemsProvider
        self.llmPreflightCheck = llmPreflightCheck
        self.modelReadinessCheck = modelReadinessCheck
        self.markMetadataScrubUsed = markMetadataScrubUsed
        self.updateState = updateState
        self.validateDocxStructure = validateDocxStructure
        self.finalizeProcessing = finalizeProcessing
        self.assignFailureMessageIfNeeded = assignFailureMessageIfNeeded
        self.loadFailureReport = loadFailureReport
        self.mintAttemptToken = mintAttemptToken
        self.isAttemptCurrent = isAttemptCurrent
        self.registerProcessingTask = registerProcessingTask
        self.isProcessingCancelled = isProcessingCancelled
    }

    /// Every other member of this file reads the runner through here, mirroring
    /// `DocumentRedactionViewModel.pythonRunner`.
    private var pythonRunner: (any RedactionRunning)? {
        runnerProvider()
    }

    /// Every other member of this file reads settings through here, mirroring
    /// `DocumentRedactionViewModel.settings`.
    private var settings: RedactionSettings {
        settingsProvider()
    }

    // MARK: - Metadata report (in-place)

    func generateMetadataReport(
        for item: DocumentItem,
        runner: any RedactionRunning,
        destination: URL?
    ) async {
        let originalStatus = item.status
        _ = item.acquireSecurityScope()
        await MainActor.run {
            item.status = .processing
            item.metadataReportErrorMessage = nil
            item.metadataReportNeedsPermissionRetry = false
            updateState()
        }

        let formatter = DateFormatter()
        formatter.dateFormat = "M-d-yy hmma"
        let timestamp = formatter.string(from: Date())
        let label = "(metadata-report \(timestamp))"

        let inputURL = URL(fileURLWithPath: item.path)
        let reportFileName = inputURL.deletingPathExtension().lastPathComponent + " " + label + "_metadata_report.json"
        guard let reportDirectory = outputArtifactManager.resolveTemporaryReportDirectory() else {
            let message = "Failed to prepare temporary storage for report. Please check disk space."
            await MainActor.run {
                item.status = originalStatus
                item.errorMessage = message
                outputArtifactManager.setMetadataReportError(message, needsPermissionRetry: false, item: item)
                updateState()
            }
            item.releaseSecurityScope()
            return
        }
        let reportURL = reportDirectory.appendingPathComponent(reportFileName)

        do {
            let result = try await runner.metadataReportOnlyAsync(
                inputPath: item.path,
                reportPath: reportURL.path
            )

            var htmlURL: URL? = nil
            if let htmlPath = result.htmlPath, !htmlPath.isEmpty {
                htmlURL = URL(fileURLWithPath: htmlPath)
            } else {
                htmlURL = await outputArtifactManager.generateScrubHTMLIfMissing(at: reportURL)
            }
            if htmlURL == nil {
                let fallbackHTML = reportURL.deletingPathExtension().appendingPathExtension("html")
                if FileManager.default.fileExists(atPath: fallbackHTML.path) {
                    htmlURL = fallbackHTML
                }
            }

            await MainActor.run {
                item.status = originalStatus
                if let destination {
                    item.lastDestinationURL = destination
                }
                if result.success {
                    DebugLogger.shared.log(
                        "✅ Metadata report generated in-place: \(reportURL.path)",
                        component: "DocumentRedactionViewModel"
                    )
                    item.metadataReport = result.report
                    item.metadataReportOutputURL = reportURL
                    item.errorMessage = nil
                    item.metadataReportErrorMessage = nil
                    item.metadataReportNeedsPermissionRetry = false
                    if let htmlURL {
                        item.metadataReportHTMLOutputURL = htmlURL
                    } else {
                        let message = "Metadata report HTML was not generated. Please retry."
                        item.errorMessage = message
                        outputArtifactManager.setMetadataReportError(message, needsPermissionRetry: false, item: item)
                        DebugLogger.shared.log(
                            "❌ Metadata report HTML missing for: \(reportURL.path)",
                            component: "DocumentRedactionViewModel"
                        )
                    }
                } else {
                    let rawError = result.error ?? "Metadata report failed."
                    let payload = outputArtifactManager.metadataReportErrorPayload(for: item, error: rawError)
                    item.errorMessage = payload.message
                    DebugLogger.shared.log(
                        "❌ Metadata report failed: \(rawError)",
                        component: "DocumentRedactionViewModel"
                    )
                    outputArtifactManager.setMetadataReportError(
                        payload.message,
                        needsPermissionRetry: payload.needsPermissionRetry,
                        item: item
                    )
                }
                updateState()
            }
        } catch {
            let payload = outputArtifactManager.metadataReportErrorPayload(for: item, error: error.localizedDescription)
            await MainActor.run {
                item.status = originalStatus
                item.errorMessage = payload.message
                outputArtifactManager.setMetadataReportError(
                    payload.message,
                    needsPermissionRetry: payload.needsPermissionRetry,
                    item: item
                )
                updateState()
            }
            DebugLogger.shared.log(
                "❌ Metadata report exception: \(error.localizedDescription)",
                component: "DocumentRedactionViewModel"
            )
        }
        item.releaseSecurityScope()
    }

    // MARK: - Metadata scrub

    /// Process a single document for metadata-only scrubbing
    func scrubDocumentMetadataOnly(_ item: DocumentItem, destination: URL) async {
        defer {
            item.releaseSecurityScope()
        }

        await MainActor.run {
            item.status = .processing
            item.lastOperation = .scrub
            item.lastDestinationURL = destination
            item.metadataReportErrorMessage = nil
            item.metadataReportNeedsPermissionRetry = false
            updateState()
        }

        if Task.isCancelled {
            await MainActor.run {
                item.status = .cancelled
                updateState()
            }
            return
        }

        DebugLogger.shared.log("Metadata scrub for: \(item.path)", component: "DocumentRedactionViewModel")

        let inputPath = item.path
        let inputURL = URL(fileURLWithPath: inputPath)

        let formatter = DateFormatter()
        formatter.dateFormat = "M-d-yy hmma"
        let timestamp = formatter.string(from: Date())
        let label = "(metadata-scrubbed \(timestamp))"

        let outputFileName = inputURL.deletingPathExtension().lastPathComponent + " " + label + ".docx"
        let outputPath = destination.appendingPathComponent(outputFileName).path

        guard let runner = pythonRunner else {
            DebugLogger.shared.log("❌ Python runtime unavailable", component: "DocumentRedactionViewModel")
            await MainActor.run {
                item.status = .failed
                item.errorMessage = "Processing unavailable: Python runtime not initialized."
                updateState()
            }
            return
        }

        // Load metadata settings and set environment variable
        let metadataSettings = MetadataCleaningSettings.load(defaults: defaults)
        applyMetadataSettingsEnvironment(metadataSettings, context: "metadata scrub")

        // Also set flag to skip rules and LLM
        setenv("MARCUT_METADATA_ONLY", "1", 1)
        defer {
            unsetenv("MARCUT_METADATA_ONLY")
        }

        // Process using Python
        do {
            let result = try await runner.scrubMetadataOnlyAsync(
                inputPath: inputPath,
                outputPath: outputPath
            )

            if Task.isCancelled {
                await MainActor.run {
                    item.status = .cancelled
                    updateState()
                }
                return
            }

            if result.success {
                let outputURL = URL(fileURLWithPath: outputPath)
                let outputValid = await validateDocxStructure(outputURL)
                var scrubReportURL: URL? = nil
                var scrubHTMLURL: URL? = nil

                if outputValid {
                    // Log and store the metadata cleaning report
                    if let report = result.report {
                        let summary = report["summary"] as? [String: Any]
                        let cleaned = summary?["total_cleaned"] as? Int ?? 0
                        let preserved = summary?["total_preserved"] as? Int ?? 0
                        let embedded = (report["embedded_docs_found"] as? [String])?.count ?? 0

                        DebugLogger.shared.log(
                            "✅ Metadata scrub complete: \(outputPath)",
                            component: "DocumentRedactionViewModel"
                        )
                        DebugLogger.shared.log(
                            "📊 Report: \(cleaned) cleaned, \(preserved) preserved, \(embedded) embedded docs",
                            component: "DocumentRedactionViewModel"
                        )

                        // Save report JSON file matching redaction report naming convention
                        let reportFileName = inputURL.deletingPathExtension().lastPathComponent + " \(label)_scrub_report.json"
                        let reportOutputPath = destination.appendingPathComponent(reportFileName)

                        do {
                            let reportData = try JSONSerialization.data(
                                withJSONObject: report,
                                options: [.prettyPrinted, .sortedKeys]
                            )
                            try reportData.write(to: reportOutputPath)
                            DocumentRedactionViewModel.makeSensitiveReportFilePrivate(reportOutputPath)
                            scrubReportURL = reportOutputPath
                            item.metadataReportOutputURL = reportOutputPath

                            // Check for HTML report (generated by Python alongside JSON)
                            let htmlReportURL = reportOutputPath.deletingPathExtension().appendingPathExtension("html")
                            if FileManager.default.fileExists(atPath: htmlReportURL.path) {
                                DocumentRedactionViewModel.makeSensitiveReportFilePrivate(htmlReportURL)
                                scrubHTMLURL = htmlReportURL
                                item.metadataReportHTMLOutputURL = htmlReportURL
                                DebugLogger.shared.log(
                                    "📄 HTML Report found: \(htmlReportURL.path)",
                                    component: "DocumentRedactionViewModel"
                                )
                            } else if let generatedHTML = await outputArtifactManager
                                .generateScrubHTMLIfMissing(at: reportOutputPath)
                            {
                                DocumentRedactionViewModel.makeSensitiveReportFilePrivate(generatedHTML)
                                scrubHTMLURL = generatedHTML
                                item.metadataReportHTMLOutputURL = generatedHTML
                                DebugLogger.shared.log(
                                    "📄 Generated HTML report: \(generatedHTML.path)",
                                    component: "DocumentRedactionViewModel"
                                )
                            }

                            DebugLogger.shared.log(
                                "📄 Report saved: \(reportOutputPath.path)",
                                component: "DocumentRedactionViewModel"
                            )
                        } catch {
                            DebugLogger.shared.log(
                                "⚠️ Failed to save report: \(error)",
                                component: "DocumentRedactionViewModel"
                            )
                        }

                        // Log embedded docs warning if any
                        if let embeddedDocs = report["embedded_docs_found"] as? [String], !embeddedDocs.isEmpty {
                            DebugLogger.shared.log(
                                "⚠️ Embedded documents found (need recursive cleaning): \(embeddedDocs)",
                                component: "DocumentRedactionViewModel"
                            )
                        }
                    } else {
                        DebugLogger.shared.log(
                            "✅ Metadata scrub complete: \(outputPath)",
                            component: "DocumentRedactionViewModel"
                        )
                    }
                }

                await MainActor.run {
                    if outputValid {
                        item.status = .completed
                        markMetadataScrubUsed()

                        // Set output URLs for document and report
                        item.redactedOutputURL = outputURL
                        item.scrubOutputURL = outputURL
                        item.metadataReport = result.report
                        if let scrubReportURL {
                            item.scrubReportOutputURL = scrubReportURL
                            item.metadataReportOutputURL = scrubReportURL
                        }
                        if let scrubHTMLURL {
                            item.scrubReportHTMLOutputURL = scrubHTMLURL
                            item.metadataReportHTMLOutputURL = scrubHTMLURL
                        }
                    } else {
                        item.status = .failed
                        item.errorMessage = "Scrubbed file appears to be a corrupt DOCX package"
                        DebugLogger.shared.log(
                            "❌ Metadata scrub output failed validation: \(outputPath)",
                            component: "DocumentRedactionViewModel"
                        )
                    }
                    updateState()
                }
            } else {
                await MainActor.run {
                    item.status = .failed
                    // The raw bridge error (e.g. `"Python error: \(error)"` from
                    // `scrubMetadataOnlyAsync`) is logged below, not shown to the user --
                    // see `FailureMessagePresenter`.
                    item.errorMessage = FailureMessagePresenter.message(forCode: nil)
                    DebugLogger.shared.log(
                        "❌ Metadata scrub failed: \(result.error ?? "Unknown")",
                        component: "DocumentRedactionViewModel"
                    )
                    updateState()
                }
            }
        } catch {
            await MainActor.run {
                item.status = .failed
                item.errorMessage = error.localizedDescription
                updateState()
            }
        }
    }

    // MARK: - Redaction

    func processDocument(_ item: DocumentItem, destination: URL) async {
        // Show immediate progress indication on main thread
        await MainActor.run {
            item.status = .processing
            item.lastOperation = .redaction
            item.lastDestinationURL = destination
            progressMonitor.batchProcessingStartTimes[item.id] = Date()
            updateState()
        }

        // Add logging at ViewModel level
        DebugLogger.shared.log(
            "ViewModel.processDocument called for: \(item.path)",
            component: "DocumentRedactionViewModel"
        )

        // Prepare file paths for PythonKit processing
        let inputPath = item.path
        let inputURL = URL(fileURLWithPath: inputPath)

        let formatter = DateFormatter()
        formatter.dateFormat = "M-d-yy hmma" // e.g., 12-20-25 1130PM
        let timestamp = formatter.string(from: Date())
        let label = "(redacted \(timestamp))"

        // Output format: Filename (redacted M-d-yy hmma).docx
        let outputFileName = inputURL.deletingPathExtension().lastPathComponent + " " + label + ".docx"
        // Report format: Filename (redacted M-d-yy hmma)_report.json
        let reportFileName = inputURL.deletingPathExtension().lastPathComponent + " " + label + "_report.json"
        let scrubReportFileName = inputURL.deletingPathExtension().lastPathComponent + " " + label + "_scrub_report.json"

        let outputPath = destination.appendingPathComponent(outputFileName).path
        let reportPath = destination.appendingPathComponent(reportFileName).path
        let scrubReportPath = destination.appendingPathComponent(scrubReportFileName).path

        // Determine processing mode
        let useEnhanced = settings.mode.usesLLM
        let modelName = settings.model
        let backend = settings.backend.lowercased()
        let runnerStatus = pythonRunner == nil ? "nil" : "ready"
        DebugLogger.shared.log(
            "Pre-flight: runner=\(runnerStatus) backend=\(backend)",
            component: "DocumentRedactionViewModel"
        )
        logAdvancedSettingsSnapshot(useEnhanced: useEnhanced, modelName: modelName, backend: backend)

        guard let runner = pythonRunner else {
            DebugLogger.shared.log(
                "❌ Python runtime unavailable; cannot process document",
                component: "DocumentRedactionViewModel"
            )
            await MainActor.run {
                item.status = .failed
                item.errorMessage = "Processing unavailable: embedded Python runtime not initialized. Please restart the app."
                updateState()
            }
            PermissionManager.shared.sendSystemNotification(
                title: "Processing Failed",
                body: "Fatal Error: Embedded AI runtime could not be initialized."
            )
            return
        }

        if settings.mode.usesLLM {
            guard backend == "ollama" else {
                DebugLogger.shared.log(
                    "❌ Unsupported backend for App Store-safe build: \(backend)",
                    component: "DocumentRedactionViewModel"
                )
                await MainActor.run {
                    item.status = .failed
                    item.errorMessage = "Unsupported backend. Use Ollama in Settings and restart."
                    updateState()
                }
                return
            }
        }

        // Strict Pre-flight Check for Enhanced Mode
        if useEnhanced {
            let ready = await llmPreflightCheck(modelName)
            if !ready {
                DebugLogger.shared.log(
                    "❌ Pre-flight failed: Ollama service or model \(modelName) unavailable",
                    component: "DocumentRedactionViewModel"
                )
                await MainActor.run {
                    item.status = .failed
                    item.errorMessage = "AI service is not ready (missing model or offline). Please restart the app or redownload the model. Check App Log in Settings."
                    updateState()
                }
                return
            }
        }

        DebugLogger.shared.log(
            "🚀 Using in-process PythonKit pipeline (\(useEnhanced ? "LLM" : "Rules") mode) -> output=\(outputPath), report=\(reportPath)",
            component: "DocumentRedactionViewModel"
        )
        await processDocumentWithPythonKit(
            item,
            outputPath: outputPath,
            reportPath: reportPath,
            scrubReportPath: scrubReportPath,
            useEnhanced: useEnhanced,
            modelName: modelName,
            runner: runner
        )
    }

    private func logAdvancedSettingsSnapshot(useEnhanced: Bool, modelName: String, backend: String) {
        let advancedEnabled = defaults.bool(forKey: DefaultsKey.advancedModeEnabled.key)
        let advancedModeRaw = defaults.string(forKey: DefaultsKey.advancedAIMode.key) ?? "unknown"
        let advancedConfidence = defaults.integer(forKey: DefaultsKey.advancedLLMConfidence.key)
        let timeoutSeconds = settings.processingTimeoutSeconds
        let timeoutLabel = timeoutSeconds <= 0 || timeoutSeconds == Int.max ? "no_limit" : "\(timeoutSeconds)s"
        DebugLogger.shared.log(
            "Advanced settings: advanced_mode=\(advancedEnabled) advanced_ai_mode=\(advancedModeRaw) advanced_confidence=\(advancedConfidence)% effective_mode=\(settings.mode.rawValue) llm_confidence=\(settings.llmConfidenceThreshold)% temp=\(String(format: "%.2f", settings.temperature)) chunk_tokens=\(settings.chunkTokens) overlap=\(settings.overlap) timeout=\(timeoutLabel) seed=\(settings.seed) model=\(modelName) backend=\(backend) enhanced=\(useEnhanced)",
            component: "DocumentRedactionViewModel"
        )
    }

    func applyAdvancedSettingsEnvironment() {
        let advancedEnabled = defaults.bool(forKey: DefaultsKey.advancedModeEnabled.key)
        let advancedModeRaw = defaults.string(forKey: DefaultsKey.advancedAIMode.key) ?? RedactionMode.rulesOverride
            .rawValue
        let advancedConfidence = defaults.integer(forKey: DefaultsKey.advancedLLMConfidence.key)
        setenv("MARCUT_ADVANCED_MODE_ENABLED", advancedEnabled ? "1" : "0", 1)
        setenv("MARCUT_ADVANCED_AI_MODE", advancedModeRaw, 1)
        setenv("MARCUT_ADVANCED_CONFIDENCE", "\(advancedConfidence)", 1)
    }

    func applyMetadataSettingsEnvironment(_ metadataSettings: MetadataCleaningSettings, context: String) {
        let metadataArgs = metadataSettings.toCLIArguments().joined(separator: " ")
        setenv("MARCUT_METADATA_ARGS", metadataArgs, 1)
        setenv("MARCUT_METADATA_PRESET", metadataSettings.detectPreset().rawValue, 1)
        if let settingsJSON = metadataSettings.toEnvironmentJSON(), !settingsJSON.isEmpty {
            setenv("MARCUT_METADATA_SETTINGS_JSON", settingsJSON, 1)
        } else {
            unsetenv("MARCUT_METADATA_SETTINGS_JSON")
        }
        DebugLogger.shared.log(
            "📋 Metadata settings (\(context)): preset=\(metadataSettings.detectPreset().rawValue) args=\(metadataArgs.isEmpty ? "(defaults)" : metadataArgs)",
            component: "DocumentRedactionViewModel"
        )
    }

    private func processDocumentWithPythonKit(
        _ item: DocumentItem,
        outputPath: String,
        reportPath: String,
        scrubReportPath: String,
        useEnhanced: Bool,
        modelName: String,
        runner: any RedactionRunning
    ) async {
        runner.clearCancellationRequest()
        // Mint a fresh attempt token for this run (see `activeAttemptTokens`) so a stale
        // completion from an earlier, abandoned attempt on this same item can't clobber it.
        let attemptToken = mintAttemptToken(item.id)
        DebugLogger.shared.log(
            "🔄 processDocumentWithPythonKit started for item.id=\(item.id) (\(item.url.lastPathComponent))",
            component: "DocumentRedactionViewModel"
        )
        if settings.debug {
            setenv("MARCUT_LOG_PATH", DebugLogger.shared.logPath, 1)
        } else {
            unsetenv("MARCUT_LOG_PATH")
        }
        applyAdvancedSettingsEnvironment()
        item.metadataReportErrorMessage = nil
        item.metadataReportNeedsPermissionRetry = false
        item.beginStage(.preflight)
        let debug = settings.debug
        let cancellationChecker: () -> Bool = { [weak self] in
            guard let self else {
                DebugLogger.shared.log(
                    "⚠️ cancellationChecker: self is nil, returning true",
                    component: "CancellationCheck"
                )
                return true
            }
            let isCancelled = self.isProcessingCancelled(item.id)
            if isCancelled {
                DebugLogger.shared.log(
                    "⚠️ cancellationChecker: task for item.id=\(item.id) is cancelled",
                    component: "CancellationCheck"
                )
            }
            return isCancelled
        }

        // Propagate metadata cleaning settings to Python via environment variable
        let metadataSettings = MetadataCleaningSettings.load(defaults: defaults)
        applyMetadataSettingsEnvironment(metadataSettings, context: "redaction")

        if useEnhanced {
            let modelReady = await modelReadinessCheck(modelName)
            if !modelReady {
                item.status = .failed
                item.errorMessage = "Model \(modelName) is not ready yet. Please try again in a moment."
                DebugLogger.shared.log(
                    "❌ Model readiness check failed for \(modelName)",
                    component: "DocumentRedactionViewModel"
                )
                finalizeProcessing(item)
                return
            }
        }

        setenv("MARCUT_SCRUB_REPORT_PATH", scrubReportPath, 1)
        DebugLogger.shared.log("📄 Scrub report path: \(scrubReportPath)", component: "DocumentRedactionViewModel")

        let streamAndResult: (AsyncStream<PythonRunnerProgressUpdate>, Task<PythonRunOutcome, Never>) = runner
            .runEnhancedOllamaWithProgress(
                inputPath: item.path,
                outputPath: outputPath,
                reportPath: reportPath,
                model: modelName,
                debug: debug,
                mode: useEnhanced ? settings.mode.rawValue : "rules",
                llmSkipConfidence: settings.llmConfidenceThresholdValue,
                llmConcurrency: settings.llmConcurrency,
                chunkTokens: settings.chunkTokens,
                overlap: settings.overlap,
                temperature: settings.temperature,
                seed: settings.seed,
                processingStepTimeout: useEnhanced && settings.processingTimeoutSeconds != Int
                    .max ? TimeInterval(settings.processingTimeoutSeconds) : nil,
                cancellationChecker: cancellationChecker
            )

        let progressTask = Task.detached { [weak self] in
            guard let self else {
                DebugLogger.shared.log("⚠️ Progress task: self is nil", component: "ProgressMonitor")
                return
            }
            DebugLogger.shared.log(
                "🔄 Progress task started for item.id=\(item.id) (\(item.url.lastPathComponent))",
                component: "ProgressMonitor"
            )
            var updateCount = 0
            for await update in streamAndResult.0 {
                updateCount += 1
                if Task.isCancelled {
                    DebugLogger.shared.log(
                        "⚠️ Progress task cancelled after \(updateCount) updates for \(item.url.lastPathComponent)",
                        component: "ProgressMonitor"
                    )
                    break
                }
                let updateIndex = updateCount
                let itemId = item.id
                let itemName = item.url.lastPathComponent
                let updateSnapshot = update
                let enhancedMode = useEnhanced
                await MainActor.run { [weak self] in
                    guard let self else { return }
                    guard let currentItem = self.itemsProvider().first(where: { $0.id == itemId }) else {
                        DebugLogger.shared.log(
                            "⚠️ Progress update #\(updateIndex) dropped: item.id=\(itemId) not found in items",
                            component: "ProgressMonitor"
                        )
                        return
                    }

                    // Always update heartbeat timestamp to prevent false stall detection
                    // This is critical during status transitions (processing → completed)
                    currentItem.lastHeartbeat = Date()

                    // Allow progress updates during processing OR completed (to handle race at completion)
                    // Block only for failed/cancelled states where updates are meaningless
                    guard currentItem.status == .processing || currentItem.status == .completed else {
                        DebugLogger.shared.log(
                            "⚠️ Progress update #\(updateIndex) dropped: item status=\(currentItem.status) (expected .processing or .completed) for \(itemName)",
                            component: "ProgressMonitor"
                        )
                        return
                    }

                    self.progressMonitor.ensureHeartbeatMonitorRunning(for: currentItem)

                    self.progressMonitor.applyPythonKitProgress(
                        updateSnapshot,
                        to: currentItem,
                        isEnhanced: enhancedMode
                    )
                }
            }
            DebugLogger.shared.log(
                "🔄 Progress task finished for \(item.url.lastPathComponent) after \(updateCount) updates",
                component: "ProgressMonitor"
            )
        }

        let completionTask = Task.detached { [weak self] in
            defer { unsetenv("MARCUT_SCRUB_REPORT_PATH") }
            guard let self else { return }
            let outcome = await self.awaitPythonOutcome(streamAndResult.1, runner: runner)
            progressTask.cancel()

            await MainActor.run {
                // A wedged embedded Python call can only be abandoned, never killed (see
                // `PythonBridgeError`), so this completion may fire long after the fact --
                // possibly after the heartbeat watchdog already failed this document and the
                // user retried it. If a newer attempt has since taken over `item.id`, this
                // result is stale: apply nothing.
                guard self.isAttemptCurrent(item.id, attemptToken) else {
                    DebugLogger.shared.log(
                        "⚠️ Ignoring stale completion for \(item.url.lastPathComponent) (superseded by a newer attempt or abandoned)",
                        component: "CompletionTask"
                    )
                    return
                }
                guard let currentItem = self.itemsProvider().first(where: { $0.id == item.id }) else {
                    DebugLogger.shared.log(
                        "⚠️ Completion task: item.id=\(item.id) not found in items",
                        component: "CompletionTask"
                    )
                    return
                }

                let previousStatus = currentItem.status
                switch outcome {
                case .success:
                    currentItem.status = .completed
                    self.outputArtifactManager.applyOutputArtifacts(
                        to: currentItem,
                        outputPath: outputPath,
                        reportPath: reportPath,
                        scrubReportPath: scrubReportPath
                    )
                    currentItem.errorMessage = nil
                    DebugLogger.shared.log(
                        "✅ PythonKit processing completed for \(currentItem.url.lastPathComponent) (prevStatus=\(previousStatus))",
                        component: "DocumentRedactionViewModel"
                    )
                case .cancelled:
                    let outputExists = FileManager.default.fileExists(atPath: outputPath)
                    let reportExists = FileManager.default.fileExists(atPath: reportPath)
                    if outputExists, reportExists {
                        currentItem.status = .completed
                        self.outputArtifactManager.applyOutputArtifacts(
                            to: currentItem,
                            outputPath: outputPath,
                            reportPath: reportPath,
                            scrubReportPath: scrubReportPath
                        )
                        currentItem.errorMessage = nil
                        DebugLogger.shared.log(
                            "⚠️ Cancellation received after outputs were written; marking completed for \(currentItem.url.lastPathComponent)",
                            component: "DocumentRedactionViewModel"
                        )
                    } else {
                        currentItem.status = .cancelled
                        DebugLogger.shared.log(
                            "⏹️ PythonKit processing cancelled for \(currentItem.url.lastPathComponent)",
                            component: "DocumentRedactionViewModel"
                        )
                    }
                case .failure:
                    currentItem.status = .failed
                    if let failure = self.loadFailureReport(reportPath) {
                        // The raw code/message/details are logged here for the App Log/Log
                        // Viewer; the alert itself only ever shows the mapped, friendly text
                        // (see `FailureMessagePresenter`) -- never the bare pipeline error_code
                        // or message as the headline.
                        currentItem.errorMessage = FailureMessagePresenter.message(forCode: failure.code)
                        DebugLogger.shared.log(
                            "❌ PythonKit processing failed for \(currentItem.url.lastPathComponent) code=\(failure.code) message=\(failure.message) details=\(failure.details)",
                            component: "DocumentRedactionViewModel"
                        )
                        // Dump Ollama logs to see why the runner crashed
                        self.pythonBridge.dumpOllamaLogs()
                    } else {
                        if currentItem.errorMessage == nil {
                            currentItem.errorMessage = FailureMessagePresenter.message(forCode: nil)
                        }
                        DebugLogger.shared.log(
                            "❌ PythonKit processing failed for \(currentItem.url.lastPathComponent) (no failure report found)",
                            component: "DocumentRedactionViewModel"
                        )
                    }
                    self.assignFailureMessageIfNeeded(currentItem)
                case .stalled:
                    currentItem.status = .failed
                    currentItem.errorMessage = DocumentRedactionViewModel.processingStalledMessage
                    DebugLogger.shared.log(
                        "❌ PythonKit processing stalled (bridge watchdog abandoned the worker) for \(currentItem.url.lastPathComponent)",
                        component: "DocumentRedactionViewModel"
                    )
                }
                self.finalizeProcessing(currentItem)
            }
        }

        registerProcessingTask(item.id, completionTask)
    }

    private func awaitPythonOutcome(
        _ resultTask: Task<PythonRunOutcome, Never>,
        runner: any RedactionRunning
    ) async -> PythonRunOutcome {
        if Task.isCancelled {
            resultTask.cancel()
            runner.cancelCurrentOperation(source: "awaitPythonOutcome_taskCancelled")
            return .cancelled
        }

        return await withTaskCancellationHandler {
            await resultTask.value
        } onCancel: {
            resultTask.cancel()
            runner.cancelCurrentOperation(source: "awaitPythonOutcome_taskCancelled")
        }
    }
}
