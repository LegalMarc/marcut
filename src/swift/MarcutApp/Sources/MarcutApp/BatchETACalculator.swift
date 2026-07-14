import Foundation

/// A single completed-document sample used to estimate batch processing throughput.
///
/// `size` is a relative work signal — `DocumentRedactionViewModel.documentSizeSignal(for:)`
/// prefers a document's extracted word count (a much better proxy for rules/LLM processing
/// cost than raw file bytes, since a DOCX's compressed byte size can vary independently of
/// its actual text content) and falls back to file byte size when word count isn't available.
/// Either way it's not an absolute unit that needs to match any particular scale, since only
/// the ratio of size to duration (rate) and the ratio of remaining size to that rate (ETA)
/// are ever computed.
struct BatchETASample {
    let duration: TimeInterval
    let size: Int64
}

/// Pure, side-effect-free batch ETA estimation used by `DocumentRedactionViewModel` to show
/// a rough "time remaining" figure during a multi-document redaction run.
///
/// This is intentionally a simple moving-average-rate model — not a sophisticated predictor —
/// per the ticket scope: rate = total observed size / total observed duration across all
/// documents completed so far *in this run*, then ETA = remaining size / rate.
enum BatchETACalculator {
    /// Minimum number of completed-document samples required before an estimate is produced.
    /// Below this, there isn't enough data to infer a meaningful rate.
    static let minimumSamples = 2

    /// Estimates remaining time for a batch run.
    ///
    /// - Parameters:
    ///   - samples: (duration, size) pairs for documents that have already completed in this
    ///     run, in any order.
    ///   - remainingSizes: size signal for each document still queued/in-flight.
    /// - Returns: An estimated `TimeInterval` remaining, or `nil` when there isn't enough data
    ///   (fewer than `minimumSamples` samples), the observed rate is degenerate (zero/invalid),
    ///   or there is no remaining work.
    static func estimate(samples: [BatchETASample], remainingSizes: [Int64]) -> TimeInterval? {
        guard samples.count >= minimumSamples else { return nil }

        let totalDuration = samples.reduce(0.0) { $0 + max($1.duration, 0.0) }
        let totalSize = samples.reduce(Int64(0)) { $0 + max($1.size, 0) }

        guard totalDuration > 0, totalSize > 0 else { return nil }

        let rate = Double(totalSize) / totalDuration // size units per second
        guard rate.isFinite, rate > 0 else { return nil }

        let remainingTotal = remainingSizes.reduce(Int64(0)) { $0 + max($1, 0) }
        guard remainingTotal > 0 else { return 0 }

        let eta = Double(remainingTotal) / rate
        guard eta.isFinite else { return nil }
        return eta
    }
}
