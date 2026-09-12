import Foundation

/// Heartbeat/stall watchdog (B1) plus batch-ETA estimation, extracted from
/// `DocumentRedactionViewModel` (`docs/design/view_controller_decomposition.md` §2.1, slice 3).
/// Owned by the view model as a single collaborator. Takes what it needs as constructor
/// closures -- an items snapshot, the `hasProcessingDocuments` flag, a "fail this item"
/// callback, and a `batchETA` sink -- rather than reaching back into the view model directly;
/// `@Published var batchETA` itself stays on the view model.
@MainActor
final class ProgressMonitor {
    private var heartbeatTasks: [UUID: Task<Void, Never>] = [:]

    /// Wall-clock time each document started processing in the current run, keyed by item id.
    /// Used to compute a per-document duration sample once the document reaches a terminal state.
    var batchProcessingStartTimes: [UUID: Date] = [:]
    /// (duration, size) samples for documents completed so far in the current run. Reset at the
    /// start of every `processAllDocuments` call.
    var batchETASamples: [BatchETASample] = []
    private let heartbeatTimeout: TimeInterval = 120.0
    /// How often the heartbeat watchdog re-checks a processing document for staleness. Small
    /// relative to `heartbeatTimeout` so a stall is reported soon after crossing the threshold,
    /// without busy-polling.
    private let heartbeatPollInterval: TimeInterval = 5.0

    /// Snapshot of the view model's current documents. Backs both the heartbeat loop's
    /// per-id lookup and `updateBatchETA()`'s remaining-work scan.
    private let itemsProvider: () -> [DocumentItem]
    private let hasProcessingDocumentsProvider: () -> Bool
    /// Invoked once a document is marked `.failed` by the heartbeat watchdog. The view model
    /// owns invalidating `activeAttemptTokens`, best-effort cancelling the underlying run, and
    /// `finalizeProcessing(for:)` -- none of which this collaborator reaches back for directly.
    private let failItem: (DocumentItem) -> Void
    private let batchETASink: (TimeInterval?) -> Void

    init(
        itemsProvider: @escaping () -> [DocumentItem],
        hasProcessingDocuments: @escaping () -> Bool,
        failItem: @escaping (DocumentItem) -> Void,
        batchETASink: @escaping (TimeInterval?) -> Void
    ) {
        self.itemsProvider = itemsProvider
        self.hasProcessingDocumentsProvider = hasProcessingDocuments
        self.failItem = failItem
        self.batchETASink = batchETASink
    }

    deinit {
        for (_, task) in heartbeatTasks {
            task.cancel()
        }
        heartbeatTasks.removeAll()
    }

    /// Cancels and drops the heartbeat task for a single document, if one is running. Used
    /// when a document leaves processing through any path other than the watchdog itself
    /// (normal completion, removal, or a user-initiated stop).
    func cancelHeartbeat(for itemId: UUID) {
        if let task = heartbeatTasks[itemId] {
            task.cancel()
            heartbeatTasks.removeValue(forKey: itemId)
        }
    }

    /// Cancels every running heartbeat task. Used by `stopProcessing()`.
    func cancelAllHeartbeats() {
        for (_, task) in heartbeatTasks {
            task.cancel()
        }
        heartbeatTasks.removeAll()
    }

    /// Records a (duration, size) sample for the batch ETA estimator once a document that
    /// actually ran (completed or failed) reaches a terminal state. Cancelled documents are
    /// skipped — their elapsed time isn't a meaningful processing-rate signal.
    func recordBatchETASample(for item: DocumentItem) {
        guard let startedAt = batchProcessingStartTimes.removeValue(forKey: item.id) else { return }
        guard item.status == .completed || item.status == .failed else { return }

        let duration = Date().timeIntervalSince(startedAt)
        guard duration > 0 else { return }

        let size = documentSizeSignal(for: item)
        guard size > 0 else { return }

        batchETASamples.append(BatchETASample(duration: duration, size: size))
    }

    /// Recomputes `batchETA` from samples collected so far in this run plus the size signal
    /// for documents still queued or in-flight. Clears the estimate once no documents remain
    /// in a processing state, or while there isn't enough data yet.
    func updateBatchETA() {
        guard hasProcessingDocumentsProvider() else {
            batchETASink(nil)
            return
        }

        let remainingSizes = itemsProvider()
            .filter { $0.status.isProcessing || $0.status == .validDocument }
            .map { documentSizeSignal(for: $0) }

        batchETASink(BatchETACalculator.estimate(samples: batchETASamples, remainingSizes: remainingSizes))
    }

    /// Relative "work" signal for a document, used for batch ETA estimation
    /// (`BatchETACalculator`). Prefers the word count extracted from
    /// `word/document.xml` during validation (`extractWordCount`, wired in
    /// `checkDocument`) over raw file byte size -- a DOCX's compressed byte
    /// size can vary independently of its actual text content (embedded
    /// images/styles inflate size without adding rules/LLM processing work),
    /// so word count is a much better predictor of how long a document will
    /// take. Falls back to file byte size when word count isn't available
    /// yet (e.g. validation hasn't completed for this item).
    func documentSizeSignal(for item: DocumentItem) -> Int64 {
        if let words = item.wordCount, words > 0 {
            return Int64(words)
        }
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: item.url.path),
              let size = attributes[.size] as? Int64
        else {
            return 0
        }
        return size
    }
}

// MARK: - Heartbeat Monitoring (B1 watchdog)

//
// Detects a genuinely wedged embedded Python call: one where not even the keepalive signal
// Python emits roughly every 3s during a long LLM call (`send_keepalive` in
// `model_enhanced.py`) is getting through, which only happens if the interpreter itself is
// stuck (GIL held forever, blocked in native C code) rather than merely slow. A single
// long-but-alive chunk still refreshes `item.lastHeartbeat` via that keepalive, so watching for
// prolonged *total* silence (`heartbeatTimeout`, not a per-chunk gap) is what avoids the false
// positives that got an earlier version of this mechanism disabled: it used a 30s per-chunk-gap
// threshold that fired on legitimately slow (but alive) chunks. `heartbeatTimeout` (120s of no
// progress signal at all, whether chunk boundary or keepalive) plus the keepalive protocol above
// is the fix for that.
//
// This is deliberately independent from, and fires much sooner than, the separate bridge-level
// watchdog in `PythonKitBridge.swift` (`PythonBridgeError.workerStalled` / `PythonRunOutcome
// .stalled`): that one exists to eventually reclaim the worker thread itself and stop future
// calls from silently queuing behind it forever, but its bound is necessarily generous (tens of
// minutes) so it doesn't cut off a legitimate long run before that run's own configured timeout
// would. This one exists to give the *user* a fast, specific "processing stalled" signal instead
// of a progress bar that silently stops moving forever.
extension ProgressMonitor {
    func ensureHeartbeatMonitorRunning(for item: DocumentItem) {
        guard heartbeatTasks[item.id] == nil else { return }

        let itemId = item.id
        let timeout = heartbeatTimeout
        let pollInterval = heartbeatPollInterval

        let task = Task { @MainActor [weak self] in
            while !Task.isCancelled {
                guard let self else { return }
                guard let currentItem = self.itemsProvider().first(where: { $0.id == itemId }) else {
                    self.heartbeatTasks.removeValue(forKey: itemId)
                    return
                }
                guard currentItem.status == .processing else {
                    // Reached a terminal state through the normal completion path (or was
                    // stopped/removed) -- nothing left for the watchdog to do.
                    self.heartbeatTasks.removeValue(forKey: itemId)
                    return
                }
                if let last = currentItem.lastHeartbeat {
                    let elapsed = Date().timeIntervalSince(last)
                    if elapsed >= timeout {
                        DebugLogger.shared.log(
                            "⏱️ Heartbeat watchdog: no progress signal for \(String(format: "%.0f", elapsed))s (>= \(String(format: "%.0f", timeout))s) on \(currentItem.url.lastPathComponent); marking stalled",
                            component: "HeartbeatWatchdog"
                        )
                        self.failStalledDocument(currentItem)
                        return
                    }
                }
                try? await Task.sleep(nanoseconds: UInt64(pollInterval * 1_000_000_000))
            }
        }
        heartbeatTasks[item.id] = task
    }

    /// Marks a document that has gone silent past `heartbeatTimeout` as failed with a
    /// user-facing "processing stalled" message, then hands it to the injected `failItem`
    /// callback, which invalidates its attempt token (see `DocumentRedactionViewModel
    /// .activeAttemptTokens`) so a late completion from the still-wedged underlying call can't
    /// resurrect it, and best-effort requests cancellation of the underlying run -- best-effort
    /// only, since PythonKit cannot forcibly reclaim a call already stuck in native code (see
    /// `PythonBridgeError`).
    func failStalledDocument(_ item: DocumentItem) {
        guard item.status == .processing else { return }
        item.status = .failed
        item.errorMessage = DocumentRedactionViewModel.processingStalledMessage
        DebugLogger.shared.log(
            "❌ Heartbeat watchdog marked \(item.url.lastPathComponent) failed (processing stalled)",
            component: "HeartbeatWatchdog"
        )
        failItem(item)
    }
}

// MARK: - Progress Mapping

extension ProgressMonitor {
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
            if item.isMassTrackingActive, stage == .enhancedDetection {
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
           let match = message.range(of: #"Processing chunk\s+(\d+)\s*/\s*(\d+)"#, options: .regularExpression)
        {
            let substring = message[match]
            let numbers = substring.replacingOccurrences(of: "Processing chunk", with: "")
            let parts = numbers.split(separator: "/").map { $0.trimmingCharacters(in: .whitespaces) }
            if parts.count == 2,
               let chunk = Int(parts[0]),
               let total = Int(parts[1]),
               total > 0
            {
                return (chunk, total)
            }
        }

        return nil
    }
}
