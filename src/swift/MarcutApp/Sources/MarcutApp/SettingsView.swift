import SwiftUI
import AppKit

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
}

struct SettingsView: View {
    @ObservedObject var viewModel: DocumentRedactionViewModel
    @State private var localSettings: RedactionSettings
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme
    @State private var pendingManageModels = false
    @State private var showingExcludedWordsEditor = false
    @State private var showingSystemPromptEditor = false
    @State private var showingMetadataEditor = false
    @State private var metadataSettings = MetadataCleaningSettings.load()
    @State private var isCustomExcludedWords = UserOverridesManager.shared.hasCustomExcludedWords
    @State private var isCustomSystemPrompt = UserOverridesManager.shared.hasCustomSystemPrompt
    @State private var excludedWordsDraft = ""
    @State private var excludedWordsBaseline = ""
    @State private var systemPromptDraft = ""
    @State private var systemPromptBaseline = ""
    @State private var overrideErrorMessage: String?
    @State private var appTheme: AppTheme = {
        // Load saved theme preference from UserDefaults
        if let saved = UserDefaults.standard.string(forKey: "AppTheme"),
           let theme = AppTheme(rawValue: saved) {
            return theme
        }
        return .system
    }()
    @ObservedObject private var permissionManager = PermissionManager.shared
    private let overridesManager = UserOverridesManager.shared
    
    init(viewModel: DocumentRedactionViewModel) {
        self.viewModel = viewModel
        var initialSettings = viewModel.settings
        if viewModel.availableModels.count == 1, let onlyModel = viewModel.availableModels.first {
            initialSettings.model = onlyModel
        } else if !viewModel.availableModels.contains(initialSettings.model), let first = viewModel.availableModels.first {
            initialSettings.model = first
        }
        self._localSettings = State(initialValue: initialSettings)
    }
    
    var body: some View {
        VStack(spacing: 24) {
            // Header
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
            
            Form {
                // Processing Mode Section
                Section("Processing Mode") {
                    Picker("Mode", selection: $localSettings.mode) {
                        ForEach(RedactionMode.allCases, id: \.self) { mode in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(mode.displayName)
                                    .font(.system(size: 14, weight: .medium))
                                Text(mode.description)
                                    .font(.system(size: 12))
                                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            }
                            .tag(mode)
                        }
                    }
                    .pickerStyle(.radioGroup)
                }

                // Shared Settings (System Notifications at top per user request)
                Section("Shared Settings") {
                    VStack(alignment: .leading, spacing: 12) {
                        // 1. System Notifications (moved to top)
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text("System Notifications")
                                    .font(.system(size: 14, weight: .medium))
                                Spacer()
                                // Status indicator (only show issues)
                                switch PermissionManager.shared.notificationStatus {
                                case .authorized, .provisional:
                                    EmptyView()
                                case .denied:
                                    Image(systemName: "xmark.circle.fill")
                                        .foregroundColor(.red)
                                default:
                                    // Make "!" clickable to retry check
                                    Button {
                                        Task { try? await PermissionManager.shared.forceRequestNotificationPermission() }
                                    } label: {
                                        Image(systemName: "exclamationmark.circle.fill")
                                            .foregroundColor(.gray)
                                    }
                                    .buttonStyle(.plain)
                                }
                            }
                            // Auto-refresh on appear
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
                            .onChange(of: permissionManager.userEnabledNotifications) { newValue in
                                if newValue {
                                    // User turned it ON locally.
                                    // Ensure we actually have OS permission and the delegate is set.
                                    Task {
                                        // Calling this ensures the delegate is attached (critical for foreground banners)
                                        // and verifies authorization status without re-prompting if already granted.
                                        try? await permissionManager.requestNotificationPermission()
                                    }
                                }
                                // If turning OFF, strictly local. No side effects.
                            }
                            .toggleStyle(.switch)
                            
                            // Helper buttons if stuck
                            if PermissionManager.shared.notificationStatus == .denied {
                                Button("Open System Settings (Permission Denied)") {
                                     if let url = URL(string: "x-apple.systempreferences:com.apple.preference.notifications") {
                                         NSWorkspace.shared.open(url)
                                     }
                                }
                                .font(.caption)
                                .buttonStyle(.link)
                            } else if PermissionManager.shared.notificationStatus == .notDetermined && permissionManager.userEnabledNotifications {
                                // If enabled but not determined, offer manual trigger
                                Button("Authorize Notifications") {
                                    Task { try? await PermissionManager.shared.forceRequestNotificationPermission() }
                                }
                                .font(.caption)
                                .buttonStyle(.bordered)
                            }
                        }
                        
                        Divider()
                        
                        // 2. Appearance Theme
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Appearance")
                                .font(.system(size: 14, weight: .medium))
                            Text("Choose light, dark, or follow system appearance.")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            
                            Picker("", selection: $appTheme) {
                                ForEach(AppTheme.allCases, id: \.self) { theme in
                                    Text(theme.displayName).tag(theme)
                                }
                            }
                            .pickerStyle(.segmented)
                            .labelsHidden()
                            .onChange(of: appTheme) { newTheme in
                                // Save to UserDefaults
                                UserDefaults.standard.set(newTheme.rawValue, forKey: "AppTheme")
                                // Apply to app window
                                NSApp.windows.forEach { window in
                                    window.appearance = newTheme.appearance
                                }
                            }
                        }
                        
                        Divider()
                        
                        // 3. Metadata Cleaning
                        VStack(alignment: .leading, spacing: 6) {
                            Text("Metadata Cleaning")
                                .font(.system(size: 14, weight: .medium))
                            Text("Remove hidden document properties during redaction.")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            Button("Configure Metadata…") {
                                showingMetadataEditor = true
                            }
                            .buttonStyle(.bordered)
                            .controlSize(.small)
                        }
                        
                        Divider()
                        
                        // 3. Boilerplate Exclusions
                        VStack(alignment: .leading, spacing: 6) {
                            HStack {
                                Text("Boilerplate Exclusions")
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
                                
                                if isCustomExcludedWords {
                                    Button("Reset to Defaults") {
                                        resetExcludedWordsToDefault()
                                    }
                                    .buttonStyle(.bordered)
                                    .controlSize(.small)
                                }
                            }
                        }
                    }
                }
                
                // AI Model Section (only for enhanced mode)
                if localSettings.mode == .enhanced {
                    Section("AI Model") {
                        VStack(alignment: .leading, spacing: 12) {
                            Text("Select AI Model")
                                .font(.system(size: 14, weight: .medium))
                                .foregroundColor(CustomColors.primaryText(for: colorScheme))

                            ForEach([
                                ("llama3.1:8b", "Llama 3.1 8B", "Gold standard. The most accurate model tested.", "~45s", CustomColors.accentColor(for: colorScheme)),
                                ("mistral:7b", "Mistral 7B", "Solid alternative, but less consistent than Llama 3.1.", "~35s", Color.orange),
                                ("llama3.2:3b", "Llama 3.2 3B", "Very fast, but frequently misses entities. Use with caution.", "~20s", Color.green)
                            ], id: \.0) { model in
                                ModelSelectionRow(
                                    modelId: model.0,
                                    displayName: model.1,
                                    description: model.2,
                                    processingTime: model.3,
                                    accentColor: model.4,
                                    isSelected: localSettings.model == model.0,
                                    isInstalled: viewModel.availableModels.contains(model.0)
                                ) {
                                    localSettings.model = model.0
                                }
                                .padding(.horizontal, 12)
                            }

                            Text("Processing times are estimates for a 5,000 word document")
                                .font(.caption)
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                                .italic()

                            // System Prompt Section
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
                                    
                                    if isCustomSystemPrompt {
                                        Button("Reset to Defaults") {
                                            resetSystemPromptToDefault()
                                        }
                                        .buttonStyle(.bordered)
                                        .controlSize(.small)
                                    }
                                }
                            }
                            .padding(.top, 4)
                            
                            Divider()
                                .padding(.vertical, 4)

                            // Model Management Actions
                            HStack(spacing: 8) {
                                Button("Manage Models…") {
                                    pendingManageModels = true
                                    dismiss()
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)

                                Button("Reveal Models…") {
                                    NSWorkspace.shared.open(viewModel.modelsDirectoryURL)
                                }
                                .buttonStyle(.bordered)
                                .controlSize(.small)

                                Spacer()
                            }
                        }

                        if viewModel.availableModels.isEmpty {
                            HStack {
                                Image(systemName: "exclamationmark.triangle.fill")
                                    .foregroundColor(.orange)
                                Text("No AI models installed. Click 'Manage Models…' to download one.")
                                    .font(.caption)
                                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            }
                        }
                    }
                }


                
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

                            Spacer()
                        }

                        ForEach(RedactionRule.allCases.sorted { $0.displayName < $1.displayName }) { rule in
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
                        }

                    }
                }

                if localSettings.mode == .enhanced {
                    Section("Advanced AI Settings") {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Temperature: \(localSettings.temperature, specifier: "%.1f")")
                                .font(.system(size: 14, weight: .medium))
                                .foregroundColor(CustomColors.primaryText(for: colorScheme))
                            Slider(value: $localSettings.temperature, in: 0.0...2.0, step: 0.1)
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
                            ), in: 50...500, step: 25)
                            Text("Higher = catches entities at chunk boundaries but increases processing time. Lower = faster but may miss split names.")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }

                        VStack(alignment: .leading, spacing: 8) {
                            // Custom timeout display
                            let timeoutDisplay: String = {
                                let seconds = localSettings.processingTimeoutSeconds
                                if seconds <= 0 || seconds == Int.max {
                                    return "∞ (No Limit)"
                                } else if seconds < 60 {
                                    return "\(seconds) sec"
                                } else {
                                    return "\(seconds / 60) min"
                                }
                            }()
                            Text("Processing Timeout: \(timeoutDisplay)")
                                .font(.system(size: 14, weight: .medium))
                                .foregroundColor(CustomColors.primaryText(for: colorScheme))
                            
                            // Custom discrete slider with non-linear steps
                            // Steps: 0.5, 1, 2, 3-45 (1-min), 50-195 (5-min), ∞
                            let timeoutSteps: [Int] = {
                                var steps: [Int] = [30, 60, 120] // 0.5, 1, 2 min in seconds
                                for m in 3...45 { steps.append(m * 60) } // 3-45 min
                                for i in 0..<30 { steps.append((50 + i * 5) * 60) } // 50-195 min in 5-min increments
                                steps.append(Int.max) // Infinity
                                return steps
                            }()
                            
                            let sliderIndex = Binding<Double>(
                                get: {
                                    let currentSeconds = localSettings.processingTimeoutSeconds
                                    if currentSeconds <= 0 || currentSeconds == Int.max {
                                        return Double(timeoutSteps.count - 1)
                                    }
                                    if let idx = timeoutSteps.firstIndex(of: currentSeconds) {
                                        return Double(idx)
                                    }
                                    // Find closest step
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
                            
                            Slider(value: sliderIndex, in: 0...Double(timeoutSteps.count - 1), step: 1)
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
                            Text("Fixed seed = reproducible results on same document. Change to get different AI outputs for testing.")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }

                    }
                }

                // Debug Section
                Section("Debug") {
                    Toggle("Enable Debug Logging", isOn: $localSettings.debug)
                        .toggleStyle(.checkbox)

                    Text("When enabled, both the app and helper write verbose diagnostics to logs for troubleshooting. This may impact performance and generate large files.")
                        .font(.system(size: 12))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        .padding(.top, 4)

                    HStack(spacing: 12) {
                        Button("Open App Log") {
                            DebugLogger.shared.ensureLogInitialized()
                            let logURL = DebugLogger.shared.logURL
                            NSWorkspace.shared.open(logURL)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)

                        Button("Open Ollama Log") {
                            let logURL = viewModel.ollamaLogURL
                            NSWorkspace.shared.open(logURL)
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)

                        Button("Clear Logs") {
                            viewModel.clearLogs()
                        }
                        .buttonStyle(.bordered)
                        .controlSize(.small)

                        Spacer()
                    }
                    .padding(.top, 8)
                }
            }
            .formStyle(.grouped)
            
            Spacer()
            
            // Buttons
            HStack(spacing: 12) {
                Button("Cancel") {
                    dismiss()
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                
                Button("Save Settings") {
                    viewModel.updateSettings(localSettings)
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                .tint(CustomColors.accentColor(for: colorScheme))
            }
        }
        .padding(32)
        .frame(width: 600, height: 700)
        .background(CustomColors.cardBackground(for: colorScheme))
        .onDisappear {
            if pendingManageModels {
                pendingManageModels = false
                DispatchQueue.main.async {
                    viewModel.requestFirstRunSetup(fromManageModels: true)
                }
            }
        }
        .sheet(isPresented: $showingExcludedWordsEditor) {
            OverrideEditorSheet(
                title: "Edit Excluded Words",
                description: "Terms listed here will never be redacted. Additionally, organization names containing only excluded words (like 'Target Company' or 'Acquired LLC') are automatically skipped to prevent over-redaction of legal defined terms.\n\nOne term or regex per line. Comments starting with # are ignored.",
                text: $excludedWordsDraft,
                onCancel: { cancelExcludedWordsEditing() },
                onSave: { saveExcludedWords() },
                onRestoreDefaults: { restoreExcludedWordsDefaults() }
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
        .alert("Override Error", isPresented: overrideErrorBinding, presenting: overrideErrorMessage) { _ in
            Button("OK", role: .cancel) { }
        } message: { message in
            Text(message)
        }
    }

    private var overrideErrorBinding: Binding<Bool> {
        Binding(
            get: { overrideErrorMessage != nil },
            set: { if !$0 { overrideErrorMessage = nil } }
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

            HStack(spacing: 12) {
                Button("Cancel") {
                    onCancel()
                }
                .buttonStyle(.bordered)

                Button("Restore Defaults") {
                    onRestoreDefaults()
                }
                .buttonStyle(.bordered)

                Spacer()

                Button("Save Changes") {
                    onSave()
                }
                .buttonStyle(.borderedProminent)
            }

            Spacer()
        }
        .padding(24)
        .frame(minWidth: 500, minHeight: 625)
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

    @State private var selectedModel = "llama3.1:8b"
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

    private var isManageFlow: Bool {
        viewModel.firstRunEntryPoint == .manageModels
    }

    init(viewModel: DocumentRedactionViewModel, onComplete: @escaping () -> Void) {
        self.viewModel = viewModel
        self.onComplete = onComplete
        let initialStep: SetupStep = viewModel.firstRunEntryPoint == .manageModels ? .modelSelection : .welcome
        _setupStep = State(initialValue: initialStep)
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
                    }

                    Spacer()

                    if setupStep != .downloading {
                        Button(buttonTitle) {
                            handleNextButton()
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(CustomColors.accentColor(for: colorScheme))
                        .disabled(isDownloading)
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
            // If a supported model already exists and we're not in the manage-models flow,
            // skip the download prompt and finish onboarding immediately.
            if !isManageFlow && hasInstalledSupportedModel {
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
                ForEach([
                    ("llama3.1:8b", "Llama 3.1 8B", "Gold standard. The most accurate model tested. Recommended.", "4.7 GB", "Best"),
                    ("mistral:7b", "Mistral 7B", "Solid alternative, but less consistent than Llama 3.1.", "4.1 GB", "Balanced"),
                    ("llama3.2:3b", "Llama 3.2 3B", "Very fast, but frequently misses entities. Use with caution.", "2.0 GB", "Fast")
                ], id: \.0) { model in
                    ModelSelectionRow(
                        modelId: model.0,
                        displayName: model.1,
                        description: model.2,
                        size: model.3,
                        badge: model.4,
                        isSelected: selectedModel == model.0,
                        isInstalled: viewModel.availableModels.contains(model.0)
                    ) {
                        selectedModel = model.0
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
        dismissSheet()
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
                    errorMessage = "Failed to download model. Please check your internet connection and try again."
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
    @Environment(\.colorScheme) private var colorScheme

    // Convenience initializers for different use cases
    init(modelId: String, displayName: String, description: String, processingTime: String, accentColor: Color, isSelected: Bool, isInstalled: Bool, onSelect: @escaping () -> Void) {
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
    }

    init(modelId: String, displayName: String, description: String, size: String, badge: String, isSelected: Bool, isInstalled: Bool, onSelect: @escaping () -> Void) {
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
    }
}
