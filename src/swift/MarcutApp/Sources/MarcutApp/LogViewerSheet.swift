import AppKit
import SwiftUI

/// Sheet that lets users view app log files in-app instead of navigating Finder to
/// `~/Library/Application Support/MarcutApp/logs`. Shows the most recently modified log by
/// default, with a picker to switch between files if more than one exists.
struct LogViewerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme

    @State private var logFiles: [URL] = []
    @State private var selectedLogFile: URL?
    @State private var logContent: String = ""
    @State private var loadError: String?

    private let logsDirectoryURL: URL

    init(logsDirectoryURL: URL = DebugLogger.shared.logsDirectoryURL) {
        self.logsDirectoryURL = logsDirectoryURL
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            header

            if logFiles.isEmpty {
                emptyState
            } else {
                if logFiles.count > 1 {
                    filePicker
                }
                logContentView
            }

            footer
        }
        .padding(24)
        .frame(minWidth: 640, minHeight: 480)
        .background(CustomColors.cardBackground(for: colorScheme))
        .onAppear { reload() }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text("View Logs")
                .font(.title2)
                .fontWeight(.semibold)
                .foregroundColor(CustomColors.primaryText(for: colorScheme))
            Text("Diagnostic logs from \(logsDirectoryURL.path)")
                .font(.caption)
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
        }
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Spacer()
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 36))
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            Text("No logs yet")
                .font(.headline)
                .foregroundColor(CustomColors.primaryText(for: colorScheme))
            Text("Enable debug logging in Settings and run a redaction to generate log output.")
                .font(.caption)
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                .multilineTextAlignment(.center)
                .frame(maxWidth: 360)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .accessibilityIdentifier("logViewer.emptyState")
    }

    private var filePicker: some View {
        Picker("Log File", selection: Binding(
            get: { selectedLogFile ?? logFiles.first },
            set: { newValue in
                selectedLogFile = newValue
                loadSelectedLogContent()
            }
        )) {
            ForEach(logFiles, id: \.self) { url in
                Text(url.lastPathComponent).tag(Optional(url))
            }
        }
        .pickerStyle(.menu)
        .labelsHidden()
        .frame(maxWidth: 320, alignment: .leading)
        .accessibilityIdentifier("logViewer.filePicker")
    }

    @ViewBuilder
    private var logContentView: some View {
        if let loadError {
            Text(loadError)
                .font(.callout)
                .foregroundColor(CustomColors.destructiveColor(for: colorScheme))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        } else if logContent.isEmpty {
            Text("This log file is empty.")
                .font(.callout)
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        } else {
            ScrollView([.vertical, .horizontal]) {
                Text(logContent)
                    .font(.system(size: 11, design: .monospaced))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(8)
            }
            .background(Color(NSColor.textBackgroundColor))
            .border(CustomColors.subtleBorder(for: colorScheme))
            .accessibilityIdentifier("logViewer.content")
        }
    }

    private var footer: some View {
        HStack(spacing: 12) {
            Button("Reveal in Finder") {
                revealInFinder()
            }
            .buttonStyle(.bordered)
            .accessibilityIdentifier("logViewer.revealInFinder")

            Spacer()

            Button("Close") {
                dismiss()
            }
            .buttonStyle(.borderedProminent)
            .accessibilityIdentifier("logViewer.close")
        }
    }

    private func reload() {
        logFiles = DebugLogger.discoverLogFiles(in: logsDirectoryURL)
        selectedLogFile = logFiles.first
        loadSelectedLogContent()
    }

    private func loadSelectedLogContent() {
        guard let selectedLogFile else {
            logContent = ""
            loadError = nil
            return
        }
        do {
            logContent = try String(contentsOf: selectedLogFile, encoding: .utf8)
            loadError = nil
        } catch {
            logContent = ""
            loadError = "Unable to read log file: \(error.localizedDescription)"
        }
    }

    private func revealInFinder() {
        if let selectedLogFile, FileManager.default.fileExists(atPath: selectedLogFile.path) {
            NSWorkspace.shared.activateFileViewerSelecting([selectedLogFile])
        } else {
            NSWorkspace.shared.open(logsDirectoryURL)
        }
    }
}

#Preview {
    LogViewerSheet(logsDirectoryURL: FileManager.default.temporaryDirectory)
}
