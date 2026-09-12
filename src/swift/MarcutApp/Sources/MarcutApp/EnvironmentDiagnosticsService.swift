import Foundation

/// Environment/model diagnostics collaborator, extracted from `DocumentRedactionViewModel`
/// (`docs/design/view_controller_decomposition.md` §2.1, slice 4). Mostly forwards to
/// `pythonBridge`/the injected runner provider already -- moving it changes who calls, not
/// what is called. Takes the bridge and the runner provider as constructor parameters and
/// returns values from every method rather than reaching back into the view model;
/// `frameworkAvailable`, `shouldShowFirstRunSetup`, and the first-run flags stay `@Published`
/// on the view model, set there from this collaborator's returned results.
@MainActor
final class EnvironmentDiagnosticsService {
    private static let supportedModelIdentifiers: Set<String> = ModelCatalog.shared.modelIds
    private static func normalizeModelIdentifier(_ modelName: String) -> String {
        let trimmed = modelName.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = trimmed.split(separator: "/")
        var relevant = Array(parts)
        if parts.count >= 3 {
            relevant = Array(parts.suffix(2))
        }
        if relevant.count == 2, relevant.first == "library" {
            return String(relevant[1]).lowercased()
        }
        return relevant.map { String($0).lowercased() }.joined(separator: "/")
    }

    private let pythonBridge: PythonBridgeService
    /// Resolves the embedded-Python runner, mirroring `DocumentRedactionViewModel.runnerProvider`
    /// -- a closure rather than a stored snapshot for the same reason as that property (the
    /// runner is assigned asynchronously after construction).
    private let runnerProvider: () -> (any RedactionRunning)?

    init(pythonBridge: PythonBridgeService, runnerProvider: @escaping () -> (any RedactionRunning)?) {
        self.pythonBridge = pythonBridge
        self.runnerProvider = runnerProvider
    }

    // MARK: - Environment Status

    func isEnvironmentReady(mode: RedactionMode, frameworkAvailable: Bool) -> Bool {
        // In Rules Only mode, we don't need Ollama or models
        if mode == .rules {
            return frameworkAvailable
        }

        // Environment is only truly ready when the Ollama service is confirmed to be running.
        // The UI will reflect the startup process until this is true.
        // In LLM modes, we also require at least one model to be installed.
        if mode.usesLLM {
            return frameworkAvailable && pythonBridge.isOllamaRunning && !availableModels.isEmpty
        }
        return frameworkAvailable && pythonBridge.isOllamaRunning
    }

    private func getOllamaPath() -> String? {
        // Correctly check Contents/MacOS for the binary
        if let executableURL = Bundle.main.executableURL {
            let macosOllamaURL = executableURL.deletingLastPathComponent().appendingPathComponent(
                "ollama",
                isDirectory: false
            )
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

    func environmentStatus(mode: RedactionMode, frameworkAvailable: Bool) -> String {
        let supportedModels = availableModels

        // Provide specific, actionable error messages
        if !frameworkAvailable {
            return "❌ Python framework missing - Please reinstall MarcutApp"
        }

        // In Rules Only mode, we bypass AI checks
        if mode == .rules {
            return "✅ Ready (Rules Only Mode)"
        }

        if let launchError = pythonBridge.ollamaLaunchError, !pythonBridge.isOllamaRunning {
            return "❌ \(launchError)"
        }

        if !pythonBridge.isOllamaRunning, getOllamaPath() == nil {
            return "❌ Ollama service not found - Check installation"
        } else if !pythonBridge.isOllamaRunning {
            return "Starting Ollama service..."
        } else if supportedModels.isEmpty {
            if pythonBridge.installedModels.isEmpty {
                return "⚠️ No AI models available - Will download on first use"
            } else {
                return "⚠️ No supported models - Install qwen2.5:14b or similar"
            }
        } else {
            return "✅ Ready with \(supportedModels.count) AI model(s)"
        }
    }

    // MARK: - Enhanced Error Recovery Methods

    /// Result of one recovery attempt: the final readiness verdict.
    struct RecoveryOutcome {
        let ready: Bool
    }

    /// `refresh` performs the same work as the view model's `refreshEnvironmentStatus
    /// (triggerFirstRunCheck: false)` -- including applying the returned `RefreshOutcome` to the
    /// view model's own published state -- without this collaborator reaching back into the view
    /// model to do it directly.
    func attemptEnvironmentRecovery(
        mode: RedactionMode,
        currentModel: String,
        refresh: (RedactionMode, String) async -> RefreshOutcome
    ) async -> RecoveryOutcome {
        DebugLogger.shared.log("🔧 ATTEMPTING ENVIRONMENT RECOVERY", component: "DocumentRedactionViewModel")

        // Try to recover from common issues
        var recoveryAttempts = 0

        // 1. Try to refresh environment status
        let refreshResult = await refresh(mode, currentModel)
        recoveryAttempts += 1
        DebugLogger.shared.log(
            "Recovery attempt \(recoveryAttempts): Environment refresh - \(refreshResult.ready ? "✅" : "❌")",
            component: "DocumentRedactionViewModel"
        )

        if refreshResult.ready {
            return RecoveryOutcome(ready: true)
        }

        // 2. If framework is missing, we can't recover without reinstall
        if !refreshResult.frameworkAvailable {
            DebugLogger.shared.log(
                "❌ Cannot recover - Python framework missing",
                component: "DocumentRedactionViewModel"
            )
            return RecoveryOutcome(ready: false)
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
            DebugLogger.shared.log(
                "Recovery attempt \(recoveryAttempts): Ollama restart - \(pythonBridge.isOllamaRunning ? "✅" : "❌")",
                component: "DocumentRedactionViewModel"
            )
        }

        // Final status check
        let finalStatus = isEnvironmentReady(mode: mode, frameworkAvailable: refreshResult.frameworkAvailable)
        DebugLogger.shared.log(
            "🏁 Recovery completed - Final status: \(finalStatus ? "✅ Ready" : "❌ Still not ready")",
            component: "DocumentRedactionViewModel"
        )

        return RecoveryOutcome(ready: finalStatus)
    }

    func detailedEnvironmentDiagnostics(mode: RedactionMode, frameworkAvailable: Bool) -> [String: String] {
        var diagnostics: [String: String] = [:]

        diagnostics["framework_available"] = frameworkAvailable ? "✅ Yes" : "❌ No"
        diagnostics["framework_path"] = runnerProvider() != nil ? "PythonKit + BeeWare framework" : "PythonKit not available"
        diagnostics["ollama_running"] = pythonBridge.isOllamaRunning ? "✅ Yes" : "❌ No"
        diagnostics["ollama_binary"] = getOllamaPath() ?? "Not found"
        diagnostics["installed_models"] = "\(pythonBridge.installedModels.count) total"
        diagnostics["supported_models"] = "\(availableModels.count) supported"
        diagnostics["environment_ready"] = isEnvironmentReady(mode: mode, frameworkAvailable: frameworkAvailable) ?
            "✅ Yes" : "❌ No"
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

    var lastModelDownloadError: String? {
        pythonBridge.lastModelDownloadError
    }

    /// `frameworkAvailable`'s recheck runs on a deferred `Task` in the original method (a
    /// same-actor hop, not a real async wait) -- this keeps that shape and hands the result to
    /// `frameworkAvailableSink` instead of writing a view-model property directly.
    func checkEnvironment(frameworkAvailableSink: @escaping (Bool) -> Void) {
        pythonBridge.checkEnvironment()
        Task { @MainActor in
            frameworkAvailableSink(Bundle.main.path(forResource: "python_launcher", ofType: "sh") != nil)
        }
    }

    func downloadModel(
        _ modelName: String,
        progress: @escaping (Double) -> Void,
        refreshAfterSuccess: () async -> Void
    ) async -> Bool {
        let result = await pythonBridge.downloadModel(modelName, progress: progress)
        if result {
            await refreshAfterSuccess()
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
        pythonBridge.installedModels.filter { model in
            let normalized = Self.normalizeModelIdentifier(model)
            return Self.supportedModelIdentifiers.contains(normalized) && pythonBridge.isModelAvailable(model)
        }
    }

    var installedModelCount: Int {
        pythonBridge.installedModels.count
    }

    func shouldSuppressModelSetupPrompt(mode: RedactionMode, hasUsedMetadataScrub: Bool) -> Bool {
        mode == .rules || (hasUsedMetadataScrub && availableModels.isEmpty)
    }

    /// Result of `refreshEnvironment`: the recomputed `frameworkAvailable`/readiness state, plus
    /// (when applicable) the model that should replace `settings.model` because the previously
    /// selected one is no longer available. The view model applies these to its own published
    /// state and settings.
    struct RefreshOutcome {
        let frameworkAvailable: Bool
        let ready: Bool
        let selectedModel: String?
    }

    /// Core of `refreshEnvironmentStatus(triggerFirstRunCheck:)` minus the Python-initialization
    /// wait loop and the first-run-prompt decision tree, both of which stay on the view model:
    /// the former depends on `isPythonInitializing`/`pythonInitializationError`, state this
    /// collaborator has no reason to own, and the latter needs `hasCompletedFirstRun`/
    /// `markFirstRunComplete()`, which are already view-model concerns unrelated to environment
    /// diagnostics.
    func refreshEnvironment(mode: RedactionMode, currentModel: String) async -> RefreshOutcome {
        DebugLogger.shared.log("=== REFRESHING ENVIRONMENT STATUS ===", component: "DocumentRedactionViewModel")

        // Check PythonKit + BeeWare framework availability OR CLI subprocess availability
        let pythonKitAvailable = runnerProvider() != nil
        let cliScriptAvailable = Bundle.main.path(forResource: "marcut_cli_launcher", ofType: "sh") != nil

        // Framework is available if either PythonKit works OR CLI script is available
        let frameworkAvailable = pythonKitAvailable || cliScriptAvailable

        if pythonKitAvailable {
            DebugLogger.shared.log("✅ PythonKit + BeeWare framework available", component: "DocumentRedactionViewModel")
        } else if cliScriptAvailable {
            DebugLogger.shared.log("✅ CLI subprocess launcher available", component: "DocumentRedactionViewModel")
        } else {
            DebugLogger.shared.log(
                "❌ Neither PythonKit nor CLI launcher available",
                component: "DocumentRedactionViewModel"
            )
        }

        // Check Python bridge with error handling
        // XPC removed - CLI subprocess only (no execution strategy needed)
        // pythonBridge.setExecutionStrategy(executionStrategy) // Removed - executionStrategy property deleted

        await pythonBridge.refreshEnvironment()
        DebugLogger.shared.log("✅ Python bridge refresh completed", component: "DocumentRedactionViewModel")

        let ready = isEnvironmentReady(mode: mode, frameworkAvailable: frameworkAvailable)
        let hasSupportedModels = !availableModels.isEmpty
        var selectedModel: String?
        if hasSupportedModels,
           !availableModels
           .contains(where: { Self.normalizeModelIdentifier($0) == Self.normalizeModelIdentifier(currentModel) })
        {
            if let first = availableModels.first {
                selectedModel = first
                DebugLogger.shared.log(
                    "🎯 Auto-selected available model \(first) as default",
                    component: "DocumentRedactionViewModel"
                )
            }
        }

        DebugLogger.shared.log("📊 Environment ready status: \(ready)", component: "DocumentRedactionViewModel")

        return RefreshOutcome(frameworkAvailable: frameworkAvailable, ready: ready, selectedModel: selectedModel)
    }
}
