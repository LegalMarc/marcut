import Foundation

final class UserOverridesManager {
    static let shared = UserOverridesManager()

    private let fileManager = FileManager.default
    private let overridesDirectory: URL
    
    // MARK: - Custom State Detection
    
    var hasCustomExcludedWords: Bool {
        fileManager.fileExists(atPath: overridesExcludedWordsURL.path)
    }
    
    var hasCustomSystemPrompt: Bool {
        fileManager.fileExists(atPath: overridesSystemPromptURL.path)
    }

    private init() {
        overridesDirectory = UserOverridesManager.resolveOverridesDirectory(fileManager: fileManager)
        // No seeding - we use bundled defaults until user customizes
        syncEnvironment()
    }

    // MARK: - Override Paths (writable user locations)

    private var overridesExcludedWordsURL: URL {
        overridesDirectory.appendingPathComponent("excluded-words.txt")
    }
    
    private var overridesSystemPromptURL: URL {
        overridesDirectory.appendingPathComponent("system-prompt.txt")
    }
    
    // MARK: - Active Paths (either custom or default)
    
    var activeExcludedWordsURL: URL {
        if hasCustomExcludedWords {
            return overridesExcludedWordsURL
        }
        return resolveDefaultResourceURL(named: "excluded-words", ext: "txt") 
            ?? overridesExcludedWordsURL
    }
    
    var activeSystemPromptURL: URL {
        if hasCustomSystemPrompt {
            return overridesSystemPromptURL
        }
        return resolveDefaultResourceURL(named: "system-prompt", ext: "txt")
            ?? overridesSystemPromptURL
    }

    // MARK: - Excluded Words API

    func loadExcludedWords() throws -> String {
        return try String(contentsOf: activeExcludedWordsURL, encoding: .utf8)
    }

    func saveExcludedWords(_ text: String) throws {
        try text.trimmingCharacters(in: .whitespacesAndNewlines)
            .appending("\n")
            .write(to: overridesExcludedWordsURL, atomically: true, encoding: .utf8)
        syncEnvironment()
    }
    
    func restoreDefaultExcludedWords() {
        try? fileManager.removeItem(at: overridesExcludedWordsURL)
        syncEnvironment()
    }
    
    func defaultExcludedWords() throws -> String {
        if let url = resolveDefaultResourceURL(named: "excluded-words", ext: "txt") {
            return try String(contentsOf: url, encoding: .utf8)
        }
        throw NSError(domain: "UserOverrides", code: 404, userInfo: [NSLocalizedDescriptionKey: "Default excluded-words.txt not found in bundle"])
    }

    // MARK: - System Prompt API

    func loadSystemPrompt() throws -> String {
        return try String(contentsOf: activeSystemPromptURL, encoding: .utf8)
    }

    func saveSystemPrompt(_ text: String) throws {
        try text.trimmingCharacters(in: .whitespacesAndNewlines)
            .appending("\n")
            .write(to: overridesSystemPromptURL, atomically: true, encoding: .utf8)
        syncEnvironment()
    }
    
    func restoreDefaultSystemPrompt() {
        try? fileManager.removeItem(at: overridesSystemPromptURL)
        syncEnvironment()
    }
    
    func defaultSystemPrompt() throws -> String {
        if let url = resolveDefaultResourceURL(named: "system-prompt", ext: "txt") {
            return try String(contentsOf: url, encoding: .utf8)
        }
        throw NSError(domain: "UserOverrides", code: 404, userInfo: [NSLocalizedDescriptionKey: "Default system-prompt.txt not found in bundle"])
    }
    
    /// Legacy compatibility - returns default prompt text as fallback
    func defaultSystemPromptText() -> String {
        do {
            return try defaultSystemPrompt()
        } catch {
            // Fallback hardcoded prompt if bundle is missing
            return """
You are an extractor for legal-document redaction.

Goal: list only real entities with semantic identity — people (NAME), organizations (ORG), and geographical locations (LOC). Do not include generic roles, headings, placeholders, or boilerplate even if capitalized or defined in the document.

Entity types:
- NAME: Personal names. Prefer full names. Titles like Mr./Ms./Dr. may appear but should be attached to a real name. Single generic words (Company, Board, Stockholders) are NOT names.
- ORG: Registered organizations and companies. Prefer strings that include a company designator (Inc., LLC, Ltd., Corp., LLP, GmbH, AG, SA, BV, NV, PLC, Co., Holdings, Partners, Capital, Group, Management, Ventures, Bank, Trust, University). Do NOT output generic roles like "Company", "Board of Directors", "Stockholders", "Purchaser", "Seller", "Party/Parties".
- LOC: Geographic locations such as countries, states, cities, or specific street addresses.

Rules:
- Return the exact surface text as it appears in the passage.
- Exclude boilerplate and document structural terms.
- Output strictly JSON of the form: {"entities": [{"text": "...", "type": "NAME|ORG|LOC"}, ...]}. No extra text.
Your entire response must be a single, valid JSON object inside a ```json code block.
"""
        }
    }

    // MARK: - Environment Sync

    func syncEnvironment() {
        // Excluded words - always point to active path
        setenv("MARCUT_EXCLUDED_WORDS_PATH", activeExcludedWordsURL.path, 1)

        // System prompt - always point to active path  
        setenv("MARCUT_SYSTEM_PROMPT_PATH", activeSystemPromptURL.path, 1)
    }

    // MARK: - Helpers

    private func resolveDefaultResourceURL(named name: String, ext: String) -> URL? {
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

    private static func resolveOverridesDirectory(fileManager: FileManager) -> URL {
        var candidates: [URL] = []

        if let groupURL = fileManager.containerURL(forSecurityApplicationGroupIdentifier: "group.com.marclaw.marcutapp") {
            candidates.append(groupURL.appendingPathComponent("MarcutOverrides", isDirectory: true))
        }

        if let appSupport = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            candidates.append(appSupport.appendingPathComponent("MarcutApp/Overrides", isDirectory: true))
        }

        for candidate in candidates {
            do {
                try fileManager.createDirectory(at: candidate, withIntermediateDirectories: true)
                let probe = candidate.appendingPathComponent(".write_test")
                try "ok".write(to: probe, atomically: true, encoding: .utf8)
                try? fileManager.removeItem(at: probe)
                return candidate
            } catch {
                continue
            }
        }

        let fallback = fileManager.temporaryDirectory.appendingPathComponent("MarcutOverrides", isDirectory: true)
        try? fileManager.createDirectory(at: fallback, withIntermediateDirectories: true)
        return fallback
    }
}
