import SwiftUI
import UniformTypeIdentifiers
import AppKit
import Foundation

@MainActor
final class DocumentRedactionViewModel: ObservableObject {
    private static let supportedModelIdentifiers: Set<String> = [
        "llama3.1:8b",
        "mistral:7b",
        "llama3.2:3b"
    ]
    @Published var items: [DocumentItem] = []
    @Published var hasDocuments: Bool = false
    @Published var hasValidDocuments: Bool = false
    @Published var hasProcessingDocuments: Bool = false
    @Published var hasCompletedDocuments: Bool = false
    @Published var hasFinishedProcessing: Bool = false
    @Published var settings = RedactionSettings()
    @Published var frameworkAvailable: Bool = true
    @Published var shouldShowFirstRunSetup: Bool = false
    @Published var isPythonInitializing: Bool = (AppDelegate.pythonRunner == nil)
    @Published var pythonInitializationError: String?
    // XPC removed - CLI subprocess only
    // @Published var executionStrategy: OllamaExecutionStrategy = .direct

    // MARK: - Initialization & Cleanup
    private var pythonInitObservers: [NSObjectProtocol] = []

    init() {
        let center = NotificationCenter.default
        let ready = center.addObserver(forName: .pythonRunnerReady, object: nil, queue: .main) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor [weak self] in
                self?.isPythonInitializing = false
                self?.pythonInitializationError = nil
                await self?.refreshEnvironmentStatus(triggerFirstRunCheck: true)
            }
        }
        let failed = center.addObserver(forName: .pythonRunnerFailed, object: nil, queue: .main) { [weak self] notification in
            guard let self else { return }
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.isPythonInitializing = false
                if let message = notification.userInfo?["error"] as? String {
                    self.pythonInitializationError = message
                } else if let message = notification.object as? String {
                    self.pythonInitializationError = message
                } else {
                    self.pythonInitializationError = "Failed to initialize the AI engine. Please restart Marcut."
                }
            }
        }
        pythonInitObservers = [ready, failed]

        // Fast-path: Check for models asynchronously.
        // The service method handles off-main-thread I/O and MainActor state updates internally.
        Task { @MainActor [weak self] in
            guard let self = self else { return }
            if await self.pythonBridge.populateInstalledModelsFromDisk() {
                self.hasPrefetchedModels = true
                if !self.hasCompletedFirstRun {
                    self.markFirstRunComplete()
                }
                self.shouldShowFirstRunSetup = false
            }
        }

        pythonBridge.updateRuleFilter(settings.enabledRules)
        AppDelegate.pythonRunner?.updateRuleFilter(settings.enabledRules)
    }

    deinit {
        // Clean up all running tasks to prevent memory leaks
        for (_, task) in processingTasks {
            task.cancel()
        }
        processingTasks.removeAll()

        for (_, task) in heartbeatTasks {
            task.cancel()
        }
        heartbeatTasks.removeAll()

        for token in pythonInitObservers {
            NotificationCenter.default.removeObserver(token)
        }

        DebugLogger.shared.log("DocumentRedactionViewModel deallocated", component: "ViewModel")
    }

    // Removed init() to prevent circular dependencies during @Published property initialization

    private let pythonBridge: PythonBridgeService = .shared
    private var processingTasks: [UUID: Task<Void, Never>] = [:]
    private var heartbeatTasks: [UUID: Task<Void, Never>] = [:]
    private let heartbeatTimeout: TimeInterval = 30.0
    // Note: retryCounts was removed along with retry logic - heartbeat stalls now immediately fail
    private let firstRunCompletedKey = "MarcutApp.hasCompletedFirstRun"
    private var hasPrefetchedModels = false

    enum FirstRunEntryPoint {
        case onboarding
        case manageModels
    }

    @Published var firstRunEntryPoint: FirstRunEntryPoint = .onboarding

    var hasCompletedFirstRun: Bool {
        UserDefaults.standard.bool(forKey: firstRunCompletedKey)
    }

    func markFirstRunComplete() {
        UserDefaults.standard.set(true, forKey: firstRunCompletedKey)
    }
    
    // MARK: - Document Management
    
    func add(urls: [URL]) {
        for url in urls where !items.contains(where: { $0.url == url }) {
            let item = DocumentItem(url: url)
            items.append(item)
            Task { [weak self, weak item] in
                guard let self = self, let item = item else { return }
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
            updateState()
            return
        }

        // Use proper security scope management that persists through processing
        guard item.ensureFileAccess() else {
            item.status = .invalidDocument
            item.errorMessage = "File is not readable or does not exist"
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
            updateState()
            return
        }

        item.status = .validDocument
        updateState()
    }
    
    // MARK: - Batch Processing
    
    func processAllDocuments(to destination: URL) async {
        // Clear any lingering cancellation flags from previous operations
        AppDelegate.pythonRunner?.clearCancellationRequest()

        // Add comprehensive logging for batch processing
        let logPath = DebugLogger.shared.logPath
        let timestamp = ISO8601DateFormatter().string(from: Date())

        DebugLogger.shared.log("=== processAllDocuments CALLED ===", component: "DocumentRedactionViewModel")

        // Log all document statuses in a batch to avoid opening the file 1000s of times
        var batchLog = ""
        batchLog += "[\(timestamp)] Total documents: \(items.count)\n"
        for (index, item) in items.enumerated() {
            batchLog += "[\(timestamp)] Doc \(index): \(item.url.lastPathComponent) - Status: \(item.status)\n"
        }
        
        let validItems = items.filter { $0.status == .validDocument || $0.status.canRetry }
        batchLog += "[\(timestamp)] Valid items for processing: \(validItems.count)\n"

        if let fileHandle = FileHandle(forWritingAtPath: logPath) {
            fileHandle.seekToEndOfFile()
            fileHandle.write(batchLog.data(using: .utf8) ?? Data())
            fileHandle.closeFile()
        }

        guard !validItems.isEmpty else {
            let emptyMessage = "[\(timestamp)] No valid items - exiting processAllDocuments\n"
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write(emptyMessage.data(using: .utf8) ?? Data())
                fileHandle.closeFile()
            }
            return
        }

        for item in validItems {
            // CRITICAL: Clear any lingering cancellation state before starting new document
            // This prevents race conditions where the previous document's cleanup affects the next
            AppDelegate.pythonRunner?.clearCancellationRequest()
            DebugLogger.shared.log("🔄 Cleared cancellation state before processing: \(item.url.lastPathComponent)", component: "DocumentRedactionViewModel")

            if Task.isCancelled {
                DebugLogger.shared.log("processAllDocuments cancelled before processing next item", component: "DocumentRedactionViewModel")
                updateState()
                return
            }

            let itemStartMessage = "[\(timestamp)] Starting processing for: \(item.url.lastPathComponent)\n"
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write(itemStartMessage.data(using: .utf8) ?? Data())
                fileHandle.closeFile()
            }

            await processDocument(item, destination: destination)
            if let task = processingTasks[item.id] {
                await task.value
            }

            // Clear cancellation again after document completion to ensure clean state
            AppDelegate.pythonRunner?.clearCancellationRequest()
            DebugLogger.shared.log("🔄 Cleared cancellation state after completing: \(item.url.lastPathComponent)", component: "DocumentRedactionViewModel")

            if Task.isCancelled {
                DebugLogger.shared.log("processAllDocuments cancelled during processing", component: "DocumentRedactionViewModel")
                updateState()
                return
            }
        }

        updateState()

        let endMessage = "[\(timestamp)] === processAllDocuments COMPLETED ===\n"
        if let fileHandle = FileHandle(forWritingAtPath: logPath) {
            fileHandle.seekToEndOfFile()
            fileHandle.write(endMessage.data(using: .utf8) ?? Data())
            fileHandle.closeFile()
        }
        
        // Send completion notification with accurate counts
        let succeeded = validItems.filter { $0.status == .completed }.count
        let failed = validItems.filter { $0.status == .failed }.count
        let title = "Redaction Complete"
        let body = "Finished processing \(validItems.count) document(s). Success: \(succeeded), Failed: \(failed)."
        PermissionManager.shared.sendSystemNotification(title: title, body: body)
    }
    
    /// Scrub metadata only - no rules or LLM redaction
    /// This is a fast operation that only applies metadata cleaning based on saved preferences
    func scrubMetadataOnly(to destination: URL) async {
        DebugLogger.shared.log("=== scrubMetadataOnly CALLED ===", component: "DocumentRedactionViewModel")

        AppDelegate.pythonRunner?.clearCancellationRequest()

        if Task.isCancelled {
            DebugLogger.shared.log("Metadata scrub cancelled before start", component: "DocumentRedactionViewModel")
            return
        }
        
        let validItems = items.filter { $0.status == .validDocument || $0.status.canRetry }
        
        guard !validItems.isEmpty else {
            DebugLogger.shared.log("No valid items for metadata scrub", component: "DocumentRedactionViewModel")
            return
        }
        
        for item in validItems {
            if Task.isCancelled {
                DebugLogger.shared.log("Metadata scrub cancelled while processing queue", component: "DocumentRedactionViewModel")
                await MainActor.run {
                    item.status = .cancelled
                    updateState()
                }
                return
            }
            await scrubDocumentMetadataOnly(item, destination: destination)
        }
        
        updateState()
        
        // Send completion notification
        let succeeded = items.filter { $0.status == .completed }.count
        PermissionManager.shared.sendSystemNotification(
            title: "Metadata Scrub Complete",
            body: "Scrubbed metadata from \(succeeded) document(s)."
        )
    }
    
    /// Process a single document for metadata-only scrubbing
    private func scrubDocumentMetadataOnly(_ item: DocumentItem, destination: URL) async {
        defer {
            item.releaseSecurityScope()
        }

        await MainActor.run {
            item.status = .processing
            item.lastDestinationURL = destination
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
        
        guard let runner = AppDelegate.pythonRunner else {
            DebugLogger.shared.log("❌ Python runtime unavailable", component: "DocumentRedactionViewModel")
            await MainActor.run {
                item.status = .failed
                item.errorMessage = "Processing unavailable: Python runtime not initialized."
                updateState()
            }
            return
        }
        
        // Load metadata settings and set environment variable
        let metadataSettings = MetadataCleaningSettings.load()
        let metadataArgs = metadataSettings.toCLIArguments().joined(separator: " ")
        setenv("MARCUT_METADATA_ARGS", metadataArgs, 1)
        DebugLogger.shared.log("Metadata args: \(metadataArgs)", component: "DocumentRedactionViewModel")
        
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
                let outputValid = await validateDocxStructure(at: outputURL)

                await MainActor.run {
                    if outputValid {
                        item.status = .completed
                        
                        // Set output URLs for document and report
                        item.redactedOutputURL = outputURL
                        item.scrubOutputURL = outputURL
                        
                        // Log and store the metadata cleaning report
                        if let report = result.report {
                            let summary = report["summary"] as? [String: Any]
                            let cleaned = summary?["total_cleaned"] as? Int ?? 0
                            let preserved = summary?["total_preserved"] as? Int ?? 0
                            let embedded = (report["embedded_docs_found"] as? [String])?.count ?? 0
                            
                            DebugLogger.shared.log("✅ Metadata scrub complete: \(outputPath)", component: "DocumentRedactionViewModel")
                            DebugLogger.shared.log("📊 Report: \(cleaned) cleaned, \(preserved) preserved, \(embedded) embedded docs", component: "DocumentRedactionViewModel")
                            
                            // Store report for potential UI display
                            item.metadataReport = report
                            
                            // Save report JSON file matching redaction report naming convention
                            let reportFileName = inputURL.deletingPathExtension().lastPathComponent + " (scrub-report \(timestamp)).json"
                            let reportOutputPath = destination.appendingPathComponent(reportFileName)
                            
                            do {
                                let reportData = try JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
                                try reportData.write(to: reportOutputPath)
                                item.scrubReportOutputURL = reportOutputPath
                                DebugLogger.shared.log("📄 Report saved: \(reportOutputPath.path)", component: "DocumentRedactionViewModel")
                            } catch {
                                DebugLogger.shared.log("⚠️ Failed to save report: \(error)", component: "DocumentRedactionViewModel")
                            }
                            
                            // Log embedded docs warning if any
                            if let embeddedDocs = report["embedded_docs_found"] as? [String], !embeddedDocs.isEmpty {
                                DebugLogger.shared.log("⚠️ Embedded documents found (need recursive cleaning): \(embeddedDocs)", component: "DocumentRedactionViewModel")
                            }
                        } else {
                            DebugLogger.shared.log("✅ Metadata scrub complete: \(outputPath)", component: "DocumentRedactionViewModel")
                        }
                    } else {
                        item.status = .failed
                        item.errorMessage = "Scrubbed file appears to be a corrupt DOCX package"
                        DebugLogger.shared.log("❌ Metadata scrub output failed validation: \(outputPath)", component: "DocumentRedactionViewModel")
                    }
                    updateState()
                }
            } else {
                await MainActor.run {
                    item.status = .failed
                    item.errorMessage = result.error ?? "Unknown error"
                    DebugLogger.shared.log("❌ Metadata scrub failed: \(result.error ?? "Unknown")", component: "DocumentRedactionViewModel")
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
    
    func processDocument(_ item: DocumentItem, destination: URL) async {
        // Show immediate progress indication on main thread
        await MainActor.run {
            item.status = .processing
            item.lastDestinationURL = destination
            updateState()
        }

        // Add logging at ViewModel level
        DebugLogger.shared.log("ViewModel.processDocument called for: \(item.path)", component: "DocumentRedactionViewModel")

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
        let scrubReportFileName = inputURL.deletingPathExtension().lastPathComponent + " (scrub-report \(timestamp)).json"
        
        let outputPath = destination.appendingPathComponent(outputFileName).path
        let reportPath = destination.appendingPathComponent(reportFileName).path
        let scrubReportPath = destination.appendingPathComponent(scrubReportFileName).path

        // Determine processing mode
        let useEnhanced = settings.mode == .enhanced
        let modelName = settings.model
        let backend = settings.backend.lowercased()
        let runnerStatus = AppDelegate.pythonRunner == nil ? "nil" : "ready"
        DebugLogger.shared.log("Pre-flight: runner=\(runnerStatus) backend=\(backend)", component: "DocumentRedactionViewModel")

        guard let runner = AppDelegate.pythonRunner else {
            DebugLogger.shared.log("❌ Python runtime unavailable; cannot process document", component: "DocumentRedactionViewModel")
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

        guard backend == "ollama" else {
            DebugLogger.shared.log("❌ Unsupported backend for App Store-safe build: \(backend)", component: "DocumentRedactionViewModel")
            await MainActor.run {
                item.status = .failed
                item.errorMessage = "Unsupported backend. Use Ollama in Settings and restart."
                updateState()
            }
            return
        }

        // Strict Pre-flight Check for Enhanced Mode
        if useEnhanced {
            let ready = await pythonBridge.ensureOllamaReadyForPythonKit(requiredModel: modelName)
            if !ready {
                DebugLogger.shared.log("❌ Pre-flight failed: Ollama service or model \(modelName) unavailable", component: "DocumentRedactionViewModel")
                await MainActor.run {
                    item.status = .failed
                    item.errorMessage = "AI service is not ready (missing model or offline). Please restart the app or redownload the model. Check App Log in Settings."
                    updateState()
                }
                return
            }
        }

        DebugLogger.shared.log("🚀 Using in-process PythonKit pipeline (\(useEnhanced ? "Enhanced" : "Rules") mode) -> output=\(outputPath), report=\(reportPath)", component: "DocumentRedactionViewModel")
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

    private func processDocumentWithCLISubprocess(
        _ item: DocumentItem,
        inputPath: String,
        outputPath: String,
        reportPath: String,
        scrubReportPath: String,
        useEnhanced: Bool,
        modelName: String
    ) {
        DebugLogger.shared.log("🚀 GUI: Starting CLI subprocess processing - \(useEnhanced ? "Enhanced" : "Rules") mode", component: "DocumentRedactionViewModel")

        let bridge = PythonBridgeService.shared
        var completionContinuation: CheckedContinuation<Void, Never>?
        let completionTask = Task { @MainActor in
            await withCheckedContinuation { continuation in
                completionContinuation = continuation
            }
        }

        bridge.runRedactionWithCLI(
            inputPath: inputPath,
            outputPath: outputPath,
            reportPath: reportPath,
            scrubReportPath: scrubReportPath,
            model: modelName,
            mode: useEnhanced ? "enhanced" : "rules",
            debug: settings.debug,
            progressUpdater: { [weak self] update in
                // Check if document was cancelled/removed during processing
                if Task.isCancelled { return }

                // Dispatch UI updates to MainActor (eb43162 pattern)
                Task { @MainActor in
                    guard let self = self else { return }
                    // Find current item and update progress immediately
                    guard let currentItem = self.items.first(where: { $0.id == item.id }) else {
                        DebugLogger.shared.log("Document removed during processing, stopping updates", component: "CLI_SUBPROCESS")
                        return
                    }

                    // Don't update if document is already in terminal state
                    guard currentItem.status == .processing else {
                        DebugLogger.shared.log("Document in terminal state (\(currentItem.status)), stopping progress updates", component: "CLI_SUBPROCESS")
                        return
                    }

                    self.ensureHeartbeatMonitorRunning(for: currentItem)
                    self.applyPythonKitProgress(update, to: currentItem, isEnhanced: useEnhanced)
                }
            },
            completion: { [weak self] success in
                // Handle completion on main actor
                Task { @MainActor in
                    guard let self = self else {
                        completionContinuation?.resume()
                        completionContinuation = nil
                        return
                    }
                    DebugLogger.shared.log("🔄 CLI subprocess completed with success: \(success) for: \(item.url.lastPathComponent)", component: "DocumentRedactionViewModel")

                    // Find current item (it might have changed during processing)
                    guard let currentItem = self.items.first(where: { $0.id == item.id }) else {
                        DebugLogger.shared.log("Document removed before completion handling", component: "DocumentRedactionViewModel")
                        completionContinuation?.resume()
                        completionContinuation = nil
                        return
                    }

                    DebugLogger.shared.log("🔄 Updating status from \(currentItem.status) based on CLI result: \(success)", component: "DocumentRedactionViewModel")

                    // Update status based on result
                    if success {
                        currentItem.status = .completed
                        // Clean up smooth progress animations
                        currentItem.markProcessingComplete(success: true)
                        // CRITICAL: Set output URLs to enable document action buttons
                        currentItem.redactedOutputURL = URL(fileURLWithPath: outputPath)
                        currentItem.reportOutputURL = URL(fileURLWithPath: reportPath)
                        let scrubReportURL = URL(fileURLWithPath: scrubReportPath)
                        if FileManager.default.fileExists(atPath: scrubReportURL.path) {
                            currentItem.scrubReportOutputURL = scrubReportURL
                        } else {
                            // Search for alternative naming: Filename_scrub_report.json
                            let directory = URL(fileURLWithPath: outputPath).deletingLastPathComponent()
                            let baseName = currentItem.url.deletingPathExtension().lastPathComponent
                            if let foundScrubReport = self.findScrubReport(in: directory, matching: baseName) {
                                currentItem.scrubReportOutputURL = foundScrubReport
                                DebugLogger.shared.log("📄 Found scrub report at alternate path: \(foundScrubReport.path)", component: "DocumentRedactionViewModel")
                            } else {
                                DebugLogger.shared.log("⚠️ Scrub report missing: \(scrubReportPath)", component: "DocumentRedactionViewModel")
                            }
                        }
                        DebugLogger.shared.log("📄 Set output URLs - DOCX: \(outputPath), JSON: \(reportPath)", component: "DocumentRedactionViewModel")
                        DebugLogger.shared.log("✅ Processing completed successfully for: \(currentItem.url.lastPathComponent)", component: "DocumentRedactionViewModel")
                    } else {
                        // Clean up smooth progress animations
                        currentItem.markProcessingComplete(success: false)
                        if currentItem.errorMessage == nil {
                            currentItem.errorMessage = "Processing failed - check App Log in Settings for details"
                        }
                        DebugLogger.shared.log("❌ Processing failed for: \(currentItem.url.lastPathComponent)", component: "DocumentRedactionViewModel")
                        self.assignFailureMessageIfNeeded(currentItem)
                    }
                    DebugLogger.shared.log("🔄 Final status after updateState(): \(currentItem.status)", component: "DocumentRedactionViewModel")
                    self.finalizeProcessing(for: currentItem)
                    completionContinuation?.resume()
                    completionContinuation = nil
                }
            }
        )

        // Track for cancellation and sequencing
        processingTasks[item.id]?.cancel()
        processingTasks[item.id] = completionTask

        return
    }

    private func processDocumentWithPythonKit(
        _ item: DocumentItem,
        outputPath: String,
        reportPath: String,
        scrubReportPath: String,
        useEnhanced: Bool,
        modelName: String,
        runner: PythonKitRunner
    ) async {
        runner.clearCancellationRequest()
        DebugLogger.shared.log("🔄 processDocumentWithPythonKit started for item.id=\(item.id) (\(item.url.lastPathComponent))", component: "DocumentRedactionViewModel")
        setenv("MARCUT_LOG_PATH", DebugLogger.shared.logPath, 1)
        item.beginStage(.preflight)
        let debug = settings.debug
        let cancellationChecker: () -> Bool = { [weak self] in
            guard let self = self else {
                DebugLogger.shared.log("⚠️ cancellationChecker: self is nil, returning true", component: "CancellationCheck")
                return true
            }
            let isCancelled = self.processingTasks[item.id]?.isCancelled ?? false
            if isCancelled {
                DebugLogger.shared.log("⚠️ cancellationChecker: task for item.id=\(item.id) is cancelled", component: "CancellationCheck")
            }
            return isCancelled
        }

        // Propagate metadata cleaning settings to Python via environment variable
        let metadataSettings = MetadataCleaningSettings.load()
        let metadataArgs = metadataSettings.toCLIArguments().joined(separator: " ")
        setenv("MARCUT_METADATA_ARGS", metadataArgs, 1)
        DebugLogger.shared.log("📋 Metadata args: \(metadataArgs.isEmpty ? "(defaults)" : metadataArgs)", component: "DocumentRedactionViewModel")

        if useEnhanced {
            let modelReady = await pythonBridge.waitForModelReadiness(modelName: modelName)
            if !modelReady {
                item.status = .failed
                item.errorMessage = "Model \(modelName) is not ready yet. Please try again in a moment."
                DebugLogger.shared.log("❌ Model readiness check failed for \(modelName)", component: "DocumentRedactionViewModel")
                finalizeProcessing(for: item)
                return
            }
        }

        setenv("MARCUT_SCRUB_REPORT_PATH", scrubReportPath, 1)
        DebugLogger.shared.log("📄 Scrub report path: \(scrubReportPath)", component: "DocumentRedactionViewModel")

        let streamAndResult: (AsyncStream<PythonRunnerProgressUpdate>, Task<PythonRunOutcome, Never>) = {
            runner.runEnhancedOllamaWithProgress(
                inputPath: item.path,
                outputPath: outputPath,
                reportPath: reportPath,
                model: modelName,
                debug: debug,
                mode: useEnhanced ? "enhanced" : "strict",
                chunkTokens: settings.chunkTokens,
                overlap: settings.overlap,
                temperature: settings.temperature,
                seed: settings.seed,
                processingStepTimeout: useEnhanced && settings.processingTimeoutSeconds != Int.max ? TimeInterval(settings.processingTimeoutSeconds) : nil,
                cancellationChecker: cancellationChecker
            )
        }()

        let progressTask = Task.detached { [weak self] in
            guard let self = self else {
                DebugLogger.shared.log("⚠️ Progress task: self is nil", component: "ProgressMonitor")
                return
            }
            DebugLogger.shared.log("🔄 Progress task started for item.id=\(item.id) (\(item.url.lastPathComponent))", component: "ProgressMonitor")
            var updateCount = 0
            for await update in streamAndResult.0 {
                updateCount += 1
                if Task.isCancelled {
                    DebugLogger.shared.log("⚠️ Progress task cancelled after \(updateCount) updates for \(item.url.lastPathComponent)", component: "ProgressMonitor")
                    break
                }
                await MainActor.run {
                    guard let currentItem = self.items.first(where: { $0.id == item.id }) else {
                        DebugLogger.shared.log("⚠️ Progress update #\(updateCount) dropped: item.id=\(item.id) not found in items", component: "ProgressMonitor")
                        return
                    }
                    
                    // Always update heartbeat timestamp to prevent false stall detection
                    // This is critical during status transitions (processing → completed)
                    currentItem.lastHeartbeat = Date()
                    
                    // Allow progress updates during processing OR completed (to handle race at completion)
                    // Block only for failed/cancelled states where updates are meaningless
                    guard currentItem.status == .processing || currentItem.status == .completed else {
                        DebugLogger.shared.log("⚠️ Progress update #\(updateCount) dropped: item status=\(currentItem.status) (expected .processing or .completed) for \(item.url.lastPathComponent)", component: "ProgressMonitor")
                        return
                    }

                    self.ensureHeartbeatMonitorRunning(for: currentItem)

                    self.applyPythonKitProgress(update, to: currentItem, isEnhanced: useEnhanced)
                }
            }
            DebugLogger.shared.log("🔄 Progress task finished for \(item.url.lastPathComponent) after \(updateCount) updates", component: "ProgressMonitor")
        }

        let completionTask = Task.detached { [weak self] in
            defer { unsetenv("MARCUT_SCRUB_REPORT_PATH") }
            guard let self = self else { return }
            let outcome = await self.awaitPythonOutcome(streamAndResult.1, runner: runner)
            progressTask.cancel()

            await MainActor.run {
                guard let currentItem = self.items.first(where: { $0.id == item.id }) else {
                    DebugLogger.shared.log("⚠️ Completion task: item.id=\(item.id) not found in items", component: "CompletionTask")
                    return
                }
                
                // If status was already changed by handleHeartbeatStall or another path,
                // just log and ensure cleanup happens
                guard currentItem.status == .processing else {
                    DebugLogger.shared.log("⚠️ Completion task: skipping outcome handling, status=\(currentItem.status) (expected .processing) for \(currentItem.url.lastPathComponent)", component: "CompletionTask")
                    // Still finalize to ensure cleanup - the status was already set by whoever changed it
                    self.finalizeProcessing(for: currentItem)
                    return
                }
                
                switch outcome {
                case .success:
                    currentItem.status = .completed
                    currentItem.redactedOutputURL = URL(fileURLWithPath: outputPath)
                    currentItem.reportOutputURL = URL(fileURLWithPath: reportPath)
                    
                    // Search for scrub report - Python may use different naming convention
                    // Try exact path first, then search for files containing "scrub"
                    let scrubReportURL = URL(fileURLWithPath: scrubReportPath)
                    if FileManager.default.fileExists(atPath: scrubReportURL.path) {
                        currentItem.scrubReportOutputURL = scrubReportURL
                    } else {
                        // Search for alternative naming: Filename_scrub_report.json
                        let directory = URL(fileURLWithPath: outputPath).deletingLastPathComponent()
                        let baseName = currentItem.url.deletingPathExtension().lastPathComponent
                        if let foundScrubReport = self.findScrubReport(in: directory, matching: baseName) {
                            currentItem.scrubReportOutputURL = foundScrubReport
                            DebugLogger.shared.log("📄 Found scrub report at alternate path: \(foundScrubReport.path)", component: "DocumentRedactionViewModel")
                        } else {
                            DebugLogger.shared.log("⚠️ Scrub report missing: \(scrubReportPath)", component: "DocumentRedactionViewModel")
                        }
                    }
                    currentItem.errorMessage = nil
                    DebugLogger.shared.log("✅ PythonKit processing completed for \(currentItem.url.lastPathComponent)", component: "DocumentRedactionViewModel")
                case .cancelled:
                    currentItem.status = .cancelled
                    DebugLogger.shared.log("⏹️ PythonKit processing cancelled for \(currentItem.url.lastPathComponent)", component: "DocumentRedactionViewModel")
                case .failure:
                    currentItem.status = .failed
                    if let failure = self.loadFailureReport(at: reportPath) {
                        currentItem.errorMessage = "Processing failed (\(failure.code)): \(failure.message)"
                        DebugLogger.shared.log("❌ PythonKit processing failed for \(currentItem.url.lastPathComponent) code=\(failure.code) message=\(failure.message) details=\(failure.details)", component: "DocumentRedactionViewModel")
                        // Dump Ollama logs to see why the runner crashed
                        PythonBridgeService.shared.dumpOllamaLogs()
                    } else {
                        if currentItem.errorMessage == nil {
                            currentItem.errorMessage = "Processing failed - see App Log in Settings for details."
                        }
                        DebugLogger.shared.log("❌ PythonKit processing failed for \(currentItem.url.lastPathComponent) (no failure report found)", component: "DocumentRedactionViewModel")
                    }
                    self.assignFailureMessageIfNeeded(currentItem)
                }
                self.finalizeProcessing(for: currentItem)
            }
        }

        processingTasks[item.id]?.cancel()
        processingTasks[item.id] = completionTask
    }

    private func awaitPythonOutcome(
        _ resultTask: Task<PythonRunOutcome, Never>,
        runner: PythonKitRunner
    ) async -> PythonRunOutcome {
        if Task.isCancelled {
            resultTask.cancel()
            runner.cancelCurrentOperation(source: "awaitPythonOutcome_taskCancelled")
            return .cancelled
        }

        return await withTaskGroup(of: PythonRunOutcome.self) { group in
            group.addTask {
                await resultTask.value
            }
            group.addTask {
                while !Task.isCancelled {
                    try? await Task.sleep(nanoseconds: 200_000_000)
                }
                resultTask.cancel()
                runner.cancelCurrentOperation(source: "awaitPythonOutcome_pollingCancelled")
                return .cancelled
            }

            let outcome = await group.next() ?? .failure
            group.cancelAll()
            return outcome
        }
    }

    func stopProcessing() {
        if !processingTasks.isEmpty, let runner = AppDelegate.pythonRunner {
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
        }
        processingTasks.removeAll()

        for (_, task) in heartbeatTasks {
            task.cancel()
        }
        heartbeatTasks.removeAll()
        AppDelegate.pythonRunner?.clearCancellationRequest()
        updateState()
    }
    
    func retryDocument(_ item: DocumentItem, destination: URL) {
        item.errorMessage = nil
        let task = Task { [weak self, weak item] in
            guard let self = self, let item = item else { return }
            await self.processDocument(item, destination: destination)
        }
        processingTasks[item.id] = task
        updateState()
    }
    
    // MARK: - State Management
    
    private func updateState() {
        hasDocuments = !items.isEmpty
        hasValidDocuments = items.contains { $0.status == .validDocument }
        hasProcessingDocuments = items.contains { $0.status.isProcessing }
        hasCompletedDocuments = items.contains { $0.status.isComplete }

        let hasPendingDocuments = items.contains { $0.status.isPendingReview }
        hasFinishedProcessing = hasCompletedDocuments && !hasProcessingDocuments && !hasPendingDocuments
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
            AppDelegate.pythonRunner?.cancelCurrentOperation(source: "removeDocument_itemProcessing")
        }
        if let hbTask = heartbeatTasks[item.id] {
            hbTask.cancel()
            heartbeatTasks.removeValue(forKey: item.id)
        }

        // Release security scope when document is removed
        item.releaseSecurityScope()

        items.removeAll { $0.id == item.id }
        updateState()
    }
    
    // MARK: - Output Management
    
    @discardableResult
    func openRedactedDocument(_ item: DocumentItem) -> Bool {
        guard let url = item.redactedOutputURL else { return false }
        return NSWorkspace.shared.open(url)
    }
    
    @discardableResult
    func openReport(_ item: DocumentItem) -> Bool {
        guard let url = item.reportOutputURL else { return false }
        return NSWorkspace.shared.open(url)
    }
    
    @discardableResult
    func openScrubReport(_ item: DocumentItem) -> Bool {
        guard let url = item.scrubReportOutputURL else { return false }
        return NSWorkspace.shared.open(url)
    }
    
    @discardableResult
    func revealInFinder(_ item: DocumentItem) -> Bool {
        if let url = item.redactedOutputURL ?? item.reportOutputURL ?? item.scrubReportOutputURL {
            return NSWorkspace.shared.selectFile(url.path, inFileViewerRootedAtPath: "")
        }
        return false
    }
    
    // MARK: - Settings Management
    
    func updateSettings(_ newSettings: RedactionSettings) {
        settings = newSettings
        // Sync debug setting with global logger
        DebugLogger.shared.updateDebugSetting(newSettings.debug)
        pythonBridge.updateLoggingPreference(newSettings.debug)
        pythonBridge.updateRuleFilter(newSettings.enabledRules)

        // Also update the rule filter in PythonKitRunner since that's what actually processes documents
        AppDelegate.pythonRunner?.updateRuleFilter(newSettings.enabledRules)
    }

    func initializeDebugSync() {
        // Call this after view model is fully initialized to sync debug settings
        DebugLogger.shared.updateDebugSetting(settings.debug)
        pythonBridge.updateLoggingPreference(settings.debug)
    }

    func requestFirstRunSetup(fromManageModels: Bool = false) {
        firstRunEntryPoint = fromManageModels ? .manageModels : .onboarding
        shouldShowFirstRunSetup = true
    }

    func clearLogs() {
        DebugLogger.shared.clearLog()
        pythonBridge.clearOllamaLog()
    }

    func resetFirstRunEntryPoint() {
        firstRunEntryPoint = .onboarding
    }

    private func finalizeProcessing(for item: DocumentItem) {
        processingTasks.removeValue(forKey: item.id)
        if let hbTask = heartbeatTasks[item.id] {
            hbTask.cancel()
            heartbeatTasks.removeValue(forKey: item.id)
        }
        // Clean up progress animations for all terminal states
        item.cleanupProgressAnimations()
        item.releaseSecurityScope()
        updateState()

        // Auto-wipe secure temp storage if idle
        if !hasProcessingDocuments {
            PythonRuntime.cleanupTempDir { msg in
                DebugLogger.shared.log(msg, component: "SecurityCleanup")
            }
        }
    }
    
    private func loadFailureReport(at path: String) -> (code: String, message: String, details: String)? {
        let url = URL(fileURLWithPath: path)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        do {
            let data = try Data(contentsOf: url)
            guard let json = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
                return nil
            }
            let code = (json["error_code"] as? String) ?? (json["status"] as? String) ?? "unknown"
            let message = (json["message"] as? String) ?? "Unspecified failure"
            let details = (json["technical_details"] as? String) ?? ""
            return (code: code, message: message, details: details)
        } catch {
            DebugLogger.shared.log("⚠️ Failed to parse failure report at \(path): \(error)", component: "DocumentRedactionViewModel")
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
            } else if logContent.contains("PK_PROCESSING_TIMEOUT") || logContent.contains("AI_PROCESSING_TIMEOUT") || logContent.contains("Step timeout") {
                specificError = "AI processing timed out - try increasing Processing Timeout or reducing Chunk Size/Overlap"
            } else if logContent.contains("OLLAMA_HOST") && logContent.contains("empty") && settings.mode == .enhanced {
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
    
    var isEnvironmentReady: Bool {
        // In Rules Only mode, we don't need Ollama or models
        if settings.mode == .rules {
            return frameworkAvailable
        }
        
        // Environment is only truly ready when the Ollama service is confirmed to be running.
        // The UI will reflect the startup process until this is true.
        // In Enhanced mode, we also require at least one model to be installed.
        if settings.mode == .enhanced {
            return frameworkAvailable && pythonBridge.isOllamaRunning && !availableModels.isEmpty
        }
        return frameworkAvailable && pythonBridge.isOllamaRunning
    }

    private func getOllamaPath() -> String? {
        // Correctly check Contents/MacOS for the binary
        if let executableURL = Bundle.main.executableURL {
            let macosOllamaURL = executableURL.deletingLastPathComponent().appendingPathComponent("ollama", isDirectory: false)
            if FileManager.default.fileExists(atPath: macosOllamaURL.path) {
                return macosOllamaURL.path
            }
        }
        
        // Fallback to legacy Resources location (just in case)
        if let bundledPath = Bundle.main.path(forResource: "ollama", ofType: nil) {
            return bundledPath
        }

        return nil
    }
    
    var environmentStatus: String {
        let supportedModels = availableModels

        // Provide specific, actionable error messages
        if !frameworkAvailable {
            return "❌ Python framework missing - Please reinstall MarcutApp"
        }
        
        // In Rules Only mode, we bypass AI checks
        if settings.mode == .rules {
            return "✅ Ready (Rules Only Mode)"
        }

        if let launchError = pythonBridge.ollamaLaunchError, !pythonBridge.isOllamaRunning {
            return "❌ \(launchError)"
        }
        
        if !pythonBridge.isOllamaRunning && getOllamaPath() == nil {
            return "❌ Ollama service not found - Check installation"
        } else if !pythonBridge.isOllamaRunning {
            return "Starting Ollama service..."
        } else if supportedModels.isEmpty {
            if pythonBridge.installedModels.isEmpty {
                return "⚠️ No AI models available - Will download on first use"
            } else {
                return "⚠️ No supported models - Install llama3.1:8b or similar"
            }
        } else {
            return "✅ Ready with \(supportedModels.count) AI model(s)"
        }
    }

    // MARK: - Enhanced Error Recovery Methods

    func attemptEnvironmentRecovery() async -> Bool {
        DebugLogger.shared.log("🔧 ATTEMPTING ENVIRONMENT RECOVERY", component: "DocumentRedactionViewModel")

        // Try to recover from common issues
        var recoveryAttempts = 0

        // 1. Try to refresh environment status
        let refreshSuccess = await refreshEnvironmentStatus(triggerFirstRunCheck: false)
        recoveryAttempts += 1
        DebugLogger.shared.log("Recovery attempt \(recoveryAttempts): Environment refresh - \(refreshSuccess ? "✅" : "❌")", component: "DocumentRedactionViewModel")

        if refreshSuccess {
            return true
        }

        // 2. If framework is missing, we can't recover without reinstall
        if !frameworkAvailable {
            DebugLogger.shared.log("❌ Cannot recover - Python framework missing", component: "DocumentRedactionViewModel")
            return false
        }

        // 3. Try to restart Ollama service
        if !pythonBridge.isOllamaRunning {
            DebugLogger.shared.log("🔄 Attempting to restart Ollama service", component: "DocumentRedactionViewModel")

            // Force check Ollama status
            await pythonBridge.checkOllamaStatus()
            recoveryAttempts += 1

            // Give it a moment to start
            try? await Task.sleep(nanoseconds: 2_000_000_000)

            // Check again
            await pythonBridge.checkOllamaStatus()
            DebugLogger.shared.log("Recovery attempt \(recoveryAttempts): Ollama restart - \(pythonBridge.isOllamaRunning ? "✅" : "❌")", component: "DocumentRedactionViewModel")
        }

        // Final status check
        let finalStatus = isEnvironmentReady
        DebugLogger.shared.log("🏁 Recovery completed - Final status: \(finalStatus ? "✅ Ready" : "❌ Still not ready")", component: "DocumentRedactionViewModel")

        return finalStatus
    }

    func getDetailedEnvironmentDiagnostics() -> [String: String] {
        var diagnostics: [String: String] = [:]

        diagnostics["framework_available"] = frameworkAvailable ? "✅ Yes" : "❌ No"
        diagnostics["framework_path"] = AppDelegate.pythonRunner != nil ? "PythonKit + BeeWare framework" : "PythonKit not available"
        diagnostics["ollama_running"] = pythonBridge.isOllamaRunning ? "✅ Yes" : "❌ No"
        diagnostics["ollama_binary"] = getOllamaPath() ?? "Not found"
        diagnostics["installed_models"] = "\(pythonBridge.installedModels.count) total"
        diagnostics["supported_models"] = "\(availableModels.count) supported"
        diagnostics["environment_ready"] = isEnvironmentReady ? "✅ Yes" : "❌ No"
        diagnostics["app_version"] = Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "Unknown"
        diagnostics["app_build"] = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "Unknown"

        return diagnostics
    }

    var ollamaLogURL: URL {
        pythonBridge.ollamaLogURL
    }

    var modelsDirectoryURL: URL {
        pythonBridge.modelsDirectoryURL
    }
    
    func checkEnvironment() {
        pythonBridge.checkEnvironment()
        Task { @MainActor [weak self] in
            self?.frameworkAvailable = Bundle.main.path(forResource: "python_launcher", ofType: "sh") != nil
        }
    }
    
    func downloadModel(_ modelName: String, progress: @escaping (Double) -> Void) async -> Bool {
        let result = await pythonBridge.downloadModel(modelName, progress: progress)
        if result {
            _ = await refreshEnvironmentStatus()
        }
        return result
    }

    var ollamaRunning: Bool {
        pythonBridge.isOllamaRunning
    }

    func cancelModelDownload() {
        pythonBridge.cancelModelDownload()
    }

    var availableModels: [String] {
        pythonBridge.installedModels.filter { Self.supportedModelIdentifiers.contains($0) }
    }

      @discardableResult
    func refreshEnvironmentStatus(triggerFirstRunCheck: Bool = true) async -> Bool {
        DebugLogger.shared.log("=== REFRESHING ENVIRONMENT STATUS ===", component: "DocumentRedactionViewModel")

        // Wait for Python initialization to complete before checking framework availability
        // This prevents false "framework missing" errors during the async startup sequence
        let initStart = Date()
        while isPythonInitializing && pythonInitializationError == nil {
            if Date().timeIntervalSince(initStart) > 30 {
                DebugLogger.shared.log("⚠️ Python initialization timeout in refreshEnvironmentStatus", component: "DocumentRedactionViewModel")
                break
            }
            try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
        }

        // Check PythonKit + BeeWare framework availability OR CLI subprocess availability
        let pythonKitAvailable = AppDelegate.pythonRunner != nil
        let cliScriptAvailable = Bundle.main.path(forResource: "marcut_cli_launcher", ofType: "sh") != nil

        // Framework is available if either PythonKit works OR CLI script is available
        frameworkAvailable = pythonKitAvailable || cliScriptAvailable

        if pythonKitAvailable {
            DebugLogger.shared.log("✅ PythonKit + BeeWare framework available", component: "DocumentRedactionViewModel")
        } else if cliScriptAvailable {
            DebugLogger.shared.log("✅ CLI subprocess launcher available", component: "DocumentRedactionViewModel")
        } else {
            DebugLogger.shared.log("❌ Neither PythonKit nor CLI launcher available", component: "DocumentRedactionViewModel")
        }

        // Check Python bridge with error handling
        // XPC removed - CLI subprocess only (no execution strategy needed)
        // pythonBridge.setExecutionStrategy(executionStrategy) // Removed - executionStrategy property deleted

        await pythonBridge.refreshEnvironment()
        DebugLogger.shared.log("✅ Python bridge refresh completed", component: "DocumentRedactionViewModel")

        let ready = isEnvironmentReady
        let hasSupportedModels = !availableModels.isEmpty
        if hasSupportedModels && !availableModels.contains(settings.model) {
            if let first = availableModels.first {
                settings.model = first
                DebugLogger.shared.log("🎯 Auto-selected available model \(first) as default", component: "DocumentRedactionViewModel")
            }
        }

        DebugLogger.shared.log("📊 Environment ready status: \(ready)", component: "DocumentRedactionViewModel")

        // Enhanced first-run logic with better error guidance
        if triggerFirstRunCheck {
            if !hasCompletedFirstRun {
                if ready && hasSupportedModels {
                    DebugLogger.shared.log("✅ Detected configured environment with \(availableModels.count) model(s); auto-completing onboarding", component: "DocumentRedactionViewModel")
                    markFirstRunComplete()
                    shouldShowFirstRunSetup = false
                } else {
                    firstRunEntryPoint = .onboarding
                    shouldShowFirstRunSetup = true
                    DebugLogger.shared.log("🔧 Showing first-time setup (onboarding not completed)", component: "DocumentRedactionViewModel")
                }
            } else if !ready {
                // Provide specific guidance based on what's missing
                if !frameworkAvailable {
                    DebugLogger.shared.log("⚠️ Framework missing - prompting setup", component: "DocumentRedactionViewModel")
                    firstRunEntryPoint = .onboarding
                } else if !pythonBridge.isOllamaRunning {
                    DebugLogger.shared.log("⚠️ Ollama not running - prompting setup", component: "DocumentRedactionViewModel")
                    firstRunEntryPoint = .manageModels
                } else {
                    DebugLogger.shared.log("⚠️ Other environment issue - prompting setup", component: "DocumentRedactionViewModel")
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
    
    func validateDestination(_ url: URL) -> String? {
        // Check write permissions
        let testFileURL = url.appendingPathComponent(".marcut-writetest")
        do {
            try "test".data(using: .utf8)?.write(to: testFileURL)
            try FileManager.default.removeItem(at: testFileURL)
        } catch {
            return "Cannot write to selected destination - please choose a different folder"
        }
        
        // Check disk space
        do {
            let validItems = items.filter { $0.status == .validDocument }
            let totalSize = try validItems.reduce(Int64(0)) { sum, item in
                let attributes = try FileManager.default.attributesOfItem(atPath: item.url.path)
                return sum + (attributes[.size] as? Int64 ?? 0)
            }
            
            let resourceValues = try url.resourceValues(forKeys: [.volumeAvailableCapacityKey])
            if let freeSpace = resourceValues.volumeAvailableCapacity {
                let buffer = max(totalSize * 2, 100 * 1024 * 1024) // 2x file size or 100MB buffer
                if Int64(buffer) > freeSpace {
                    return "Insufficient disk space - need at least \(ByteCountFormatter().string(fromByteCount: buffer))"
                }
            }
        } catch {
            print("Warning: Could not verify disk space: \(error)")
        }
        
        return nil
    }
    
    /// Search for scrub report file in directory matching document basename
    /// Handles both naming conventions: "(scrub-report DATE).json" and "_scrub_report.json"
    func findScrubReport(in directory: URL, matching baseName: String) -> URL? {
        let fm = FileManager.default
        guard let contents = try? fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) else {
            return nil
        }
        
        // Sanitize baseName for matching (remove special characters that might differ)
        let normalizedBaseName = baseName.lowercased()
        
        for fileURL in contents {
            let fileName = fileURL.lastPathComponent.lowercased()
            
            // Must be a JSON file
            guard fileName.hasSuffix(".json") else { continue }
            
            // Must contain "scrub" 
            guard fileName.contains("scrub") else { continue }
            
            // Must start with or contain the document base name (normalized)
            // Handle cases where basename might be truncated or have different separators
            let baseNameStart = String(normalizedBaseName.prefix(min(20, normalizedBaseName.count)))
            if fileName.contains(baseNameStart) {
                return fileURL
            }
        }
        
        return nil
    }
}

// MARK: - Heartbeat Monitoring (Logging Only)
// NOTE: Heartbeat stall detection has been DISABLED.
// The processing timeout (user-configurable) is the only timeout mechanism now.
// This heartbeat system now only logs activity for debugging purposes.
private extension DocumentRedactionViewModel {
    func ensureHeartbeatMonitorRunning(for item: DocumentItem) {
        // Heartbeat monitoring disabled - rely on processing timeout only.
        // The heartbeat stall detection was causing false positives when
        // gaps between LLM chunks exceeded 30 seconds, even though processing
        // was still working correctly.
        //
        // We still update lastHeartbeat timestamps for UI display purposes,
        // but we no longer fail documents based on heartbeat gaps.
    }

    func startHeartbeatMonitor(for item: DocumentItem) {
        // No-op: monitoring disabled
    }
}
// MARK: - Progress Mapping
private extension DocumentRedactionViewModel {
    func applyPythonKitProgress(
        _ update: PythonRunnerProgressUpdate,
        to item: DocumentItem,
        isEnhanced: Bool
    ) {
        let stage = mapPhaseToStage(
            identifier: update.phaseIdentifier,
            displayName: update.phaseDisplayName,
            isEnhancedMode: isEnhanced
        )

        if item.currentStage != stage {
            item.concludeCurrentStage()
            item.beginStage(stage)
        }

        if let message = update.message, !message.isEmpty {
            let handledMassEvent = item.ingestProgressPayload(message)
            if !handledMassEvent {
                DebugLogger.shared.log("Progress update: \(message)", component: "DocumentProgress")
            }
        }

        if let chunkInfo = extractChunkInfo(from: update) {
            if item.isMassTrackingActive && stage == .enhancedDetection {
                item.recordHeartbeatOnly(chunkIndex: chunkInfo.chunk, totalChunks: chunkInfo.total)
            } else {
                item.recordHeartbeat(chunkIndex: chunkInfo.chunk, totalChunks: chunkInfo.total)
            }
        }

        let shouldApplyProgress = !(item.isMassTrackingActive && stage == .enhancedDetection)
        if shouldApplyProgress {
            if let overall = update.overallProgress {
                item.setExplicitProgress(overall)
            } else if let phaseFraction = update.phaseProgress {
                item.applyStageProgressFraction(phaseFraction)
            }
        }
    }

    func mapPhaseToStage(identifier: String?, displayName: String?, isEnhancedMode: Bool) -> ProcessingStage {
        let candidate = (identifier ?? displayName ?? "").lowercased()
        if candidate.contains("preflight") || candidate.contains("loading") {
            return .preflight
        } else if candidate.contains("rule") || candidate.contains("structured") {
            return .ruleDetection
        } else if candidate.contains("analysis") {
            return .ruleDetection
        } else if candidate.contains("validation") {
            return .llmValidation
        } else if candidate.contains("llm") || candidate.contains("ai") || candidate.contains("extraction") {
            return .enhancedDetection
        } else if candidate.contains("merge") {
            return .merging
        } else if candidate.contains("track") || candidate.contains("output") || candidate.contains("complete") {
            return .outputGeneration
        }
        return isEnhancedMode ? .enhancedDetection : .ruleDetection
    }

    func extractChunkInfo(from update: PythonRunnerProgressUpdate) -> (chunk: Int, total: Int)? {
        if let chunk = update.chunk, let total = update.total, total > 0 {
            return (chunk, total)
        }

        if let message = update.message,
           let match = message.range(of: #"Processing chunk\s+(\d+)\s*/\s*(\d+)"#, options: .regularExpression) {
            let substring = message[match]
            let numbers = substring.replacingOccurrences(of: "Processing chunk", with: "")
            let parts = numbers.split(separator: "/").map { $0.trimmingCharacters(in: .whitespaces) }
            if parts.count == 2,
               let chunk = Int(parts[0]),
               let total = Int(parts[1]),
               total > 0 {
                return (chunk, total)
            }
        }

        return nil
    }
}

// MARK: - DOCX Validation
extension DocumentRedactionViewModel {
    /// Deep validation of DOCX structure to catch corrupt files before processing
    func validateDocxStructure(at url: URL) async -> Bool {
        await Task.detached(priority: .utility) { () -> Bool in
            // Step 1: Verify file exists and has content
            guard let data = try? Data(contentsOf: url, options: .mappedIfSafe), data.count > 4 else {
                DebugLogger.shared.log("DOCX validation: File too small or unreadable", component: "DocValidation")
                return false
            }

            // Step 2: Check ZIP signature (PK\x03\x04)
            let zipSignature = Data([0x50, 0x4B, 0x03, 0x04])
            guard data.starts(with: zipSignature) else {
                DebugLogger.shared.log("DOCX validation: Not a valid ZIP archive", component: "DocValidation")
                return false
            }

                // Step 3: Try to open as ZIP archive and extract entries
                do {
                    let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
                    try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true)
                    defer { 
                    // Secure deletion: zero all files before removing to prevent recovery
                    if let enumerator = FileManager.default.enumerator(at: tempDir, includingPropertiesForKeys: [.isRegularFileKey]) {
                        for case let fileURL as URL in enumerator {
                            if let attrs = try? fileURL.resourceValues(forKeys: [.isRegularFileKey]),
                               attrs.isRegularFile == true,
                               let size = try? FileManager.default.attributesOfItem(atPath: fileURL.path)[.size] as? Int,
                               size > 0 {
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
                
                // Use unzip to extract and verify integrity
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
                process.arguments = ["-t", "-q", tempCopy.path]  // Test archive integrity
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                
                try process.run()
                process.waitUntilExit()
                
                guard process.terminationStatus == 0 else {
                    DebugLogger.shared.log("DOCX validation: ZIP archive corrupt (unzip test failed)", component: "DocValidation")
                    return false
                }
                
                // Step 3.5: List zip entries for duplicate/relationship validation
                var zipEntries: [String] = []
                do {
                    let listProcess = Process()
                    listProcess.executableURL = URL(fileURLWithPath: "/usr/bin/unzip")
                    listProcess.arguments = ["-Z", "-1", tempCopy.path]
                    let listPipe = Pipe()
                    listProcess.standardOutput = listPipe
                    listProcess.standardError = FileHandle.nullDevice
                    try listProcess.run()
                    listProcess.waitUntilExit()
                    guard listProcess.terminationStatus == 0 else {
                        DebugLogger.shared.log("DOCX validation: Failed to list ZIP entries (unzip -Z)", component: "DocValidation")
                        return false
                    }
                    let data = listPipe.fileHandleForReading.readDataToEndOfFile()
                    if let output = String(data: data, encoding: .utf8) {
                        zipEntries = output.split(separator: "\n").map { String($0) }
                    }
                } catch {
                    DebugLogger.shared.log("DOCX validation: ZIP listing failed: \(error.localizedDescription)", component: "DocValidation")
                    return false
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
                    "\\[Content_Types\\].xml",  // Escape brackets for unzip glob pattern
                    "-d", tempDir.path
                ]
                extractProcess.standardOutput = FileHandle.nullDevice
                extractProcess.standardError = FileHandle.nullDevice
                
                try extractProcess.run()
                extractProcess.waitUntilExit()

                
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
                    DebugLogger.shared.log("DOCX validation: Missing word/_rels/document.xml.rels", component: "DocValidation")
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
                          rootElement?.name == "document" else {
                        DebugLogger.shared.log("DOCX validation: Invalid WordprocessingML namespace: \(namespaceURI)", component: "DocValidation")
                        return false
                    }
                    
                    // Step 6: Relationship Integrity Check
                    // Corrupt files often have elements referring to missing relationships
                    if FileManager.default.fileExists(atPath: relsPath.path),
                       let relsData = try? Data(contentsOf: relsPath),
                       let relsDoc = try? XMLDocument(data: relsData) {
                        
                        // Collect valid Relationship IDs
                        var validRelIds = Set<String>()
                        if let relsRoot = relsDoc.rootElement() {
                            for child in relsRoot.children ?? [] {
                                if let element = child as? XMLElement,
                                   let id = element.attribute(forName: "Id")?.stringValue {
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
                                    if attr.localName == "id" && (attr.prefix == "r" || attr.name == "r:id") {
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
                            DebugLogger.shared.log("⚠️ DOCX validation warning: Found \(orphanedRels.count) orphaned relationships (e.g., \(orphanedRels.first ?? "?")) - Proceeding despite warnings", component: "DocValidation")
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
                        let duplicateEntries = Set(entryCounts.filter { $0.value > 1 }.map { $0.key })
                        if !duplicateEntries.isEmpty {
                            DebugLogger.shared.log("DOCX validation: Duplicate ZIP entries detected (e.g., \(duplicateEntries.first ?? "?"))", component: "DocValidation")
                            return false
                        }

                        func relsSourceDir(_ relsPath: String) -> String {
                            if relsPath == "_rels/.rels" { return "" }
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
                                if part.isEmpty || part == "." { continue }
                                if part == ".." {
                                    if !parts.isEmpty { parts.removeLast() }
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
                                  let relsRoot = relsDoc.rootElement() else {
                                DebugLogger.shared.log("DOCX validation: Unable to parse \(relsPath)", component: "DocValidation")
                                return false
                            }
                            for child in relsRoot.children ?? [] {
                                guard let element = child as? XMLElement else { continue }
                                let targetMode = element.attribute(forName: "TargetMode")?.stringValue ?? ""
                                if targetMode == "External" { continue }
                                guard let target = element.attribute(forName: "Target")?.stringValue else { continue }
                                let resolved = resolveTarget(relsPath: relsPath, target: target)
                                if !entrySet.contains(resolved) {
                                    DebugLogger.shared.log("DOCX validation: Missing relationship target \(resolved) from \(relsPath)", component: "DocValidation")
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
                    DebugLogger.shared.log("DOCX validation: XML parsing failed: \(error.localizedDescription)", component: "DocValidation")
                    return false
                }
                
            } catch {
                DebugLogger.shared.log("DOCX validation: Process error: \(error.localizedDescription)", component: "DocValidation")
                return false
            }
        }.value
    }
}
