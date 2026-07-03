import Foundation

/// Shared bundled-resource lookup used by anything that ships a default file
/// inside the app bundle (excluded-words.txt, system-prompt.txt, models.json, ...).
///
/// Centralizing this avoids re-implementing the bundle/dev-path search order
/// (App Bundle -> Swift Package resource bundle -> `Bundle.module` (debug) ->
/// known development-tree relative paths) in every manager that owns a
/// bundled default file. See `UserOverridesManager` and `ModelCatalog` for
/// callers.
enum BundleResourceLocator {
    static func resolveDefaultResourceURL(
        named name: String,
        ext: String,
        fileManager: FileManager = .default
    ) -> URL? {
        // 1. Check App Bundle
        if let url = Bundle.main.url(forResource: name, withExtension: ext) {
            return url
        }

        // 2. Check Package Bundle (e.g. if we are inside a Swift Package structure)
        if let packageURL = Bundle.main.url(forResource: "MarcutApp_MarcutApp", withExtension: "bundle"),
           let packageBundle = Bundle(url: packageURL) {
            if let url = packageBundle.url(forResource: name, withExtension: ext) {
                return url
            }
            if let url = packageBundle.url(forResource: name, withExtension: ext, subdirectory: "Resources") {
                return url
            }
        }

        #if SWIFT_PACKAGE && DEBUG
        if let url = Bundle.module.url(forResource: name, withExtension: ext) ??
            Bundle.module.url(forResource: name, withExtension: ext, subdirectory: "Resources") {
            return url
        }
        #endif

        // 3. Check development paths (relative to CWD or known locations)
        let candidatePaths = [
            "Resources/\(name).\(ext)",
            "\(name).\(ext)",
            "MarcutApp/Sources/MarcutApp/Resources/\(name).\(ext)",
            "src/swift/MarcutApp/Sources/MarcutApp/Resources/\(name).\(ext)",
            "marcut/\(name).\(ext)"
        ]

        for path in candidatePaths {
            let url = URL(fileURLWithPath: path)
            if fileManager.fileExists(atPath: url.path) {
                return url
            }
        }

        return nil
    }
}
