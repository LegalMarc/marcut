import Foundation

/// Pure, side-effect-light disk-space preflight helpers used before starting long-running,
/// disk-heavy operations (redaction output, model downloads) so a shortage of free space
/// surfaces immediately with an actionable message instead of partway through a multi-minute
/// run (or, for model downloads, only after `ollama pull` fails and its stderr happens to
/// mention the OS's own "no space" wording).
///
/// Kept decoupled from `DocumentRedactionViewModel` and `PythonBridgeService` -- both depend
/// on this, this depends on neither -- and every function accepts its data source as an
/// injectable parameter (defaulting to the real system source) so tests can simulate a full
/// disk without needing to actually fill one.
enum DiskSpaceCheck {
    /// Free space, in bytes, available at `url`'s volume for "important" usage (i.e. space the
    /// OS could still reclaim from purgeable/cache data is excluded, unlike the raw
    /// `volumeAvailableCapacity` figure). Returns `nil` if the volume doesn't support the query
    /// -- callers should treat `nil` as "unknown" and not block on it.
    static func availableBytes(at url: URL) -> Int64? {
        (try? url.resourceValues(forKeys: [.volumeAvailableCapacityForImportantUsageKey]))?
            .volumeAvailableCapacityForImportantUsage
    }

    /// Parses a human size label in the style used by `assets/models.json`'s `sizeLabel` field
    /// (e.g. `"9.0 GB"`, `"512 MB"`) into an estimated byte count. Returns `nil` if the label
    /// can't be parsed -- callers should treat that as "unknown" and not block on it.
    static func parseByteSize(_ label: String) -> Int64? {
        let cleaned = label.trimmingCharacters(in: .whitespaces)
        let pattern = #"(\d+\.?\d*)\s*([KMGT]B)"#
        guard let regex = try? NSRegularExpression(pattern: pattern, options: [.caseInsensitive]),
              let match = regex.firstMatch(in: cleaned, options: [], range: NSRange(cleaned.startIndex..., in: cleaned)),
              let valueRange = Range(match.range(at: 1), in: cleaned),
              let unitRange = Range(match.range(at: 2), in: cleaned),
              let value = Double(cleaned[valueRange]),
              value > 0 else {
            return nil
        }

        let multiplier: Double
        switch String(cleaned[unitRange]).uppercased() {
        case "KB": multiplier = 1024
        case "MB": multiplier = 1024 * 1024
        case "GB": multiplier = 1024 * 1024 * 1024
        case "TB": multiplier = 1024 * 1024 * 1024 * 1024
        default: return nil
        }

        return Int64(value * multiplier)
    }

    /// Human-readable "X.XX GB" formatting for error messages (binary GiB under the hood, but
    /// labeled "GB" to match the rest of the app's model-size labels).
    static func formatGB(_ bytes: Int64) -> String {
        String(format: "%.2f GB", Double(bytes) / 1_073_741_824.0)
    }

    /// Returns an actionable error message if `directory` doesn't (probably) have
    /// `estimatedBytesNeeded` free, or `nil` if the check passes -- including when either side
    /// of the comparison can't be determined, since we'd rather fail open on the space estimate
    /// than block a run over an estimate we're not confident in (the write-permission check
    /// callers pair this with is what actually guards correctness).
    static func insufficientSpaceMessage(
        estimatedBytesNeeded: Int64,
        directory: URL,
        subject: String,
        freeSpaceProvider: (URL) -> Int64? = DiskSpaceCheck.availableBytes
    ) -> String? {
        guard estimatedBytesNeeded > 0,
              let available = freeSpaceProvider(directory),
              available < estimatedBytesNeeded else {
            return nil
        }
        return "Not enough free disk space to \(subject) (needs ~\(formatGB(estimatedBytesNeeded)), "
            + "\(formatGB(available)) available) - please free up space or choose a different location"
    }
}
