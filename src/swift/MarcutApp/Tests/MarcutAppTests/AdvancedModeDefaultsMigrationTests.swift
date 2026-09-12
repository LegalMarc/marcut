@testable import MarcutApp
import XCTest

/// Pins today's (pre-unification) behavior of the two independent UserDefaults
/// seeding/migration blocks -- `SettingsView.init` and
/// `DocumentRedactionViewModel.applyAdvancedModeDefaultsIfNeeded()` -- across a matrix of
/// plausible on-disk start states and every call order the real app can produce, so slice #106
/// can unify them with proof neither call site's written state silently changes.
///
/// `docs/design/view_controller_decomposition.md` §2.2 and §3.2 item 5. Tests only -- this file
/// makes no production behavior change (see issue #102's "Out of scope"); the two intentional
/// drift points (`outputSaveLocationPreference`/`unsavedReportQuitBehavior` seeded only by
/// `SettingsView.init`) are pinned as-is, not resolved.
@MainActor
final class AdvancedModeDefaultsMigrationTests: XCTestCase {
    // MARK: - Isolated defaults

    /// A fresh, empty `UserDefaults` suite -- never `.standard` -- so tests never read or leave
    /// behind real preference state.
    private func makeIsolatedDefaults() -> UserDefaults {
        let suiteName = "com.marclaw.marcutapp.tests.advancedModeDefaultsMigration.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defaults.removePersistentDomain(forName: suiteName)
        return defaults
    }

    /// `defaults.dictionaryRepresentation()` filtered to only the keys `DefaultsKey` knows
    /// about, per the acceptance criteria ("assert the suite's `dictionaryRepresentation()`
    /// filtered to `DefaultsKey` keys"). Values are cast to `AnyHashable` so the result is
    /// `Equatable` for a single `XCTAssertEqual` per matrix cell; every value either block
    /// writes (`Bool`, `Int`, `String`) bridges cleanly.
    /// A `SettingsOverridesController` backed by a fresh, throwaway `UserOverridesManager`
    /// instance pointed at a temp directory -- never `.shared` -- so constructing `SettingsView`
    /// below never touches the real, shared `~/Library/Application Support/MarcutApp/Overrides`
    /// directory or its synchronous `.write_test` probe write.
    private func makeIsolatedOverridesController() -> SettingsOverridesController {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let overridesManager = UserOverridesManager(overridesDirectoryOverride: tempDir)
        return SettingsOverridesController(overridesManager: overridesManager)
    }

    private func filteredDefaultsDump(_ defaults: UserDefaults) -> [String: AnyHashable] {
        var dump: [String: AnyHashable] = [:]
        for (key, value) in defaults.dictionaryRepresentation() {
            guard DefaultsKey(rawValue: key) != nil else { continue }
            guard let hashable = value as? AnyHashable else {
                XCTFail("Unexpected non-hashable value for DefaultsKey \(key): \(value)")
                continue
            }
            dump[key] = hashable
        }
        return dump
    }

    // MARK: - Start states

    /// The eight start states named in issue #102, each seeded onto a fresh, isolated suite.
    private enum StartState: CustomStringConvertible {
        case empty
        case legacyDownloadsTrue
        case legacyDownloadsFalse
        case fullyMigrated
        case confidence95MigrationFlagAbsent
        case confidence95MigrationFlagPresent
        case advancedModeDisabledFirstRunTrue
        case advancedModeDisabledFirstRunFalse

        var description: String {
            switch self {
            case .empty: "empty"
            case .legacyDownloadsTrue: "legacyDownloadsTrue"
            case .legacyDownloadsFalse: "legacyDownloadsFalse"
            case .fullyMigrated: "fullyMigrated"
            case .confidence95MigrationFlagAbsent: "confidence95MigrationFlagAbsent"
            case .confidence95MigrationFlagPresent: "confidence95MigrationFlagPresent"
            case .advancedModeDisabledFirstRunTrue: "advancedModeDisabledFirstRunTrue"
            case .advancedModeDisabledFirstRunFalse: "advancedModeDisabledFirstRunFalse"
            }
        }

        func seed(_ defaults: UserDefaults) {
            switch self {
            case .empty:
                break
            case .legacyDownloadsTrue:
                defaults.set(true, forKey: DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key)
            case .legacyDownloadsFalse:
                defaults.set(false, forKey: DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key)
            case .fullyMigrated:
                defaults.set(true, forKey: DefaultsKey.advancedModeEnabled.key)
                defaults.set(RedactionMode.llmOverrides.rawValue, forKey: DefaultsKey.advancedAIMode.key)
                defaults.set(
                    RedactionSettings.standardNormalModeConfidence,
                    forKey: DefaultsKey.advancedLLMConfidence.key
                )
                defaults.set(true, forKey: DefaultsKey.advancedLLMConfidenceMigratedTo99.key)
                defaults.set(
                    OutputSaveLocation.sameAsOriginal.rawValue,
                    forKey: DefaultsKey.outputSaveLocationPreference.key
                )
                defaults.set(
                    UnsavedReportQuitBehavior.alwaysQuit.rawValue,
                    forKey: DefaultsKey.unsavedReportQuitBehavior.key
                )
            case .confidence95MigrationFlagAbsent:
                defaults.set(95, forKey: DefaultsKey.advancedLLMConfidence.key)
            case .confidence95MigrationFlagPresent:
                defaults.set(95, forKey: DefaultsKey.advancedLLMConfidence.key)
                defaults.set(true, forKey: DefaultsKey.advancedLLMConfidenceMigratedTo99.key)
            case .advancedModeDisabledFirstRunTrue:
                defaults.set(false, forKey: DefaultsKey.advancedModeEnabled.key)
                defaults.set(true, forKey: DefaultsKey.hasCompletedFirstRun.key)
            case .advancedModeDisabledFirstRunFalse:
                defaults.set(false, forKey: DefaultsKey.advancedModeEnabled.key)
                defaults.set(false, forKey: DefaultsKey.hasCompletedFirstRun.key)
            }
        }
    }

    // MARK: - Call-order harnesses

    /// A resolved matrix cell: the migrated suite's filtered dump, plus the resulting
    /// `settings.mode`/`llmConfidenceThreshold` the acceptance criteria call for.
    private struct Cell {
        let dump: [String: AnyHashable]
        let mode: RedactionMode
        let llmConfidenceThreshold: Int
    }

    /// "View-model init only": constructs `DocumentRedactionViewModel(defaults:)` against the
    /// seeded suite. `applyAdvancedModeDefaultsIfNeeded()` runs once, automatically, as part of
    /// the view model's own `init` (`DocumentRedactionViewModel.swift:234`).
    private func runViewModelInitOnly(_ state: StartState) -> Cell {
        let defaults = makeIsolatedDefaults()
        state.seed(defaults)
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        return Cell(
            dump: filteredDefaultsDump(defaults),
            mode: viewModel.settings.mode,
            llmConfidenceThreshold: viewModel.settings.llmConfidenceThreshold
        )
    }

    /// "SettingsView.init only": constructs `SettingsView(viewModel:defaults:)` against the
    /// seeded suite. `SettingsView.init` needs a live view model (for `viewModel.settings`,
    /// `.availableModels`, `.hasCompletedFirstRun`), but that view model's own constructor
    /// unconditionally runs `applyAdvancedModeDefaultsIfNeeded()` as a side effect
    /// (`DocumentRedactionViewModel.swift:234`) -- there is no way to construct one without
    /// triggering it. To isolate "SettingsView.init only" from that side effect, the view model
    /// here is backed by a *second*, identically-seeded suite rather than the suite under test,
    /// so its migration writes land there instead of contaminating the measured suite. In
    /// production both are the same `.standard` instance; this only matters for the one guarded
    /// read (`viewModel.hasCompletedFirstRun`) that seeds `advancedModeEnabled` when absent, and
    /// seeding both suites identically keeps that read's value consistent with the scenario.
    ///
    /// `viewModel.availableModels` is empty here (`PythonBridgeService.shared` finds no
    /// installed models under `swift test`), which only affects `initialSettings.model` --
    /// untouched by these assertions (see `docs/design/view_controller_decomposition.md`,
    /// issue #102 Notes).
    private func runSettingsViewInitOnly(_ state: StartState) -> Cell {
        let defaults = makeIsolatedDefaults()
        state.seed(defaults)

        let viewModelDefaults = makeIsolatedDefaults()
        state.seed(viewModelDefaults)
        let viewModel = DocumentRedactionViewModel(defaults: viewModelDefaults)

        let settingsView = SettingsView(
            viewModel: viewModel,
            defaults: defaults,
            overridesController: makeIsolatedOverridesController()
        )
        let localSettings = settingsView.initialLocalSettingsForTesting
        return Cell(
            dump: filteredDefaultsDump(defaults),
            mode: localSettings.mode,
            llmConfidenceThreshold: localSettings.llmConfidenceThreshold
        )
    }

    /// "View-model init, then SettingsView.init" -- the app's actual startup order
    /// (`MarcutApp.swift`/`ContentView.swift` construct the view model first, then present
    /// `SettingsView(viewModel:)` later, both against the same `.standard` suite).
    private func runViewModelThenSettingsView(_ state: StartState) -> Cell {
        let defaults = makeIsolatedDefaults()
        state.seed(defaults)
        let viewModel = DocumentRedactionViewModel(defaults: defaults)
        let settingsView = SettingsView(
            viewModel: viewModel,
            defaults: defaults,
            overridesController: makeIsolatedOverridesController()
        )
        let localSettings = settingsView.initialLocalSettingsForTesting
        return Cell(
            dump: filteredDefaultsDump(defaults),
            mode: localSettings.mode,
            llmConfidenceThreshold: localSettings.llmConfidenceThreshold
        )
    }

    private func assertCell(
        _ cell: Cell,
        dump expectedDump: [String: AnyHashable],
        mode expectedMode: RedactionMode,
        confidence expectedConfidence: Int,
        _ label: String,
        file: StaticString = #filePath,
        line: UInt = #line
    ) {
        XCTAssertEqual(cell.dump, expectedDump, "\(label): filtered defaults dump mismatch", file: file, line: line)
        XCTAssertEqual(cell.mode, expectedMode, "\(label): resolved settings.mode mismatch", file: file, line: line)
        XCTAssertEqual(
            cell.llmConfidenceThreshold,
            expectedConfidence,
            "\(label): resolved llmConfidenceThreshold mismatch",
            file: file,
            line: line
        )
    }

    // MARK: - Matrix: start state x call order

    func testEmptyStartState() {
        assertCell(
            runViewModelInitOnly(.empty),
            dump: [
                DefaultsKey.advancedModeEnabled.key: false,
                DefaultsKey.advancedAIMode.key: "rules_override",
                DefaultsKey.advancedLLMConfidence.key: 99,
                DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            ],
            mode: .rulesOverride,
            confidence: 99,
            "empty / view-model init only"
        )
        let expectedAfterSettingsView: [String: AnyHashable] = [
            DefaultsKey.advancedModeEnabled.key: false,
            DefaultsKey.advancedAIMode.key: "rules_override",
            DefaultsKey.advancedLLMConfidence.key: 99,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.alwaysAsk.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.warn.rawValue,
        ]
        assertCell(
            runSettingsViewInitOnly(.empty),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "empty / SettingsView init only"
        )
        assertCell(
            runViewModelThenSettingsView(.empty),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "empty / view-model then SettingsView"
        )
    }

    func testLegacyDownloadsTrueStartState() {
        assertCell(
            runViewModelInitOnly(.legacyDownloadsTrue),
            dump: [
                DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key: true,
                DefaultsKey.advancedModeEnabled.key: false,
                DefaultsKey.advancedAIMode.key: "rules_override",
                DefaultsKey.advancedLLMConfidence.key: 99,
                DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            ],
            mode: .rulesOverride,
            confidence: 99,
            "legacyDownloadsTrue / view-model init only -- the legacy key is never consulted here"
        )
        let expectedAfterSettingsView: [String: AnyHashable] = [
            DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key: true,
            DefaultsKey.advancedModeEnabled.key: false,
            DefaultsKey.advancedAIMode.key: "rules_override",
            DefaultsKey.advancedLLMConfidence.key: 99,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.downloads.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.warn.rawValue,
        ]
        assertCell(
            runSettingsViewInitOnly(.legacyDownloadsTrue),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "legacyDownloadsTrue / SettingsView init only -- legacy true maps to .downloads"
        )
        assertCell(
            runViewModelThenSettingsView(.legacyDownloadsTrue),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "legacyDownloadsTrue / view-model then SettingsView"
        )
    }

    func testLegacyDownloadsFalseStartState() {
        assertCell(
            runViewModelInitOnly(.legacyDownloadsFalse),
            dump: [
                DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key: false,
                DefaultsKey.advancedModeEnabled.key: false,
                DefaultsKey.advancedAIMode.key: "rules_override",
                DefaultsKey.advancedLLMConfidence.key: 99,
                DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            ],
            mode: .rulesOverride,
            confidence: 99,
            "legacyDownloadsFalse / view-model init only -- the legacy key is never consulted here"
        )
        let expectedAfterSettingsView: [String: AnyHashable] = [
            DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key: false,
            DefaultsKey.advancedModeEnabled.key: false,
            DefaultsKey.advancedAIMode.key: "rules_override",
            DefaultsKey.advancedLLMConfidence.key: 99,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.alwaysAsk.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.warn.rawValue,
        ]
        assertCell(
            runSettingsViewInitOnly(.legacyDownloadsFalse),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "legacyDownloadsFalse / SettingsView init only -- legacy false maps to .alwaysAsk"
        )
        assertCell(
            runViewModelThenSettingsView(.legacyDownloadsFalse),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "legacyDownloadsFalse / view-model then SettingsView"
        )
    }

    func testFullyMigratedStartState() {
        let seeded: [String: AnyHashable] = [
            DefaultsKey.advancedModeEnabled.key: true,
            DefaultsKey.advancedAIMode.key: RedactionMode.llmOverrides.rawValue,
            DefaultsKey.advancedLLMConfidence.key: RedactionSettings.standardNormalModeConfidence,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.sameAsOriginal.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.alwaysQuit.rawValue,
        ]
        // Every key both blocks would seed is already present, so neither block writes
        // anything -- the dump is identical, byte-for-byte, to what was seeded, in every order.
        assertCell(
            runViewModelInitOnly(.fullyMigrated),
            dump: seeded,
            mode: .llmOverrides,
            confidence: 99,
            "fullyMigrated / view-model init only -- fully seeded state is left untouched"
        )
        assertCell(
            runSettingsViewInitOnly(.fullyMigrated),
            dump: seeded,
            mode: .llmOverrides,
            confidence: 99,
            "fullyMigrated / SettingsView init only -- fully seeded state is left untouched"
        )
        assertCell(
            runViewModelThenSettingsView(.fullyMigrated),
            dump: seeded,
            mode: .llmOverrides,
            confidence: 99,
            "fullyMigrated / view-model then SettingsView -- fully seeded state is left untouched"
        )
    }

    /// The one-time 95->99 confidence migration fires -- flipping the *stored* value to 99 --
    /// whenever the migration flag is absent, regardless of call order.
    func testConfidence95MigrationFlagAbsentStartState() {
        assertCell(
            runViewModelInitOnly(.confidence95MigrationFlagAbsent),
            dump: [
                DefaultsKey.advancedModeEnabled.key: false,
                DefaultsKey.advancedAIMode.key: "rules_override",
                DefaultsKey.advancedLLMConfidence.key: 99,
                DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            ],
            mode: .rulesOverride,
            confidence: 99,
            "confidence95MigrationFlagAbsent / view-model init only -- 95 migrates to 99"
        )
        let expectedAfterSettingsView: [String: AnyHashable] = [
            DefaultsKey.advancedModeEnabled.key: false,
            DefaultsKey.advancedAIMode.key: "rules_override",
            DefaultsKey.advancedLLMConfidence.key: 99,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.alwaysAsk.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.warn.rawValue,
        ]
        assertCell(
            runSettingsViewInitOnly(.confidence95MigrationFlagAbsent),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "confidence95MigrationFlagAbsent / SettingsView init only -- 95 migrates to 99"
        )
        assertCell(
            runViewModelThenSettingsView(.confidence95MigrationFlagAbsent),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "confidence95MigrationFlagAbsent / view-model then SettingsView -- 95 migrates to 99"
        )
    }

    /// Once the migration flag is already present, a stored 95 is *never* revisited -- it stays
    /// 95 in the defaults dump forever, even though the resolved `settings` still end up on the
    /// standard-mode default of 99 via the "advanced mode disabled" branch. This is the
    /// characterization the flag exists to protect: pin it before any unification touches it.
    func testConfidence95MigrationFlagPresentStartState() {
        assertCell(
            runViewModelInitOnly(.confidence95MigrationFlagPresent),
            dump: [
                DefaultsKey.advancedModeEnabled.key: false,
                DefaultsKey.advancedAIMode.key: "rules_override",
                DefaultsKey.advancedLLMConfidence.key: 95,
                DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            ],
            mode: .rulesOverride,
            confidence: 99,
            "confidence95MigrationFlagPresent / view-model init only -- stored 95 is never revisited"
        )
        let expectedAfterSettingsView: [String: AnyHashable] = [
            DefaultsKey.advancedModeEnabled.key: false,
            DefaultsKey.advancedAIMode.key: "rules_override",
            DefaultsKey.advancedLLMConfidence.key: 95,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.alwaysAsk.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.warn.rawValue,
        ]
        assertCell(
            runSettingsViewInitOnly(.confidence95MigrationFlagPresent),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "confidence95MigrationFlagPresent / SettingsView init only -- stored 95 is never revisited"
        )
        assertCell(
            runViewModelThenSettingsView(.confidence95MigrationFlagPresent),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "confidence95MigrationFlagPresent / view-model then SettingsView -- stored 95 is never revisited"
        )
    }

    /// When `advancedModeEnabled` is already present (here, `false`), neither block reads
    /// `hasCompletedFirstRun` at all -- the seeded value survives untouched and the outcome is
    /// identical whether it was `true` or `false` (paired with the test below).
    func testAdvancedModeDisabledFirstRunTrueStartState() {
        assertCell(
            runViewModelInitOnly(.advancedModeDisabledFirstRunTrue),
            dump: [
                DefaultsKey.advancedModeEnabled.key: false,
                DefaultsKey.hasCompletedFirstRun.key: true,
                DefaultsKey.advancedAIMode.key: "rules_override",
                DefaultsKey.advancedLLMConfidence.key: 99,
                DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            ],
            mode: .rulesOverride,
            confidence: 99,
            "advancedModeDisabledFirstRunTrue / view-model init only"
        )
        let expectedAfterSettingsView: [String: AnyHashable] = [
            DefaultsKey.advancedModeEnabled.key: false,
            DefaultsKey.hasCompletedFirstRun.key: true,
            DefaultsKey.advancedAIMode.key: "rules_override",
            DefaultsKey.advancedLLMConfidence.key: 99,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.alwaysAsk.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.warn.rawValue,
        ]
        assertCell(
            runSettingsViewInitOnly(.advancedModeDisabledFirstRunTrue),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "advancedModeDisabledFirstRunTrue / SettingsView init only"
        )
        assertCell(
            runViewModelThenSettingsView(.advancedModeDisabledFirstRunTrue),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "advancedModeDisabledFirstRunTrue / view-model then SettingsView"
        )
    }

    /// Companion to the test above: `hasCompletedFirstRun == false` produces the exact same
    /// outcome, proving neither block reads it once `advancedModeEnabled` is already set.
    func testAdvancedModeDisabledFirstRunFalseStartState() {
        assertCell(
            runViewModelInitOnly(.advancedModeDisabledFirstRunFalse),
            dump: [
                DefaultsKey.advancedModeEnabled.key: false,
                DefaultsKey.hasCompletedFirstRun.key: false,
                DefaultsKey.advancedAIMode.key: "rules_override",
                DefaultsKey.advancedLLMConfidence.key: 99,
                DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            ],
            mode: .rulesOverride,
            confidence: 99,
            "advancedModeDisabledFirstRunFalse / view-model init only"
        )
        let expectedAfterSettingsView: [String: AnyHashable] = [
            DefaultsKey.advancedModeEnabled.key: false,
            DefaultsKey.hasCompletedFirstRun.key: false,
            DefaultsKey.advancedAIMode.key: "rules_override",
            DefaultsKey.advancedLLMConfidence.key: 99,
            DefaultsKey.advancedLLMConfidenceMigratedTo99.key: true,
            DefaultsKey.outputSaveLocationPreference.key: OutputSaveLocation.alwaysAsk.rawValue,
            DefaultsKey.unsavedReportQuitBehavior.key: UnsavedReportQuitBehavior.warn.rawValue,
        ]
        assertCell(
            runSettingsViewInitOnly(.advancedModeDisabledFirstRunFalse),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "advancedModeDisabledFirstRunFalse / SettingsView init only"
        )
        assertCell(
            runViewModelThenSettingsView(.advancedModeDisabledFirstRunFalse),
            dump: expectedAfterSettingsView,
            mode: .rulesOverride,
            confidence: 99,
            "advancedModeDisabledFirstRunFalse / view-model then SettingsView"
        )
    }

    // MARK: - Named drift-point tests

    /// Drift point 1 (`docs/design/view_controller_decomposition.md` §2.2): only
    /// `SettingsView.init` seeds `outputSaveLocationPreference` (with the legacy-key mapping).
    /// `applyAdvancedModeDefaultsIfNeeded()` never touches it, on any start state -- pinned here
    /// on `.empty` as the simplest witness. Unifying the two blocks (#106) must decide, on the
    /// record, whether the unified migrator keeps seeding this key.
    func testDriftOutputSaveLocationPreferenceIsSeededOnlyBySettingsViewInit() {
        let viewModelOnly = runViewModelInitOnly(.empty)
        XCTAssertNil(
            viewModelOnly.dump[DefaultsKey.outputSaveLocationPreference.key],
            "applyAdvancedModeDefaultsIfNeeded() must not seed outputSaveLocationPreference today"
        )

        let settingsViewOnly = runSettingsViewInitOnly(.empty)
        XCTAssertEqual(
            settingsViewOnly.dump[DefaultsKey.outputSaveLocationPreference.key],
            OutputSaveLocation.alwaysAsk.rawValue,
            "SettingsView.init must seed outputSaveLocationPreference today"
        )
    }

    /// Drift point 2 (`docs/design/view_controller_decomposition.md` §2.2): only
    /// `SettingsView.init` seeds `unsavedReportQuitBehavior`.
    /// `applyAdvancedModeDefaultsIfNeeded()` never touches it, on any start state -- pinned here
    /// on `.empty` as the simplest witness. Unifying the two blocks (#106) must decide, on the
    /// record, whether the unified migrator keeps seeding this key.
    func testDriftUnsavedReportQuitBehaviorIsSeededOnlyBySettingsViewInit() {
        let viewModelOnly = runViewModelInitOnly(.empty)
        XCTAssertNil(
            viewModelOnly.dump[DefaultsKey.unsavedReportQuitBehavior.key],
            "applyAdvancedModeDefaultsIfNeeded() must not seed unsavedReportQuitBehavior today"
        )

        let settingsViewOnly = runSettingsViewInitOnly(.empty)
        XCTAssertEqual(
            settingsViewOnly.dump[DefaultsKey.unsavedReportQuitBehavior.key],
            UnsavedReportQuitBehavior.warn.rawValue,
            "SettingsView.init must seed unsavedReportQuitBehavior today"
        )
    }
}
