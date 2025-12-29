import SwiftUI
import UniformTypeIdentifiers
import Foundation
import AppKit

// MARK: - AttributeGraph Debugging Extensions
extension ContentView {
    private func debugAttributeGraph() {
        print("🔍 ContentView AttributeGraph Analysis:")
        print("  - @StateObject viewModel: \(ObjectIdentifier(viewModel))")
        print("  - @State isTargeted: \(isTargeted)")
        print("  - @State showSettings: \(showSettings)")
        print("  - ViewModel.shouldShowFirstRunSetup: \(viewModel.shouldShowFirstRunSetup)")
        print("  - @State alertInfo: \(alertInfo?.id.uuidString ?? "nil")")
        print("  - @State isPreparing: \(isPreparing)")

        // Log ViewModel published properties
        print("  - ViewModel.items.count: \(viewModel.items.count)")
        print("  - ViewModel.hasDocuments: \(viewModel.hasDocuments)")
        print("  - ViewModel.hasValidDocuments: \(viewModel.hasValidDocuments)")
        print("  - ViewModel.isEnvironmentReady: \(viewModel.isEnvironmentReady)")

        ContentView.logToFile("AttributeGraph debug info logged to console")
    }

    private func monitorAttributeGraphCycles() async {
        print("🔍 Starting AttributeGraph cycle monitoring...")
        ContentView.logToFile("Starting AttributeGraph cycle monitoring")

        // Monitor for changes in key properties that might trigger cycles
        var previousItemsCount = viewModel.items.count
        var previousHasDocuments = viewModel.hasDocuments
        var previousIsEnvironmentReady = viewModel.isEnvironmentReady

        for i in 0..<30 { // Monitor for 30 seconds
            try? await Task.sleep(nanoseconds: 1_000_000_000) // 1 second

            let currentItemsCount = viewModel.items.count
            let currentHasDocuments = viewModel.hasDocuments
            let currentIsEnvironmentReady = viewModel.isEnvironmentReady

            if currentItemsCount != previousItemsCount ||
               currentHasDocuments != previousHasDocuments ||
               currentIsEnvironmentReady != previousIsEnvironmentReady {

                print("🔄 AttributeGraph state change detected at \(i)s:")
                print("  - items.count: \(previousItemsCount) → \(currentItemsCount)")
                print("  - hasDocuments: \(previousHasDocuments) → \(currentHasDocuments)")
                print("  - isEnvironmentReady: \(previousIsEnvironmentReady) → \(currentIsEnvironmentReady)")

                ContentView.logToFile("AttributeGraph state change at \(i)s - items:\(currentItemsCount) docs:\(currentHasDocuments) env:\(currentIsEnvironmentReady)")

                previousItemsCount = currentItemsCount
                previousHasDocuments = currentHasDocuments
                previousIsEnvironmentReady = currentIsEnvironmentReady
            }
        }

        print("🔍 AttributeGraph monitoring completed")
        ContentView.logToFile("AttributeGraph monitoring completed after 30s")
    }
}

// MARK: - Custom Color Palette (Adaptive for Light/Dark Mode)
struct CustomColors {
    // Adaptive color properties that respond to color scheme
    static func appBackground(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color(NSColor(calibratedHue: 0.58, saturation: 0.04, brightness: 0.98, alpha: 1.0))
        case .dark:
            // Deep navy background for dark mode
            return Color(NSColor(calibratedRed: 0.10, green: 0.10, blue: 0.18, alpha: 1.0))
        @unknown default:
            return Color(NSColor(calibratedHue: 0.58, saturation: 0.04, brightness: 0.98, alpha: 1.0))
        }
    }

    static func contentBackground(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color(NSColor(calibratedHue: 0.58, saturation: 0.07, brightness: 0.93, alpha: 1.0))
        case .dark:
            // Slightly lighter navy for content areas
            return Color(NSColor(calibratedRed: 0.15, green: 0.15, blue: 0.24, alpha: 1.0))
        @unknown default:
            return Color(NSColor(calibratedHue: 0.58, saturation: 0.07, brightness: 0.93, alpha: 1.0))
        }
    }

    static func accentColor(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color(NSColor(calibratedHue: 0.53, saturation: 0.60, brightness: 0.68, alpha: 1.0))
        case .dark:
            // Softer, warmer blue-purple for dark mode
            return Color(NSColor(calibratedRed: 0.55, green: 0.65, blue: 0.85, alpha: 1.0))
        @unknown default:
            return Color(NSColor(calibratedHue: 0.53, saturation: 0.60, brightness: 0.68, alpha: 1.0))
        }
    }

    static func destructiveColor(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color(NSColor(calibratedRed: 0.85, green: 0.35, blue: 0.35, alpha: 1.0))
        case .dark:
            // Slightly desaturated red for dark mode
            return Color(NSColor(calibratedRed: 0.90, green: 0.45, blue: 0.45, alpha: 1.0))
        @unknown default:
            return Color(NSColor(calibratedRed: 0.85, green: 0.35, blue: 0.35, alpha: 1.0))
        }
    }

    static func primaryText(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color(NSColor.labelColor)
        case .dark:
            // Warm cream color for better contrast
            return Color(NSColor(calibratedRed: 0.97, green: 0.95, blue: 0.91, alpha: 1.0))
        @unknown default:
            return Color(NSColor.labelColor)
        }
    }

    static func secondaryText(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color(NSColor.secondaryLabelColor)
        case .dark:
            // Softer cream for secondary text
            return Color(NSColor(calibratedRed: 0.80, green: 0.78, blue: 0.74, alpha: 1.0))
        @unknown default:
            return Color(NSColor.secondaryLabelColor)
        }
    }

    static func shadow(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color.black.opacity(0.12)
        case .dark:
            return Color.black.opacity(0.4)
        @unknown default:
            return Color.black.opacity(0.12)
        }
    }

    static func subtleBorder(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color.black.opacity(0.1)
        case .dark:
            return Color.white.opacity(0.1)
        @unknown default:
            return Color.black.opacity(0.1)
        }
    }

    static func cardBackground(for scheme: ColorScheme) -> Color {
        switch scheme {
        case .light:
            return Color(NSColor.windowBackgroundColor)
        case .dark:
            // Dark card background with hint of navy
            return Color(NSColor(calibratedRed: 0.12, green: 0.12, blue: 0.20, alpha: 1.0))
        @unknown default:
            return Color(NSColor.windowBackgroundColor)
        }
    }

    // Legacy static properties for compatibility - will use light mode as default
    static let appBackground = appBackground(for: .light)
    static let contentBackground = contentBackground(for: .light)
    static let accentColor = accentColor(for: .light)
    static let destructiveColor = destructiveColor(for: .light)
    static let primaryText = primaryText(for: .light)
    static let secondaryText = secondaryText(for: .light)
    static let shadow = shadow(for: .light)
    static let subtleBorder = subtleBorder(for: .light)
    static let cardBackground = cardBackground(for: .light)
}

// MARK: - Window Background Helper
struct WindowBackgroundView: NSViewRepresentable {
    @Environment(\.colorScheme) var colorScheme

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        DispatchQueue.main.async {
            if let window = view.window {
                let bgColor = CustomColors.appBackground(for: colorScheme)
                window.backgroundColor = NSColor(bgColor)
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        if let window = nsView.window {
            let bgColor = CustomColors.appBackground(for: colorScheme)
            window.backgroundColor = NSColor(bgColor)
        }
    }
}

// MARK: - Main Content View
struct ContentView: View {
    @StateObject private var viewModel = DocumentRedactionViewModel()
    @State private var isTargeted = false
    @State private var showSettings = false

    @State private var alertInfo: AlertInfo?
    @State private var currentProcessingTask: Task<Void, Never>?
    @State private var isPreparing = false
    @State private var isStopping = false
    @State private var hasCheckedEnvironment = false
    @Environment(\.colorScheme) private var colorScheme

    // Check if first run has been completed before
    private var hasCompletedFirstRun: Bool {
        UserDefaults.standard.bool(forKey: "MarcutApp.hasCompletedFirstRun")
    }
    
    var body: some View {
        VStack(spacing: 24) {
            // Drop zone
            dropZone

            // Document list with Clear List button above
            VStack(spacing: 8) {
                // Clear List button (above document list, rounded like rows, smaller)
                if viewModel.hasDocuments {
                    HStack {
                        Button(action: {
                            currentProcessingTask?.cancel()
                            viewModel.clearAllDocuments()
                        }) {
                            HStack(spacing: 4) {
                                Image(systemName: "xmark.circle.fill")
                                    .font(.system(size: 9))
                                Text("Clear List")
                                    .font(.system(size: 9, weight: .medium))
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 5)
                            .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                            .background(
                                RoundedRectangle(cornerRadius: 12)
                                    .fill(CustomColors.cardBackground(for: colorScheme))
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 12)
                                            .stroke(CustomColors.subtleBorder(for: colorScheme), lineWidth: 1)
                                    )
                            )
                        }
                        .buttonStyle(.plain)
                        .disabled(isPreparing)
                        Spacer()
                    }
                    .padding(.leading, 18) // Align with row content (matches row padding)
                }
                
                DocumentListView(viewModel: viewModel, alertInfo: $alertInfo)
                    .frame(maxHeight: .infinity)
            }

            // Action buttons (Redact + Scrub Metadata side by side)
            actionButtons

            // Environment status banner (moved above footer)
            EnvironmentStatusBanner(viewModel: viewModel)

            // Footer
            FooterView()
        }
        .padding(24)
        .frame(minWidth: 800, minHeight: 700)
        .background(CustomColors.appBackground(for: colorScheme).ignoresSafeArea())
        .background(WindowBackgroundView().opacity(0))
        .onChange(of: viewModel.hasProcessingDocuments) { hasProcessing in
            if !hasProcessing {
                isStopping = false
            }
        }
        .onAppear {
            print("💡 CONTENT VIEW APPEARED - Console output")
            ContentView.logToFile("=== APP APPEARED ===")
            LaunchDiagnostics.shared.markContentViewAppeared()

            // Debug AttributeGraph state
            debugAttributeGraph()

            // Initialize debug sync after view model is ready
            viewModel.initializeDebugSync()

            // Ensure a visible, foreground window after any permission prompts
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.25) {
                NSApp.activate(ignoringOtherApps: true)
                if let win = NSApp.windows.first {
                    win.center()
                    win.makeKeyAndOrderFront(nil)
                    win.orderFrontRegardless()
                }
            }

            // Check environment asynchronously and wait for result
            Task {
                // Only check environment once per app launch
                guard !hasCheckedEnvironment else { return }
                hasCheckedEnvironment = true

                // OPTIMIZATION: Check first-run status immediately before heavy environment checks
                if !hasCompletedFirstRun && viewModel.availableModels.isEmpty {
                    ContentView.logToFile("🚀 Fast-path: Launching first-run setup immediately")
                    viewModel.requestFirstRunSetup()
                    // We still run environment check in background to populate status, but don't block UI
                } else if !hasCompletedFirstRun {
                    ContentView.logToFile("✅ Found installed models on disk; marking onboarding complete")
                    viewModel.markFirstRunComplete()
                    viewModel.shouldShowFirstRunSetup = false
                }

                ContentView.logToFile("Checking environment...")
                let isReady = await viewModel.refreshEnvironmentStatus()
                let hasModels = !viewModel.availableModels.isEmpty

                ContentView.logToFile("Environment check complete - isReady: \(isReady)")
                ContentView.logToFile("Has completed first run: \(hasCompletedFirstRun)")
                ContentView.logToFile("Has models: \(hasModels)")

                // First-run logic:
                // 1. If onboarding hasn't been completed, always show it once
                // 2. If onboarding completed but environment is missing prerequisites, prompt again
                if !hasCompletedFirstRun {
                    ContentView.logToFile("Launching first-run setup (onboarding not completed)")
                    viewModel.requestFirstRunSetup()
                } else if !hasModels {
                    ContentView.logToFile("No models installed — prompting setup")
                    viewModel.requestFirstRunSetup()
                } else if !isReady {
                    ContentView.logToFile("Models installed but environment not ready — attempting recovery")
                    viewModel.shouldShowFirstRunSetup = false

                    // Attempt automatic recovery first
                    Task {
                        ContentView.logToFile("🔧 Attempting automatic environment recovery...")
                        let recoverySuccess = await viewModel.attemptEnvironmentRecovery()

                        await MainActor.run {
                            if recoverySuccess {
                                ContentView.logToFile("✅ Automatic recovery successful!")
                                // Show success message to user
                                alertInfo = AlertInfo(
                                    title: "Environment Fixed",
                                    message: "Good news! The environment issues have been resolved automatically. You can now proceed with redaction."
                                )
                            } else {
                                ContentView.logToFile("❌ Automatic recovery failed - showing detailed error")
                                // Show detailed error with recovery options
                                let diagnostics = viewModel.getDetailedEnvironmentDiagnostics()
                                let diagnosticText = diagnostics.map { "\($0.key): \($0.value)" }.joined(separator: "\n")

                                alertInfo = AlertInfo(
                                    title: "Environment Issues Detected",
                                    message: """
                                    Marcut detected environment configuration issues:

                                    \(viewModel.environmentStatus)

                                    Technical Details:
                                    \(diagnosticText)

                                    Recommended actions:
                                    • Try restarting the application
                                    • Ensure you have sufficient disk space
                                    • If problems persist, contact support at https://www.linkedin.com/in/marcmandel/
                                    """
                                )
                            }
                        }
                    }
                } else {
                    ContentView.logToFile("Environment ready and onboarding complete")
                    viewModel.shouldShowFirstRunSetup = false
                }

                // Monitor for AttributeGraph cycles
                await monitorAttributeGraphCycles()
            }
        }
        .sheet(isPresented: $showSettings) {
            SettingsView(viewModel: viewModel)
        }

        .sheet(isPresented: $viewModel.shouldShowFirstRunSetup, onDismiss: {
            viewModel.resetFirstRunEntryPoint()
        }) {
            FirstRunSetupView(viewModel: viewModel) {
                viewModel.shouldShowFirstRunSetup = false
                Task { await viewModel.refreshEnvironmentStatus() }
            }
            .interactiveDismissDisabled() // Prevents dismissal by clicking outside
        }
        .alert(item: $alertInfo) { info in
            Alert(
                title: Text(info.title),
                message: Text(info.message),
                dismissButton: .default(Text("OK"))
            )
        }
    }
    
    // MARK: - Drop Zone
    private var dropZone: some View {
        VStack(spacing: 0) {
            // Drop area
            VStack(spacing: 18) {
                Image(systemName: "doc.text.magnifyingglass")
                    .font(.system(size: 48, weight: .light))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))

                Text("Drag & Drop .docx files here")
                    .font(.system(size: 17, weight: .medium))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
            }
            .frame(maxWidth: .infinity, minHeight: 160)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(CustomColors.contentBackground(for: colorScheme))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .strokeBorder(
                        isTargeted ? CustomColors.accentColor(for: colorScheme) : CustomColors.subtleBorder(for: colorScheme).opacity(0.2),
                        style: StrokeStyle(lineWidth: 2.5, dash: isTargeted ? [] : [8, 4])
                    )
                    .animation(.easeInOut(duration: 0.2), value: isTargeted)
            )
            .scaleEffect(isTargeted ? 1.02 : 1.0)
            .animation(.spring(response: 0.3, dampingFraction: 0.7), value: isTargeted)
            .padding([.horizontal, .top], 20)
            .onDrop(of: [UTType.fileURL], isTargeted: $isTargeted) { providers in
                handleDrop(providers: providers)
                return true
            }

            // Browse button bar
            HStack {
                Button(action: { openPanel() }) {
                    Text("Browse...")
                        .font(.system(size: 15, weight: .semibold))
                        .padding(.horizontal, 20)
                        .padding(.vertical, 10)
                }
                .tint(CustomColors.accentColor(for: colorScheme))
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
                
                Spacer()
                
                Button(action: { showSettings = true }) {
                    HStack(spacing: 6) {
                        Image(systemName: "gearshape.fill")
                            .font(.system(size: 14))
                        Text("Settings")
                            .font(.system(size: 14, weight: .medium))
                    }
                    .padding(.horizontal, 16)
                    .padding(.vertical, 8)
                }
                .buttonStyle(.bordered)
                .controlSize(.regular)
            }
            .padding(20)
        }
        .background(CustomColors.cardBackground(for: colorScheme))
        .cornerRadius(16)
        .shadow(color: CustomColors.shadow(for: colorScheme), radius: 8, x: 0, y: 2)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(CustomColors.subtleBorder(for: colorScheme).opacity(0.3), lineWidth: 1)
        )
    }
    
    // MARK: - Action Buttons
    private var actionButtons: some View {
        HStack(spacing: 12) {
            // Scrub Metadata Button (left side)
            Button(action: { startMetadataScrub() }) {
                HStack(spacing: 8) {
                    Image(systemName: "doc.badge.gearshape")
                        .font(.system(size: 16, weight: .semibold))
                    Text("Scrub Metadata")
                        .font(.system(size: 16, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .padding(.horizontal, 20)
                .foregroundColor(.white)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(viewModel.hasValidDocuments ? Color.orange : Color.gray.opacity(0.4))
                        .shadow(color: viewModel.hasValidDocuments ? Color.orange.opacity(0.2) : Color.clear, radius: 6, y: 3)
                )
            }
            .disabled(!viewModel.hasValidDocuments || isPreparing || isStopping || viewModel.hasProcessingDocuments || currentProcessingTask != nil)
            .buttonStyle(.plain)
            .scaleEffect(viewModel.hasValidDocuments ? 1.0 : 0.98)
            .animation(.easeInOut(duration: 0.2), value: viewModel.hasValidDocuments)
            
            // Process/Stop Button (right side)
            if isPreparing {
                // Show progress indicator while preparing
                HStack(spacing: 8) {
                    ProgressView()
                        .scaleEffect(0.8)
                        .frame(width: 16, height: 16)
                    Text("Preparing...")
                        .font(.system(size: 16, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .padding(.horizontal, 20)
                .foregroundColor(.white)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(CustomColors.accentColor(for: colorScheme).opacity(0.8))
                        .shadow(color: CustomColors.accentColor(for: colorScheme).opacity(0.2), radius: 6, y: 3)
                )
            } else if isStopping {
                HStack(spacing: 8) {
                    ProgressView()
                        .scaleEffect(0.8)
                        .frame(width: 16, height: 16)
                    Text("Stopping...")
                        .font(.system(size: 16, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .padding(.horizontal, 20)
                .foregroundColor(.white)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(CustomColors.destructiveColor(for: colorScheme).opacity(0.8))
                        .shadow(color: CustomColors.destructiveColor(for: colorScheme).opacity(0.2), radius: 6, y: 3)
                )
            } else if viewModel.hasProcessingDocuments || currentProcessingTask != nil {
                Button(action: { stopProcessing() }) {
                    HStack(spacing: 8) {
                        Image(systemName: "stop.fill")
                            .font(.system(size: 16, weight: .semibold))
                        // If any item is in analyzing state (model download), reflect that in label
                        Text(viewModel.items.contains(where: { $0.status == .analyzing }) ? "Cancel Download" : "Stop Processing")
                            .font(.system(size: 16, weight: .semibold))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .padding(.horizontal, 20)
                    .foregroundColor(.white)
                    .background(
                        RoundedRectangle(cornerRadius: 12)
                            .fill(CustomColors.destructiveColor(for: colorScheme))
                            .shadow(color: CustomColors.destructiveColor(for: colorScheme).opacity(0.2), radius: 6, y: 3)
                    )
                }
                .buttonStyle(.plain)
            } else if viewModel.hasFinishedProcessing {
                // Show "Finished Processing" when all documents are complete
                HStack(spacing: 8) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 16, weight: .semibold))
                    Text("Finished Processing")
                        .font(.system(size: 16, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .padding(.horizontal, 20)
                .foregroundColor(.white)
                .background(
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.green.opacity(0.8))
                        .shadow(color: Color.green.opacity(0.2), radius: 6, y: 3)
                )
            } else {
                if viewModel.isPythonInitializing {
                    HStack(spacing: 8) {
                        ProgressView()
                            .controlSize(.small)
                        Text("Initializing AI engine…")
                            .font(.system(size: 14))
                            .foregroundColor(.secondary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.bottom, 8)
                } else if let error = viewModel.pythonInitializationError {
                    Text(error)
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.red)
                        .frame(maxWidth: .infinity)
                        .padding(.bottom, 8)
                }

                Button(action: { startProcessing() }) {
                    HStack(spacing: 8) {
                        Image(systemName: "wand.and.stars")
                            .font(.system(size: 16, weight: .semibold))
                        Text("Redact & Scrub")
                            .font(.system(size: 16, weight: .semibold))
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 14)
                    .padding(.horizontal, 20)
                    .foregroundColor(.white)
                    .background(
                        RoundedRectangle(cornerRadius: 12)
                            .fill(viewModel.hasValidDocuments ? CustomColors.accentColor(for: colorScheme) : Color.gray.opacity(0.4))
                            .shadow(color: viewModel.hasValidDocuments ? CustomColors.accentColor(for: colorScheme).opacity(0.2) : Color.clear, radius: 6, y: 3)
                    )
                }
                .disabled(!viewModel.hasValidDocuments || !viewModel.isEnvironmentReady || isPreparing || viewModel.isPythonInitializing || viewModel.pythonInitializationError != nil)
                .buttonStyle(.plain)
                .scaleEffect(viewModel.hasValidDocuments ? 1.0 : 0.98)
                .animation(.easeInOut(duration: 0.2), value: viewModel.hasValidDocuments)
            }
        }
    }
    
    // MARK: - Actions
    private func handleDrop(providers: [NSItemProvider]) {
        ContentView.logToFile("=== HANDLING FILE DROP ===")
        ContentView.logToFile("Number of providers: \(providers.count)")

        // Permissions are handled centrally by FileAccessCoordinator - no need to check on every drop
        ContentView.logToFile("🔐 File drop - using centralized permission system")

        for provider in providers {
            if provider.hasItemConformingToTypeIdentifier(UTType.fileURL.identifier) {
                ContentView.logToFile("Provider has file URL identifier")
                provider.loadItem(forTypeIdentifier: UTType.fileURL.identifier, options: nil) { item, error in
                    if let error = error {
                        DispatchQueue.main.async {
                            ContentView.logToFile("Error loading item: \(error.localizedDescription)")
                        }
                        return
                    }

                       if let data = item as? Data,
                          let url = URL(dataRepresentation: data, relativeTo: nil) {
                           DispatchQueue.main.async {
                               ContentView.logToFile("Adding file: \(url.lastPathComponent)")
                               viewModel.add(urls: [url])
                               ContentView.logToFile("After adding - hasValidDocuments: \(viewModel.hasValidDocuments)")
                                Task { await viewModel.refreshEnvironmentStatus() }
                           }
                    } else {
                        DispatchQueue.main.async {
                            ContentView.logToFile("Failed to extract URL from dropped item")
                        }
                    }
                }
            } else {
                ContentView.logToFile("Provider does not have file URL identifier")
            }
        }
    }
    
    private func openPanel() {
        // Permissions are handled centrally by FileAccessCoordinator - no need to check on every browse
        ContentView.logToFile("🔐 File browser - using centralized permission system")

        Task {
            await MainActor.run {
                let panel = NSOpenPanel()
                panel.allowsMultipleSelection = true
                panel.allowedContentTypes = [UTType.init(filenameExtension: "docx") ?? UTType.data]
                panel.message = "Select Microsoft Word documents (.docx) to redact"

                if panel.runModal() == .OK {
                    viewModel.add(urls: panel.urls)
                    Task { await viewModel.refreshEnvironmentStatus() }
                }
            }
        }
    }
    
    private func startProcessing() {
        // Log that the button was clicked
        ContentView.logToFile("=== REDACT DOCUMENTS BUTTON CLICKED ===")
        ContentView.logToFile("hasValidDocuments: \(viewModel.hasValidDocuments)")
        ContentView.logToFile("isEnvironmentReady: \(viewModel.isEnvironmentReady)")
        ContentView.logToFile("isPreparing: \(isPreparing)")

        // Show preparing state immediately
        isStopping = false
        isPreparing = true
        ContentView.logToFile("Set isPreparing = true")

        // Use async to prevent blocking the main thread
        Task {
            // Small delay to show the preparing state
            try? await Task.sleep(nanoseconds: 100_000_000) // 0.1 second

            await MainActor.run {
                ContentView.logToFile("Creating NSOpenPanel")
                let panel = NSOpenPanel()
                panel.canChooseFiles = false
                panel.canChooseDirectories = true
                panel.canCreateDirectories = true
                panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
                panel.message = "Choose a folder to save the redacted documents and reports"
                panel.prompt = "Save Here"

                isPreparing = false // Reset preparing state after panel opens
                ContentView.logToFile("Set isPreparing = false before showing panel")

                ContentView.logToFile("About to show NSOpenPanel")
                if panel.runModal() == .OK, let destination = panel.url {
                    ContentView.logToFile("User selected destination: \(destination.path)")

                    // Validate destination
                    if let error = viewModel.validateDestination(destination) {
                        ContentView.logToFile("Destination validation failed: \(error)")
                        alertInfo = AlertInfo(title: "Destination Error", message: error)
                        return
                    }
                    ContentView.logToFile("Destination validation passed")

                    if viewModel.isPythonInitializing {
                        ContentView.logToFile("Python runtime still initializing")
                        alertInfo = AlertInfo(
                            title: "Please Wait",
                            message: "The AI engine is still warming up. Try again in a few seconds."
                        )
                        return
                    }

                    if let error = viewModel.pythonInitializationError {
                        ContentView.logToFile("Python initialization error: \(error)")
                        alertInfo = AlertInfo(
                            title: "Initialization Failed",
                            message: error
                        )
                        return
                    }

                    // Check environment before processing
                    if !viewModel.isEnvironmentReady {
                        ContentView.logToFile("Environment not ready: \(viewModel.environmentStatus)")
                        alertInfo = AlertInfo(
                            title: "Environment Not Ready",
                            message: viewModel.environmentStatus
                        )
                        viewModel.requestFirstRunSetup()
                        return
                    }
                    ContentView.logToFile("Environment ready, starting processAllDocuments task")

                    currentProcessingTask = Task {
                        await viewModel.processAllDocuments(to: destination)
                        // Ensure UI state is updated when processing completes
                        await MainActor.run {
                            currentProcessingTask = nil
                        }
                    }
                } else {
                    ContentView.logToFile("User cancelled panel or no destination selected")
                }

                // Always reset isPreparing when done
                isPreparing = false
            }
        }
    }

    private static func logToFile(_ message: String) {
        DebugLogger.shared.log(message, component: "ContentView")
    }
    
    private func stopProcessing() {
        isStopping = true
        currentProcessingTask?.cancel()
        currentProcessingTask = nil
        viewModel.stopProcessing()
    }
    
    /// Scrub metadata only - no rules or LLM redaction
    /// Uses saved metadata preferences from MetadataCleaningSettings
    private func startMetadataScrub() {
        ContentView.logToFile("=== SCRUB METADATA BUTTON CLICKED ===")
        ContentView.logToFile("hasValidDocuments: \(viewModel.hasValidDocuments)")

        // Show preparing state
        isStopping = false
        isPreparing = true
        
        Task {
            try? await Task.sleep(nanoseconds: 100_000_000) // 0.1 second
            
            await MainActor.run {
                let panel = NSOpenPanel()
                panel.canChooseFiles = false
                panel.canChooseDirectories = true
                panel.canCreateDirectories = true
                panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
                panel.message = "Choose a folder to save the metadata-scrubbed documents"
                panel.prompt = "Save Here"
                
                isPreparing = false
                
                if panel.runModal() == .OK, let destination = panel.url {
                    ContentView.logToFile("Metadata scrub destination: \(destination.path)")
                    
                    // Validate destination
                    if let error = viewModel.validateDestination(destination) {
                        alertInfo = AlertInfo(title: "Destination Error", message: error)
                        return
                    }
                    
                    // Start metadata-only processing
                    currentProcessingTask = Task {
                        await viewModel.scrubMetadataOnly(to: destination)
                        await MainActor.run {
                            currentProcessingTask = nil
                        }
                    }
                }
                
                isPreparing = false
            }
        }
    }
}

// MARK: - Document List View
struct DocumentListView: View {
    @ObservedObject var viewModel: DocumentRedactionViewModel
    @Binding var alertInfo: AlertInfo?
    @Environment(\.colorScheme) private var colorScheme
    
    var body: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(viewModel.items) { item in
                    Group {
                        if item.status == .failed || item.status == .invalidDocument {
                            DocumentRow(item: item, viewModel: viewModel, alertInfo: $alertInfo)
                                .onTapGesture { handleTap(on: item) }
                        } else {
                            DocumentRow(item: item, viewModel: viewModel, alertInfo: $alertInfo)
                        }
                    }
                    .animation(.easeInOut(duration: 0.2), value: item.status)
                }
            }
            .padding(.horizontal, 4)
        }
        .scrollContentBackground(.hidden)
    }
    
    private func handleTap(on item: DocumentItem) {
        switch item.status {
        case .failed:
            if let message = item.errorMessage {
                alertInfo = AlertInfo(title: "Processing Failed", message: message)
            }
        case .invalidDocument:
            if let message = item.errorMessage {
                alertInfo = AlertInfo(title: "Invalid Document", message: message)
            }
        case .completed:
            // Show completion options
            break
        default:
            break
        }
    }
}

// MARK: - Document Row
struct DocumentRow: View {
    @ObservedObject var item: DocumentItem
    @ObservedObject var viewModel: DocumentRedactionViewModel
    @State private var currentTime = Date()
    @Binding var alertInfo: AlertInfo?
    @Environment(\.colorScheme) private var colorScheme
    
    let timer = Timer.publish(every: 1, on: .main, in: .common).autoconnect()
    private let heartbeatTimeout: TimeInterval = 30.0
    
    var body: some View {
        HStack(spacing: 12) {
            // Trash button to remove this document
            Button(action: { viewModel.removeDocument(item) }) {
                Image(systemName: "trash")
                    .font(.system(size: 20, weight: .medium))
                    .foregroundColor(iconColor)
                    .frame(width: 24, height: 24)
            }
            .buttonStyle(.plain)
            .disabled(item.status.isProcessing)
            .opacity(item.status.isProcessing ? 0.3 : 1.0)
            .help("Remove from list")
            
            // Status icon
            Image(systemName: iconName)
                .font(.system(size: 20, weight: .medium))
                .foregroundColor(iconColor)
                .frame(width: 24, height: 24)
            
            // Document info and progress
            VStack(alignment: .leading, spacing: 6) {
                // Document name
                Text(item.url.lastPathComponent)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .font(.system(size: 15, weight: .medium, design: .default))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                
                // Enhanced status display for processing documents
                if item.status.isProcessing {
                    VStack(alignment: .leading, spacing: 8) {
                        HeartbeatStatusView(
                            item: item,
                            stageColor: getStageColor(item.currentStage),
                            heartbeatTimeout: heartbeatTimeout
                        )

                        HStack {
                            Spacer()
                            CountdownTimerView(
                                remainingSeconds: item.estimatedTimeRemaining,
                                isActive: item.status.isProcessing
                            )
                        }

                        ProgressView(value: item.progress)
                            .progressViewStyle(LinearProgressViewStyle(tint: getStageColor(item.currentStage)))
                            .frame(height: 4)
                            .background(Color.gray.opacity(0.1))
                            .cornerRadius(2)
                    }
                }
            }
            
            Spacer(minLength: 12)
            
            if item.status.isComplete {
                // Action buttons for completed items with enhanced tooltips
                HStack(spacing: 8) {
                    TooltipButton(
                        action: { performUserAction(failureMessage: "The document is not available yet.") { viewModel.openRedactedDocument(item) } },
                        icon: "doc.text.fill",
                        tooltip: item.reportOutputURL != nil ? "Open Redacted Document" : "Open Metadata Scrubbed Document",
                        description: item.reportOutputURL != nil ? "Opens the redacted .docx file with sensitive information removed" : "Opens the metadata-cleaned .docx file",
                        isEnabled: item.redactedOutputURL != nil
                    )

                    TooltipButton(
                        action: { performUserAction(failureMessage: "Output files could not be revealed in Finder.") { viewModel.revealInFinder(item) } },
                        icon: "folder.fill",
                        tooltip: "Show in Finder",
                        description: "Reveals output files in Finder for easy access",
                        isEnabled: item.redactedOutputURL != nil || item.reportOutputURL != nil || item.scrubReportOutputURL != nil
                    )
                    
                    // Show redaction report button if available
                    if item.reportOutputURL != nil {
                        TooltipButton(
                            action: { performUserAction(failureMessage: "The audit report is not available yet.") { viewModel.openReport(item) } },
                            icon: "list.clipboard.fill",
                            tooltip: "View Audit Report",
                            description: "Shows detailed report of all detected entities and redactions",
                            isEnabled: true
                        )
                    }
                    
                    // Show scrub report button (always available, enabled if URL exists)
                    TooltipButton(
                        action: { performUserAction(failureMessage: "The scrub report is not available yet.") { viewModel.openScrubReport(item) } },
                        icon: "doc.badge.gearshape.fill",
                        tooltip: "View Scrub Report",
                        description: "Shows detailed report of cleaned metadata and remaining items",
                        isEnabled: item.scrubReportOutputURL != nil
                    )
                }
            } else if !item.status.isProcessing {
                StatusView(status: item.status)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 16)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(CustomColors.cardBackground(for: colorScheme))
                .shadow(color: colorScheme == .dark ? Color.black.opacity(0.2) : Color.black.opacity(0.03), radius: 6, x: 0, y: 1)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(CustomColors.subtleBorder(for: colorScheme), lineWidth: 1)
        )
        .onReceive(timer) { _ in
            currentTime = Date()
            if item.status.isProcessing {
                item.updateEstimatesForCurrentTime()
            }
        }
    }
    
    private var iconName: String {
        switch item.status {
        case .checking: return "doc.text.magnifyingglass"
        case .validDocument: return "doc.text.fill"
        case .invalidDocument: return "doc.badge.exclamationmark"
        case .processing, .analyzing, .redacting: return "doc.text.magnifyingglass"
        case .completed: return "checkmark.circle.fill"
        case .failed: return "xmark.circle.fill"
        case .cancelled: return "stop.circle.fill"
        }
    }
    
    private var iconColor: Color {
        switch item.status {
        case .validDocument, .completed: return CustomColors.accentColor(for: colorScheme)
        case .invalidDocument, .failed: return CustomColors.destructiveColor(for: colorScheme)
        case .cancelled: return CustomColors.secondaryText(for: colorScheme)
        default: return CustomColors.accentColor(for: colorScheme)
        }
    }
    
    private func getStageColor(_ stage: ProcessingStage) -> Color {
        switch stage {
        case .preflight: return .blue
        case .ruleDetection: return .green
        case .llmValidation: return .orange
        case .enhancedDetection: return .purple
        case .merging: return .indigo
        case .outputGeneration: return .teal
        }
    }
    
    private func performUserAction(failureMessage: String, action: () -> Bool) {
        guard action() else {
            alertInfo = AlertInfo(title: "Action Unavailable", message: failureMessage)
            return
        }
    }
}

// MARK: - Status View
struct StatusView: View {
    let status: RedactionStatus
    @Environment(\.colorScheme) private var colorScheme
    
    var body: some View {
        Group {
            switch status {
            case .checking:
                HStack(spacing: 6) {
                    ProgressView()
                        .scaleEffect(0.8)
                        .frame(width: 12, height: 12)
                    Text(status.displayText)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(CustomColors.accentColor(for: colorScheme))
                }
            case .processing, .analyzing, .redacting:
                HStack(spacing: 6) {
                    ProgressView()
                        .scaleEffect(0.8)
                        .frame(width: 12, height: 12)
                    Text(status.displayText)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(CustomColors.accentColor(for: colorScheme))
                }
            case .validDocument:
                Text(status.displayText)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(CustomColors.accentColor(for: colorScheme))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(
                        RoundedRectangle(cornerRadius: 6)
                            .fill(CustomColors.accentColor(for: colorScheme).opacity(0.1))
                    )
            case .completed:
                Text(status.displayText)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(CustomColors.accentColor(for: colorScheme))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(
                        RoundedRectangle(cornerRadius: 6)
                            .fill(CustomColors.accentColor(for: colorScheme).opacity(0.15))
                    )
            case .failed, .invalidDocument:
                Text(status.displayText)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(CustomColors.destructiveColor(for: colorScheme))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(
                        RoundedRectangle(cornerRadius: 6)
                            .fill(CustomColors.destructiveColor(for: colorScheme).opacity(0.1))
                    )
            case .cancelled:
                Text(status.displayText)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(
                        RoundedRectangle(cornerRadius: 6)
                            .fill(CustomColors.secondaryText(for: colorScheme).opacity(0.1))
                    )
            }
        }
        .transition(.opacity.combined(with: .scale))
    }
}

// MARK: - Footer View
struct FooterView: View {
    @Environment(\.colorScheme) private var colorScheme
    var body: some View {
        VStack(spacing: 6) {
            HStack(spacing: 4) {
                Text("Released by Marc Mandel under the MIT license at")
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                Link("github.com/LegalMarc/Marcut", destination: URL(string: "https://github.com/LegalMarc/Marcut")!)
            }
            .lineLimit(2)
            .multilineTextAlignment(.center)
            .font(.system(size: 13, weight: .medium))
            
            HStack(spacing: 4) {
                Text("Got bugs? Message me at")
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                Link("linkedin.com/in/marcmandel/", destination: URL(string: "https://www.linkedin.com/in/marcmandel/")!)
            }
            .lineLimit(2)
            .multilineTextAlignment(.center)
            .font(.system(size: 13, weight: .medium))
            

        }
        .multilineTextAlignment(.center)
        .padding(.top, 8)
    }
}

struct EnvironmentStatusBanner: View {
    @ObservedObject var viewModel: DocumentRedactionViewModel
    @Environment(\.colorScheme) private var colorScheme

    @State private var animationDotCount = 0
    @State private var timer: Timer?

    private var frameworkStatus: (String, Color, String) {
        viewModel.frameworkAvailable
            ? ("checkmark.circle.fill", .green, "Framework ready")
            : ("exclamationmark.triangle.fill", .orange, "Framework missing")
    }

    private var ollamaStatus: (String, Color, String) {
        viewModel.ollamaRunning
            ? ("bolt.circle.fill", .green, "Ollama running")
            : ("bolt.slash.fill", .orange, "Ollama offline")
    }
    
    private var environmentStatusComponents: (String, String?) {
        let baseStatus = viewModel.environmentStatus
        if baseStatus.contains("Starting") {
            let dots = String(repeating: ".", count: animationDotCount)
            // Clean status text (remove any existing dots just in case)
            let cleanStatus = baseStatus.replacingOccurrences(of: "...", with: "")
                                        .replacingOccurrences(of: "..", with: "")
                                        .trimmingCharacters(in: .punctuationCharacters)
            return (cleanStatus, dots)
        }
        return (baseStatus, nil)
    }

    var body: some View {
        HStack(spacing: 16) {
            StatusLabel(icon: frameworkStatus.0, color: frameworkStatus.1, text: frameworkStatus.2)
            StatusLabel(icon: ollamaStatus.0, color: ollamaStatus.1, text: ollamaStatus.2)
            StatusLabel(icon: "shippingbox.fill", color: viewModel.availableModels.isEmpty ? .orange : .blue, text: "\(viewModel.availableModels.count) models")
            Spacer()
            
            // Simplified ready status - just checkmark and "Ready with AI"
            if viewModel.isEnvironmentReady {
                StatusLabel(
                    icon: "checkmark.circle.fill", 
                    color: .green, 
                    text: "Ready with AI",
                    animatingDots: nil
                )
            } else {
                let (statusText, dots) = environmentStatusComponents
                StatusLabel(
                    icon: "hourglass", 
                    color: .orange, 
                    text: statusText,
                    animatingDots: dots
                )
            }
        }
        .font(.system(size: 12, weight: .medium))
        .foregroundColor(CustomColors.primaryText(for: colorScheme))
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(CustomColors.contentBackground(for: colorScheme).opacity(0.85))
                .shadow(color: Color.black.opacity(0.05), radius: 4, y: 1)
        )
        .padding(.horizontal, 4)
        .onAppear {
            startAnimation()
        }
        .onDisappear {
            stopAnimation()
        }
    }
    
    private func startAnimation() {
        stopAnimation()
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
            Task { @MainActor in
                if viewModel.environmentStatus.contains("Starting") {
                    withAnimation {
                        animationDotCount = (animationDotCount + 1) % 4
                    }
                } else {
                    animationDotCount = 0
                }
            }
        }
    }
    
    private func stopAnimation() {
        timer?.invalidate()
        timer = nil
    }

    private struct StatusLabel: View {
        let icon: String
        let color: Color
        let text: String
        var animatingDots: String? = nil

        var body: some View {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .foregroundColor(color)
                
                HStack(spacing: 0) {
                    Text(text)
                    if let dots = animatingDots {
                        Text(dots)
                            .frame(width: 12, alignment: .leading)
                    }
                }
            }
        }
    }
}

// MARK: - Enhanced Progress Components

extension DocumentRow {
    private func formatTimeRemaining(_ timeInterval: TimeInterval) -> String {
        let minutes = Int(timeInterval) / 60
        let seconds = Int(timeInterval) % 60
        
        if minutes > 60 {
            let hours = minutes / 60
            let remainingMinutes = minutes % 60
            return String(format: "%dh %02dm", hours, remainingMinutes)
        } else if minutes > 0 {
            return String(format: "%dm %02ds", minutes, seconds)
        } else {
            return String(format: "%ds", seconds)
        }
    }
}


// Countdown timer component
struct CountdownTimerView: View {
    let remainingSeconds: TimeInterval
    let isActive: Bool
    @Environment(\.colorScheme) private var colorScheme
    
    var body: some View {
        Group {
            if isActive {
                HStack(spacing: 2) {
                    Image(systemName: remainingSeconds > 0 ? "clock" : "hourglass")
                        .font(.system(size: 10, weight: .medium))
                        .foregroundColor(CustomColors.accentColor(for: colorScheme))

                    Text(remainingSeconds > 0 ? formatTime(remainingSeconds) : "Processing...")
                        .font(.system(size: 12, weight: .semibold, design: .monospaced))
                        .foregroundColor(CustomColors.accentColor(for: colorScheme))
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(
                    Capsule()
                        .fill(CustomColors.accentColor(for: colorScheme).opacity(0.1))
                        .overlay(
                            Capsule()
                                .stroke(CustomColors.accentColor(for: colorScheme).opacity(0.2), lineWidth: 0.5)
                        )
                )
            } else if !isActive {
                HStack(spacing: 2) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.green)
                    
                    Text("Done")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundColor(.green)
                }
                .padding(.horizontal, 8)
                .padding(.vertical, 3)
                .background(
                    Capsule()
                        .fill(Color.green.opacity(0.1))
                )
            }
        }
    }
    
    private func formatTime(_ timeInterval: TimeInterval) -> String {
        let totalSeconds = Int(timeInterval)
        let minutes = totalSeconds / 60
        let seconds = totalSeconds % 60
        
        if minutes > 60 {
            let hours = minutes / 60
            let remainingMinutes = minutes % 60
            return String(format: "%dh %02dm", hours, remainingMinutes)
        } else if minutes > 0 {
            return String(format: "%dm %02ds", minutes, seconds)
        } else {
            return String(format: "%ds", seconds)
        }
    }
}

struct HeartbeatStatusView: View {
    @ObservedObject var item: DocumentItem
    let stageColor: Color
    let heartbeatTimeout: TimeInterval
    @Environment(\.colorScheme) private var colorScheme

    private var heartbeatSummary: (String, Color) {
        guard let last = item.lastHeartbeat else {
            return ("Awaiting heartbeat", CustomColors.secondaryText(for: colorScheme))
        }
        let elapsed = Date().timeIntervalSince(last)
        if elapsed > heartbeatTimeout {
            return ("No response for \(Int(elapsed))s", .red)
        }
        if elapsed < 1 {
            return ("Heartbeat just now", CustomColors.secondaryText(for: colorScheme))
        }
        return ("Updated \(Int(elapsed))s ago", CustomColors.secondaryText(for: colorScheme))
    }

    private var chunkSummary: String {
        if item.totalHeartbeatChunks > 0 {
            let current = max(1, min(item.lastHeartbeatChunk, item.totalHeartbeatChunks))
            return "Chunk \(current)/\(item.totalHeartbeatChunks)"
        }
        return "Chunk pending"
    }

    var body: some View {
        let (statusText, statusColor) = heartbeatSummary
        HStack(spacing: 10) {
            Image(systemName: "waveform.path.ecg")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(statusColor == .red ? .red : stageColor)

            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(item.currentStage.displayName)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(CustomColors.primaryText(for: colorScheme))

                    Text(chunkSummary)
                        .font(.system(size: 11, weight: .medium))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                }

                Text(statusText)
                    .font(.system(size: 11))
                    .foregroundColor(statusColor)
            }

            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(CustomColors.contentBackground(for: colorScheme).opacity(0.8))
        )
    }
}

// MARK: - Enhanced Tooltip Button
struct TooltipButton: View {
    let action: () -> Void
    let iconView: (Color) -> AnyView
    let tooltip: String
    let description: String
    var isEnabled: Bool = true  // Default to enabled
    let iconName: String?

    // Hover state purely for scaling effect, unrelated to popup
    @State private var isHovered = false
    @Environment(\.colorScheme) private var colorScheme

    init(
        action: @escaping () -> Void,
        icon: String,
        tooltip: String,
        description: String,
        isEnabled: Bool = true
    ) {
        self.action = action
        self.tooltip = tooltip
        self.description = description
        self.isEnabled = isEnabled
        self.iconName = icon
        self.iconView = { color in
            AnyView(
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .medium))
                    .foregroundColor(color)
            )
        }
    }

    init(
        action: @escaping () -> Void,
        iconView: @escaping (Color) -> AnyView,
        tooltip: String,
        description: String,
        isEnabled: Bool = true
    ) {
        self.action = action
        self.iconView = iconView
        self.tooltip = tooltip
        self.description = description
        self.isEnabled = isEnabled
        self.iconName = nil
    }

    var body: some View {
        let iconColor = isEnabled ? CustomColors.accentColor(for: colorScheme) : Color.gray.opacity(0.4)
        Button(action: isEnabled ? action : {}) {
            iconView(iconColor)
                .frame(width: 20, height: 20)
                .contentShape(Rectangle())
                .scaleEffect(isHovered ? 1.1 : 1.0)
                .animation(.easeInOut(duration: 0.15), value: isHovered)
        }
        .frame(width: 28, height: 28)
        .contentShape(Rectangle())
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .onHover { hovering in
            isHovered = isEnabled ? hovering : false
        }
        .help(isEnabled ? "\(tooltip): \(description)" : "\(tooltip): Not available")
    }
}
