import SwiftUI

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
        case let .downloadSpecificModel(targetModelId):
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
                    if setupStep != .welcome, setupStep != .downloading,
                       !(isManageFlow && setupStep == .modelSelection)
                    {
                        Button("Back") {
                            withAnimation(.easeInOut(duration: 0.3)) {
                                setupStep = previousStep
                            }
                        }
                        .buttonStyle(.bordered)
                        .accessibilityIdentifier("setup.back")
                    }

                    if setupStep != .downloading, !isManageFlow {
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
            } else if !isManageFlow, hasInstalledSupportedModel {
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

    private var welcomeContent: some View {
        VStack(spacing: 24) {
            VStack(spacing: 16) {
                Text("First-time setup")
                    .font(.title2)
                    .fontWeight(.semibold)

                Text(
                    "MarcutApp uses local AI models to identify and redact sensitive information in your documents. All processing happens on your device - no data ever leaves your computer."
                )
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
        case .welcome: "Get Started"
        case .modelSelection: "Download Model"
        case .downloading: "Downloading..."
        case .complete: "Finish"
        }
    }

    private var previousStep: SetupStep {
        switch setupStep {
        case .welcome: .welcome
        case .modelSelection: .welcome
        case .downloading: .modelSelection
        case .complete: .downloading
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
