import AppKit
import Foundation

/// Share/export flow collaborator, extracted from `DocumentRedactionViewModel`
/// (`docs/design/view_controller_decomposition.md` §2.1, slice 6). Small and self-contained --
/// it already reads like a service, constructing its own `NSAlert`s. Takes the runner provider
/// and `applyMetadataSettingsEnvironment` as constructor closures (the latter stays owned by the
/// view model/`ProcessRunner` until #110, since other call sites besides this flow use it too)
/// rather than reaching back into the view model directly. `shareFinalRedactedCopy` reports its
/// error back by returning it instead of mutating `DocumentItem.errorMessage` itself; callers
/// (the view model's forwarding method, and this service's own `shareDocument`) apply it.
@MainActor
final class DocumentShareService {
    /// Resolves the embedded-Python runner, mirroring `DocumentRedactionViewModel.runnerProvider`
    /// -- a closure rather than a stored snapshot for the same reason as that property (the
    /// runner is assigned asynchronously after construction).
    private let runnerProvider: () -> (any RedactionRunning)?
    private let applyMetadataSettingsEnvironment: (MetadataCleaningSettings, String) -> Void

    /// Presents the share sheet for a finished document. `lazy` so the default can reference
    /// `self.presentSharePicker(for:)`, and overridable so tests can avoid
    /// `shareFinalRedactedCopy`/`confirmAndShareReviewCopy` opening Finder via
    /// `NSWorkspace.activateFileViewerSelecting`. Moved verbatim from
    /// `DocumentRedactionViewModel` (the `sharePresenter` seam from #98).
    lazy var sharePresenter: (URL) -> Bool = { [weak self] url in
        self?.presentSharePicker(for: url) ?? false
    }

    init(
        runnerProvider: @escaping () -> (any RedactionRunning)?,
        applyMetadataSettingsEnvironment: @escaping (MetadataCleaningSettings, String) -> Void
    ) {
        self.runnerProvider = runnerProvider
        self.applyMetadataSettingsEnvironment = applyMetadataSettingsEnvironment
    }

    // MARK: - Output Management

    @discardableResult
    func openRedactedDocument(_ item: DocumentItem) -> Bool {
        guard let url = item.redactedOutputURL else { return false }
        return NSWorkspace.shared.open(url)
    }

    @discardableResult
    func shareDocument(_ item: DocumentItem) -> Bool {
        guard item.redactedOutputURL != nil || item.scrubOutputURL != nil else {
            item.errorMessage = "No DOCX output is available to send."
            return false
        }

        let alert = NSAlert()
        alert.messageText = "Send Document"
        alert.informativeText = "Choose the DOCX you want to send.\n\n"
            + "Final redacted copy accepts Marcut's redaction Track Changes in a new copy and scrubs metadata before sending.\n\n"
            + "Review copy sends the current review artifact with Track Changes and metadata exactly as they are in that file."
        alert.alertStyle = .warning
        alert.addButton(withTitle: "Send Final Redacted Copy")
        alert.addButton(withTitle: "Send Review Copy")
        alert.addButton(withTitle: "Cancel")

        switch alert.runModal() {
        case .alertFirstButtonReturn:
            Task { [weak self, weak item] in
                guard let self, let item else { return }
                item.errorMessage = await self.shareFinalRedactedCopy(item)
            }
            return true
        case .alertSecondButtonReturn:
            return confirmAndShareReviewCopy(item)
        default:
            return false
        }
    }

    private func confirmAndShareReviewCopy(_ item: DocumentItem) -> Bool {
        guard let url = item.redactedOutputURL ?? item.scrubOutputURL else { return false }

        let alert = NSAlert()
        alert.messageText = "Send Review Copy?"
        alert.informativeText = """
        This sends the current DOCX review artifact. It may contain recoverable original text in Track Changes and document metadata. Use this only when the recipient should review proposed redactions with full context.
        """
        alert.alertStyle = .critical
        alert.addButton(withTitle: "Send Review Copy")
        alert.addButton(withTitle: "Cancel")

        guard alert.runModal() == .alertFirstButtonReturn else { return false }
        return sharePresenter(url)
    }

    /// Scrubs a final, maximum-privacy copy and hands it to `sharePresenter`. Returns an error
    /// message on failure, `nil` on success -- see the type doc for why this returns rather than
    /// mutating `item.errorMessage` directly.
    func shareFinalRedactedCopy(_ item: DocumentItem) async -> String? {
        guard let sourceURL = item.redactedOutputURL ?? item.scrubOutputURL else {
            return "No DOCX output is available to finalize."
        }
        guard let runner = runnerProvider() else {
            return "The Python runtime is not available to finalize this document."
        }

        let finalURL = DocumentRedactionViewModel.finalRedactedCopyURL(for: sourceURL)
        let previousPreset = getenv("MARCUT_METADATA_PRESET").map { String(cString: $0) }
        let previousArgs = getenv("MARCUT_METADATA_ARGS").map { String(cString: $0) }
        let previousSettingsJSON = getenv("MARCUT_METADATA_SETTINGS_JSON").map { String(cString: $0) }

        applyMetadataSettingsEnvironment(.maximumPrivacy, "final share copy")
        defer {
            restoreEnvironmentValue(previousPreset, forKey: "MARCUT_METADATA_PRESET")
            restoreEnvironmentValue(previousArgs, forKey: "MARCUT_METADATA_ARGS")
            restoreEnvironmentValue(previousSettingsJSON, forKey: "MARCUT_METADATA_SETTINGS_JSON")
        }

        do {
            let result = try await runner.scrubMetadataOnlyAsync(
                inputPath: sourceURL.path,
                outputPath: finalURL.path
            )
            guard result.success else {
                try? FileManager.default.removeItem(at: finalURL)
                return result.error ?? "Unable to create the final redacted copy."
            }
            _ = sharePresenter(finalURL)
            return nil
        } catch {
            try? FileManager.default.removeItem(at: finalURL)
            return "Unable to create the final redacted copy: \(error.localizedDescription)"
        }
    }

    private func restoreEnvironmentValue(_ value: String?, forKey key: String) {
        if let value {
            setenv(key, value, 1)
        } else {
            unsetenv(key)
        }
    }

    @discardableResult
    private func presentSharePicker(for url: URL) -> Bool {
        guard FileManager.default.fileExists(atPath: url.path) else { return false }
        guard let view = NSApp.keyWindow?.contentView else {
            NSWorkspace.shared.activateFileViewerSelecting([url])
            return true
        }
        let picker = NSSharingServicePicker(items: [url])
        picker.show(relativeTo: .zero, of: view, preferredEdge: .minY)
        return true
    }
}
