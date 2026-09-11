import Foundation
@testable import MarcutApp
import XCTest

/// Golden bridge-call characterization harness for `DocumentRedactionViewModel` (issue #100,
/// `docs/design/view_controller_decomposition.md` §3 "Behavior-Parity Verification Plan").
///
/// This is the prerequisite gate for every extraction slice in that design doc's decomposition
/// (#103-#111): a committed, re-runnable snapshot of exactly what the view model hands to the
/// Python runner -- which runner method, with which arguments, with which `MARCUT_*`
/// environment variables set at the moment of the call -- and what item/flag state and
/// environment remain afterwards. Every slice must run
/// `swift test --package-path src/swift/MarcutApp --filter RedactionCharacterizationTests`
/// before and after its change and get zero golden diffs; a diff means the slice moved behavior,
/// not just code, and should block the PR.
///
/// ## What is snapshotted, per scenario
///
/// `{scenario, envBefore, events[], itemsAfter[], flagsAfter{}, envAfter}` -- see
/// `CharacterizationSnapshot` below for the exact shape. `events[]` comes from the single shared
/// `EventRecorder` that both the `RecordingRedactionRunner` (the seven `RedactionRunning`
/// members the view model calls) and the harness-installed `llmPreflightCheck`/
/// `modelReadinessCheck`/`sharePresenter` closures append to, in call order -- so the golden
/// content itself pins cross-seam ordering (e.g. "preflight before modelReadinessCheck before
/// the runner call"), not a comment asserting it.
///
/// Progress-derived item fields (`currentStage`, fractions, `lastHeartbeatChunk`) are
/// deliberately excluded: the detached progress consumer in `processDocumentWithPythonKit` races
/// the completion task, so pinning them here would be flaky. #101 pins those directly.
///
/// ## The environment allowlist
///
/// Exactly the nine `MARCUT_*` keys the view model itself sets or reads as a side effect:
/// `MARCUT_LOG_PATH`, `MARCUT_ADVANCED_MODE_ENABLED`, `MARCUT_ADVANCED_AI_MODE`,
/// `MARCUT_ADVANCED_CONFIDENCE`, `MARCUT_METADATA_ARGS`, `MARCUT_METADATA_PRESET`,
/// `MARCUT_METADATA_SETTINGS_JSON`, `MARCUT_SCRUB_REPORT_PATH`, `MARCUT_METADATA_ONLY`. Never
/// "all `MARCUT_*`" -- `PythonBridgeService.init` sets `MARCUT_OLLAMA_HOST`/`OLLAMA_HOST` to a
/// random free port, which would make every snapshot non-reproducible. Read via `getenv`/set via
/// `setenv`/`unsetenv` (matching how the view model itself touches them), never
/// `ProcessInfo.environment`, which does not reliably reflect environment mutations made after
/// process launch. `RedactionCharacterizationTests.setUpWithError`/`tearDownWithError`
/// `unsetenv` all nine before and after every test -- `setenv` leaks across tests sharing one
/// process.
///
/// ## The normalizer
///
/// Snapshots are built from raw values, canonically re-serialized (see
/// `CanonicalJSON.encode(_:)`), and the *entire* resulting JSON text is then normalized in one
/// pass rather than field-by-field, so nothing is missed:
/// - the scenario's temp directory -> `<TMP>`
/// - `NSHomeDirectory()` -> `<HOME>` (covers `MARCUT_LOG_PATH`, which is `DebugLogger.shared
///   .logPath`)
/// - the repo root (resolved the same way `sampleFileURL` in `MarcutAppTests.swift` does) ->
///   `<REPO>`
/// - the output-name timestamp label (`DateFormatter "M-d-yy hmma"` in `processDocument`,
///   `scrubDocumentMetadataOnly`, `generateMetadataReport`) via regex, keeping the label
///   (`redacted`/`metadata-scrubbed`/`metadata-report`) but collapsing the timestamp itself to
///   `<TS>`
///
/// A fresh `UserDefaults(suiteName: UUID().uuidString)` per scenario (with
/// `removePersistentDomain` on teardown) keeps preference state isolated and seeded explicitly
/// rather than touched via an injected clock -- see `RedactionCharacterizationHarness
/// .makeViewModel(defaults:)`.
///
/// ## Re-baselining
///
/// `MARCUT_GOLDEN_UPDATE=1 swift test --package-path src/swift/MarcutApp --filter
/// RedactionCharacterizationTests` regenerates every golden this run touches. A missing golden
/// fails with a "generate once, review the diff, commit" message, exactly like
/// `tests/docx_io_golden/harness.py` on the Python side (issue #70) -- this is the Swift
/// counterpart of that same pattern. Golden files are *not* copied into the test bundle via a
/// `resources:` target entry: `Bundle.module` copies into `.build`, so an update run there would
/// write to the build product rather than the source tree. They are resolved via `#filePath`
/// instead, exactly like `MarcutAppTests.sampleFileURL`.
enum RedactionCharacterizationHarness {
    /// The only `MARCUT_*` keys the view model itself sets or reads. See the type doc above.
    static let envAllowlist: [String] = [
        "MARCUT_LOG_PATH",
        "MARCUT_ADVANCED_MODE_ENABLED",
        "MARCUT_ADVANCED_AI_MODE",
        "MARCUT_ADVANCED_CONFIDENCE",
        "MARCUT_METADATA_ARGS",
        "MARCUT_METADATA_PRESET",
        "MARCUT_METADATA_SETTINGS_JSON",
        "MARCUT_SCRUB_REPORT_PATH",
        "MARCUT_METADATA_ONLY",
    ]

    static func currentEnvSnapshot() -> [String: String] {
        var result: [String: String] = [:]
        for key in envAllowlist {
            if let raw = getenv(key) {
                result[key] = String(cString: raw)
            }
        }
        return result
    }

    static func unsetAllowlistedEnv() {
        for key in envAllowlist {
            unsetenv(key)
        }
    }

    enum Fixture {
        case validDocx
        case corruptDocx
    }

    private static let repoRoot: URL = .init(fileURLWithPath: #filePath)
        .deletingLastPathComponent() // RedactionCharacterizationHarness.swift
        .deletingLastPathComponent() // MarcutAppTests
        .deletingLastPathComponent() // Tests
        .deletingLastPathComponent() // MarcutApp
        .deletingLastPathComponent() // swift
        .deletingLastPathComponent() // src

    static func fixturePath(_ fixture: Fixture) -> String {
        let name = fixture == .validDocx ? "Consent.docx" : "Consent Corrupt.docx"
        return repoRoot.appendingPathComponent("sample-files").appendingPathComponent(name).path
    }

    /// Builds a fresh, isolated `DocumentRedactionViewModel` for one scenario: a real
    /// (non-`.shared`) `PowerAssertionGuard` backed by no-op acquire/release so no real IOKit
    /// assertion is taken, and the caller-supplied `UserDefaults` suite.
    @MainActor
    static func makeViewModel(defaults: UserDefaults) -> DocumentRedactionViewModel {
        DocumentRedactionViewModel(
            powerAssertion: PowerAssertionGuard(acquire: { _ in 1 }, release: { _ in }),
            defaults: defaults
        )
    }

    /// A fresh, isolated `UserDefaults` suite for one scenario, seeded per the type doc above.
    /// Callers must call `removePersistentDomain` (via `tearDownDefaults`) when done.
    static func makeDefaults(hasCompletedFirstRun: Bool = true) -> UserDefaults {
        let suiteName = "com.marcut.characterization.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        defaults.set(OutputSaveLocation.alwaysAsk.rawValue, forKey: DefaultsKey.outputSaveLocationPreference.key)
        defaults.set(hasCompletedFirstRun, forKey: DefaultsKey.hasCompletedFirstRun.key)
        return defaults
    }
}

// MARK: - Snapshot shape

struct ItemSnapshot: Codable, Equatable {
    let name: String
    let status: String
    let errorMessage: String?
    let redactedOutputURL: String?
    let reportOutputURL: String?
    let reportHTMLOutputURL: String?
    let scrubOutputURL: String?
    let scrubReportOutputURL: String?
    let scrubReportHTMLOutputURL: String?
    let metadataReportOutputURL: String?
    let metadataReportHTMLOutputURL: String?
    let lastOperation: String?
    let lastDestinationURL: String?

    @MainActor
    init(_ item: DocumentItem) {
        name = item.url.lastPathComponent
        status = "\(item.status)"
        errorMessage = item.errorMessage
        redactedOutputURL = item.redactedOutputURL?.path
        reportOutputURL = item.reportOutputURL?.path
        reportHTMLOutputURL = item.reportHTMLOutputURL?.path
        scrubOutputURL = item.scrubOutputURL?.path
        scrubReportOutputURL = item.scrubReportOutputURL?.path
        scrubReportHTMLOutputURL = item.scrubReportHTMLOutputURL?.path
        metadataReportOutputURL = item.metadataReportOutputURL?.path
        metadataReportHTMLOutputURL = item.metadataReportHTMLOutputURL?.path
        lastOperation = item.lastOperation?.rawValue
        lastDestinationURL = item.lastDestinationURL?.path
    }
}

struct FlagsSnapshot: Codable, Equatable {
    let hasDocuments: Bool
    let hasValidDocuments: Bool
    let hasProcessingDocuments: Bool
    let hasCompletedDocuments: Bool
    let hasFinishedProcessing: Bool
    let hasFailedDocuments: Bool
    let reportErrorMessage: String?
    let metadataReportErrorMessage: String?
    let metadataReportNeedsPermissionRetry: Bool
    let batchETAIsNil: Bool

    @MainActor
    init(_ viewModel: DocumentRedactionViewModel) {
        hasDocuments = viewModel.hasDocuments
        hasValidDocuments = viewModel.hasValidDocuments
        hasProcessingDocuments = viewModel.hasProcessingDocuments
        hasCompletedDocuments = viewModel.hasCompletedDocuments
        hasFinishedProcessing = viewModel.hasFinishedProcessing
        hasFailedDocuments = viewModel.hasFailedDocuments
        reportErrorMessage = viewModel.reportErrorMessage
        metadataReportErrorMessage = viewModel.metadataReportErrorMessage
        metadataReportNeedsPermissionRetry = viewModel.metadataReportNeedsPermissionRetry
        batchETAIsNil = viewModel.batchETA == nil
    }
}

struct CharacterizationSnapshot: Codable, Equatable {
    let scenario: String
    let envBefore: [String: String]
    let events: [EventRecorder.Event]
    let itemsAfter: [ItemSnapshot]
    let flagsAfter: FlagsSnapshot
    let envAfter: [String: String]
}

// MARK: - Canonical JSON + normalization

enum CanonicalJSON {
    /// Encodes `value`, then re-serializes through `JSONSerialization` with `[.prettyPrinted,
    /// .sortedKeys]` for stable, diffable 2-space-indented output (mirrors
    /// `tests/docx_io_golden/harness.py`'s `json.dump(..., indent=2, sort_keys=True)` on the
    /// Python side), then appends a trailing newline.
    ///
    /// `JSONSerialization` escapes every `/` as `\/` (a legal but purely cosmetic JSON escape);
    /// left in place, that would stop `Normalizer`'s plain-substring path replacements from ever
    /// matching (every path in this snapshot contains `/`). Un-escaping is safe -- `/` needs no
    /// escaping in JSON -- and is done here, once, rather than taught to every normalizer rule.
    static func encode(_ value: some Encodable) throws -> String {
        let data = try JSONEncoder().encode(value)
        let object = try JSONSerialization.jsonObject(with: data, options: [.fragmentsAllowed])
        let prettyData = try JSONSerialization.data(
            withJSONObject: object,
            options: [.prettyPrinted, .sortedKeys]
        )
        guard let text = String(data: prettyData, encoding: .utf8) else {
            throw NSError(domain: "RedactionCharacterizationHarness", code: 1)
        }
        return text.replacingOccurrences(of: "\\/", with: "/") + "\n"
    }
}

enum Normalizer {
    private static let timestampLabelRegex = try! NSRegularExpression(
        pattern: #"\((redacted|metadata-scrubbed|metadata-report) \d{1,2}-\d{1,2}-\d{2} \S+\)"#
    )

    /// Applied to the *entire* canonical JSON text in one pass (see the harness type doc's
    /// "normalizer" section for why) rather than field-by-field.
    static func normalize(_ text: String, tempDir: URL) -> String {
        var result = text
        result = result.replacingOccurrences(of: tempDir.path, with: "<TMP>")
        result = result.replacingOccurrences(of: NSHomeDirectory(), with: "<HOME>")
        result = result.replacingOccurrences(of: RedactionCharacterizationHarness.repoRootPath, with: "<REPO>")
        let range = NSRange(result.startIndex ..< result.endIndex, in: result)
        result = timestampLabelRegex.stringByReplacingMatches(
            in: result,
            options: [],
            range: range,
            withTemplate: "($1 <TS>)"
        )
        return result
    }
}

extension RedactionCharacterizationHarness {
    static var repoRootPath: String {
        repoRoot.path
    }
}

// MARK: - Golden file I/O

enum GoldenStore {
    private static var goldenDir: URL {
        URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent() // RedactionCharacterizationHarness.swift
            .appendingPathComponent("Golden")
    }

    private static func path(for name: String) -> URL {
        goldenDir.appendingPathComponent("\(name).json")
    }

    static func assertMatchesGolden(
        name: String,
        snapshot: CharacterizationSnapshot,
        tempDir: URL,
        file: StaticString = #filePath,
        line: UInt = #line
    ) throws {
        let canonical = try CanonicalJSON.encode(snapshot)
        let normalized = Normalizer.normalize(canonical, tempDir: tempDir)

        if ProcessInfo.processInfo.environment["MARCUT_GOLDEN_UPDATE"] == "1" {
            try FileManager.default.createDirectory(at: goldenDir, withIntermediateDirectories: true)
            try normalized.write(to: path(for: name), atomically: true, encoding: .utf8)
            return
        }

        let goldenURL = path(for: name)
        guard FileManager.default.fileExists(atPath: goldenURL.path) else {
            XCTFail(
                """
                No golden snapshot at \(goldenURL.path). Generate it once with \
                MARCUT_GOLDEN_UPDATE=1 swift test --package-path src/swift/MarcutApp \
                --filter RedactionCharacterizationTests, review the diff, then commit it.
                """,
                file: file,
                line: line
            )
            return
        }
        let expected = try String(contentsOf: goldenURL, encoding: .utf8)
        XCTAssertEqual(
            normalized,
            expected,
            """
            Golden snapshot mismatch for '\(name)'. DocumentRedactionViewModel's bridge-call \
            behavior changed. If this is an intentional, reviewed change, regenerate with \
            MARCUT_GOLDEN_UPDATE=1 (see RedactionCharacterizationHarness.swift); otherwise this \
            is exactly the regression this harness exists to catch.
            """,
            file: file,
            line: line
        )
    }
}
