import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// App appearance theme preference
enum AppTheme: String, CaseIterable {
    case system = "system"
    case light = "light"
    case dark = "dark"

    var displayName: String {
        switch self {
        case .system: return "Follow System"
        case .light: return "Light"
        case .dark: return "Dark"
        }
    }

    var appearance: NSAppearance? {
        switch self {
        case .system: return nil
        case .light: return NSAppearance(named: .aqua)
        case .dark: return NSAppearance(named: .darkAqua)
        }
    }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

struct SettingsView: View {
    @ObservedObject var viewModel: DocumentRedactionViewModel
    @State private var localSettings: RedactionSettings
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme
    @State private var searchQuery = ""
    @State private var pendingManageModels = false
    @State private var pendingDownloadModel: String? = nil
    @State private var showingExcludedWordsEditor = false
    @State private var showingSystemPromptEditor = false
    @State private var showingMetadataEditor = false
    @State private var showingLogViewer = false
    @State private var metadataSettings = MetadataCleaningSettings.load()
    @State private var isCustomExcludedWords = UserOverridesManager.shared.hasCustomExcludedWords
    @State private var isCustomSystemPrompt = UserOverridesManager.shared.hasCustomSystemPrompt
    @State private var excludedWordsDraft = ""
    @State private var excludedWordsBaseline = ""
    @State private var systemPromptDraft = ""
    @State private var systemPromptBaseline = ""
    @State private var overrideErrorMessage: String?
    @State private var downloadsAccessError: String?
    @State private var profileErrorMessage: String?
    @State private var profileImportSucceeded = false
    @AppStorage(DefaultsKey.advancedModeEnabled.key) private var isAdvancedModeEnabled = true
    @AppStorage(DefaultsKey.advancedAIMode.key) private var advancedAIModeRaw = RedactionMode.rulesOverride.rawValue
    @AppStorage(DefaultsKey.advancedLLMConfidence.key) private var advancedLlmConfidence = RedactionSettings.standardNormalModeConfidence
    @AppStorage(DefaultsKey.outputSaveLocationPreference.key) private var outputSaveLocationRaw = OutputSaveLocation.alwaysAsk.rawValue
    @AppStorage(DefaultsKey.unsavedReportQuitBehavior.key) private var unsavedReportQuitBehaviorRaw = UnsavedReportQuitBehavior.warn.rawValue
    @AppStorage(DefaultsKey.appTheme.key) private var appThemeRaw = AppTheme.system.rawValue
    @ObservedObject private var permissionManager = PermissionManager.shared
    private let overridesManager = UserOverridesManager.shared

    private var outputSaveLocationBinding: Binding<OutputSaveLocation> {
        Binding(
            get: { OutputSaveLocation(rawValue: outputSaveLocationRaw) ?? .alwaysAsk },
            set: { outputSaveLocationRaw = $0.rawValue }
        )
    }

    private var unsavedReportQuitBehaviorBinding: Binding<UnsavedReportQuitBehavior> {
        Binding(
            get: { UnsavedReportQuitBehavior(rawValue: unsavedReportQuitBehaviorRaw) ?? .warn },
            set: { unsavedReportQuitBehaviorRaw = $0.rawValue }
        )
    }

    /// Identifies each top-level settings Section so search can gate its visibility (including header).
    private enum SettingsSection {
        case processingMode
        case sharedSettings
        case rulesEngine
        case aiModel
        case advancedAI
        case debug
    }

    /// Static, human-visible row labels for each section, used to decide whether a search
    /// query matches anything inside that section. Kept in sync with the Text labels rendered
    /// in the corresponding `*Section` view builder below.
    private static let sectionLabels: [SettingsSection: [String]] = [
        .processingMode: [
            "Processing Mode", "Rules Only", "Fast rule-based detection for structured PII.",
            "Rules + AI"
        ],
        .sharedSettings: [
            "Shared Settings", "System Notifications", "Enable Completion Banners",
            "Show banner when redaction finishes.", "Output Location",
            "Choose where redactions and reports are saved.", "Quit Warning",
            "Warn if unsaved reports would be deleted when quitting.", "Appearance",
            "Choose light, dark, or follow system appearance.", "Metadata Cleaning",
            "Remove hidden document properties during redaction.", "Configure Cleaning…",
            "Excluded Terms", "Phrases that should never be redacted.", "Customize…",
            "Edit Custom List…", "Reset to Defaults", "Settings Profile",
            "Share this configuration with your team as a JSON file, or load one someone else exported.",
            "Export Profile…", "Import Profile…", "Advanced Mode",
            "Show advanced AI controls and override modes."
        ],
        .rulesEngine: [
            "Rules Engine", "Select which deterministic rules run.", "Invert Selection"
        ],
        .aiModel: [
            "AI Model", "Select AI Model", "Qwen 3.5 35B A3B", "Qwen 2.5 14B", "Qwen 2.5 7B", "Phi-4 Mini 3.8B",
            "AI System Prompt", "Customize Prompt…", "Manage Models…", "Reveal Models…"
        ],
        .advancedAI: [
            "Advanced AI Settings", "Rules + AI Behavior", "Rules Override",
            "Constrained LLM Overrides", "LLM Overrides", "LLM Confidence", "Temperature",
            "Chunk Size", "Chunk Overlap", "Processing Timeout", "Random Seed"
        ],
        .debug: [
            "Debug", "Enable Debug Logging", "View Logs", "Open App Log", "Open Ollama Log", "Clear Logs"
        ]
    ]

    /// Pure, testable predicate: does `label` match `query`? Empty query always matches.
    /// Matching is a case-insensitive substring match.
    static func matchesSearch(_ label: String, query: String) -> Bool {
        let trimmedQuery = query.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmedQuery.isEmpty { return true }
        return label.range(of: trimmedQuery, options: [.caseInsensitive, .diacriticInsensitive]) != nil
    }

    /// Whether a whole section (including its header) should be shown given the current search query.
    private func isSectionVisible(_ section: SettingsSection) -> Bool {
        guard !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return true }
        if section == .rulesEngine {
            // Rules Engine has dynamic, per-rule rows in addition to its static labels.
            let ruleMatches = RedactionRule.allCases.contains { rule in
                Self.matchesSearch(rule.displayName, query: searchQuery)
            }
            if ruleMatches { return true }
        }
        let labels = Self.sectionLabels[section] ?? []
        return labels.contains { Self.matchesSearch($0, query: searchQuery) }
    }

    /// Whether an individual redaction rule row should be shown given the current search query.
    private func isRuleVisible(_ rule: RedactionRule) -> Bool {
        guard !searchQuery.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return true }
        // If the section header itself matches (e.g. "Rules Engine"), show all rows.
        let sectionLabels = Self.sectionLabels[.rulesEngine] ?? []
        if sectionLabels.contains(where: { Self.matchesSearch($0, query: searchQuery) }) { return true }
        return Self.matchesSearch(rule.displayName, query: searchQuery)
    }

    init(viewModel: DocumentRedactionViewModel) {
        self.viewModel = viewModel
        var initialSettings = viewModel.settings
        if viewModel.availableModels.count == 1, let onlyModel = viewModel.availableModels.first {
            initialSettings.model = onlyModel
        } else if !viewModel.availableModels.contains(initialSettings.model), let first = viewModel.availableModels.first {
            initialSettings.model = first
        }
        let defaults = UserDefaults.standard
        if defaults.object(forKey: DefaultsKey.advancedModeEnabled.key) == nil {
            defaults.set(viewModel.hasCompletedFirstRun, forKey: DefaultsKey.advancedModeEnabled.key)
        }
        if defaults.object(forKey: DefaultsKey.advancedAIMode.key) == nil {
            let seedMode = initialSettings.mode.usesLLM ? initialSettings.mode : .rulesOverride
            defaults.set(seedMode.rawValue, forKey: DefaultsKey.advancedAIMode.key)
        }
        if defaults.object(forKey: DefaultsKey.advancedLLMConfidence.key) == nil {
            defaults.set(initialSettings.llmConfidenceThreshold, forKey: DefaultsKey.advancedLLMConfidence.key)
        }
        if defaults.object(forKey: DefaultsKey.advancedLLMConfidenceMigratedTo99.key) == nil {
            if let storedConfidence = defaults.object(forKey: DefaultsKey.advancedLLMConfidence.key) as? NSNumber,
               storedConfidence.intValue == 95 {
                defaults.set(RedactionSettings.standardNormalModeConfidence, forKey: DefaultsKey.advancedLLMConfidence.key)
            }
            defaults.set(true, forKey: DefaultsKey.advancedLLMConfidenceMigratedTo99.key)
        }
        if defaults.object(forKey: DefaultsKey.outputSaveLocationPreference.key) == nil {
            if let legacy = defaults.object(forKey: DefaultsKey.legacyMetadataReportAlwaysSaveToDownloads.key) as? Bool {
                let mapped = legacy ? OutputSaveLocation.downloads.rawValue : OutputSaveLocation.alwaysAsk.rawValue
                defaults.set(mapped, forKey: DefaultsKey.outputSaveLocationPreference.key)
            } else {
                defaults.set(OutputSaveLocation.alwaysAsk.rawValue, forKey: DefaultsKey.outputSaveLocationPreference.key)
            }
        }
        if defaults.object(forKey: DefaultsKey.unsavedReportQuitBehavior.key) == nil {
            defaults.set(UnsavedReportQuitBehavior.warn.rawValue, forKey: DefaultsKey.unsavedReportQuitBehavior.key)
        }

        let advancedEnabled = defaults.bool(forKey: DefaultsKey.advancedModeEnabled.key)
        let storedModeRaw = defaults.string(forKey: DefaultsKey.advancedAIMode.key) ?? RedactionMode.rulesOverride.rawValue
        let storedMode = RedactionMode(rawValue: storedModeRaw) ?? .rulesOverride
        let normalizedMode = storedMode == .rules ? .rulesOverride : storedMode
        let storedConfidence = defaults.integer(forKey: DefaultsKey.advancedLLMConfidence.key)
        let resolvedConfidence = storedConfidence

        if advancedEnabled {
            if initialSettings.mode != .rules {
                initialSettings.mode = normalizedMode
            }
            initialSettings.llmConfidenceThreshold = resolvedConfidence
        } else {
            initialSettings.applyStandardNormalModeDefaults(keepingMode: initialSettings.mode == .rules)
        }

        self._localSettings = State(initialValue: initialSettings)
    }

    var body: some View {
        VStack(spacing: 24) {
            headerView

            NavigationStack {
                Form {
                    if isSectionVisible(.processingMode) {
                        processingModeSection
                    }
                    if isSectionVisible(.sharedSettings) {
                        sharedSettingsSection
                    }
                    if isSectionVisible(.rulesEngine) {
                        rulesEngineSection
                    }
                    if localSettings.mode.usesLLM && isSectionVisible(.aiModel) {
                        aiModelSection
                    }
                    if isAdvancedModeEnabled && isSectionVisible(.advancedAI) {
                        advancedAISection
                    }
                    if isSectionVisible(.debug) {
                        debugSection
                    }
                }
                .formStyle(.grouped)
                .searchable(text: $searchQuery, placement: .automatic, prompt: "Search settings")
            }

            Spacer()

            footerButtons
        }
        .padding(32)
        .frame(width: 600, height: 700)
        .background(CustomColors.cardBackground(for: colorScheme))
        .onDisappear {
            if pendingManageModels {
                pendingManageModels = false
                DispatchQueue.main.async {
                    viewModel.requestFirstRunSetup(entryPoint: .manageModels)
                }
            } else if let modelToDownload = pendingDownloadModel {
                pendingDownloadModel = nil
                DispatchQueue.main.async {
                    viewModel.requestFirstRunSetup(entryPoint: .downloadSpecificModel(modelToDownload))
                }
            }
        }
        .sheet(isPresented: $showingExcludedWordsEditor) {
            OverrideEditorSheet(
                title: "Edit Excluded Terms",
                description: "Terms listed here will never be redacted. Matching is case-insensitive, ignores leading determiners (the/a/an/etc.), and treats simple plurals as equivalent (trailing s, (s), or ies -> y). Regex patterns are supported (case-insensitive). In Rules Only and guardrailed Rules + AI modes (Rules Override, Constrained Overrides), ORG/NAME/LOC spans made up only of excluded words and connectors are skipped to prevent over-redaction of legal defined terms.\n\nOne term or regex per line. Comments starting with # are ignored.",
                text: $excludedWordsDraft,
                onCancel: { cancelExcludedWordsEditing() },
                onSave: { saveExcludedWords() },
                onRestoreDefaults: { restoreExcludedWordsDefaults() },
                showsMatchPreview: true
            )
        }
        .sheet(isPresented: $showingSystemPromptEditor) {
            OverrideEditorSheet(
                title: "Edit AI System Prompt",
                description: "Customize the instruction sent to the language model. Keep the guidance focused on redaction accuracy. Warning: LLM processing time is highly sensitive to prompt length.",
                text: $systemPromptDraft,
                onCancel: { cancelSystemPromptEditing() },
                onSave: { saveSystemPrompt() },
                onRestoreDefaults: { restoreSystemPromptDefaults() }
            )
        }
        .sheet(isPresented: $showingMetadataEditor) {
            MetadataCleaningSheet(settings: $metadataSettings)
        }
        .sheet(isPresented: $showingLogViewer) {
            LogViewerSheet()
        }
        .alert("Override Error", isPresented: overrideErrorBinding, presenting: overrideErrorMessage) { _ in
            Button("OK", role: .cancel) { }
                .accessibilityIdentifier("settings.overrideError.ok")
        } message: { message in
            Text(message)
        }
        .alert("Import Failed", isPresented: profileErrorBinding, presenting: profileErrorMessage) { _ in
            Button("OK", role: .cancel) { }
                .accessibilityIdentifier("settings.profile.importError.ok")
        } message: { message in
            Text(message)
        }
        .alert("Profile Imported", isPresented: $profileImportSucceeded) {
            Button("OK", role: .cancel) { }
                .accessibilityIdentifier("settings.profile.importSuccess.ok")
        } message: {
            Text("Settings were replaced with the imported profile. Click Save Settings to apply.")
        }
    }

    @ViewBuilder
    private var headerView: some View {
        VStack(spacing: 8) {
            Text("Redaction Settings")
                .font(.title2)
                .fontWeight(.semibold)
                .foregroundColor(CustomColors.primaryText(for: colorScheme))

            Text("Configure how documents are processed and redacted")
                .font(.body)
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                .multilineTextAlignment(.center)
        }
    }

    private var processingModeSection: some View {
        Section("Processing Mode") {
            VStack(alignment: .leading, spacing: 12) {
                HStack(alignment: .center, spacing: 12) {
                    Button {
                        selectRulesOnly()
                    } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: localSettings.mode == .rules ? "largecircle.fill.circle" : "circle")
                                .foregroundColor(CustomColors.primaryText(for: colorScheme))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Rules Only")
                                    .font(.system(size: 14, weight: .medium))
                                Text("Fast rule-based detection for structured PII.")
                                    .font(.system(size: 12))
                                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("settings.mode.rules_only")
                }

                HStack(alignment: .center, spacing: 12) {
                    Button {
                        selectRulesPlusAI()
                    } label: {
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: localSettings.mode == .rules ? "circle" : "largecircle.fill.circle")
                                .foregroundColor(CustomColors.primaryText(for: colorScheme))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("Rules + AI")
                                    .font(.system(size: 14, weight: .medium))
                                Text(rulesPlusAiDescription)
                                    .font(.system(size: 12))
                                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("settings.mode.rules_plus_ai")
                }
            }
            .accessibilityIdentifier("settings.mode")
        }
    }

    private var sharedSettingsSection: some View {
        Section("Shared Settings") {
            VStack(alignment: .leading, spacing: 12) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("System Notifications")
                            .font(.system(size: 14, weight: .medium))
                        Spacer()
                        switch PermissionManager.shared.notificationStatus {
                        case .authorized, .provisional:
                            EmptyView()
                        case .denied:
                            Image(systemName: "xmark.circle.fill")
                                .foregroundColor(.red)
                        default:
                            Button {
                                Task { try? await PermissionManager.shared.forceRequestNotificationPermission() }
                            } label: {
                                Image(systemName: "exclamationmark.circle.fill")
                                    .foregroundColor(.gray)
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier("settings.notifications.refresh")
                        }
                    }
                    .onAppear {
                        Task { await PermissionManager.shared.refreshNotificationStatus() }
                    }

                    Toggle(isOn: $permissionManager.userEnabledNotifications) {
                        VStack(alignment: .leading) {
                            Text("Enable Completion Banners")
                                .font(.system(size: 13))
                            Text("Show banner when redaction finishes.")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }
                    }
                    .onChange(of: permissionManager.userEnabledNotifications) { _, newValue in
                        if newValue {
                            Task {
                                try? await permissionManager.requestNotificationPermission()
                            }
                        }
                    }
                    .toggleStyle(.switch)
                    .accessibilityIdentifier("settings.notifications.toggle")

                    if PermissionManager.shared.notificationStatus == .denied {
                        Button("Open System Settings (Permission Denied)") {
                             if let url = URL(string: "x-apple.systempreferences:com.apple.preference.notifications") {
                                 NSWorkspace.shared.open(url)
                             }
                        }
                        .font(.caption)
                        .buttonStyle(.link)
                        .accessibilityIdentifier("settings.notifications.openSystemSettings")
                    } else if PermissionManager.shared.notificationStatus == .notDetermined && permissionManager.userEnabledNotifications {
                        Button("Authorize Notifications") {
                            Task { try? await PermissionManager.shared.forceRequestNotificationPermission() }
                        }
                        .font(.caption)
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("settings.notifications.authorize")
                    }
                }

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    Text("Output Location")
                        .font(.system(size: 14, weight: .medium))
                    Text("Choose where redactions and reports are saved.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                    HStack {
                        Picker("", selection: outputSaveLocationBinding) {
                            ForEach(OutputSaveLocation.allCases) { option in
                                Text(option.label).tag(option)
                            }
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        .frame(maxWidth: 360, alignment: .leading)
                        Spacer()
                    }
                    .onChange(of: outputSaveLocationRaw) { _, newValue in
                        let selection = OutputSaveLocation(rawValue: newValue) ?? .alwaysAsk
                        guard selection == .downloads else {
                            downloadsAccessError = nil
                            return
                        }
                        FileAccessCoordinator.shared.resetDownloadsAccessPromptState()
                        Task {
                            let granted = await FileAccessCoordinator.shared.requestDownloadsAccessForReports()
                            await MainActor.run {
                                if granted {
                                    downloadsAccessError = nil
                                } else {
                                    outputSaveLocationRaw = OutputSaveLocation.alwaysAsk.rawValue
                                    downloadsAccessError = "Downloads access not granted."
                                }
                            }
                        }
                    }
                    .accessibilityIdentifier("settings.outputLocation.segmented")

                    if let downloadsAccessError {
                        Text(downloadsAccessError)
                            .font(.system(size: 12))
                            .foregroundColor(CustomColors.destructiveColor(for: colorScheme))
                    }
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Quit Warning")
                        .font(.system(size: 14, weight: .medium))
                    Text("Warn if unsaved reports would be deleted when quitting.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                    HStack {
                        Picker("", selection: unsavedReportQuitBehaviorBinding) {
                            ForEach(UnsavedReportQuitBehavior.allCases) { option in
                                Text(option.label).tag(option)
                            }
                        }
                        .pickerStyle(.segmented)
                        .labelsHidden()
                        .frame(maxWidth: 360, alignment: .leading)
                        Spacer()
                    }
                    .accessibilityIdentifier("settings.quitWarning.segmented")
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text("Appearance")
                        .font(.system(size: 14, weight: .medium))
                    Text("Choose light, dark, or follow system appearance.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                    Picker("", selection: appThemeBinding) {
                        ForEach(AppTheme.allCases, id: \.self) { theme in
                            Text(theme.displayName).tag(theme)
                        }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .accessibilityIdentifier("settings.appearance.theme")
                }

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    Text("Metadata Cleaning")
                        .font(.system(size: 14, weight: .medium))
                    Text("Remove hidden document properties during redaction.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                    Button("Configure Cleaning…") {
                        showingMetadataEditor = true
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .accessibilityIdentifier("settings.metadata.configure")
                }

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("Excluded Terms")
                            .font(.system(size: 14, weight: .medium))
                        Spacer()
                        if isCustomExcludedWords {
                            Text("Custom List")
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.blue.opacity(0.1))
                                .foregroundColor(.blue)
                                .cornerRadius(4)
                        } else {
                            Text("Using Defaults")
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.gray.opacity(0.1))
                                .foregroundColor(.secondary)
                                .cornerRadius(4)
                        }
                    }

                    Text("Phrases that should never be redacted.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                    HStack {
                        Button(isCustomExcludedWords ? "Edit Custom List…" : "Customize…") {
                            openExcludedWordsEditor()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .accessibilityIdentifier("settings.excludedWords.edit")

                        if isCustomExcludedWords {
                            Button("Reset to Defaults") {
                                resetExcludedWordsToDefault()
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .accessibilityIdentifier("settings.excludedWords.reset")
                        }
                    }
                }

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    Text("Settings Profile")
                        .font(.system(size: 14, weight: .medium))
                    Text("Share this configuration with your team as a JSON file, or load one someone else exported.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                    HStack(spacing: 8) {
                        Button("Export Profile…") {
                            exportSettingsProfile()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .accessibilityIdentifier("settings.profile.export")

                        Button("Import Profile…") {
                            importSettingsProfile()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .accessibilityIdentifier("settings.profile.import")
                    }
                }

                Divider()

                VStack(alignment: .leading, spacing: 6) {
                    Toggle(isOn: $isAdvancedModeEnabled) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("Advanced Mode")
                                .font(.system(size: 14, weight: .medium))
                            Text("Show advanced AI controls and override modes. Normal mode is equivalent to Advanced Mode set to Rules Override at 99% confidence.")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }
                    }
                    .toggleStyle(.switch)
                    .accessibilityIdentifier("settings.mode.advanced")
                    .onChange(of: isAdvancedModeEnabled) { _, newValue in
                        applyAdvancedModeSelection(newValue)
                    }
                }
            }
        }
    }

    private var rulesEngineSection: some View {
        Section("Rules Engine") {
            VStack(alignment: .leading, spacing: 10) {
                Text("Select which deterministic rules run.")
                    .font(.system(size: 13))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                HStack {
                    Button("Invert Selection") {
                        invertRuleSelection()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .accessibilityIdentifier("settings.rules.invert")

                    Spacer()
                }

                ForEach(RedactionRule.allCases.sorted { $0.displayName < $1.displayName }.filter(isRuleVisible)) { rule in
                    Toggle(isOn: binding(for: rule)) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(rule.displayName)
                                .font(.system(size: 13, weight: .semibold))
                            Text(rule.description)
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }
                    }
                    .toggleStyle(.checkbox)
                    .accessibilityIdentifier("settings.rules.toggle.\(rule.rawValue)")
                }

            }
        }
    }

    private var aiModelSection: some View {
        Section("AI Model") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Select AI Model")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))

                ForEach(ModelCatalog.shared.models) { model in
                    ModelSelectionRow(
                        modelId: model.id,
                        displayName: model.displayName,
                        description: model.description,
                        processingTime: model.processingTime,
                        accentColor: model.resolvedAccentColor(for: colorScheme),
                        isSelected: localSettings.model == model.id,
                        isInstalled: viewModel.availableModels.contains(model.id),
                        accessibilityId: "settings.model.\(model.id)",
                        onDownload: {
                            pendingDownloadModel = model.id
                            dismiss()
                        }
                    ) {
                        localSettings.model = model.id
                    }
                    .padding(.horizontal, 12)
                }

                Text("Processing times are estimates for a 5,000 word document")
                    .font(.caption)
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                    .italic()

                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("AI System Prompt")
                            .font(.system(size: 13, weight: .medium))
                        Spacer()
                        if isCustomSystemPrompt {
                            Text("Custom")
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.blue.opacity(0.1))
                                .foregroundColor(.blue)
                                .cornerRadius(4)
                        } else {
                            Text("Using Defaults")
                                .font(.caption2)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.gray.opacity(0.1))
                                .foregroundColor(.secondary)
                                .cornerRadius(4)
                        }
                    }

                    HStack(spacing: 8) {
                        Button(isCustomSystemPrompt ? "Edit Custom Prompt…" : "Customize Prompt…") {
                            openSystemPromptEditor()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)
                        .accessibilityIdentifier("settings.systemPrompt.edit")

                        if isCustomSystemPrompt {
                            Button("Reset to Defaults") {
                                resetSystemPromptToDefault()
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                            .accessibilityIdentifier("settings.systemPrompt.reset")
                        }
                    }
                }
                .padding(.top, 4)

                Divider()
                    .padding(.vertical, 4)

                VStack(alignment: .leading, spacing: 6) {
                    Text("LLM Processing Concurrency")
                        .font(.system(size: 14, weight: .medium))
                    Text("Higher concurrency extracts entities faster but uses significantly more system Unified Memory.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                    HStack {
                        Slider(
                            value: Binding(
                                get: { Double(localSettings.llmConcurrency) },
                                set: { localSettings.llmConcurrency = Int($0) }
                            ),
                            in: 1...5,
                            step: 1
                        )
                        .accessibilityIdentifier("settings.llmConcurrency.slider")

                        Text("\(localSettings.llmConcurrency) worker\((localSettings.llmConcurrency > 1) ? "s" : "")")
                            .font(.system(size: 13, weight: .semibold))
                            .frame(width: 80, alignment: .trailing)
                    }
                }
                .padding(.top, 4)

                Divider()
                    .padding(.vertical, 4)

                HStack(spacing: 8) {
                    Button("Manage Models…") {
                        pendingManageModels = true
                        dismiss()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .accessibilityIdentifier("settings.models.manage")

                    Button("Reveal Models…") {
                        NSWorkspace.shared.open(viewModel.modelsDirectoryURL)
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                    .accessibilityIdentifier("settings.models.reveal")

                    Spacer()
                }
            }

            if viewModel.availableModels.isEmpty {
                HStack {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                    if viewModel.installedModelCount > 0 {
                        Text("No supported AI models installed. Click 'Manage Models…' to download one.")
                            .font(.caption)
                            .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                    } else {
                        Text("No AI models installed. Click 'Manage Models…' to download one.")
                            .font(.caption)
                            .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                    }
                }
            }
        }
    }

    private var timeoutSteps: [Int] {
        var steps: [Int] = [30, 60, 120]
        for m in 3...45 { steps.append(m * 60) }
        for i in 0..<30 { steps.append((50 + i * 5) * 60) }
        steps.append(Int.max)
        return steps
    }

    private var timeoutDisplay: String {
        let seconds = localSettings.processingTimeoutSeconds
        if seconds <= 0 || seconds == Int.max {
            return "∞ (No Limit)"
        }
        if seconds < 60 {
            return "\(seconds) sec"
        }
        return "\(seconds / 60) min"
    }

    private var timeoutSliderIndex: Binding<Double> {
        Binding(
            get: {
                let currentSeconds = localSettings.processingTimeoutSeconds
                if currentSeconds <= 0 || currentSeconds == Int.max {
                    return Double(timeoutSteps.count - 1)
                }
                if let idx = timeoutSteps.firstIndex(of: currentSeconds) {
                    return Double(idx)
                }
                let closest = timeoutSteps.enumerated().min(by: {
                    abs($0.element - currentSeconds) < abs($1.element - currentSeconds)
                })?.offset ?? 0
                return Double(closest)
            },
            set: { newValue in
                let idx = min(max(Int(newValue), 0), timeoutSteps.count - 1)
                localSettings.processingTimeoutSeconds = timeoutSteps[idx]
            }
        )
    }

    private var advancedAISection: some View {
        Section("Advanced AI Settings") {
            VStack(alignment: .leading, spacing: 8) {
                Text("Rules + AI Behavior")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                Text("Select how the LLM can override deterministic rules when Rules + AI is active.")
                    .font(.system(size: 12))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                ForEach(advancedAIModes, id: \.self) { mode in
                    HStack(alignment: .top, spacing: 12) {
                        Button {
                            selectAdvancedAIMode(mode)
                        } label: {
                            HStack(alignment: .top, spacing: 10) {
                                Image(systemName: advancedAIMode == mode ? "largecircle.fill.circle" : "circle")
                                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(advancedModeTitle(mode))
                                        .font(.system(size: 13, weight: .medium))
                                    Text(mode.description)
                                        .font(.system(size: 12))
                                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("settings.mode.ai.\(mode.rawValue)")

                        VStack(alignment: .trailing, spacing: 4) {
                            Text("LLM Confidence")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            HStack(spacing: 8) {
                                Text("\(advancedLlmConfidence)%")
                                    .font(.system(size: 12, weight: .medium))
                                    .frame(width: 44, alignment: .trailing)
                                Stepper(
                                    "",
                                    value: advancedConfidenceBinding,
                                    in: 0...100,
                                    step: 1
                                )
                                .labelsHidden()
                                .controlSize(.small)
                                .accessibilityIdentifier("settings.mode.ai.confidence.\(mode.rawValue)")
                            }
                        }
                        .disabled(advancedAIMode != mode)
                    }
                }

                Text("Confidence is the minimum certainty required to override a rules match. Higher = more likely to remain redacted. Confidence has no impact on system prompt based redaction (a separate pipeline).")
                    .font(.system(size: 10))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            Divider()

            VStack(alignment: .leading, spacing: 8) {
                Text("Temperature: \(localSettings.temperature, specifier: "%.1f")")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                Slider(value: $localSettings.temperature, in: 0.0...2.0, step: 0.1)
                    .accessibilityIdentifier("settings.ai.temperature")
                Text("Lower = more focused and deterministic. Higher = more creative but may hallucinate entities.")
                    .font(.system(size: 12))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Chunk Size: \(localSettings.chunkTokens) tokens")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                Slider(value: Binding(
                    get: { Double(localSettings.chunkTokens) },
                    set: { localSettings.chunkTokens = Int($0) }
                ), in: 500...2000, step: 100)
                .accessibilityIdentifier("settings.ai.chunkSize")
                Text("Larger = fewer chunks, faster overall but may miss entities in long sections. Smaller = more thorough but slower.")
                    .font(.system(size: 12))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Chunk Overlap: \(localSettings.overlap) tokens")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                Slider(value: Binding(
                    get: { Double(localSettings.overlap) },
                    set: { localSettings.overlap = Int($0) }
                ), in: 50...400, step: 25)
                .accessibilityIdentifier("settings.ai.chunkOverlap")
                Text("Higher = catches entities at chunk boundaries but increases processing time. Lower = faster but may miss split names.")
                    .font(.system(size: 12))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Processing Timeout: \(timeoutDisplay)")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))

                Slider(value: timeoutSliderIndex, in: 0...Double(timeoutSteps.count - 1), step: 1)
                    .accessibilityIdentifier("settings.ai.timeout")
                Text("Maximum time per document. Increase for very large documents. Use ∞ to disable timeout entirely.")
                    .font(.system(size: 12))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            VStack(alignment: .leading, spacing: 8) {
                Text("Random Seed: \(localSettings.seed)")
                    .font(.system(size: 14, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                Slider(value: Binding(
                    get: { Double(localSettings.seed) },
                    set: { localSettings.seed = Int($0) }
                ), in: 1...1000, step: 1)
                .accessibilityIdentifier("settings.ai.seed")
                Text("Fixed seed = reproducible results on same document. Change to get different AI outputs for testing.")
                    .font(.system(size: 12))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

        }
    }

    private var debugSection: some View {
        Section("Debug") {
            Toggle("Enable Debug Logging", isOn: $localSettings.debug)
                .toggleStyle(.checkbox)
                .accessibilityIdentifier("settings.debug.toggle")

            Text("When enabled, both the app and helper write verbose diagnostics to logs for troubleshooting. This may impact performance and generate large files.")
                .font(.system(size: 12))
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                .padding(.top, 4)

            HStack(spacing: 12) {
                Button("View Logs") {
                    DebugLogger.shared.ensureLogInitialized()
                    showingLogViewer = true
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .accessibilityIdentifier("settings.debug.viewLogs")

                Button("Open App Log") {
                    DebugLogger.shared.ensureLogInitialized()
                    let logURL = DebugLogger.shared.logURL
                    NSWorkspace.shared.open(logURL)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .accessibilityIdentifier("settings.debug.openAppLog")

                Button("Open Ollama Log") {
                    let logURL = viewModel.ollamaLogURL
                    NSWorkspace.shared.open(logURL)
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .accessibilityIdentifier("settings.debug.openOllamaLog")

                Button("Clear Logs") {
                    viewModel.clearLogs()
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .accessibilityIdentifier("settings.debug.clearLogs")

                Spacer()
            }
            .padding(.top, 8)
        }
    }

    private var footerButtons: some View {
        HStack(spacing: 12) {
            Button("Cancel") {
                dismiss()
            }
            .buttonStyle(.bordered)
            .controlSize(.large)
            .accessibilityIdentifier("settings.cancel")

            Button("Save Settings") {
                viewModel.updateSettings(localSettings)
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.large)
            .tint(CustomColors.accentColor(for: colorScheme))
            .accessibilityIdentifier("settings.save")
        }
    }

    private var overrideErrorBinding: Binding<Bool> {
        Binding(
            get: { overrideErrorMessage != nil },
            set: { if !$0 { overrideErrorMessage = nil } }
        )
    }

    private var profileErrorBinding: Binding<Bool> {
        Binding(
            get: { profileErrorMessage != nil },
            set: { if !$0 { profileErrorMessage = nil } }
        )
    }

    // MARK: - Settings Profile Export/Import

    private func exportSettingsProfile() {
        let profile = RedactionProfile(metadataCleaningSettings: metadataSettings, redactionSettings: localSettings)

        let data: Data
        do {
            data = try profile.encoded()
        } catch {
            profileErrorMessage = "Could not prepare the profile for export: \(error.localizedDescription)"
            return
        }

        let panel = NSSavePanel()
        panel.title = "Export Settings Profile"
        panel.nameFieldStringValue = "Marcut Settings Profile.json"
        panel.allowedContentTypes = [UTType.json]
        panel.canCreateDirectories = true
        panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first

        guard panel.runModal() == .OK, let destinationURL = panel.url else { return }

        let securityScopedURL = destinationURL.deletingLastPathComponent()
        let didStartAccess = securityScopedURL.startAccessingSecurityScopedResource()
        defer {
            if didStartAccess {
                securityScopedURL.stopAccessingSecurityScopedResource()
            }
        }

        do {
            try data.write(to: destinationURL, options: .atomic)
        } catch {
            profileErrorMessage = "Could not write the profile file: \(error.localizedDescription)"
        }
    }

    private func importSettingsProfile() {
        let panel = NSOpenPanel()
        panel.title = "Import Settings Profile"
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [UTType.json]
        panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first

        guard panel.runModal() == .OK, let sourceURL = panel.url else { return }

        let didStartAccess = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if didStartAccess {
                sourceURL.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let data = try Data(contentsOf: sourceURL)
            let profile = try RedactionProfile.decoded(from: data)
            // Replace current values wholesale — no merging with existing settings.
            localSettings = profile.redactionSettings
            metadataSettings = profile.metadataCleaningSettings
            metadataSettings.save()
            profileImportSucceeded = true
        } catch {
            profileErrorMessage = error.localizedDescription
        }
    }

    private var appThemeBinding: Binding<AppTheme> {
        Binding(
            get: { AppTheme(rawValue: appThemeRaw) ?? .system },
            set: { appThemeRaw = $0.rawValue }
        )
    }

    private var advancedAIMode: RedactionMode {
        let mode = RedactionMode(rawValue: advancedAIModeRaw) ?? .rulesOverride
        return mode == .rules ? .rulesOverride : mode
    }

    private var advancedAIModes: [RedactionMode] {
        [.rulesOverride, .constrainedOverrides, .llmOverrides]
    }

    private var rulesPlusAiDescription: String {
        if isAdvancedModeEnabled {
            return "AI extraction and validation. Behavior: \(advancedModeTitle(advancedAIMode))."
        }
        return "AI extraction with rules override at 99% confidence."
    }

    private var advancedConfidenceBinding: Binding<Int> {
        Binding(
            get: { advancedLlmConfidence },
            set: { newValue in
                advancedLlmConfidence = newValue
                if isAdvancedModeEnabled && localSettings.mode != .rules {
                    localSettings.llmConfidenceThreshold = newValue
                }
            }
        )
    }

    private func binding(for rule: RedactionRule) -> Binding<Bool> {
        Binding(
            get: { localSettings.enabledRules.contains(rule) },
            set: { isOn in
                if isOn {
                    localSettings.enabledRules.insert(rule)
                } else {
                    localSettings.enabledRules.remove(rule)
                }
            }
        )
    }

    private func invertRuleSelection() {
        let all = Set(RedactionRule.allCases)
        localSettings.enabledRules = all.subtracting(localSettings.enabledRules)
    }

    private func selectRulesOnly() {
        localSettings.mode = .rules
    }

    private func selectRulesPlusAI() {
        if isAdvancedModeEnabled {
            localSettings.mode = advancedAIMode
            localSettings.llmConfidenceThreshold = advancedLlmConfidence
        } else {
            localSettings.applyStandardNormalModeDefaults()
        }
    }

    private func applyAdvancedModeSelection(_ enabled: Bool) {
        if enabled {
            if localSettings.mode != .rules {
                localSettings.mode = advancedAIMode
            }
            localSettings.llmConfidenceThreshold = advancedLlmConfidence
        } else {
            localSettings.applyStandardNormalModeDefaults(keepingMode: localSettings.mode == .rules)
        }
    }

    private func selectAdvancedAIMode(_ mode: RedactionMode) {
        let normalized = mode == .rules ? .rulesOverride : mode
        advancedAIModeRaw = normalized.rawValue
        if isAdvancedModeEnabled && localSettings.mode != .rules {
            localSettings.mode = normalized
        }
    }

    private func advancedModeTitle(_ mode: RedactionMode) -> String {
        switch mode {
        case .rulesOverride:
            return "Rules Override"
        case .constrainedOverrides:
            return "Constrained LLM Overrides"
        case .llmOverrides:
            return "LLM Overrides"
        case .rules:
            return "Rules Only"
        }
    }

    private func openExcludedWordsEditor() {
        do {
            let text = try overridesManager.loadExcludedWords()
            excludedWordsBaseline = text
            excludedWordsDraft = text
            showingExcludedWordsEditor = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    private func openSystemPromptEditor() {
        do {
            let text = try overridesManager.loadSystemPrompt()
            systemPromptBaseline = text
            systemPromptDraft = text
            showingSystemPromptEditor = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    private func saveExcludedWords() {
        do {
            try overridesManager.saveExcludedWords(excludedWordsDraft)
            excludedWordsBaseline = excludedWordsDraft
            showingExcludedWordsEditor = false
            isCustomExcludedWords = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    private func resetExcludedWordsToDefault() {
        overridesManager.restoreDefaultExcludedWords()
        isCustomExcludedWords = false
    }

    private func cancelExcludedWordsEditing() {
        excludedWordsDraft = excludedWordsBaseline
        showingExcludedWordsEditor = false
    }

    private func restoreExcludedWordsDefaults() {
        do {
            excludedWordsDraft = try overridesManager.defaultExcludedWords()
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    private func saveSystemPrompt() {
        do {
            try overridesManager.saveSystemPrompt(systemPromptDraft)
            systemPromptBaseline = systemPromptDraft
            showingSystemPromptEditor = false
            isCustomSystemPrompt = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    private func resetSystemPromptToDefault() {
        overridesManager.restoreDefaultSystemPrompt()
        isCustomSystemPrompt = false
    }

    private func cancelSystemPromptEditing() {
        systemPromptDraft = systemPromptBaseline
        showingSystemPromptEditor = false
    }

    private func restoreSystemPromptDefaults() {
        systemPromptDraft = overridesManager.defaultSystemPromptText()
    }
}

private struct OverrideEditorSheet: View {
    let title: String
    let description: String
    @Binding var text: String
    let onCancel: () -> Void
    let onSave: () -> Void
    let onRestoreDefaults: () -> Void
    var showsMatchPreview: Bool = false
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title)
                .font(.title2)
                .fontWeight(.semibold)
                .foregroundColor(CustomColors.primaryText(for: colorScheme))

            Text(description)
                .font(.body)
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))

            ScrollableTextEditor(text: $text)
                .frame(minHeight: 300)
                .accessibilityIdentifier("settings.override.text")

            if showsMatchPreview {
                ExcludedWordMatchPreview(excludedWordsText: text)
            }

            HStack(spacing: 12) {
                Button("Cancel") {
                    onCancel()
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("settings.override.cancel")

                Button("Restore Defaults") {
                    onRestoreDefaults()
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("settings.override.restoreDefaults")

                Spacer()

                Button("Save Changes") {
                    onSave()
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("settings.override.save")
            }

            Spacer()
        }
        .padding(24)
        .frame(minWidth: 500, minHeight: 625)
    }
}

/// Live "does this phrase match an excluded-word entry" preview shown in the
/// excluded-words `OverrideEditorSheet`. Matches against the same rule the redaction
/// pipeline uses (`ExcludedWordMatcher`, ported from `marcut.rules._is_excluded`),
/// evaluated against the sheet's in-progress (possibly unsaved) text.
private struct ExcludedWordMatchPreview: View {
    let excludedWordsText: String

    @State private var testPhrase: String = ""
    @State private var debouncedPhrase: String = ""
    @State private var debounceTask: Task<Void, Never>?
    @Environment(\.colorScheme) private var colorScheme

    /// Small debounce so a fast typist doesn't recompile/match on every keystroke.
    private static let debounceNanoseconds: UInt64 = 150_000_000

    private var compiledEntries: [ExcludedWordMatcher.CompiledEntry] {
        ExcludedWordMatcher.compileAllEntries(editorText: excludedWordsText)
    }

    private var result: ExcludedWordMatcher.MatchResult? {
        guard !debouncedPhrase.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        return ExcludedWordMatcher.match(debouncedPhrase, entries: compiledEntries)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Test a Phrase")
                .font(.system(size: 13, weight: .medium))
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))

            HStack(spacing: 10) {
                TextField("Type a phrase to test against the terms above…", text: $testPhrase)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("settings.override.matchPreview.input")
                    .onChange(of: testPhrase) { _, newValue in
                        debounceTask?.cancel()
                        debounceTask = Task {
                            try? await Task.sleep(nanoseconds: Self.debounceNanoseconds)
                            guard !Task.isCancelled else { return }
                            await MainActor.run {
                                debouncedPhrase = newValue
                            }
                        }
                    }

                matchIndicator
                    .accessibilityIdentifier("settings.override.matchPreview.result")
            }
        }
        .onAppear {
            debouncedPhrase = testPhrase
        }
    }

    @ViewBuilder
    private var matchIndicator: some View {
        if let result {
            if result.matched {
                Label(
                    result.matchedEntry.map { "Matches: \($0)" } ?? "Matches",
                    systemImage: "checkmark.circle.fill"
                )
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.green)
                .lineLimit(1)
                .truncationMode(.tail)
            } else {
                Label("No match", systemImage: "xmark.circle")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }
        } else {
            Color.clear.frame(width: 1, height: 1)
        }
    }
}

private struct ScrollableTextEditor: NSViewRepresentable {
    @Binding var text: String

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = true
        scrollView.autohidesScrollers = false
        scrollView.drawsBackground = false
        scrollView.borderType = .bezelBorder

        let textView = NSTextView()
        textView.isRichText = false
        textView.isAutomaticQuoteSubstitutionEnabled = false
        textView.isAutomaticDashSubstitutionEnabled = false
        textView.font = NSFont.monospacedSystemFont(ofSize: NSFont.systemFontSize, weight: .regular)
        textView.backgroundColor = NSColor.textBackgroundColor
        textView.textColor = NSColor.labelColor
        textView.string = text
        textView.delegate = context.coordinator
        textView.isVerticallyResizable = true
        textView.isHorizontallyResizable = true
        textView.autoresizingMask = [.width]
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(width: scrollView.contentSize.width, height: .greatestFiniteMagnitude)

        scrollView.documentView = textView
        return scrollView
    }

    func updateNSView(_ nsView: NSScrollView, context: Context) {
        guard let textView = nsView.documentView as? NSTextView else { return }
        if textView.string != text {
            textView.string = text
        }
    }

    final class Coordinator: NSObject, NSTextViewDelegate {
        var parent: ScrollableTextEditor

        init(parent: ScrollableTextEditor) {
            self.parent = parent
        }

        func textDidChange(_ notification: Notification) {
            guard let textView = notification.object as? NSTextView else { return }
            parent.text = textView.string
        }
    }
}

struct FirstRunSetupView: View {
    @ObservedObject var viewModel: DocumentRedactionViewModel
    let onComplete: () -> Void

    @State private var selectedModel: String
    @State private var isDownloading = false
    @State private var downloadProgress: Double = 0.0
    @State private var setupStep: SetupStep = .welcome
    @State private var errorMessage: String?
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dismiss) private var dismissSheet
    private var hasInstalledSupportedModel: Bool {
        !viewModel.availableModels.isEmpty
    }

    enum SetupStep {
        case welcome
        case modelSelection
        case downloading
        case complete
    }

    @State private var autoStartDownload = false

    private var isManageFlow: Bool {
        viewModel.firstRunEntryPoint != .onboarding
    }

    init(viewModel: DocumentRedactionViewModel, onComplete: @escaping () -> Void) {
        self.viewModel = viewModel
        self.onComplete = onComplete

        var initialStep: SetupStep = .welcome
        // Default dynamically falls back to the normal recommendation.
        var resolvedModel = ModelCatalog.shared.defaultModelId
        var shouldAutoDownload = false

        switch viewModel.firstRunEntryPoint {
        case .manageModels:
            initialStep = .modelSelection
        case .downloadSpecificModel(let targetModelId):
            initialStep = .modelSelection
            resolvedModel = targetModelId
            shouldAutoDownload = true
        case .onboarding:
            initialStep = .welcome
        }

        if !shouldAutoDownload {
            let supportedModelIds = ModelCatalog.shared.modelIds
            let preferred = viewModel.availableModels.first ?? viewModel.settings.model
            resolvedModel = supportedModelIds.contains(preferred) ? preferred : ModelCatalog.shared.defaultModelId
        }

        _setupStep = State(initialValue: initialStep)
        _selectedModel = State(initialValue: resolvedModel)
        _autoStartDownload = State(initialValue: shouldAutoDownload)
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                // Header
                VStack(spacing: 12) {
                    Image(systemName: "scissors")
                        .font(.system(size: 48, weight: .light))
                        .foregroundColor(CustomColors.accentColor(for: colorScheme))

                    if setupStep != .downloading {
                        Text("Download a Model")
                            .font(.largeTitle)
                            .fontWeight(.bold)
                            .foregroundColor(CustomColors.primaryText(for: colorScheme))
                    }
                }

                // Content based on setup step
                Group {
                    switch setupStep {
                    case .welcome:
                        welcomeContent
                    case .modelSelection:
                        modelSelectionContent
                    case .downloading:
                        downloadingContent
                    case .complete:
                        completeContent
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)

                // Navigation buttons
                HStack(spacing: 16) {
                    if setupStep != .welcome && setupStep != .downloading && !(isManageFlow && setupStep == .modelSelection) {
                        Button("Back") {
                            withAnimation(.easeInOut(duration: 0.3)) {
                                setupStep = previousStep
                            }
                        }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("setup.back")
                    }

                    if setupStep != .downloading && !isManageFlow {
                        Button("Use Rules Only") {
                            completeRulesOnly()
                        }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("setup.rulesOnly")
                    }

                    Spacer()

                    if setupStep != .downloading {
                        Button(buttonTitle) {
                            handleNextButton()
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(CustomColors.accentColor(for: colorScheme))
                        .disabled(isDownloading)
                        .accessibilityIdentifier("setup.next")
                    }
                }
                .padding(.horizontal, 4) // Add slight internal padding to button row
            }
            .padding(.bottom, 60) // Reduced extra space for button safe area
        }
        .padding(.horizontal, 40) // Increased horizontal padding to prevent button cutoff
        .padding(.vertical, 40)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(CustomColors.cardBackground(for: colorScheme))
        .overlay(alignment: .topTrailing) {
            closeButton
                .padding(24)
        }
        .onAppear {
            if autoStartDownload {
                autoStartDownload = false
                downloadModel()
            } else if !isManageFlow && hasInstalledSupportedModel {
                // If a supported model already exists and we're not in the manage-models flow,
                // skip the download prompt and finish onboarding immediately.
                viewModel.markFirstRunComplete()
                onComplete()
            }
        }
    }

    private var closeButton: some View {
        let glyphColor: Color = colorScheme == .dark ? .white : .black
        let backgroundColor: Color = colorScheme == .dark ? Color.white.opacity(0.25) : Color.black.opacity(0.12)

        return Button(action: { closeSetup() }) {
            Image(systemName: "xmark")
                .font(.system(size: 18, weight: .semibold))
                .foregroundColor(glyphColor)
                .padding(8)
                .background(backgroundColor)
                .clipShape(Circle())
                .shadow(color: .black.opacity(0.25), radius: 2, y: 1)
        }
        .buttonStyle(.plain)
        .keyboardShortcut(.cancelAction)
        .focusable(false)
        .help("Close setup")
        .accessibilityIdentifier("setup.close")
    }

    @ViewBuilder
    private var welcomeContent: some View {
        VStack(spacing: 24) {
            VStack(spacing: 16) {
                Text("First-time setup")
                    .font(.title2)
                    .fontWeight(.semibold)

                Text("MarcutApp uses local AI models to identify and redact sensitive information in your documents. All processing happens on your device - no data ever leaves your computer.")
                    .font(.body)
                    .multilineTextAlignment(.center)
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            VStack(alignment: .leading, spacing: 12) {
                FeatureRow(
                    icon: "shield.fill",
                    title: "Privacy First",
                    description: "100% local processing with no internet connections during redaction"
                )

                FeatureRow(
                    icon: "brain.head.profile",
                    title: "AI-Powered",
                    description: "Advanced language models detect names, organizations, and contextual PII"
                )

                FeatureRow(
                    icon: "doc.text.magnifyingglass",
                    title: "Verified Output",
                    description: "Generates Microsoft Word documents with detailed audit reports"
                )
            }
        }
    }

    @ViewBuilder
    private var modelSelectionContent: some View {
        VStack(spacing: 24) {
            // Model selection cards

            // Model selection cards
            VStack(spacing: 12) {
                ForEach(ModelCatalog.shared.models) { model in
                    ModelSelectionRow(
                        modelId: model.id,
                        displayName: model.displayName,
                        description: model.setupDescription,
                        size: model.sizeLabel,
                        badge: model.badge,
                        isSelected: selectedModel == model.id,
                        isInstalled: viewModel.availableModels.contains(model.id),
                        accessibilityId: "setup.model.\(model.id)"
                    ) {
                        selectedModel = model.id
                    }
                    .padding(.horizontal, 12)
                }
            }
        }
    }

    @ViewBuilder
    private var downloadingContent: some View {
        VStack(spacing: 32) {
            VStack(spacing: 16) {
                Text("Downloading \(selectedModel)...")
                    .font(.title2)
                    .fontWeight(.semibold)
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
            }

            // Progress indicator
            VStack(spacing: 16) {
                ProgressView(value: downloadProgress)
                    .progressViewStyle(LinearProgressViewStyle())
                    .frame(maxWidth: 400)

                Text("\(Int(downloadProgress * 100))%")
                    .font(.body)
                    .fontWeight(.medium)
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                Text("Servers are slow — it’s normal for this download to take a long time.")
                    .font(.callout)
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: 420)
            }

            if let error = errorMessage {
                Text(error)
                    .foregroundColor(.red)
                    .font(.body)
                    .multilineTextAlignment(.center)
            }
        }
    }

    @ViewBuilder
    private var completeContent: some View {
        VStack(spacing: 24) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundColor(.green)

            VStack(spacing: 12) {
                Text("Setup Complete!")
                    .font(.title2)
                    .fontWeight(.semibold)

                Text("MarcutApp is ready to help you redact sensitive information from your documents.")
                    .font(.body)
                    .multilineTextAlignment(.center)
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }
        }
    }

    private var buttonTitle: String {
        switch setupStep {
        case .welcome: return "Get Started"
        case .modelSelection: return "Download Model"
        case .downloading: return "Downloading..."
        case .complete: return "Finish"
        }
    }

    private var previousStep: SetupStep {
        switch setupStep {
        case .welcome: return .welcome
        case .modelSelection: return .welcome
        case .downloading: return .modelSelection
        case .complete: return .downloading
        }
    }

    private func handleNextButton() {
        switch setupStep {
        case .welcome:
            withAnimation(.easeInOut(duration: 0.3)) {
                setupStep = .modelSelection
            }
        case .modelSelection:
            if viewModel.availableModels.contains(selectedModel) {
                viewModel.markFirstRunComplete()
                onComplete()
                return
            }
            downloadModel()
        case .downloading:
            // Button is disabled during download
            break
        case .complete:
            // Save that first-run setup has been completed
            viewModel.markFirstRunComplete()
            onComplete()
        }
    }

    private func closeSetup() {
        if isDownloading {
            cancelDownload()
        }
        if !isManageFlow {
            completeRulesOnly()
        } else {
            dismissSheet()
        }
    }

    private func completeRulesOnly() {
        var updated = viewModel.settings
        updated.mode = .rules
        viewModel.updateSettings(updated)
        viewModel.markFirstRunComplete()
        onComplete()
    }

    private func downloadModel() {
        isDownloading = true
        downloadProgress = 0.0
        errorMessage = nil

        withAnimation(.easeInOut(duration: 0.3)) {
            setupStep = .downloading
        }

        Task {
            let success = await viewModel.downloadModel(selectedModel) { progress in
                Task { @MainActor in
                    let normalized = max(0.0, min(progress / 100.0, 1.0))
                    downloadProgress = normalized
                }
            }

            await MainActor.run {
                isDownloading = false

                if success {
                    withAnimation(.easeInOut(duration: 0.3)) {
                        setupStep = .complete
                    }
                } else {
                    let fallback = "Failed to download model. Please check your internet connection and disk space, then try again."
                    errorMessage = viewModel.lastModelDownloadError ?? fallback
                }
            }
        }
    }

    private func cancelDownload() {
        // Cancel the download operation
        viewModel.cancelModelDownload()
        isDownloading = false
        errorMessage = nil
        withAnimation(.easeInOut(duration: 0.25)) {
            setupStep = .modelSelection
        }
    }
}

struct FeatureRow: View {
    let icon: String
    let title: String
    let description: String
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: icon)
                .font(.system(size: 24))
                .foregroundColor(CustomColors.accentColor(for: colorScheme))
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))

                Text(description)
                    .font(.system(size: 14))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            Spacer()
        }
    }
}

struct ModelSelectionRow: View {
    let modelId: String
    let displayName: String
    let description: String
    let size: String?
    let badge: String?
    let processingTime: String?
    let accentColor: Color?
    let isSelected: Bool
    let onSelect: () -> Void
    let isInstalled: Bool
    let accessibilityId: String?
    let onDownload: (() -> Void)?
    @Environment(\.colorScheme) private var colorScheme

    // Convenience initializers for different use cases
    init(modelId: String, displayName: String, description: String, processingTime: String, accentColor: Color, isSelected: Bool, isInstalled: Bool, accessibilityId: String? = nil, onDownload: (() -> Void)? = nil, onSelect: @escaping () -> Void) {
        self.modelId = modelId
        self.displayName = displayName
        self.description = description
        self.size = nil
        self.badge = nil
        self.processingTime = processingTime
        self.accentColor = accentColor
        self.isSelected = isSelected
        self.onSelect = onSelect
        self.isInstalled = isInstalled
        self.accessibilityId = accessibilityId
        self.onDownload = onDownload
    }

    init(modelId: String, displayName: String, description: String, size: String, badge: String, isSelected: Bool, isInstalled: Bool, accessibilityId: String? = nil, onDownload: (() -> Void)? = nil, onSelect: @escaping () -> Void) {
        self.modelId = modelId
        self.displayName = displayName
        self.description = description
        self.size = size
        self.badge = badge
        self.processingTime = nil
        self.accentColor = nil
        self.isSelected = isSelected
        self.onSelect = onSelect
        self.isInstalled = isInstalled
        self.accessibilityId = accessibilityId
        self.onDownload = onDownload
    }

    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 16) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 20))
                    .foregroundColor(isSelected ? (accentColor ?? CustomColors.accentColor(for: colorScheme)) : CustomColors.secondaryText(for: colorScheme))

                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(displayName)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(CustomColors.primaryText(for: colorScheme))

                        if let badge = badge {
                            Text(badge)
                                .font(.system(size: 11, weight: .medium))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 2)
                                .background(
                                    RoundedRectangle(cornerRadius: 10)
                                        .fill((accentColor ?? CustomColors.accentColor(for: colorScheme)).opacity(0.2))
                                )
                                .foregroundColor(accentColor ?? CustomColors.accentColor(for: colorScheme))
                        }

                        Spacer()
                    }

                    Text(description)
                        .font(.system(size: 14))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        .multilineTextAlignment(.leading)

                    HStack {
                        if let size = size {
                            Text(size)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }

                        if let processingTime = processingTime {
                            Text("• \(processingTime)")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }

                        Spacer()

                        let statusColor = isInstalled ? Color.green : Color.orange
                        Text(isInstalled ? "Installed" : "Download required")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(statusColor)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 4)
                            .background(
                                Capsule()
                                    .fill(statusColor.opacity(0.15))
                            )
                            .contentShape(Capsule())
                            .onTapGesture {
                                if !isInstalled {
                                    onDownload?()
                                }
                            }
                    }
                }
            }
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(isSelected ? (accentColor ?? CustomColors.accentColor(for: colorScheme)).opacity(0.12) : CustomColors.contentBackground(for: colorScheme))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(isSelected ? (accentColor ?? CustomColors.accentColor(for: colorScheme)) : Color.clear, lineWidth: 2)
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityId ?? "model.\(modelId)")
    }
}
