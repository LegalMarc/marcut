import AppKit
import Foundation
import UniformTypeIdentifiers

/// Settings-profile export/import glue, extracted from `SettingsView`
/// (`docs/design/view_controller_decomposition.md` §2.2, slice 6). Panel presentation is behind
/// injectable closures -- defaulting to a real `NSSavePanel`/`NSOpenPanel` -- so the encode/write
/// and read/decode paths are testable without driving a modal AppKit panel. `SettingsView` keeps
/// ownership of `localSettings`/`metadataSettings`/`profileErrorMessage`/`profileImportSucceeded`
/// (they are core view state read elsewhere in the view too); this type only performs the
/// encode/write and read/decode work moved verbatim from
/// `exportSettingsProfile()`/`importSettingsProfile()`.
@MainActor
final class SettingsProfileIO {
    var presentSavePanel: @MainActor () -> URL?
    var presentOpenPanel: @MainActor () -> URL?

    init(
        presentSavePanel: @escaping @MainActor () -> URL? = { SettingsProfileIO.defaultSavePanel() },
        presentOpenPanel: @escaping @MainActor () -> URL? = { SettingsProfileIO.defaultOpenPanel() }
    ) {
        self.presentSavePanel = presentSavePanel
        self.presentOpenPanel = presentOpenPanel
    }

    /// Encodes `profile` and writes it to the destination the user picks via `presentSavePanel`.
    /// Returns an error message on failure (encode or write); `nil` on success or if the user
    /// cancels the panel. Mirrors the old `SettingsView.exportSettingsProfile()` body verbatim.
    func exportProfile(_ profile: RedactionProfile) -> String? {
        let data: Data
        do {
            data = try profile.encoded()
        } catch {
            return "Could not prepare the profile for export: \(error.localizedDescription)"
        }

        guard let destinationURL = presentSavePanel() else { return nil }

        let securityScopedURL = destinationURL.deletingLastPathComponent()
        let didStartAccess = securityScopedURL.startAccessingSecurityScopedResource()
        defer {
            if didStartAccess {
                securityScopedURL.stopAccessingSecurityScopedResource()
            }
        }

        do {
            try data.write(to: destinationURL, options: .atomic)
            return nil
        } catch {
            return "Could not write the profile file: \(error.localizedDescription)"
        }
    }

    /// Presents an open panel via `presentOpenPanel` and decodes the chosen file into a
    /// `RedactionProfile`. Returns `nil` if the user cancels the panel; throws on read/decode
    /// failure. Mirrors the old `SettingsView.importSettingsProfile()` body verbatim.
    func importProfile() throws -> RedactionProfile? {
        guard let sourceURL = presentOpenPanel() else { return nil }

        let didStartAccess = sourceURL.startAccessingSecurityScopedResource()
        defer {
            if didStartAccess {
                sourceURL.stopAccessingSecurityScopedResource()
            }
        }

        let data = try Data(contentsOf: sourceURL)
        return try RedactionProfile.decoded(from: data)
    }

    static func defaultSavePanel() -> URL? {
        let panel = NSSavePanel()
        panel.title = "Export Settings Profile"
        panel.nameFieldStringValue = "Marcut Settings Profile.json"
        panel.allowedContentTypes = [UTType.json]
        panel.canCreateDirectories = true
        panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first

        guard panel.runModal() == .OK else { return nil }
        return panel.url
    }

    static func defaultOpenPanel() -> URL? {
        let panel = NSOpenPanel()
        panel.title = "Import Settings Profile"
        panel.canChooseDirectories = false
        panel.canChooseFiles = true
        panel.allowsMultipleSelection = false
        panel.allowedContentTypes = [UTType.json]
        panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first

        guard panel.runModal() == .OK else { return nil }
        return panel.url
    }
}
