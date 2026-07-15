import Foundation

/// Centralized, typed source of truth for every `UserDefaults` / `@AppStorage` key used by
/// the app. Every raw value here must stay byte-identical to the string it replaces — these
/// are on-disk keys, and changing one silently resets that setting for existing users.
///
/// Add new keys here rather than hardcoding string literals at call sites.
enum DefaultsKey: String {
    /// Whether Advanced Mode (manual AI mode / confidence overrides) is enabled.
    case advancedModeEnabled = "MarcutApp.AdvancedModeEnabled"
    /// The user's selected `RedactionMode` while Advanced Mode is enabled.
    case advancedAIMode = "MarcutApp.AdvancedAIMode"
    /// The user's selected LLM confidence threshold while Advanced Mode is enabled.
    case advancedLLMConfidence = "MarcutApp.AdvancedLLMConfidence"
    /// One-time migration marker for the confidence-threshold default change to 99.
    case advancedLLMConfidenceMigratedTo99 = "MarcutApp.AdvancedLLMConfidenceMigratedTo99"
    /// Where redacted output and reports should be saved (`OutputSaveLocation` raw value).
    case outputSaveLocationPreference = "MarcutApp.OutputSaveLocationPreference"
    /// Legacy pre-migration flag: metadata reports always saved to Downloads.
    case legacyMetadataReportAlwaysSaveToDownloads = "MarcutApp.MetadataReportAlwaysSaveToDownloads"
    /// Behavior when quitting with unsaved report files present (`UnsavedReportQuitBehavior` raw value).
    case unsavedReportQuitBehavior = "MarcutApp.UnsavedReportQuitBehavior"
    /// The user's selected `AppTheme` raw value.
    case appTheme = "AppTheme"
    /// Whether the user has completed the first-run onboarding flow.
    case hasCompletedFirstRun = "MarcutApp.hasCompletedFirstRun"
    /// Whether the user has ever used metadata scrubbing.
    case hasUsedMetadataScrub = "MarcutApp.hasUsedMetadataScrub"
    /// The last explicitly chosen output directory path.
    case lastExplicitOutputDirectoryPath = "MarcutApp.LastExplicitOutputDirectoryPath"
    /// Whether the user has enabled system notifications (in-app preference).
    case userEnabledNotifications = "MarcutApp_UserEnabledNotifications"
    /// Encoded `MetadataCleaningSettings` payload.
    case metadataCleaningSettings = "MetadataCleaningSettings"

    /// Convenience for call sites that need the raw string (e.g. `@AppStorage`, `defaults.object(forKey:)`).
    var key: String {
        rawValue
    }
}
