import Foundation
@testable import MarcutApp

/// Ordered log shared by `RecordingRedactionRunner` and the harness-installed
/// `llmPreflightCheck`/`modelReadinessCheck`/`sharePresenter` closures, so a single `events[]`
/// array in the golden snapshot pins the full call sequence across the whole seam surface --
/// not just the `RedactionRunning` methods (issue #100, ticket note: "The injected preflight
/// closures and sharePresenter also record events.").
final class EventRecorder {
    struct Event: Codable, Equatable {
        let method: String
        let args: [String]
        let envAtCall: [String: String]
    }

    private(set) var events: [Event] = []

    func record(_ method: String, _ args: [String]) {
        events.append(Event(
            method: method,
            args: args,
            envAtCall: RedactionCharacterizationHarness.currentEnvSnapshot()
        ))
    }
}

/// Single-await gate a scripted run can suspend on before resolving its `PythonRunOutcome`, so
/// "stop mid-run" scenarios are deterministic instead of racing a timer or a fixed `sleep`. The
/// harness opens the gate once it has observed whatever it needed to (typically the
/// `runEnhancedOllamaWithProgress` event landing in the shared `EventRecorder`).
actor RunGate {
    private var isOpen = false
    private var continuation: CheckedContinuation<Void, Never>?

    func wait() async {
        if isOpen {
            return
        }
        await withCheckedContinuation { continuation = $0 }
    }

    func open() {
        isOpen = true
        continuation?.resume()
        continuation = nil
    }
}

/// Scripted, recording fake standing in for `PythonKitRunner` in the golden bridge-call
/// characterization harness (#100). See `RedactionCharacterizationHarness.swift`'s header
/// doc-comment for what is snapshotted and how to re-baseline.
///
/// Every `RedactionRunning` call appends an event to the shared `EventRecorder` (method name,
/// ordered/stringified args, and the environment-allowlist snapshot at the moment of the call).
/// Each entry point's return value/outcome is scripted ahead of time via the `*Script`
/// properties below; nothing here talks to a real embedded interpreter, network, or filesystem
/// beyond the artifacts a script explicitly asks to be written.
final class RecordingRedactionRunner: RedactionRunning {
    /// What `runEnhancedOllamaWithProgress` does when called.
    struct RunScript {
        var progressUpdates: [PythonRunnerProgressUpdate] = []
        var outcome: PythonRunOutcome = .success
        /// Runs on the fake's background task right before the outcome resolves. Receives the
        /// exact `outputPath`/`reportPath` the view model passed in, and the
        /// `MARCUT_SCRUB_REPORT_PATH` value captured at the moment of the call (mirrors how the
        /// real bridge/Python side receives it -- via environment, not a call argument).
        var writeArtifacts: ((_ outputPath: String, _ reportPath: String, _ scrubReportPathAtCall: String?) -> Void)?
        /// When set, the result `Task` suspends here before resolving to `outcome`.
        var gate: RunGate?
    }

    enum OutputFixture {
        case validDocx
        case corruptDocx
        case none
    }

    struct ScrubScript {
        var success = true
        var error: String?
        var report: [String: Any]?
        var outputFixture: OutputFixture = .validDocx
        /// When set, `scrubMetadataOnlyAsync` throws this instead of returning -- exercises the
        /// `catch` path callers use to surface a raw runner/bridge exception.
        var throwsError: Error?
    }

    struct ReportScript {
        var success = true
        var error: String?
        var report: [String: Any]?
        var htmlPath: String?
        /// When true, writes a `.json` (and, if `writeHTMLSibling`, a sibling `.html`) file at
        /// the requested `reportPath` so downstream file-existence checks
        /// (`generateScrubHTMLIfMissing`, the outer fallback check) see a real report on disk,
        /// exactly as the real Python side would have written one.
        var writeReportFile = true
        var writeHTMLSibling = false
        var throwsError: Error?
    }

    let recorder: EventRecorder
    var runEnhancedScript = RunScript()
    var scrubScript = ScrubScript()
    var reportScript = ReportScript()
    /// Scripted result for `generateScrubHTML(from:)`. When non-nil, the fake writes that string
    /// as the `.html` file sibling to the requested JSON path and returns that path -- mirroring
    /// how the real bridge generates HTML alongside the JSON it's pointed at.
    var generateScrubHTMLContent: String?

    init(recorder: EventRecorder = EventRecorder()) {
        self.recorder = recorder
    }

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
        cancellationChecker _: @escaping () -> Bool
    ) -> (stream: AsyncStream<PythonRunnerProgressUpdate>, result: Task<PythonRunOutcome, Never>) {
        recorder.record("runEnhancedOllamaWithProgress", [
            inputPath, outputPath, reportPath, model, "\(debug)", mode,
            "\(llmSkipConfidence)", "\(llmConcurrency)", "\(chunkTokens)", "\(overlap)",
            "\(temperature)", "\(seed)", processingStepTimeout.map { "\($0)" } ?? "nil",
            "<cancellationChecker>",
        ])

        let script = runEnhancedScript
        let scrubReportPathAtCall = getenv("MARCUT_SCRUB_REPORT_PATH").map { String(cString: $0) }

        let stream = AsyncStream<PythonRunnerProgressUpdate> { continuation in
            for update in script.progressUpdates {
                continuation.yield(update)
            }
            continuation.finish()
        }

        let task = Task<PythonRunOutcome, Never> {
            if let gate = script.gate {
                await gate.wait()
            }
            script.writeArtifacts?(outputPath, reportPath, scrubReportPathAtCall)
            return script.outcome
        }

        return (stream: stream, result: task)
    }

    func scrubMetadataOnlyAsync(
        inputPath: String,
        outputPath: String
    ) async throws -> (success: Bool, error: String?, report: [String: Any]?) {
        recorder.record("scrubMetadataOnlyAsync", [inputPath, outputPath])
        let script = scrubScript
        if let error = script.throwsError {
            throw error
        }
        switch script.outputFixture {
        case .validDocx:
            try? FileManager.default.copyItem(
                atPath: RedactionCharacterizationHarness.fixturePath(.validDocx),
                toPath: outputPath
            )
        case .corruptDocx:
            try? FileManager.default.copyItem(
                atPath: RedactionCharacterizationHarness.fixturePath(.corruptDocx),
                toPath: outputPath
            )
        case .none:
            break
        }
        return (success: script.success, error: script.error, report: script.report)
    }

    func metadataReportOnlyAsync(
        inputPath: String,
        reportPath: String
    ) async throws -> (success: Bool, error: String?, report: [String: Any]?, htmlPath: String?) {
        recorder.record("metadataReportOnlyAsync", [inputPath, reportPath])
        let script = reportScript
        if let error = script.throwsError {
            throw error
        }
        if script.writeReportFile {
            let payload = script.report ?? ["summary": ["file_name": (inputPath as NSString).lastPathComponent]]
            if let data = try? JSONSerialization.data(withJSONObject: payload, options: [.sortedKeys]) {
                try? data.write(to: URL(fileURLWithPath: reportPath))
            }
            if script.writeHTMLSibling {
                let htmlPath = (reportPath as NSString).deletingPathExtension + ".html"
                try? "<html>fake report</html>".write(toFile: htmlPath, atomically: true, encoding: .utf8)
            }
        }
        return (success: script.success, error: script.error, report: script.report, htmlPath: script.htmlPath)
    }

    func generateScrubHTML(from jsonPath: String) async -> String? {
        recorder.record("generateScrubHTML", [jsonPath])
        guard let content = generateScrubHTMLContent else { return nil }
        let htmlPath = (jsonPath as NSString).deletingPathExtension + ".html"
        try? content.write(toFile: htmlPath, atomically: true, encoding: .utf8)
        return htmlPath
    }

    func clearCancellationRequest() {
        recorder.record("clearCancellationRequest", [])
    }

    func cancelCurrentOperation(source: String) {
        recorder.record("cancelCurrentOperation", [source])
    }

    func updateRuleFilter(_ rules: Set<RedactionRule>) {
        recorder.record("updateRuleFilter", [rules.map(\.rawValue).sorted().joined(separator: ",")])
    }
}
