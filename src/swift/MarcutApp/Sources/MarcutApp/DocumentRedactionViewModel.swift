import AppKit
import Foundation
import SwiftUI

enum ProcessingState {
    static var isProcessing = false
}

/// Typed decode target for the on-disk failure report written by
/// `pipeline._write_failure_report()` and validated (pydantic, step 1 of
/// `docs/design/bridge_schema_migration.md`) against `FailureReport` in
/// `report_schema.py`. `message`/`technical_details` stay plain `String` --
/// the `AI_PROCESSING_TIMEOUT` classifier in `pipeline.py` greps them for
/// "timeout"/"deadline", so narrowing them would silently break that check.
/// The pydantic model sets `extra="allow"`; `Decodable` already ignores
/// unknown keys by default, so no `CodingKeys` strictness is added here.
struct FailureReportPayload: Decodable {
    let status: String
    let inputFile: String
    let errorCode: String
    let message: String
    let technicalDetails: String

    enum CodingKeys: String, CodingKey {
        case status
        case inputFile = "input_file"
        case errorCode = "error_code"
        case message
        case technicalDetails = "technical_details"
    }
}

@MainActor
final class DocumentRedactionViewModel: ObservableObject {
    static func finalRedactedCopyURL(
        for sourceURL: URL,
        fileExists: (String) -> Bool = { FileManager.default.fileExists(atPath: $0) }
    ) -> URL {
        let directory = sourceURL.deletingLastPathComponent()
        let baseName = sourceURL.deletingPathExtension().lastPathComponent
        let ext = sourceURL.pathExtension.isEmpty ? "docx" : sourceURL.pathExtension
        var candidate = directory
            .appendingPathComponent("\(baseName) Final Redacted")
            .appendingPathExtension(ext)
        var index = 2
        while fileExists(candidate.path) {
            candidate = directory
                .appendingPathComponent("\(baseName) Final Redacted \(index)")
                .appendingPathExtension(ext)
            index += 1
        }
        return candidate
    }

    static func makeSensitiveReportFilePrivate(_ url: URL) {
        try? FileManager.default.setAttributes(
            [.posixPermissions: NSNumber(value: Int16(0o600))],
            ofItemAtPath: url.path
        )
    }

    @Published var items: [DocumentItem] = []
    @Published var hasDocuments: Bool = false
    @Published var hasValidDocuments: Bool = false
    @Published var hasProcessingDocuments: Bool = false
    @Published var hasCompletedDocuments: Bool = false
    @Published var hasFinishedProcessing: Bool = false
    @Published var hasFailedDocuments: Bool = false
    @Published var metadataReportErrorMessage: String?
    @Published var metadataReportNeedsPermissionRetry: Bool = false
    @Published var reportErrorMessage: String?
    @Published var settings = RedactionSettings()
    @Published var frameworkAvailable: Bool = true
    @Published var shouldShowFirstRunSetup: Bool = false
    @Published var isPythonInitializing: Bool = (AppDelegate.pythonRunner == nil)
    @Published var pythonInitializationError: String?
    // XPC removed - CLI subprocess only
    // @Published var executionStrategy: OllamaExecutionStrategy = .direct

    /// Rough estimated time remaining for the current batch run, or `nil` when there isn't
    /// yet enough data (fewer than `BatchETACalculator.minimumSamples` documents completed
    /// in this run) to produce a meaningful estimate. Reset at the start of every
    /// `processAllDocuments` run — estimates never persist across runs or app launches.
    @Published var batchETA: TimeInterval? = nil

    /// A pending-job record recovered from a previous session (crash or quit mid-batch), or `nil`
    /// once there's nothing to offer. Set at launch from `PendingBatchJobStore`; the UI observes
    /// this to show the "Resume N pending document(s)?" prompt. Cleared by `resumePendingJob()`
    /// or `discardPendingJob()`.
    @Published var pendingResumeRecord: PendingBatchJobRecord? = nil

    /// Guards against re-persisting the same empty/non-empty state repeatedly from `updateState()`.
    private var lastPersistedPendingPaths: [String] = []

    /// Set by `resumePendingJob()` and left set until the *next* state-changing event, so the
    /// alert's `isPresented` binding setter — which SwiftUI invokes with `false` right after the
    /// "Resume" button action returns, as a separate call once the alert finishes dismissing —
    /// knows that dismissal is just an echo of the resume, not an explicit Discard. Without this,
    /// `discardPendingJob()` would wipe the record `resumePendingJob()` just re-persisted, leaving
    /// nothing on disk to recover if the app quits before the next state change. A plain
    /// "in-flight" flag cleared when `resumePendingJob()` returns does NOT work here: SwiftUI's
    /// setter call happens strictly after `resumePendingJob()` has already returned.
    private var didJustResumePendingJob = false

    // MARK: - Initialization & Cleanup

    private var pythonInitObservers: [NSObjectProtocol] = []
    /// `NSWorkspace` sleep/wake observer tokens (B5). Kept separate from `pythonInitObservers`
    /// since they're registered on a different notification center.
    private var systemPowerObservers: [NSObjectProtocol] = []
    /// RAII-style holder for the "keep this Mac awake" assertion held while any document is
    /// processing (B5). Injectable so tests can verify acquire/release counts without touching
    /// real IOKit state.
    private let powerAssertion: PowerAssertionGuard

    /// Ollama health probe invoked on system wake to decide whether in-flight processing should
    /// resume or fail (see `handleSystemWake()`). Injectable for tests -- the default talks to a
    /// real Ollama HTTP endpoint via `PythonBridgeService`, which isn't available/deterministic
    /// under the `swift test` CLI sandbox.
    var wakeOllamaHealthCheck: () async -> Bool = {
        await PythonBridgeService.shared.checkOllamaStatus()
        return PythonBridgeService.shared.isOllamaRunning
    }

    /// Resolves the embedded-Python runner every call reads through. A closure rather than a
    /// stored snapshot because `AppDelegate.pythonRunner` is assigned asynchronously after this
    /// view model is constructed (`MarcutApp.swift`, then the `.pythonRunnerReady` post) -- a
    /// snapshot taken at `init` would keep reading `nil` forever in the "runner not yet ready"
    /// branches. Injectable so tests can stand in a fake `RedactionRunning` (#98, #100) without
    /// touching the real `AppDelegate` global.
    var runnerProvider: () -> (any RedactionRunning)? = { AppDelegate.pythonRunner }

    /// Every other member of this file reads the runner through here rather than
    /// `AppDelegate.pythonRunner` directly, so `runnerProvider` is the single seam tests need to
    /// override.
    private var pythonRunner: (any RedactionRunning)? {
        runnerProvider()
    }

    /// Ollama pre-flight/readiness probe, factored out of `wakeOllamaHealthCheck`'s pattern.
    /// `lazy` (rather than a plain default value) because the default routes through the
    /// injected `pythonBridge` instance, which isn't available to a stored property's default
    /// expression before `init` runs. Called from the enhanced-mode pre-flight check.
    lazy var llmPreflightCheck: (String) async -> Bool = { [weak self] model in
        guard let self else { return false }
        return await self.pythonBridge.ensureOllamaReadyForPythonKit(requiredModel: model)
    }

    /// Model-readiness probe used just before dispatching to the runner. Same `lazy`-for-`self`
    /// rationale as `llmPreflightCheck`.
    lazy var modelReadinessCheck: (String) async -> Bool = { [weak self] model in
        guard let self else { return false }
        return await self.pythonBridge.waitForModelReadiness(modelName: model)
    }

    /// Heartbeat watchdog (B1) + batch-ETA collaborator
    /// (`docs/design/view_controller_decomposition.md` §2.1, slice 3). `lazy` for the same
    /// two-phase-init reason as `llmPreflightCheck`/`modelReadinessCheck` above --
    /// its closures capture `self` weakly and read/write state (`items`, `hasProcessingDocuments`,
    /// `activeAttemptTokens`, `pythonRunner`, `batchETA`) that isn't available at property-default
    /// evaluation time. `activeAttemptTokens` stays here rather than moving with the rest of the
    /// heartbeat state until #111.
    lazy var progressMonitor = ProgressMonitor(
        itemsProvider: { [weak self] in self?.items ?? [] },
        hasProcessingDocuments: { [weak self] in self?.hasProcessingDocuments ?? false },
        failItem: { [weak self] item in
            guard let self else { return }
            self.activeAttemptTokens.removeValue(forKey: item.id)
            self.pythonRunner?.cancelCurrentOperation(source: "heartbeat_watchdog_stall")
            self.finalizeProcessing(for: item)
        },
        batchETASink: { [weak self] eta in self?.batchETA = eta }
    )

    /// Environment/model diagnostics collaborator
    /// (`docs/design/view_controller_decomposition.md` §2.1, slice 4). `lazy` for the same
    /// two-phase-init reason as `progressMonitor` above -- `runnerProvider` isn't available at
    /// property-default evaluation time.
    lazy var environmentDiagnostics = EnvironmentDiagnosticsService(
        pythonBridge: pythonBridge,
        runnerProvider: { [weak self] in self?.runnerProvider() }
    )

    /// Share/export flow collaborator (`docs/design/view_controller_decomposition.md` §2.1,
    /// slice 6). `lazy` for the same two-phase-init reason as `environmentDiagnostics` above --
    /// `runnerProvider` isn't available at property-default evaluation time.
    /// `applyMetadataSettingsEnvironment` stays owned by the view model (other call sites besides
    /// this flow use it too, until #110's `ProcessRunner` extraction).
    lazy var documentShareService = DocumentShareService(
        runnerProvider: { [weak self] in self?.runnerProvider() },
        applyMetadataSettingsEnvironment: { [weak self] settings, context in
            self?.applyMetadataSettingsEnvironment(settings, context: context)
        }
    )

    /// Output-directory resolution and report open/save/export collaborator
    /// (`docs/design/view_controller_decomposition.md` §2.1, slice 7). `lazy` for the same
    /// two-phase-init reason as `documentShareService` above -- `runnerProvider` isn't available
    /// at property-default evaluation time. `metadataReportErrorMessage`/
    /// `metadataReportNeedsPermissionRetry`/`reportErrorMessage` stay `@Published` here, applied
    /// from the collaborator's `setGlobalMetadataReportError`/`setGlobalReportError` closures.
    lazy var outputArtifactManager = OutputArtifactManager(
        defaults: defaults,
        runnerProvider: { [weak self] in self?.runnerProvider() },
        itemsProvider: { [weak self] in self?.items ?? [] },
        setGlobalMetadataReportError: { [weak self] message, needsPermissionRetry in
            self?.metadataReportErrorMessage = message
            self?.metadataReportNeedsPermissionRetry = needsPermissionRetry
        },
        setGlobalReportError: { [weak self] message in
            self?.reportErrorMessage = message
        }
    )

    /// Single-document execution collaborator, the direct PythonKit call boundary
    /// (`docs/design/view_controller_decomposition.md` §2.1, slice 8). `lazy` for the same
    /// two-phase-init reason as `outputArtifactManager` above. Holds `outputArtifactManager`/
    /// `progressMonitor` directly -- both are themselves already-extracted collaborators with no
    /// reach back into this one -- and reaches back into the view model via closures only for
    /// what this slice's scope note keeps here: `processingTasks`/`activeAttemptTokens` (until
    /// #111), and `updateState`/`validateDocxStructure`/`finalizeProcessing`/
    /// `assignFailureMessageIfNeeded`/`loadFailureReport`/`markMetadataScrubUsed` (this design
    /// doc's own §2.1 "stays on the view model directly" list; the first four of those six are
    /// also called directly by name from `@testable import MarcutApp` tests).
    lazy var processRunner = ProcessRunner(
        defaults: defaults,
        pythonBridge: pythonBridge,
        outputArtifactManager: outputArtifactManager,
        progressMonitor: progressMonitor,
        runnerProvider: { [weak self] in self?.runnerProvider() },
        settingsProvider: { [weak self] in self?.settings ?? RedactionSettings() },
        itemsProvider: { [weak self] in self?.items ?? [] },
        llmPreflightCheck: { [weak self] model in await self?.llmPreflightCheck(model) ?? false },
        modelReadinessCheck: { [weak self] model in await self?.modelReadinessCheck(model) ?? false },
        markMetadataScrubUsed: { [weak self] in self?.markMetadataScrubUsed() },
        updateState: { [weak self] in self?.updateState() },
        validateDocxStructure: { [weak self] url in await self?.validateDocxStructure(at: url) ?? false },
        finalizeProcessing: { [weak self] item in self?.finalizeProcessing(for: item) },
        assignFailureMessageIfNeeded: { [weak self] item in self?.assignFailureMessageIfNeeded(item) },
        loadFailureReport: { [weak self] path in self?.loadFailureReport(at: path) },
        mintAttemptToken: { [weak self] itemId in self?.mintAttemptToken(for: itemId) ?? UUID() },
        isAttemptCurrent: { [weak self] itemId, token in self?.isAttemptCurrent(itemId, token) ?? false },
        registerProcessingTask: { [weak self] itemId, task in self?.registerProcessingTask(itemId, task) },
        isProcessingCancelled: { [weak self] itemId in self?.isProcessingCancelled(itemId) ?? false }
    )

    init(
        powerAssertion: PowerAssertionGuard? = nil,
        pythonBridge: PythonBridgeService? = nil,
        defaults: UserDefaults = .standard
    ) {
        // `.shared` is main-actor isolated, so it can't be a default *parameter* value (that
        // default expression is evaluated in a nonisolated context per Swift's isolation rules);
        // resolving it here in the (main-actor) initializer body avoids that warning.
        self.powerAssertion = powerAssertion ?? .shared
        self.pythonBridge = pythonBridge ?? .shared
        self.defaults = defaults
        let center = NotificationCenter.default
        let ready = center.addObserver(forName: .pythonRunnerReady, object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor [weak self] in
                self?.isPythonInitializing = false
                self?.pythonInitializationError = nil
                await self?.refreshEnvironmentStatus(triggerFirstRunCheck: true)
            }
        }
        let failed = center
            .addObserver(forName: .pythonRunnerFailed, object: nil, queue: .main) { [weak self] notification in
                let failureMessage: String? = {
                    if let message = notification.userInfo?["error"] as? String {
                        return message
                    }
                    if let message = notification.object as? String {
                        return message
                    }
                    return nil
                }()
                Task { @MainActor [weak self] in
                    guard let self else { return }
                    self.isPythonInitializing = false
                    if let message = failureMessage {
                        self.pythonInitializationError = message
                    } else {
                        self.pythonInitializationError = "Failed to initialize the AI engine. Please restart Marcut."
                    }
                }
            }
        pythonInitObservers = [ready, failed]

        let workspaceCenter = NSWorkspace.shared.notificationCenter
        let wakeObserver = workspaceCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                await self?.handleSystemWake()
            }
        }
        systemPowerObservers = [wakeObserver]

        applyAdvancedModeDefaultsIfNeeded()
        if DebugPreferences.hasStoredValue(defaults) {
            settings.debug = DebugPreferences.isEnabled(defaults)
        }

        // Fast-path: Check for models asynchronously.
        // The service method handles off-main-thread I/O and MainActor state updates internally.
        Task { @MainActor [weak self] in
            guard let self else { return }
            if await self.pythonBridge.populateInstalledModelsFromDisk() {
                self.hasPrefetchedModels = true
                if !self.hasCompletedFirstRun {
                    self.markFirstRunComplete()
                }
                self.shouldShowFirstRunSetup = false
            }
        }

        self.pythonBridge.updateRuleFilter(settings.enabledRules)
        pythonRunner?.updateRuleFilter(settings.enabledRules)

        pendingResumeRecord = PendingBatchJobStore.load(defaults: defaults)
    }

    deinit {
        // Clean up all running tasks to prevent memory leaks
        for (_, task) in processingTasks {
            task.cancel()
        }
        processingTasks.removeAll()

        for token in pythonInitObservers {
            NotificationCenter.default.removeObserver(token)
        }

        let workspaceCenter = NSWorkspace.shared.notificationCenter
        for token in systemPowerObservers {
            workspaceCenter.removeObserver(token)
        }

        DebugLogger.shared.log("DocumentRedactionViewModel deallocated", component: "ViewModel")
    }

    private let pythonBridge: PythonBridgeService
    /// Injected `UserDefaults` suite every UserDefaults-backed read/write in this file routes
    /// through, so tests can seed and observe preference state without touching `.standard`
    /// (`docs/design/view_controller_decomposition.md` §3.2 item 5). Defaults to `.standard` in
    /// production; every call site keeps its plain-argument form unchanged.
    let defaults: UserDefaults
    private var processingTasks: [UUID: Task<Void, Never>] = [:]

    /// Identifies the *current* processing attempt for a document, keyed by item id. A fresh
    /// token is minted each time `processDocumentWithPythonKit` starts a run. The completion
    /// handler for that run captures the token and refuses to mutate `item.status` if it no
    /// longer matches this dictionary's entry -- i.e. a newer attempt (a retry) has since
    /// superseded it, or the attempt was explicitly abandoned (see `stopProcessing`).
    ///
    /// This exists because of B1's bridge-level watchdog: a truly wedged embedded Python call
    /// cannot be killed, only abandoned (see `PythonBridgeError`), so its completion handler may
    /// still run -- possibly much later, after the heartbeat watchdog below has already failed
    /// the document and the user has retried it. Without this guard that late, stale completion
    /// would silently overwrite the newer attempt's live status.
    private var activeAttemptTokens: [UUID: UUID] = [:]

    /// Mints a fresh attempt token for `itemId`, stores it in `activeAttemptTokens`, and returns
    /// it. `processingTasks`/`activeAttemptTokens` stay owned by the view model until #111's
    /// `BatchCoordinator` extraction, so `ProcessRunner.processDocumentWithPythonKit` reaches
    /// back through this rather than holding the dictionary itself.
    private func mintAttemptToken(for itemId: UUID) -> UUID {
        let token = UUID()
        activeAttemptTokens[itemId] = token
        return token
    }

    /// Whether `token` is still the current attempt for `itemId` -- `false` means a newer attempt
    /// (a retry) or an explicit abandon (`stopProcessing()`) has since superseded it. Used by
    /// `ProcessRunner`'s completion handler.
    private func isAttemptCurrent(_ itemId: UUID, _ token: UUID) -> Bool {
        activeAttemptTokens[itemId] == token
    }

    /// Cancels any existing processing task for `itemId` and stores `task` as the new one. Used
    /// by `ProcessRunner.processDocumentWithPythonKit`.
    private func registerProcessingTask(_ itemId: UUID, _ task: Task<Void, Never>) {
        processingTasks[itemId]?.cancel()
        processingTasks[itemId] = task
    }

    /// Whether the processing task for `itemId` has been cancelled. Used by `ProcessRunner`'s
    /// `cancellationChecker` closure.
    private func isProcessingCancelled(_ itemId: UUID) -> Bool {
        processingTasks[itemId]?.isCancelled ?? false
    }

    /// Shown when the heartbeat watchdog or the bridge-level watchdog (`PythonRunOutcome
    /// .stalled`) gives up on a document. Covers both "this call itself timed out" and "the
    /// embedded engine was already marked unavailable by an earlier stall" -- restarting the
    /// app is the only recovery in either case (see `PythonBridgeError`).
    static let processingStalledMessage = "Processing stalled - the embedded engine stopped responding. Restart Marcut to resume processing."

    /// Note: retryCounts was removed along with retry logic - heartbeat stalls now immediately fail
    private var hasPrefetchedModels = false

    enum FirstRunEntryPoint: Equatable {
        case onboarding
        case manageModels
        case downloadSpecificModel(String)
    }

    @Published var firstRunEntryPoint: FirstRunEntryPoint = .onboarding

    var hasCompletedFirstRun: Bool {
        defaults.bool(forKey: DefaultsKey.hasCompletedFirstRun.key)
    }

    func markFirstRunComplete() {
        defaults.set(true, forKey: DefaultsKey.hasCompletedFirstRun.key)
    }

    var hasUsedMetadataScrub: Bool {
        defaults.bool(forKey: DefaultsKey.hasUsedMetadataScrub.key)
    }

    private func markMetadataScrubUsed() {
        defaults.set(true, forKey: DefaultsKey.hasUsedMetadataScrub.key)
    }

    // MARK: - Document Management

    func add(urls: [URL]) {
        for url in urls where !items.contains(where: { $0.url == url }) {
            let item = DocumentItem(url: url)
            items.append(item)
            Task { [weak self, weak item] in
                guard let self, let item else { return }
                await self.checkDocument(item)
            }
        }
        updateState()
    }

    private func checkDocument(_ item: DocumentItem) async {
        item.status = .checking

        // Check if it's a valid DOCX file
        guard item.url.pathExtension.lowercased() == "docx" else {
            item.status = .invalidDocument
            item.errorMessage = "Only DOCX files are supported"
            item.releaseSecurityScope()
            updateState()
            return
        }

        // Use proper security scope management that persists through processing
        guard item.ensureFileAccess() else {
            item.status = .invalidDocument
            item.errorMessage = "File is not readable or does not exist"
            item.releaseSecurityScope()
            updateState()
            return
        }

        // Additional validation: Try to get file attributes to ensure we can access it
        var fileSize: Int64?
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: item.url.path)
            if let size = attributes[.size] as? Int64 {
                fileSize = size
                if size < 1024 {
                    DebugLogger.shared.log(
                        "Warning: \(item.url.lastPathComponent) is unusually small (\(size) bytes) — processing will continue",
                        component: "DocumentRedactionViewModel"
                    )
                }
            }
        } catch {
            DebugLogger.shared.log(
                "Warning: Could not read file attributes for \(item.url.lastPathComponent): \(error)",
                component: "DocumentRedactionViewModel"
            )
        }

        if let size = fileSize {
            item.documentComplexity = DocumentComplexity.fallback(forFileSize: size)
            DebugLogger.shared.log(
                "Document \(item.url.lastPathComponent): size=\(size) bytes, complexity=\(item.documentComplexity)",
                component: "DocumentRedactionViewModel"
            )
        }

        let isDocxValid = await validateDocxStructure(at: item.url)
        guard isDocxValid else {
            item.status = .invalidDocument
            item.errorMessage = "File appears to be a corrupt DOCX package"
            DebugLogger.shared.log(
                "Validation failed for \(item.url.lastPathComponent): invalid DOCX structure",
                component: "DocumentRedactionViewModel"
            )
            item.releaseSecurityScope()
            updateState()
            return
        }

        // Word count is a much better proxy for batch-ETA weighting than raw
        // file byte size (see ProgressMonitor.documentSizeSignal); best-effort only -- a nil
        // result just means ProgressMonitor.recordBatchETASample falls back to file size.
        if let words = await extractWordCount(at: item.url) {
            item.wordCount = words
            DebugLogger.shared.log(
                "Document \(item.url.lastPathComponent): \(words) words extracted for size-weighted batch ETA",
                component: "DocumentRedactionViewModel"
            )
        }

        item.status = .validDocument
        updateState()
    }

    // MARK: - Batch Processing

    func processAllDocuments(to destination: URL? = nil, includeRetryItems: Bool = false) async {
        // Clear any lingering cancellation flags from previous operations
        pythonRunner?.clearCancellationRequest()

        // Fresh ETA estimation for every run — never persisted across runs or app launches.
        progressMonitor.batchProcessingStartTimes.removeAll()
        progressMonitor.batchETASamples.removeAll()
        batchETA = nil

        let shouldLog = DebugPreferences.isEnabled()
        let logPath = DebugLogger.shared.logPath
        let timestamp = ISO8601DateFormatter().string(from: Date())
        DebugLogger.shared.log("=== processAllDocuments CALLED ===", component: "DocumentRedactionViewModel")

        if shouldLog {
            // Log all document statuses in a batch to avoid opening the file 1000s of times
            var batchLog = ""
            batchLog.reserveCapacity(items.count * 100)
            batchLog += "[\(timestamp)] Total documents: \(items.count)\n"
            for (index, item) in items.enumerated() {
                batchLog += "[\(timestamp)] Doc \(index): \(item.id.uuidString) - Status: \(item.status)\n"
            }
            let validItems = items.filter { needsRedaction($0, includeRetryItems: includeRetryItems) }
            batchLog += "[\(timestamp)] Valid items for processing: \(validItems.count)\n"

            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write(batchLog.data(using: .utf8) ?? Data())
                fileHandle.closeFile()
            }
        }

        var processedIDs = Set<UUID>()

        while let item = items
            .first(where: { needsRedaction($0, includeRetryItems: includeRetryItems) && !processedIDs.contains($0.id)
            })
        {
            guard items.contains(where: { $0.id == item.id }) else {
                DebugLogger.shared.log(
                    "Skipping removed document: \(item.url.lastPathComponent)",
                    component: "DocumentRedactionViewModel"
                )
                continue
            }
            processedIDs.insert(item.id)
            // CRITICAL: Clear any lingering cancellation state before starting new document
            // This prevents race conditions where the previous document's cleanup affects the next
            pythonRunner?.clearCancellationRequest()
            DebugLogger.shared.log(
                "🔄 Cleared cancellation state before processing: \(item.url.lastPathComponent)",
                component: "DocumentRedactionViewModel"
            )

            if Task.isCancelled {
                DebugLogger.shared.log(
                    "processAllDocuments cancelled before processing next item",
                    component: "DocumentRedactionViewModel"
                )
                updateState()
                return
            }

            if shouldLog {
                let itemStartMessage = "[\(timestamp)] Starting processing for: \(item.url.lastPathComponent)\n"
                if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                    fileHandle.seekToEndOfFile()
                    fileHandle.write(itemStartMessage.data(using: .utf8) ?? Data())
                    fileHandle.closeFile()
                }
            }

            guard let resolvedDestination = await resolveOutputDirectory(
                for: item,
                baseDestination: destination,
                isMetadataOperation: false
            ) else {
                let message = "\(item.url.lastPathComponent): \(outputLocationErrorMessage())"
                await MainActor.run {
                    item.status = .failed
                    item.errorMessage = message
                    setReportError(message)
                    updateState()
                }
                continue
            }

            await processDocument(item, destination: resolvedDestination)
            if let task = processingTasks[item.id] {
                await task.value
            }

            // Clear cancellation again after document completion to ensure clean state
            pythonRunner?.clearCancellationRequest()
            DebugLogger.shared.log(
                "🔄 Cleared cancellation state after completing: \(item.url.lastPathComponent)",
                component: "DocumentRedactionViewModel"
            )

            if Task.isCancelled {
                DebugLogger.shared.log(
                    "processAllDocuments cancelled during processing",
                    component: "DocumentRedactionViewModel"
                )
                updateState()
                return
            }
        }

        updateState()

        if shouldLog {
            let endMessage = "[\(timestamp)] === processAllDocuments COMPLETED ===\n"
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write(endMessage.data(using: .utf8) ?? Data())
                fileHandle.closeFile()
            }
        }

        // Send completion notification with accurate counts
        let processedItems = items.filter { processedIDs.contains($0.id) }
        let succeeded = processedItems.filter { $0.status == .completed }.count
        let failed = processedItems.filter { $0.status == .failed }.count
        let title = "Redaction Complete"
        let body = "Finished processing \(processedItems.count) document(s). Success: \(succeeded), Failed: \(failed)."
        PermissionManager.shared.sendSystemNotification(title: title, body: body)
    }

    /// Scrub metadata only - no rules or LLM redaction
    /// This is a fast operation that only applies metadata cleaning based on saved preferences
    func scrubMetadataOnly(to destination: URL? = nil, includeRetryItems: Bool = true) async {
        DebugLogger.shared.log("=== scrubMetadataOnly CALLED ===", component: "DocumentRedactionViewModel")

        pythonRunner?.clearCancellationRequest()

        if Task.isCancelled {
            DebugLogger.shared.log("Metadata scrub cancelled before start", component: "DocumentRedactionViewModel")
            return
        }

        let validItems = items.filter { item in
            if item.status.canRetry && !includeRetryItems {
                return false
            }
            let eligibleStatus = item.status == .validDocument || item.status.canRetry || item.status.isComplete
            return eligibleStatus && item.scrubOutputURL == nil
        }

        guard !validItems.isEmpty else {
            DebugLogger.shared.log("No valid items for metadata scrub", component: "DocumentRedactionViewModel")
            return
        }

        for item in validItems {
            if Task.isCancelled {
                DebugLogger.shared.log(
                    "Metadata scrub cancelled while processing queue",
                    component: "DocumentRedactionViewModel"
                )
                await MainActor.run {
                    item.status = .cancelled
                    updateState()
                }
                return
            }
            guard let resolvedDestination = await resolveOutputDirectory(
                for: item,
                baseDestination: destination,
                isMetadataOperation: true
            ) else {
                let message = "\(item.url.lastPathComponent): \(outputLocationErrorMessage())"
                await MainActor.run {
                    item.status = .failed
                    item.errorMessage = message
                    setMetadataReportError(message, needsPermissionRetry: true, item: item)
                    updateState()
                }
                continue
            }

            await scrubDocumentMetadataOnly(item, destination: resolvedDestination)
        }

        updateState()

        // Send completion notification
        let succeeded = items.filter { $0.status == .completed }.count
        PermissionManager.shared.sendSystemNotification(
            title: "Metadata Scrub Complete",
            body: "Scrubbed metadata from \(succeeded) document(s)."
        )
    }

    /// Generate metadata-only reports without modifying documents.
    /// This captures the "before" view for compliance/preview and writes to the app cache.
    func generateMetadataReportsInPlace(destination: URL? = nil) async {
        DebugLogger.shared.log("=== metadataReportOnly IN-PLACE CALLED ===", component: "DocumentRedactionViewModel")
        clearMetadataReportError()

        pythonRunner?.clearCancellationRequest()

        if Task.isCancelled {
            DebugLogger.shared.log("Metadata report cancelled before start", component: "DocumentRedactionViewModel")
            return
        }

        let validItems = items.filter { item in
            let eligibleStatus = item.status == .validDocument || item.status == .completed || item.status.canRetry
            let hasMetadataReport = item.metadataReportOutputURL != nil || item.metadataReportHTMLOutputURL != nil
            return eligibleStatus && !hasMetadataReport
        }

        guard !validItems.isEmpty else {
            DebugLogger.shared.log("No valid items for metadata report", component: "DocumentRedactionViewModel")
            return
        }

        let metadataSettings = MetadataCleaningSettings.load(defaults: defaults)
        applyMetadataSettingsEnvironment(metadataSettings, context: "report only")

        guard let runner = pythonRunner else {
            DebugLogger.shared.log(
                "❌ Python runtime unavailable for metadata report",
                component: "DocumentRedactionViewModel"
            )
            await MainActor.run {
                setMetadataReportError(
                    "Metadata reports are unavailable until the AI engine finishes starting.",
                    needsPermissionRetry: false
                )
            }
            return
        }

        for item in validItems {
            if Task.isCancelled {
                DebugLogger.shared.log(
                    "Metadata report cancelled while processing queue",
                    component: "DocumentRedactionViewModel"
                )
                await MainActor.run {
                    item.status = .cancelled
                    updateState()
                }
                return
            }
            if !item.ensureFileAccess() {
                let message = "\(item.url.lastPathComponent): Document not accessible. Re-add the file and try again."
                await MainActor.run {
                    item.errorMessage = message
                    setMetadataReportError(message, needsPermissionRetry: false, item: item)
                    updateState()
                }
                continue
            }
            await generateMetadataReport(for: item, runner: runner, destination: destination)
            await MainActor.run {
                updateState()
            }
        }

        updateState()
    }

    private func generateMetadataReport(
        for item: DocumentItem,
        runner: any RedactionRunning,
        destination: URL?
    ) async {
        await processRunner.generateMetadataReport(for: item, runner: runner, destination: destination)
    }

    // Forwards to `outputArtifactManager` (`docs/design/view_controller_decomposition.md` §2.1,
    // slice 7); `generateMetadataReportsInPlace` below and `ContentView.swift` both still call
    // through these unchanged names. `generateMetadataReport`/`scrubDocumentMetadataOnly`
    // themselves forward to `processRunner` (slice 8, #110).

    private func metadataReportErrorPayload(for item: DocumentItem,
                                            error: String) -> (message: String, needsPermissionRetry: Bool)
    {
        outputArtifactManager.metadataReportErrorPayload(for: item, error: error)
    }

    private func setMetadataReportError(_ message: String, needsPermissionRetry: Bool, item: DocumentItem? = nil) {
        outputArtifactManager.setMetadataReportError(message, needsPermissionRetry: needsPermissionRetry, item: item)
    }

    private func setReportError(_ message: String) {
        outputArtifactManager.setReportError(message)
    }

    var outputSaveLocationPreference: OutputSaveLocation {
        outputArtifactManager.outputSaveLocationPreference
    }

    private func outputLocationErrorMessage() -> String {
        outputArtifactManager.outputLocationErrorMessage()
    }

    private func setOutputAccessError(
        _ message: String,
        isMetadataOperation: Bool,
        needsPermissionRetry: Bool,
        item: DocumentItem? = nil
    ) {
        outputArtifactManager.setOutputAccessError(
            message,
            isMetadataOperation: isMetadataOperation,
            needsPermissionRetry: needsPermissionRetry,
            item: item
        )
    }

    private func resolveTemporaryReportDirectory() -> URL? {
        outputArtifactManager.resolveTemporaryReportDirectory()
    }

    private func resolveOutputDirectory(
        for item: DocumentItem,
        baseDestination: URL?,
        isMetadataOperation: Bool
    ) async -> URL? {
        await outputArtifactManager.resolveOutputDirectory(
            for: item,
            baseDestination: baseDestination,
            isMetadataOperation: isMetadataOperation
        )
    }

    func clearMetadataReportError() {
        outputArtifactManager.clearMetadataReportError()
    }

    func clearMetadataReportError(for item: DocumentItem) {
        outputArtifactManager.clearMetadataReportError(for: item)
    }

    func retryFileAccessPermissionsFromBanner() async {
        await outputArtifactManager.retryFileAccessPermissionsFromBanner()
    }

    func retryFileAccessPermissions(for item: DocumentItem) async {
        await outputArtifactManager.retryFileAccessPermissions(for: item)
    }

    func clearReportError() {
        outputArtifactManager.clearReportError()
    }

    /// Process a single document for metadata-only scrubbing
    private func scrubDocumentMetadataOnly(_ item: DocumentItem, destination: URL) async {
        await processRunner.scrubDocumentMetadataOnly(item, destination: destination)
    }

    /// Forwards to `processRunner` (`docs/design/view_controller_decomposition.md` §2.1, slice 8,
    /// #110); `retryDocument` below, `processAllDocuments`, and the golden/characterization tests
    /// all still call through this unchanged name.
    func processDocument(_ item: DocumentItem, destination: URL) async {
        await processRunner.processDocument(item, destination: destination)
    }

    /// Forwards to `processRunner` (`docs/design/view_controller_decomposition.md` §2.1, slice 8,
    /// #110); `generateMetadataReportsInPlace` above, `DocumentShareService`'s constructor
    /// closure, and the golden/characterization tests all still call through this unchanged name.
    func applyMetadataSettingsEnvironment(_ metadataSettings: MetadataCleaningSettings, context: String) {
        processRunner.applyMetadataSettingsEnvironment(metadataSettings, context: context)
    }

    func applyOutputArtifacts(
        to item: DocumentItem,
        outputPath: String,
        reportPath: String,
        scrubReportPath: String
    ) {
        outputArtifactManager.applyOutputArtifacts(
            to: item,
            outputPath: outputPath,
            reportPath: reportPath,
            scrubReportPath: scrubReportPath
        )
    }

    func stopProcessing() {
        if !processingTasks.isEmpty, let runner = pythonRunner {
            runner.cancelCurrentOperation(source: "stopProcessing_userStop")
        }
        // Cancel all running tasks
        for (id, task) in processingTasks {
            task.cancel()
            pythonBridge.cancelProcess(for: id)
            // Also cancel any ongoing model download
            pythonBridge.cancelModelDownload()

            // Update document status and release security scope
            if let item = items.first(where: { $0.id == id }) {
                item.status = .cancelled
                item.cleanupProgressAnimations()
                item.releaseSecurityScope()
            }
            // A wedged underlying call can only be abandoned, not killed (see
            // `PythonBridgeError`), so its completion may still fire after this point.
            // Dropping the attempt token here ensures that late result is ignored rather than
            // silently overwriting the `.cancelled` status set above.
            activeAttemptTokens.removeValue(forKey: id)
        }
        processingTasks.removeAll()

        progressMonitor.cancelAllHeartbeats()
        pythonRunner?.clearCancellationRequest()
        updateState()
        progressMonitor.updateBatchETA()
    }

    func retryDocument(_ item: DocumentItem, destination: URL? = nil, operation: DocumentOperation) {
        item.errorMessage = nil
        Task { [weak self, weak item] in
            guard let self, let item else { return }
            guard let resolvedDestination = await self.resolveOutputDirectory(
                for: item,
                baseDestination: destination,
                isMetadataOperation: operation == .scrub
            ) else {
                let message = "\(item.url.lastPathComponent): \(self.outputLocationErrorMessage())"
                await MainActor.run {
                    item.status = .failed
                    item.errorMessage = message
                    self.setOutputAccessError(
                        message,
                        isMetadataOperation: operation == .scrub,
                        needsPermissionRetry: true
                    )
                    self.updateState()
                }
                return
            }
            switch operation {
            case .scrub:
                await self.scrubDocumentMetadataOnly(item, destination: resolvedDestination)
                if item.status == .completed {
                    if self.outputSaveLocationPreference == .sameAsOriginal {
                        await self.scrubMetadataOnly(to: nil, includeRetryItems: false)
                    } else {
                        await self.scrubMetadataOnly(to: resolvedDestination, includeRetryItems: false)
                    }
                }
            case .redaction:
                await self.processDocument(item, destination: resolvedDestination)
                if let completionTask = self.processingTasks[item.id] {
                    await completionTask.value
                }
                if item.status == .completed {
                    if self.outputSaveLocationPreference == .sameAsOriginal {
                        await self.processAllDocuments(to: nil, includeRetryItems: false)
                    } else {
                        await self.processAllDocuments(to: resolvedDestination, includeRetryItems: false)
                    }
                }
            }
        }
        updateState()
    }

    /// Test-only injection point: when set, `retryFailedDocuments` calls this instead of
    /// dispatching the real `retryDocument` processing, so tests can assert on exactly
    /// which items were re-queued without a live Python runtime.
    var retryFailedDocumentsHandler: ((DocumentItem, URL?, DocumentOperation) -> Void)?

    /// Re-queues only the documents currently marked `.failed`, reusing whatever settings/
    /// operation/destination were active for each document's original run. Documents with any
    /// other status (including `.completed` and `.cancelled`) are left untouched.
    func retryFailedDocuments(destination: URL? = nil) {
        let failedItems = items.filter { $0.status == .failed }
        guard !failedItems.isEmpty else { return }

        for item in failedItems {
            let operation = item.lastOperation ?? .redaction
            let itemDestination = destination ?? item.lastDestinationURL
            if let handler = retryFailedDocumentsHandler {
                handler(item, itemDestination, operation)
            } else {
                retryDocument(item, destination: itemDestination, operation: operation)
            }
        }
    }

    // MARK: - State Management

    func needsRedaction(_ item: DocumentItem, includeRetryItems: Bool = true) -> Bool {
        if item.status == .validDocument {
            return true
        }
        if item.status.canRetry {
            return includeRetryItems
        }
        return false
    }

    func updateState() {
        hasDocuments = !items.isEmpty
        hasValidDocuments = items.contains { $0.status == .validDocument }

        // B5: hold (or release) the "keep this Mac awake" assertion exactly on the
        // not-processing <-> processing edge, driven off the same live-state recomputation
        // `persistPendingBatchJobIfNeeded()` below already relies on -- so every status
        // transition that can start or end processing (normal completion, heartbeat stall,
        // user-initiated stop, document removal, wake-health-check failure, ...) keeps the
        // assertion in sync without needing to be threaded through each call site individually.
        let wasProcessing = hasProcessingDocuments
        hasProcessingDocuments = items.contains { $0.status.isProcessing }
        if hasProcessingDocuments != wasProcessing {
            if hasProcessingDocuments {
                powerAssertion.begin()
            } else {
                powerAssertion.end()
            }
        }

        hasCompletedDocuments = items.contains { $0.status.isComplete }
        hasFailedDocuments = items.contains { $0.status == .failed }

        let hasPendingDocuments = items.contains { $0.status.isPendingReview }
        let hasPendingRedaction = items.contains { needsRedaction($0) }
        hasFinishedProcessing = hasCompletedDocuments && !hasProcessingDocuments && !hasPendingDocuments &&
            !hasPendingRedaction
        ProcessingState.isProcessing = hasProcessingDocuments

        persistPendingBatchJobIfNeeded()
    }

    /// Documents that are still queued (`.validDocument`) or were mid-processing
    /// (`status.isProcessing`) when the record is saved. A document that quits mid-processing
    /// resumes as `.pending`, not wherever it left off — see issue #19 "Out of scope".
    private var pendingBatchJobPaths: [String] {
        items
            .filter { $0.status == .validDocument || $0.status.isProcessing }
            .map(\.url.path)
    }

    /// Persists the current pending/in-progress document set whenever it changes, or clears the
    /// persisted record once nothing is pending. Called from every `updateState()` pass so it
    /// stays in sync with adds/removes/status transitions without needing to hook every call site.
    private func persistPendingBatchJobIfNeeded() {
        let paths = pendingBatchJobPaths
        guard paths != lastPersistedPendingPaths else { return }
        lastPersistedPendingPaths = paths

        if paths.isEmpty {
            PendingBatchJobStore.save(nil, defaults: defaults)
        } else {
            PendingBatchJobStore.save(
                PendingBatchJobRecord(documentPaths: paths, settings: settings),
                defaults: defaults
            )
        }
    }

    /// Repopulates the document list from a previously persisted pending-job record, in
    /// `.pending` (`.validDocument`) state. Does not auto-start processing — the user still
    /// presses the normal "Redact Documents" action. Restores the settings that were active for
    /// the persisted run.
    func resumePendingJob() {
        guard let record = pendingResumeRecord else { return }
        pendingResumeRecord = nil
        didJustResumePendingJob = true

        settings = record.settings
        pythonBridge.updateRuleFilter(settings.enabledRules)
        pythonRunner?.updateRuleFilter(settings.enabledRules)

        let urls = record.documentPaths.map { URL(fileURLWithPath: $0) }
        add(urls: urls)
    }

    /// Dismisses the resume prompt without repopulating the document list, clearing the
    /// persisted record so it doesn't reappear on the next launch.
    ///
    /// No-op immediately after `resumePendingJob()`: SwiftUI writes `isPresented = false` back
    /// through the alert's binding as a separate call once the "Resume" button action returns and
    /// the alert finishes dismissing, which would otherwise call this and immediately wipe the
    /// record `resumePendingJob()` just re-persisted (see `didJustResumePendingJob`). That echo
    /// call is consumed here (flag reset) so a *later*, genuine Discard still clears the record.
    func discardPendingJob() {
        if didJustResumePendingJob {
            didJustResumePendingJob = false
            return
        }
        pendingResumeRecord = nil
        PendingBatchJobStore.save(nil, defaults: defaults)
    }

    func clearAllDocuments() {
        stopProcessing()
        for item in items {
            if !item.status.isProcessing {
                item.cleanupProgressAnimations()
                item.releaseSecurityScope()
            }
        }
        items.removeAll()
        updateState()
    }

    func removeDocument(_ item: DocumentItem) {
        if let task = processingTasks[item.id] {
            task.cancel()
            pythonBridge.cancelProcess(for: item.id)
            processingTasks.removeValue(forKey: item.id)
        }
        if item.status.isProcessing {
            pythonRunner?.cancelCurrentOperation(source: "removeDocument_itemProcessing")
        }
        progressMonitor.cancelHeartbeat(for: item.id)
        // See `stopProcessing` for why this matters: a wedged call's completion can still fire
        // after the document is gone from `items`, so drop its token rather than let it resolve
        // silently against a (by then, unrelated) reused id.
        activeAttemptTokens.removeValue(forKey: item.id)

        // Release security scope when document is removed
        item.releaseSecurityScope()

        items.removeAll { $0.id == item.id }
        updateState()
    }

    // MARK: - Output Management

    //
    // Forwards to `documentShareService` (`docs/design/view_controller_decomposition.md`
    // §2.1, slice 6); the ContentView.swift call sites are unchanged.
    // `confirmAndShareReviewCopy`/`presentSharePicker` stay private to the collaborator -- no
    // other call site needs them.

    @discardableResult
    func openRedactedDocument(_ item: DocumentItem) -> Bool {
        documentShareService.openRedactedDocument(item)
    }

    @discardableResult
    func shareDocument(_ item: DocumentItem) -> Bool {
        documentShareService.shareDocument(item)
    }

    func shareFinalRedactedCopy(_ item: DocumentItem) async {
        item.errorMessage = await documentShareService.shareFinalRedactedCopy(item)
    }

    @discardableResult
    func openReport(_ item: DocumentItem) -> Bool {
        outputArtifactManager.openReport(item)
    }

    @discardableResult
    func openScrubReport(_ item: DocumentItem) -> Bool {
        outputArtifactManager.openScrubReport(item)
    }

    @discardableResult
    func openMetadataReport(_ item: DocumentItem) -> Bool {
        outputArtifactManager.openMetadataReport(item)
    }

    @discardableResult
    func saveMetadataReport(_ item: DocumentItem) -> Bool {
        outputArtifactManager.saveMetadataReport(item)
    }

    @discardableResult
    func revealInFinder(_ item: DocumentItem) -> Bool {
        outputArtifactManager.revealInFinder(item)
    }

    // MARK: - Settings Management

    func updateSettings(_ newSettings: RedactionSettings) {
        settings = newSettings
        // Sync debug setting with global logger
        DebugPreferences.setEnabled(newSettings.debug)
        DebugLogger.shared.updateDebugSetting(newSettings.debug)
        pythonBridge.updateLoggingPreference(newSettings.debug)
        pythonBridge.updateRuleFilter(newSettings.enabledRules)

        // Also update the rule filter in PythonKitRunner since that's what actually processes documents
        pythonRunner?.updateRuleFilter(newSettings.enabledRules)
    }

    func applyAdvancedModeDefaultsIfNeeded() {
        AdvancedModeDefaultsMigrator.apply(
            defaults: defaults,
            hasCompletedFirstRun: hasCompletedFirstRun,
            settings: &settings,
            seedSettingsViewOnlyKeys: false
        )
    }

    func initializeDebugSync() {
        // Call this after view model is fully initialized to sync debug settings
        DebugLogger.shared.updateDebugSetting(settings.debug)
        pythonBridge.updateLoggingPreference(settings.debug)
    }

    func requestFirstRunSetup(entryPoint: FirstRunEntryPoint = .onboarding) {
        if entryPoint == .onboarding, shouldSuppressModelSetupPrompt {
            DebugLogger.shared.log(
                "🧽 Skipping setup prompt (metadata-only usage, no models installed)",
                component: "DocumentRedactionViewModel"
            )
            shouldShowFirstRunSetup = false
            return
        }
        firstRunEntryPoint = entryPoint
        shouldShowFirstRunSetup = true
    }

    func clearLogs() {
        DebugLogger.shared.clearLog()
        pythonBridge.clearOllamaLog()
    }

    func resetFirstRunEntryPoint() {
        firstRunEntryPoint = .onboarding
    }

    func finalizeProcessing(for item: DocumentItem) {
        processingTasks.removeValue(forKey: item.id)
        progressMonitor.cancelHeartbeat(for: item.id)
        // Clean up progress animations for all terminal states
        item.cleanupProgressAnimations()
        item.releaseSecurityScope()
        progressMonitor.recordBatchETASample(for: item)
        updateState()
        progressMonitor.updateBatchETA()

        // Auto-wipe secure temp storage if idle
        if !hasProcessingDocuments {
            PythonRuntime.cleanupTempDir { msg in
                DebugLogger.shared.log(msg, component: "SecurityCleanup")
            }
        }
    }

    /// Pure, testable parse of failure-report JSON `Data`. Returns the same tuple
    /// `loadFailureReport(at:)` does, plus `usedLegacyPath` recording which of the two decode
    /// paths actually produced it -- so a test can assert the typed path ran for a well-formed
    /// report rather than only checking a result the legacy fallback would also have produced.
    /// Mirrors the pure/directory-taking shape of `DebugLogger.discoverLogFiles(in:)`
    /// (`DocumentModels.swift`).
    ///
    /// Tries `JSONDecoder` against `FailureReportPayload` first (step 2 of
    /// `docs/design/bridge_schema_migration.md`). If that fails -- e.g. a report from before
    /// the pydantic model existed, or one missing a field the current model requires -- falls
    /// back to the legacy untyped-dictionary read for one release. Does no I/O and does not
    /// log; `loadFailureReport(at:)` logs based on `usedLegacyPath`.
    static func parseFailureReport(
        _ data: Data
    ) throws -> (code: String, message: String, details: String, usedLegacyPath: Bool)? {
        if let payload = try? JSONDecoder().decode(FailureReportPayload.self, from: data) {
            return (
                code: payload.errorCode,
                message: payload.message,
                details: payload.technicalDetails,
                usedLegacyPath: false
            )
        }
        guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            return nil
        }
        let code = (json["error_code"] as? String) ?? (json["status"] as? String) ?? "unknown"
        let message = (json["message"] as? String) ?? "Unspecified failure"
        let details = (json["technical_details"] as? String) ?? ""
        return (code: code, message: message, details: details, usedLegacyPath: true)
    }

    /// Internal (not private) so the typed-decode / legacy-fallback paths are directly
    /// unit-testable via `@testable import MarcutApp`, matching the `PythonWorkerThread`
    /// precedent in `PythonKitBridge.swift`.
    ///
    /// Delegates the actual decode to `parseFailureReport(_:)` and logs the
    /// `legacy report shape encountered` line only when that helper reports
    /// `usedLegacyPath == true`, keeping the fallback's use observable rather than silent.
    func loadFailureReport(at path: String) -> (code: String, message: String, details: String)? {
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        do {
            let data = try Data(contentsOf: url)
            guard let parsed = try Self.parseFailureReport(data) else {
                return nil
            }
            if parsed.usedLegacyPath {
                DebugLogger.shared.log(
                    "legacy report shape encountered at \(path)",
                    component: "DocumentRedactionViewModel"
                )
            }
            return (code: parsed.code, message: parsed.message, details: parsed.details)
        } catch {
            DebugLogger.shared.log(
                "⚠️ Failed to parse failure report at \(path): \(error)",
                component: "DocumentRedactionViewModel"
            )
            return nil
        }
    }

    private func assignFailureMessageIfNeeded(_ item: DocumentItem) {
        guard item.errorMessage == nil else { return }
        var specificError = "Document processing failed"

        if let logContent = try? String(contentsOfFile: DebugLogger.shared.logPath) {
            if logContent.contains("PK_CRITICAL_FAILURE") {
                specificError = "Python initialization failed - try relaunching the app"
            } else if logContent.contains("PK_REDACTION_ERROR") {
                specificError = "Processing pipeline error - check document format"
            } else if logContent.contains("AI_SERVICE_UNAVAILABLE") {
                specificError = "AI service unreachable - check if Ollama is running"
            } else if logContent.contains("AI_MODEL_UNAVAILABLE") {
                specificError = "AI model missing - please download it in Settings"
            } else if logContent.contains("PK_PROCESSING_TIMEOUT") || logContent
                .contains("AI_PROCESSING_TIMEOUT") || logContent.contains("Step timeout")
            {
                specificError = "AI processing timed out - try increasing Processing Timeout or reducing Chunk Size/Overlap"
            } else if logContent.contains("OLLAMA_HOST"), logContent.contains("empty"), settings.mode.usesLLM {
                specificError = "Ollama service not configured - check settings"
            } else if logContent.contains("KeyboardInterrupt") {
                specificError = "Processing was interrupted"
            } else if logContent.contains("timeout") {
                specificError = "Processing timed out - try increasing Processing Timeout or using a smaller model"
            } else if logContent.contains("Permission denied") {
                specificError = "File permission error - check document access"
            } else if logContent.contains("No such file") {
                specificError = "Document file not found or inaccessible"
            }
        }

        item.errorMessage = "\(specificError). See \(URL(fileURLWithPath: DebugLogger.shared.logPath).lastPathComponent) for details."
    }

    // MARK: - Environment Status

    //
    // Forwards to `environmentDiagnostics` (`docs/design/view_controller_decomposition.md`
    // §2.1, slice 4); view/binding call sites in ContentView.swift/SettingsView.swift are
    // unchanged. `frameworkAvailable`, `shouldShowFirstRunSetup`, and the first-run flags stay
    // `@Published` here and are set from the collaborator's returned results, rather than the
    // collaborator reaching back into this view model directly.

    var isEnvironmentReady: Bool {
        environmentDiagnostics.isEnvironmentReady(mode: settings.mode, frameworkAvailable: frameworkAvailable)
    }

    var environmentStatus: String {
        environmentDiagnostics.environmentStatus(mode: settings.mode, frameworkAvailable: frameworkAvailable)
    }

    // MARK: - Enhanced Error Recovery Methods

    func attemptEnvironmentRecovery() async -> Bool {
        let outcome = await environmentDiagnostics.attemptEnvironmentRecovery(
            mode: settings.mode,
            currentModel: settings.model
        ) { [weak self] mode, currentModel in
            guard let self else {
                return EnvironmentDiagnosticsService.RefreshOutcome(
                    frameworkAvailable: false,
                    ready: false,
                    selectedModel: nil
                )
            }
            return await self.applyEnvironmentRefresh(mode: mode, currentModel: currentModel)
        }
        return outcome.ready
    }

    func getDetailedEnvironmentDiagnostics() -> [String: String] {
        environmentDiagnostics.detailedEnvironmentDiagnostics(
            mode: settings.mode,
            frameworkAvailable: frameworkAvailable
        )
    }

    var ollamaLogURL: URL {
        environmentDiagnostics.ollamaLogURL
    }

    var modelsDirectoryURL: URL {
        environmentDiagnostics.modelsDirectoryURL
    }

    var lastModelDownloadError: String? {
        environmentDiagnostics.lastModelDownloadError
    }

    func checkEnvironment() {
        environmentDiagnostics.checkEnvironment { [weak self] available in
            self?.frameworkAvailable = available
        }
    }

    func downloadModel(_ modelName: String, progress: @escaping (Double) -> Void) async -> Bool {
        await environmentDiagnostics.downloadModel(modelName, progress: progress) { [weak self] in
            _ = await self?.refreshEnvironmentStatus()
        }
    }

    var ollamaRunning: Bool {
        environmentDiagnostics.ollamaRunning
    }

    func cancelModelDownload() {
        environmentDiagnostics.cancelModelDownload()
    }

    var availableModels: [String] {
        environmentDiagnostics.availableModels
    }

    var installedModelCount: Int {
        environmentDiagnostics.installedModelCount
    }

    var shouldSuppressModelSetupPrompt: Bool {
        environmentDiagnostics.shouldSuppressModelSetupPrompt(
            mode: settings.mode,
            hasUsedMetadataScrub: hasUsedMetadataScrub
        )
    }

    /// Applies `environmentDiagnostics.refreshEnvironment(...)`'s result to this view model's
    /// published state (and `settings.model`, on auto-select). Shared by
    /// `refreshEnvironmentStatus(triggerFirstRunCheck:)` and `attemptEnvironmentRecovery()`, the
    /// only two call sites that need the raw refresh outcome rather than just its readiness bool.
    private func applyEnvironmentRefresh(
        mode: RedactionMode,
        currentModel: String
    ) async -> EnvironmentDiagnosticsService.RefreshOutcome {
        let outcome = await environmentDiagnostics.refreshEnvironment(mode: mode, currentModel: currentModel)
        frameworkAvailable = outcome.frameworkAvailable
        if let selectedModel = outcome.selectedModel {
            settings.model = selectedModel
        }
        return outcome
    }

    @discardableResult
    func refreshEnvironmentStatus(triggerFirstRunCheck: Bool = true) async -> Bool {
        DebugLogger.shared.log("=== REFRESHING ENVIRONMENT STATUS ===", component: "DocumentRedactionViewModel")

        // Wait for Python initialization to complete before checking framework availability
        // This prevents false "framework missing" errors during the async startup sequence
        let initStart = Date()
        while isPythonInitializing, pythonInitializationError == nil {
            if Date().timeIntervalSince(initStart) > 30 {
                DebugLogger.shared.log(
                    "⚠️ Python initialization timeout in refreshEnvironmentStatus",
                    component: "DocumentRedactionViewModel"
                )
                break
            }
            try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
        }

        let outcome = await applyEnvironmentRefresh(mode: settings.mode, currentModel: settings.model)
        let ready = outcome.ready
        let hasSupportedModels = !availableModels.isEmpty

        // Enhanced first-run logic with better error guidance
        if triggerFirstRunCheck {
            if shouldSuppressModelSetupPrompt {
                shouldShowFirstRunSetup = false
                DebugLogger.shared.log(
                    "🧽 Metadata-only usage detected with no models; skipping setup prompt",
                    component: "DocumentRedactionViewModel"
                )
                return ready
            }
            if !hasCompletedFirstRun {
                if ready, hasSupportedModels {
                    DebugLogger.shared.log(
                        "✅ Detected configured environment with \(availableModels.count) model(s); auto-completing onboarding",
                        component: "DocumentRedactionViewModel"
                    )
                    markFirstRunComplete()
                    shouldShowFirstRunSetup = false
                } else {
                    firstRunEntryPoint = .onboarding
                    shouldShowFirstRunSetup = true
                    DebugLogger.shared.log(
                        "🔧 Showing first-time setup (onboarding not completed)",
                        component: "DocumentRedactionViewModel"
                    )
                }
            } else if !ready {
                // Provide specific guidance based on what's missing
                if !frameworkAvailable {
                    DebugLogger.shared.log(
                        "⚠️ Framework missing - prompting setup",
                        component: "DocumentRedactionViewModel"
                    )
                    firstRunEntryPoint = .onboarding
                } else if !pythonBridge.isOllamaRunning {
                    DebugLogger.shared.log(
                        "⚠️ Ollama not running - prompting setup",
                        component: "DocumentRedactionViewModel"
                    )
                    firstRunEntryPoint = .manageModels
                } else {
                    DebugLogger.shared.log(
                        "⚠️ Other environment issue - prompting setup",
                        component: "DocumentRedactionViewModel"
                    )
                    firstRunEntryPoint = .onboarding
                }
                shouldShowFirstRunSetup = true
            } else {
                shouldShowFirstRunSetup = false
                DebugLogger.shared.log("✅ Environment ready, hiding setup", component: "DocumentRedactionViewModel")
            }
        }

        return ready
    }

    // MARK: - Pre-flight Validation

    // Forwards to `outputArtifactManager` (`docs/design/view_controller_decomposition.md` §2.1,
    // slice 7); `generateMetadataReport`/`scrubDocumentMetadataOnly` above (staying on the view
    // model until #110/#111) and `ContentView.swift`/`MarcutAppTests.swift` both still call
    // through these unchanged names.

    /// Preflight-validates a candidate output destination: confirms it's actually writable (a
    /// small create+delete test file, not just an existence check) and, when
    /// `estimatedBytesNeeded` is provided, that there's likely enough free space for the run.
    /// `freeSpaceProvider` is injectable so tests can simulate a full disk without filling one.
    func validateDestination(
        _ url: URL,
        estimatedBytesNeeded: Int64 = 0,
        freeSpaceProvider: (URL) -> Int64? = DiskSpaceCheck.availableBytes
    ) -> String? {
        outputArtifactManager.validateDestination(
            url,
            estimatedBytesNeeded: estimatedBytesNeeded,
            freeSpaceProvider: freeSpaceProvider
        )
    }

    private func generateScrubHTMLIfMissing(at jsonURL: URL) async -> URL? {
        await outputArtifactManager.generateScrubHTMLIfMissing(at: jsonURL)
    }
}

// MARK: - Sleep/Wake Handling (B5)

///
/// `PowerAssertionGuard` (held/released via `updateState()` above) prevents *idle* sleep while
/// processing, but not a forced lid-close or an explicit Apple-menu "Sleep" -- so processing can
/// still be interrupted by a real sleep/wake cycle. The wall-clock time spent asleep counts toward
/// the heartbeat watchdog's silence window (`heartbeatTimeout`) even though nothing was actually
/// stalled, which would otherwise surface the generic, misleading `processingStalledMessage` a few
/// heartbeat-poll cycles after wake. This gets ahead of that with an immediate, wake-specific
/// health check so the user gets a clearer signal and, when the engine did survive, doesn't lose
/// the run to a false positive.
extension DocumentRedactionViewModel {
    /// Shown when a document was mid-processing when the Mac slept, and the health check taken
    /// immediately on wake found the embedded engine unresponsive.
    static let wakeHealthCheckFailedMessage = "Processing didn't survive sleep - the embedded engine did not respond after waking. Restart Marcut to resume processing."

    /// Called on `NSWorkspace.didWakeNotification`. No-ops when nothing is in flight. Otherwise
    /// health-checks Ollama once: if it answers, this is treated as a healthy resume and
    /// `lastHeartbeat` is refreshed on every in-flight document so the heartbeat watchdog's next
    /// poll doesn't see a false silence gap from sleep; if it doesn't answer, those documents are
    /// failed now with a wake-specific message rather than waiting for the watchdog to eventually
    /// do it with a more confusing one.
    func handleSystemWake() async {
        guard hasProcessingDocuments else { return }

        let processingItems = items.filter { $0.status == .processing }
        guard !processingItems.isEmpty else { return }

        DebugLogger.shared.log(
            "☀️ System woke with \(processingItems.count) document(s) processing; health-checking the engine",
            component: "PowerAssertion"
        )

        let healthy = await wakeOllamaHealthCheck()

        if healthy {
            let now = Date()
            for item in processingItems {
                item.lastHeartbeat = now
            }
            DebugLogger.shared.log(
                "✅ Wake health check passed; resuming in-flight processing",
                component: "PowerAssertion"
            )
            return
        }

        DebugLogger.shared.log("❌ Wake health check failed; failing in-flight document(s)", component: "PowerAssertion")
        for item in processingItems {
            item.status = .failed
            item.errorMessage = Self.wakeHealthCheckFailedMessage
            activeAttemptTokens.removeValue(forKey: item.id)
            finalizeProcessing(for: item)
        }
        pythonRunner?.cancelCurrentOperation(source: "system_wake_health_check_failed")
    }
}

// MARK: - DOCX Validation

extension DocumentRedactionViewModel {
    /// Deep validation of DOCX structure to catch corrupt files before processing
    func validateDocxStructure(at url: URL) async -> Bool {
        await Task.detached(priority: .utility) { () -> Bool in
            // Step 1: Verify file exists and has content
            guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
                  let fileSize = attributes[.size] as? Int64,
                  fileSize > 4,
                  let handle = try? FileHandle(forReadingFrom: url)
            else {
                DebugLogger.shared.log("DOCX validation: File too small or unreadable", component: "DocValidation")
                return false
            }
            defer { try? handle.close() }

            // Step 2: Check ZIP signature (PK\x03\x04) without loading the whole file
            guard let header = try? handle.read(upToCount: 4),
                  header.count == 4
            else {
                DebugLogger.shared.log("DOCX validation: Unable to read ZIP signature", component: "DocValidation")
                return false
            }
            let zipSignature = Data([0x50, 0x4B, 0x03, 0x04])
            guard header == zipSignature else {
                DebugLogger.shared.log("DOCX validation: Not a valid ZIP archive", component: "DocValidation")
                return false
            }

            // Step 3: Try to open as ZIP archive and extract entries
            do {
                let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
                defer {
                    // Secure deletion: zero all files before removing to prevent recovery
                    if let enumerator = FileManager.default.enumerator(
                        at: tempDir,
                        includingPropertiesForKeys: [.isRegularFileKey]
                    ) {
                        while let fileURL = enumerator.nextObject() as? URL {
                            if let attrs = try? fileURL.resourceValues(forKeys: [.isRegularFileKey]),
                               attrs.isRegularFile == true,
                               let size = try? FileManager.default
                               .attributesOfItem(atPath: fileURL.path)[.size] as? Int,
                               size > 0
                            {
                                // Overwrite with zeros
                                if let handle = try? FileHandle(forWritingTo: fileURL) {
                                    let zeros = Data(repeating: 0, count: size)
                                    try? handle.write(contentsOf: zeros)
                                    try? handle.synchronize()
                                    try? handle.close()
                                }
                            }
                        }
                    }
                    try? FileManager.default.removeItem(at: tempDir)
                }

                // IMPORTANT: In sandboxed apps, Process() cannot access security-scoped URLs directly.
                // Copy the file to temp directory first so unzip can access it.
                let tempCopy = tempDir.appendingPathComponent("validate.docx")
                try FileManager.default.copyItem(at: url, to: tempCopy)

                func runProcess(_ process: Process, timeout: TimeInterval, label: String) -> Bool {
                    do {
                        try process.run()
                    } catch {
                        DebugLogger.shared.log(
                            "DOCX validation: Failed to start \(label): \(error.localizedDescription)",
                            component: "DocValidation"
                        )
                        return false
                    }
                    let deadline = Date().addingTimeInterval(timeout)
                    while process.isRunning, Date() < deadline {
                        Thread.sleep(forTimeInterval: 0.1)
                    }
                    if process.isRunning {
                        process.terminate()
                        process.waitUntilExit()
                        DebugLogger.shared.log("DOCX validation: \(label) timed out", component: "DocValidation")
                        return false
                    }
                    return process.terminationStatus == 0
                }

                // Use unzip to extract and verify integrity
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
                process.arguments = ["-t", "-q", tempCopy.path] // Test archive integrity
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice

                guard runProcess(process, timeout: 15, label: "unzip -t") else {
                    DebugLogger.shared.log(
                        "DOCX validation: ZIP archive corrupt (unzip test failed)",
                        component: "DocValidation"
                    )
                    return false
                }

                // Step 3.5: List zip entries for duplicate/relationship validation
                var zipEntries: [String] = []
                let listProcess = Process()
                listProcess.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
                listProcess.arguments = ["-Z", "-1", tempCopy.path]
                let listPipe = Pipe()
                listProcess.standardOutput = listPipe
                listProcess.standardError = FileHandle.nullDevice
                guard runProcess(listProcess, timeout: 15, label: "unzip -Z") else {
                    DebugLogger.shared.log(
                        "DOCX validation: Failed to list ZIP entries (unzip -Z)",
                        component: "DocValidation"
                    )
                    return false
                }
                let data = listPipe.fileHandleForReading.readDataToEndOfFile()
                if let output = String(data: data, encoding: .utf8) {
                    zipEntries = output.split(separator: "\n").map { String($0) }
                }
                if zipEntries.isEmpty {
                    DebugLogger.shared.log("DOCX validation: ZIP entry list is empty", component: "DocValidation")
                    return false
                }

                // Step 4: Extract and check required entries
                // NOTE: unzip treats [ and ] as glob patterns, must escape with backslash
                let extractProcess = Process()
                extractProcess.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
                extractProcess.arguments = [
                    "-o", "-q", tempCopy.path,
                    "_rels/.rels",
                    "word/document.xml",
                    "word/_rels/document.xml.rels",
                    "\\[Content_Types\\].xml", // Escape brackets for unzip glob pattern
                    "-d", tempDir.path,
                ]
                extractProcess.standardOutput = FileHandle.nullDevice
                extractProcess.standardError = FileHandle.nullDevice

                guard runProcess(extractProcess, timeout: 15, label: "unzip extract") else {
                    DebugLogger.shared.log("DOCX validation: unzip extract failed", component: "DocValidation")
                    return false
                }

                // Check required files were extracted
                let rootRelsPath = tempDir.appendingPathComponent("_rels/.rels")
                let documentXmlPath = tempDir.appendingPathComponent("word/document.xml")
                let relsPath = tempDir.appendingPathComponent("word/_rels/document.xml.rels")
                let contentTypesPath = tempDir.appendingPathComponent("[Content_Types].xml")

                guard FileManager.default.fileExists(atPath: rootRelsPath.path) else {
                    DebugLogger.shared.log("DOCX validation: Missing _rels/.rels", component: "DocValidation")
                    return false
                }

                guard FileManager.default.fileExists(atPath: documentXmlPath.path) else {
                    DebugLogger.shared.log("DOCX validation: Missing word/document.xml", component: "DocValidation")
                    return false
                }

                guard FileManager.default.fileExists(atPath: contentTypesPath.path) else {
                    DebugLogger.shared.log("DOCX validation: Missing [Content_Types].xml", component: "DocValidation")
                    return false
                }

                guard FileManager.default.fileExists(atPath: relsPath.path) else {
                    DebugLogger.shared.log(
                        "DOCX validation: Missing word/_rels/document.xml.rels",
                        component: "DocValidation"
                    )
                    return false
                }

                // Step 5: Verify document.xml is valid XML with correct namespace and relationships
                guard let xmlData = try? Data(contentsOf: documentXmlPath) else {
                    DebugLogger.shared.log("DOCX validation: Cannot read document.xml", component: "DocValidation")
                    return false
                }

                // Parse XML to verify it's well-formed
                do {
                    let xmlDoc = try XMLDocument(data: xmlData)

                    // Check for WordprocessingML namespace
                    let rootElement = xmlDoc.rootElement()
                    let namespaceURI = rootElement?.uri ?? ""

                    guard namespaceURI.contains("wordprocessingml") ||
                        rootElement?.name == "document"
                    else {
                        DebugLogger.shared.log(
                            "DOCX validation: Invalid WordprocessingML namespace: \(namespaceURI)",
                            component: "DocValidation"
                        )
                        return false
                    }

                    // Step 6: Relationship Integrity Check
                    // Corrupt files often have elements referring to missing relationships
                    if FileManager.default.fileExists(atPath: relsPath.path),
                       let relsData = try? Data(contentsOf: relsPath),
                       let relsDoc = try? XMLDocument(data: relsData)
                    {
                        // Collect valid Relationship IDs
                        var validRelIds = Set<String>()
                        if let relsRoot = relsDoc.rootElement() {
                            for child in relsRoot.children ?? [] {
                                if let element = child as? XMLElement,
                                   let id = element.attribute(forName: "Id")?.stringValue
                                {
                                    validRelIds.insert(id)
                                }
                            }
                        }

                        // Scan document.xml for relationship references (r:id)
                        // Using XPath to find elements with r:id attributes would be ideal but complex with namespaces
                        // Simple recursive scan
                        var orphanedRels: [String] = []

                        func scanForRels(_ element: XMLElement) {
                            if let attributes = element.attributes {
                                for attr in attributes {
                                    if attr.localName == "id", attr.prefix == "r" || attr.name == "r:id" {
                                        if let val = attr.stringValue, !validRelIds.contains(val) {
                                            orphanedRels.append(val)
                                        }
                                    }
                                }
                            }
                            for child in element.children ?? [] {
                                if let childElem = child as? XMLElement {
                                    scanForRels(childElem)
                                }
                            }
                        }

                        if let root = xmlDoc.rootElement() {
                            scanForRels(root)
                        }

                        if !orphanedRels.isEmpty {
                            DebugLogger.shared.log(
                                "⚠️ DOCX validation warning: Found \(orphanedRels.count) orphaned relationships (e.g., \(orphanedRels.first ?? "?")) - Proceeding despite warnings",
                                component: "DocValidation"
                            )
                            // Relaxed validation: Allow files with orphaned relationships to proceed
                            // return false
                        }
                    }

                    // Step 7: Validate relationship targets exist in ZIP
                    if !zipEntries.isEmpty {
                        let entrySet = Set(zipEntries)
                        var entryCounts: [String: Int] = [:]
                        for name in zipEntries {
                            entryCounts[name, default: 0] += 1
                        }
                        let duplicateEntries = Set(entryCounts.filter { $0.value > 1 }.map(\.key))
                        if !duplicateEntries.isEmpty {
                            DebugLogger.shared.log(
                                "DOCX validation: Duplicate ZIP entries detected (e.g., \(duplicateEntries.first ?? "?"))",
                                component: "DocValidation"
                            )
                            return false
                        }

                        func relsSourceDir(_ relsPath: String) -> String {
                            if relsPath == "_rels/.rels" {
                                return ""
                            }
                            if !relsPath.contains("/_rels/") {
                                return (relsPath as NSString).deletingLastPathComponent
                            }
                            var sourcePath = relsPath.replacingOccurrences(of: "/_rels/", with: "/")
                            if sourcePath.hasSuffix(".rels") {
                                sourcePath = String(sourcePath.dropLast(5))
                            }
                            return (sourcePath as NSString).deletingLastPathComponent
                        }

                        func normalizePath(_ path: String) -> String {
                            var parts: [String] = []
                            for raw in path.split(separator: "/") {
                                let part = String(raw)
                                if part.isEmpty || part == "." {
                                    continue
                                }
                                if part == ".." {
                                    if !parts.isEmpty {
                                        parts.removeLast()
                                    }
                                    continue
                                }
                                parts.append(part)
                            }
                            return parts.joined(separator: "/")
                        }

                        func resolveTarget(relsPath: String, target: String) -> String {
                            let trimmed = target.hasPrefix("/") ? String(target.dropFirst()) : target
                            if target.hasPrefix("/") {
                                return normalizePath(trimmed)
                            }
                            let baseDir = relsSourceDir(relsPath)
                            let combined = baseDir.isEmpty ? trimmed : "\(baseDir)/\(trimmed)"
                            return normalizePath(combined)
                        }

                        func validateTargets(relsPath: String, relsData: Data) -> Bool {
                            guard let relsDoc = try? XMLDocument(data: relsData),
                                  let relsRoot = relsDoc.rootElement()
                            else {
                                DebugLogger.shared.log(
                                    "DOCX validation: Unable to parse \(relsPath)",
                                    component: "DocValidation"
                                )
                                return false
                            }
                            for child in relsRoot.children ?? [] {
                                guard let element = child as? XMLElement else { continue }
                                let targetMode = element.attribute(forName: "TargetMode")?.stringValue ?? ""
                                if targetMode == "External" {
                                    continue
                                }
                                guard let target = element.attribute(forName: "Target")?.stringValue else { continue }
                                let resolved = resolveTarget(relsPath: relsPath, target: target)
                                if !entrySet.contains(resolved) {
                                    DebugLogger.shared.log(
                                        "DOCX validation: Missing relationship target \(resolved) from \(relsPath)",
                                        component: "DocValidation"
                                    )
                                    return false
                                }
                            }
                            return true
                        }

                        if let rootRelsData = try? Data(contentsOf: rootRelsPath) {
                            if !validateTargets(relsPath: "_rels/.rels", relsData: rootRelsData) {
                                return false
                            }
                        }
                        if let docRelsData = try? Data(contentsOf: relsPath) {
                            if !validateTargets(relsPath: "word/_rels/document.xml.rels", relsData: docRelsData) {
                                return false
                            }
                        }
                    }

                    DebugLogger.shared.log("DOCX validation: Document passes all checks", component: "DocValidation")
                    return true

                } catch {
                    DebugLogger.shared.log(
                        "DOCX validation: XML parsing failed: \(error.localizedDescription)",
                        component: "DocValidation"
                    )
                    return false
                }

            } catch {
                DebugLogger.shared.log(
                    "DOCX validation: Process error: \(error.localizedDescription)",
                    component: "DocValidation"
                )
                return false
            }
        }.value
    }

    /// Extracts a word-count signal for a DOCX by parsing `word/document.xml`'s
    /// text runs -- used as the "size" signal for batch ETA weighting
    /// (`ProgressMonitor.documentSizeSignal`) instead of raw file byte size. A DOCX's
    /// compressed byte size can vary independently of its actual text content
    /// (embedded images/styles inflate file size without adding processing
    /// work; a text-heavy, lightly-formatted document can be small on disk
    /// yet expensive to run through rules/LLM extraction), so word count is a
    /// much better proxy for the work a document actually represents.
    ///
    /// This intentionally re-extracts `word/document.xml` independently of
    /// `validateDocxStructure` (a small amount of duplicated unzip work)
    /// rather than threading a result out of that function, to keep the
    /// security-sensitive validation path's contract and tests completely
    /// unchanged. Returns nil if the document can't be parsed here; callers
    /// fall back to file byte size in that case.
    func extractWordCount(at url: URL) async -> Int? {
        await Task.detached(priority: .utility) { () -> Int? in
            let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
            guard (try? FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)) != nil
            else {
                return nil
            }
            defer { try? FileManager.default.removeItem(at: tempDir) }

            let tempCopy = tempDir.appendingPathComponent("word-count-signal.docx")
            guard (try? FileManager.default.copyItem(at: url, to: tempCopy)) != nil else {
                return nil
            }

            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
            process.arguments = ["-o", "-q", tempCopy.path, "word/document.xml", "-d", tempDir.path]
            process.standardOutput = FileHandle.nullDevice
            process.standardError = FileHandle.nullDevice
            do {
                try process.run()
            } catch {
                return nil
            }
            let deadline = Date().addingTimeInterval(10)
            while process.isRunning && Date() < deadline {
                try? await Task.sleep(nanoseconds: 50_000_000)
            }
            if process.isRunning {
                process.terminate()
                process.waitUntilExit()
                return nil
            }
            guard process.terminationStatus == 0 else { return nil }

            let documentXmlPath = tempDir.appendingPathComponent("word/document.xml")
            guard let xmlData = try? Data(contentsOf: documentXmlPath),
                  let xmlDoc = try? XMLDocument(data: xmlData),
                  let root = xmlDoc.rootElement()
            else {
                return nil
            }

            var text = ""
            func collectText(_ element: XMLElement) {
                if element.localName == "t" {
                    text += (element.stringValue ?? "")
                    text += " "
                }
                for child in element.children ?? [] {
                    if let childElement = child as? XMLElement {
                        collectText(childElement)
                    }
                }
            }
            collectText(root)

            let words = text.split { $0 == " " || $0 == "\n" || $0 == "\t" || $0 == "\r" }
            return words.isEmpty ? nil : words.count
        }.value
    }
}
