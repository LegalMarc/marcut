import SwiftUI

/// A single supported model entry, loaded from the bundled `models.json`
/// catalog. Mirrors `marcut.model_config.ModelConfig` on the Python side --
/// if you change this schema, update that module too (and vice versa).
struct ModelCatalogEntry: Codable, Equatable, Identifiable {
    var id: String
    var displayName: String
    var description: String
    var setupDescription: String
    var processingTime: String
    var sizeLabel: String
    var badge: String
    var accentColor: String
    var temperature: Double
    var skipConfidence: Double

    /// Resolve the symbolic `accentColor` string from `models.json` into a
    /// SwiftUI `Color`. `"accent"` defers to `CustomColors.accentColor(for:)`
    /// since that one depends on the current color scheme.
    func resolvedAccentColor(for colorScheme: ColorScheme) -> Color {
        switch accentColor {
        case "accent":
            return CustomColors.accentColor(for: colorScheme)
        case "orange":
            return Color.orange
        case "green":
            return Color.green
        case "purple":
            return Color.purple
        default:
            return CustomColors.accentColor(for: colorScheme)
        }
    }
}

private struct ModelCatalogFile: Codable {
    var defaultModel: String
    var models: [ModelCatalogEntry]
}

enum ModelCatalogError: Error {
    case resourceNotFound
    case invalidJSON(Error)
    case emptyCatalog
    case defaultModelNotListed(String)
}

/// Loads and exposes the shared `models.json` catalog of supported Ollama
/// models and their default parameters. Replaces the hardcoded model tuples
/// that used to live directly in `SettingsView.swift` /
/// `DocumentRedactionViewModel.swift`.
final class ModelCatalog {
    static let shared = ModelCatalog()

    let models: [ModelCatalogEntry]
    let defaultModelId: String

    /// All supported model identifiers, in catalog order.
    var modelIds: Set<String> {
        Set(models.map { $0.id })
    }

    private init() {
        if let loaded = try? ModelCatalog.load() {
            models = loaded.models
            defaultModelId = loaded.defaultModel
        } else {
            // Fail-soft fallback so the app remains usable if the bundled
            // resource is somehow missing; matches the values that were
            // previously hardcoded here.
            let fallback = ModelCatalogEntry(
                id: "qwen2.5:14b",
                displayName: "Qwen 2.5 14B",
                description: "Gold standard. Best accuracy for legal & complex documents.",
                setupDescription: "Gold standard. Best accuracy for legal & complex documents. Recommended.",
                processingTime: "~50s",
                sizeLabel: "9.0 GB",
                badge: "Best",
                accentColor: "accent",
                temperature: 0.1,
                skipConfidence: 0.95
            )
            models = [fallback]
            defaultModelId = fallback.id
        }
    }

    func entry(for modelId: String) -> ModelCatalogEntry? {
        models.first { $0.id == modelId }
    }

    private static func load() throws -> ModelCatalogFile {
        guard let url = BundleResourceLocator.resolveDefaultResourceURL(named: "models", ext: "json") else {
            throw ModelCatalogError.resourceNotFound
        }
        let data = try Data(contentsOf: url)
        let file: ModelCatalogFile
        do {
            file = try JSONDecoder().decode(ModelCatalogFile.self, from: data)
        } catch {
            throw ModelCatalogError.invalidJSON(error)
        }
        guard !file.models.isEmpty else {
            throw ModelCatalogError.emptyCatalog
        }
        guard file.models.contains(where: { $0.id == file.defaultModel }) else {
            throw ModelCatalogError.defaultModelNotListed(file.defaultModel)
        }
        return file
    }
}
