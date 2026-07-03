import Foundation

/// A JSON-serializable snapshot of a batch run's still-pending/in-progress documents, persisted so
/// the app can offer to resume them after a crash or quit mid-batch. Document-list-level resume
/// only: a document that was mid-processing when the app quit goes back to `.pending`, not to
/// whatever partial state it was in (see issue #19 "Out of scope").
struct PendingBatchJobRecord: Codable, Equatable {
    /// Bump this whenever the on-disk shape changes in a way older/newer clients can't safely
    /// round-trip. Decoding a record with an unrecognized version is treated the same as a
    /// malformed record: discarded without crashing (see `PendingBatchJobStore.load`).
    static let currentSchemaVersion = 1

    var schemaVersion: Int
    /// Absolute file paths for documents that were `.pending` (queued) or still mid-processing
    /// when the record was saved. Mid-processing documents resume as `.pending`, not wherever
    /// they left off.
    var documentPaths: [String]
    /// The redaction settings that were active for the run being persisted, so Resume can restore
    /// the same configuration the user had selected.
    var settings: RedactionSettings
    var savedAt: Date

    init(documentPaths: [String], settings: RedactionSettings, savedAt: Date = Date()) {
        self.schemaVersion = Self.currentSchemaVersion
        self.documentPaths = documentPaths
        self.settings = settings
        self.savedAt = savedAt
    }
}

/// Persists and restores `PendingBatchJobRecord`s in `UserDefaults`, namespaced like the rest of
/// the app's app-state keys (see `MarcutApp.AdvancedModeEnabled` and friends).
enum PendingBatchJobStore {
    static let defaultsKey = "MarcutApp.PendingBatchJobRecord"

    /// Persists `record`, or clears any existing record when `record` is `nil`.
    static func save(_ record: PendingBatchJobRecord?, defaults: UserDefaults = .standard) {
        guard let record else {
            clear(defaults: defaults)
            return
        }
        guard let data = try? JSONEncoder().encode(record) else {
            DebugLogger.shared.log(
                "Failed to encode pending batch job record — leaving previous record untouched",
                component: "PendingBatchJobStore"
            )
            return
        }
        defaults.set(data, forKey: defaultsKey)
    }

    /// Loads the persisted record, if any. Malformed or schema-incompatible data is discarded
    /// (and a warning logged) rather than crashing or partially applying — matches the "Resuming
    /// across different app versions with incompatible settings schemas" note in issue #19.
    static func load(defaults: UserDefaults = .standard) -> PendingBatchJobRecord? {
        guard let data = defaults.data(forKey: defaultsKey) else { return nil }

        guard let record = try? JSONDecoder().decode(PendingBatchJobRecord.self, from: data) else {
            DebugLogger.shared.log(
                "Discarding unreadable pending batch job record (malformed JSON)",
                component: "PendingBatchJobStore"
            )
            clear(defaults: defaults)
            return nil
        }

        guard record.schemaVersion == PendingBatchJobRecord.currentSchemaVersion else {
            DebugLogger.shared.log(
                "Discarding pending batch job record with unsupported schema version \(record.schemaVersion)",
                component: "PendingBatchJobStore"
            )
            clear(defaults: defaults)
            return nil
        }

        guard !record.documentPaths.isEmpty else {
            clear(defaults: defaults)
            return nil
        }

        return record
    }

    static func clear(defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: defaultsKey)
    }
}
