import Foundation

/// The seven `PythonKitRunner` members `DocumentRedactionViewModel` actually calls, extracted as
/// a protocol so a recording fake can stand in for the real runner in the golden harness (#100)
/// without constructing `PythonKitRunner` itself -- its `init(logger:)`
/// (`PythonKitBridge.swift`) starts a worker thread and the embedded interpreter, so it can be
/// neither constructed nor subclassed in tests. A protocol is the only fake path.
///
/// Signatures and tuple labels are copied verbatim from `PythonKitBridge.swift`. Protocol
/// requirements cannot carry default parameter values (Swift rejects them at the declaration
/// site); every `DocumentRedactionViewModel` call site already passes every argument explicitly,
/// so nothing is lost by omitting them here.
///
/// See `docs/design/view_controller_decomposition.md` SS2.1 (extracted collaborators take what
/// they need as parameters/closures) and issue #98.
protocol RedactionRunning: AnyObject {
    func runEnhancedOllamaWithProgress(
        inputPath: String,
        outputPath: String,
        reportPath: String,
        model: String,
        debug: Bool,
        mode: String,
        llmSkipConfidence: Double,
        llmConcurrency: Int,
        chunkTokens: Int,
        overlap: Int,
        temperature: Double,
        seed: Int,
        processingStepTimeout: TimeInterval?,
        cancellationChecker: @escaping () -> Bool
    ) -> (stream: AsyncStream<PythonRunnerProgressUpdate>, result: Task<PythonRunOutcome, Never>)

    func scrubMetadataOnlyAsync(
        inputPath: String,
        outputPath: String
    ) async throws -> (success: Bool, error: String?, report: [String: Any]?)

    func metadataReportOnlyAsync(
        inputPath: String,
        reportPath: String
    ) async throws -> (success: Bool, error: String?, report: [String: Any]?, htmlPath: String?)

    func generateScrubHTML(from jsonPath: String) async -> String?

    func clearCancellationRequest()

    func cancelCurrentOperation(source: String)

    func updateRuleFilter(_ rules: Set<RedactionRule>)
}

extension PythonKitRunner: RedactionRunning {}
