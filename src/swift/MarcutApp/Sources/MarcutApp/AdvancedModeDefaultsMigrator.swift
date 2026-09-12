import Foundation

/// Unifies the two independent UserDefaults seeding/migration blocks that used to live
/// separately in `SettingsView.init` and `DocumentRedactionViewModel
/// .applyAdvancedModeDefaultsIfNeeded()` (`docs/design/view_controller_decomposition.md` §2.2,
/// §3.2 item 5, §4 slice 5). Both call sites now call `apply(...)` so there is exactly one
/// definition of this logic.
///
/// Characterized by the UserDefaults migration matrix in
/// `Tests/MarcutAppTests/AdvancedModeDefaultsMigrationTests.swift` (#102) before this
/// unification landed; that matrix must keep passing byte-for-byte identical, which pins two
/// intentional drift points: only `SettingsView.init` seeds `outputSaveLocationPreference`
/// (with the legacy `legacyMetadataReportAlwaysSaveToDownloads` mapping) and
/// `unsavedReportQuitBehavior`. Per the issue #106 decision, those two keys stay
/// `SettingsView.init`-only rather than moving into the view model's launch-time seeding --
/// `seedSettingsViewOnlyKeys` gates them so `DocumentRedactionViewModel` keeps passing `false`
/// and `SettingsView` keeps passing `true`.
enum AdvancedModeDefaultsMigrator {
    /// Seeds any of the shared advanced-mode `DefaultsKey` values that are still unset, runs the
    /// one-time 95->99 LLM-confidence migration, and resolves `settings.mode`/
    /// `settings.llmConfidenceThreshold` from the (now-seeded) defaults exactly as both prior
    /// call sites did.
    ///
    /// - Parameters:
    ///   - defaults: The `UserDefaults` suite to read from and seed.
    ///   - hasCompletedFirstRun: Seeds `advancedModeEnabled` when it is unset.
    ///   - settings: The settings snapshot to seed `advancedAIMode`/`advancedLLMConfidence` from
    ///     (when those keys are unset) and to resolve the final `mode`/`llmConfidenceThreshold`
    ///     onto.
    ///   - seedSettingsViewOnlyKeys: When `true`, also seeds `outputSaveLocationPreference`
    ///     (mapping the legacy `legacyMetadataReportAlwaysSaveToDownloads` boolean when present)
    ///     and `unsavedReportQuitBehavior` -- the two keys only `SettingsView.init` seeds today.
    static func apply(
        defaults: UserDefaults,
        hasCompletedFirstRun: Bool,
        settings: inout RedactionSettings,
        seedSettingsViewOnlyKeys: Bool
    ) {
        if defaults.object(forKey: DefaultsKey.advancedModeEnabled.key) == nil {
            defaults.set(hasCompletedFirstRun, forKey: DefaultsKey.advancedModeEnabled.key)
        }
        if defaults.object(forKey: DefaultsKey.advancedAIMode.key) == nil {
            let seedMode = settings.mode.usesLLM ? settings.mode : .rulesOverride
            defaults.set(seedMode.rawValue, forKey: DefaultsKey.advancedAIMode.key)
        }
        if defaults.object(forKey: DefaultsKey.advancedLLMConfidence.key) == nil {
            defaults.set(settings.llmConfidenceThreshold, forKey: DefaultsKey.advancedLLMConfidence.key)
        }
        if defaults.object(forKey: DefaultsKey.advancedLLMConfidenceMigratedTo99.key) == nil {
            if let storedConfidence = defaults.object(forKey: DefaultsKey.advancedLLMConfidence.key) as? NSNumber,
               storedConfidence.intValue == 95
            {
                defaults.set(
                    RedactionSettings.standardNormalModeConfidence,
                    forKey: DefaultsKey.advancedLLMConfidence.key
                )
            }
            defaults.set(true, forKey: DefaultsKey.advancedLLMConfidenceMigratedTo99.key)
        }

        if seedSettingsViewOnlyKeys {
            if defaults.object(forKey: DefaultsKey.outputSaveLocationPreference.key) == nil {
                if let legacy = defaults
                    .object(forKey: DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key) as? Bool
                {
                    let mapped = legacy ? OutputSaveLocation.downloads.rawValue : OutputSaveLocation.alwaysAsk
                        .rawValue
                    defaults.set(mapped, forKey: DefaultsKey.outputSaveLocationPreference.key)
                } else {
                    defaults.set(
                        OutputSaveLocation.alwaysAsk.rawValue,
                        forKey: DefaultsKey.outputSaveLocationPreference.key
                    )
                }
            }
            if defaults.object(forKey: DefaultsKey.unsavedReportQuitBehavior.key) == nil {
                defaults.set(
                    UnsavedReportQuitBehavior.warn.rawValue,
                    forKey: DefaultsKey.unsavedReportQuitBehavior.key
                )
            }
        }

        let advancedEnabled = defaults.bool(forKey: DefaultsKey.advancedModeEnabled.key)
        let storedModeRaw = defaults.string(forKey: DefaultsKey.advancedAIMode.key) ?? RedactionMode.rulesOverride
            .rawValue
        let storedMode = RedactionMode(rawValue: storedModeRaw) ?? .rulesOverride
        let normalizedMode = storedMode == .rules ? .rulesOverride : storedMode
        let storedConfidence = defaults.integer(forKey: DefaultsKey.advancedLLMConfidence.key)
        let resolvedConfidence = storedConfidence

        if advancedEnabled {
            if settings.mode != .rules {
                settings.mode = normalizedMode
            }
            settings.llmConfidenceThreshold = resolvedConfidence
        } else {
            settings.applyStandardNormalModeDefaults(keepingMode: settings.mode == .rules)
        }
    }
}
