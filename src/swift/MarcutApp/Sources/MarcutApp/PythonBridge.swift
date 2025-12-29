import Foundation
import Combine
import Darwin

// Helper functions outside of actor context
private func logToFile(_ path: String, _ message: String) {
    let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !trimmed.isEmpty else { return }

    let timestamp = ISO8601DateFormatter().string(from: Date())
    let logMessage = "[\(timestamp)] \(trimmed)\n"

    let fileURL = URL(fileURLWithPath: path)
    let directoryURL = fileURL.deletingLastPathComponent()
    try? FileManager.default.createDirectory(at: directoryURL, withIntermediateDirectories: true)

    // Try to append to file, create if doesn't exist
    if FileManager.default.fileExists(atPath: path) {
        if let fileHandle = try? FileHandle(forWritingTo: fileURL) {
            fileHandle.seekToEndOfFile()
            fileHandle.write(logMessage.data(using: .utf8) ?? Data())
            try? fileHandle.close()
        }
    } else {
        try? logMessage.write(to: fileURL, atomically: true, encoding: .utf8)
    }
}

private func removeANSIEscapeCodes(_ input: String) -> String {
    // Remove ANSI escape sequences using regex
    let patterns = [
        "\\x1B\\[[0-9;]*[mGKH]",  // Common color and cursor codes
        "\\x1B\\[\\?[0-9]+[hl]",   // Mode settings
        "\\x1B\\[[0-9]*[ABCD]",    // Cursor movement
        "\\x1B\\[[0-9;]*[Jm]",     // Clear and color
        "\\[\\?2026[hl]",          // Bracketed paste mode
        "\\[\\?25[hl]",            // Cursor visibility
        "\\[[0-9]+G",              // Cursor column
        "\\[K"                     // Clear line
    ]

    var result = input
    for pattern in patterns {
        if let regex = try? NSRegularExpression(pattern: pattern, options: []) {
            result = regex.stringByReplacingMatches(
                in: result,
                options: [],
                range: NSRange(result.startIndex..., in: result),
                withTemplate: ""
            )
        }
    }

    // Also remove control characters
    result = result.replacingOccurrences(of: "\r", with: "\n")
    result = result.replacingOccurrences(of: "\u{001b}", with: "")

    return result
}

@inline(__always)
private func bridgeLog(_ message: String, component: String = "Ollama") {
    DebugLogger.shared.log(message, component: component)
    print("[\(component)] \(message)")
}

private func sanitizedEnvSummary(_ env: [String: String]) -> String {
    let homeDirectory = NSHomeDirectory()
    return env
        .sorted { $0.key < $1.key }
        .map { key, value in
            let collapsedHome = value.replacingOccurrences(of: homeDirectory, with: "~")
            let sanitized: String
            if collapsedHome.count > 300 {
                let prefix = collapsedHome.prefix(300)
                sanitized = "\(prefix)... truncated (\(collapsedHome.count) chars)"
            } else {
                sanitized = collapsedHome
            }
            return "\(key)=\(sanitized)"
        }
        .joined(separator: "; ")
}

private func logCLIInvocationDetails(
    logPath: String,
    executable: String,
    arguments: [String],
    environment: [String: String],
    workingDirectory: URL?
) {
    let quotedArguments = arguments.map { argument in
        let escaped = argument.replacingOccurrences(of: "\"", with: "\\\"")
        return "\"\(escaped)\""
    }.joined(separator: " ")

    logToFile(logPath, "[CLI] Executable: \(executable)")
    logToFile(logPath, "[CLI] Arguments: \(quotedArguments)")
    if let workingDirectory {
        logToFile(logPath, "[CLI] Working directory: \(workingDirectory.path)")
    } else {
        logToFile(logPath, "[CLI] Working directory: (unset)")
    }
    logToFile(logPath, "[CLI] Environment snapshot: \(sanitizedEnvSummary(environment))")
}

private enum ModelPromotion {
    struct ManifestData {
        let digest: String
        let size: Int64?
    }

    private static let fileManager = FileManager.default

    static func safeFileName(for modelName: String) -> String {
        return modelName
            .replacingOccurrences(of: ":", with: "-")
            .replacingOccurrences(of: "/", with: "-")
    }

    static func canonicalURL(for modelName: String, root: URL) -> URL {
        let safeName = safeFileName(for: modelName)
        return root.appendingPathComponent("\(safeName).gguf")
    }

    static func canonicalExists(modelName: String, root: URL, expectedSize: Int64? = nil) -> Bool {
        let url = canonicalURL(for: modelName, root: root)
        guard fileManager.fileExists(atPath: url.path) else {
            return false
        }
        guard let expectedSize else {
            return true
        }
        guard let attributes = try? fileManager.attributesOfItem(atPath: url.path),
              let size = (attributes[.size] as? NSNumber)?.int64Value else {
            return false
        }
        return size == expectedSize
    }

    static func discoverModels(in directory: URL) -> Set<String> {
        var models: Set<String> = []
        bridgeLog("MODEL_DISCOVERY: Starting discovery in \(directory.path)", component: "MODEL_PROMOTION")
        let manifestsDir = directory.appendingPathComponent("manifests", isDirectory: true)
        guard fileManager.fileExists(atPath: manifestsDir.path) else {
            return models
        }

        if let registries = try? fileManager.contentsOfDirectory(at: manifestsDir, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) {
            for registry in registries {
                bridgeLog("MODEL_DISCOVERY: Searching registry \(registry.lastPathComponent)", component: "MODEL_PROMOTION")
                guard let libraries = try? fileManager.contentsOfDirectory(at: registry, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) else { continue }
                for library in libraries {
                    bridgeLog("MODEL_DISCOVERY:  -> Library \(library.lastPathComponent)", component: "MODEL_PROMOTION")
                    guard let modelDirs = try? fileManager.contentsOfDirectory(at: library, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) else { continue }
                    for modelDir in modelDirs {
                        bridgeLog("MODEL_DISCOVERY:     -> ModelDir \(modelDir.lastPathComponent)", component: "MODEL_PROMOTION")
                        if modelDir.lastPathComponent.contains("sha256") {
                            continue
                        }
                        
                        // Check for manifest.json (legacy) OR tag files (modern)
                        // We iterate all files in the model directory
                        if let files = try? fileManager.contentsOfDirectory(at: modelDir, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) {
                            for file in files {
                                // Skip system files
                                if file.lastPathComponent.hasPrefix(".") { continue }
                                
                                // If it's a JSON file or just a tag name (no extension)
                                // We assume it's a valid model tag if it parses as a manifest
                                let libraryName = library.lastPathComponent
                                let modelName = modelDir.lastPathComponent
                                let tagName = file.lastPathComponent == "manifest.json" ? "latest" : file.lastPathComponent
                                
                                // Construct the full model ID: library/model:tag
                                // But Marcut uses library:model format mostly? 
                                // Actually, discoverModels returns a Set<String>. 
                                // The existing code returned "library:model". 
                                // Let's stick to "library:model" if tag is latest, or "library:model:tag" if not?
                                // The user selects "llama3.2:3b". 
                                // If we find "library/llama3.2/3b", we should probably return "llama3.2:3b" (omitting library if it's 'library'?)
                                
                                // Let's try to match what the user expects: "llama3.2:3b"
                                var identifier = "\(modelName)"
                                if tagName != "latest" && tagName != "manifest.json" {
                                    identifier += ":\(tagName)"
                                }
                                
                                // If library is NOT 'library', prepend it?
                                if libraryName != "library" {
                                    identifier = "\(libraryName)/\(identifier)"
                                }
                                
                                bridgeLog("MODEL_DISCOVERY:        Found model candidate: \(identifier) at \(file.path)", component: "MODEL_PROMOTION")
                                models.insert(identifier)
                            }
                        }
                    }
                }
            }
        }

        return models
    }

    static func promoteIfNeeded(modelName: String, root: URL, log: (String) -> Void) -> Bool {
        guard let manifest = manifestInfo(for: modelName, root: root, log: log) else {
            log("No manifest data for model \(modelName)")
            return false
        }

        guard let blobName = blobFileName(for: manifest.digest) else {
            log("Unrecognized digest format for model \(modelName): \(manifest.digest)")
            return false
        }

        let blobsDir = root.appendingPathComponent("blobs", isDirectory: true)
        let blobURL = blobsDir.appendingPathComponent(blobName)
        guard fileManager.fileExists(atPath: blobURL.path) else {
            log("Blob missing for model \(modelName) at \(blobURL.path)")
            return false
        }

        let canonicalURL = canonicalURL(for: modelName, root: root)

        if canonicalExists(modelName: modelName, root: root, expectedSize: manifest.size) {
            return true
        }

        do {
            try fileManager.createDirectory(at: canonicalURL.deletingLastPathComponent(), withIntermediateDirectories: true)

            if fileManager.fileExists(atPath: canonicalURL.path) {
                try fileManager.removeItem(at: canonicalURL)
            }

            let tempURL = canonicalURL.appendingPathExtension("tmp")
            if fileManager.fileExists(atPath: tempURL.path) {
                try fileManager.removeItem(at: tempURL)
            }

            do {
                try fileManager.linkItem(at: blobURL, to: tempURL)
            } catch {
                log("Hard link failed for \(modelName): \(error.localizedDescription). Copying instead.")
                try fileManager.copyItem(at: blobURL, to: tempURL)
            }

            try fileManager.moveItem(at: tempURL, to: canonicalURL)

            if let expectedSize = manifest.size,
               let attributes = try? fileManager.attributesOfItem(atPath: canonicalURL.path),
               let actualSize = (attributes[.size] as? NSNumber)?.int64Value,
               actualSize != expectedSize {
                log("Canonical file size mismatch for \(modelName). Expected \(expectedSize), got \(actualSize). Removing corrupted file.")
                try? fileManager.removeItem(at: canonicalURL)
                return false
            }

            log("Canonical model available at \(canonicalURL.path)")
            return true
        } catch {
            log("Failed to promote model \(modelName): \(error.localizedDescription)")
            return false
        }
    }

    private static func manifestInfo(for modelName: String, root: URL, log: (String) -> Void) -> ManifestData? {
        // Parse model base name and tag
        // Input: "llama3.2:3b" -> library="library", model="llama3.2", tag="3b"
        // Input: "library/llama3.2:3b" -> library="library", model="llama3.2", tag="3b"
        
        var libraryName = "library"
        var modelBaseName = modelName
        var modelTag = "latest"
        
        // Check for library prefix (e.g. "user/model")
        if modelName.contains("/") {
            let parts = modelName.split(separator: "/", maxSplits: 1)
            libraryName = String(parts[0])
            modelBaseName = String(parts[1])
        }
        
        // Check for tag suffix (e.g. "model:tag")
        if modelBaseName.contains(":") {
            let parts = modelBaseName.split(separator: ":", maxSplits: 1)
            modelBaseName = String(parts[0])
            modelTag = String(parts[1])
        }

        let manifestsDir = root.appendingPathComponent("manifests", isDirectory: true)
        guard fileManager.fileExists(atPath: manifestsDir.path) else {
            log("Manifests directory missing at \(manifestsDir.path)")
            return nil
        }

        log("MANIFEST_INFO: Searching registries in \(manifestsDir.path)...")
        log("MANIFEST_INFO: Model parsed as library='\(libraryName)', baseName='\(modelBaseName)', tag='\(modelTag)'")

        if let registries = try? fileManager.contentsOfDirectory(at: manifestsDir, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) {
            for registry in registries {
                let modelDir = registry
                    .appendingPathComponent(libraryName, isDirectory: true)
                    .appendingPathComponent(modelBaseName, isDirectory: true)

                // Try Ollama 0.12.5+ format first: manifest file named with tag
                let tagManifestURL = modelDir.appendingPathComponent(modelTag)
                log("MANIFEST_INFO:  -> Attempting Ollama 0.12.5+ format: \(tagManifestURL.path)")
                if fileManager.fileExists(atPath: tagManifestURL.path) {
                    if let parsed = parseManifest(at: tagManifestURL) {
                        log("MANIFEST_INFO:  ✅ Found manifest using Ollama 0.12.5+ format")
                        return parsed
                    }
                }

                // Fall back to legacy format: manifest.json
                let legacyManifestURL = modelDir.appendingPathComponent("manifest.json")
                log("MANIFEST_INFO:  -> Attempting legacy format: \(legacyManifestURL.path)")
                if fileManager.fileExists(atPath: legacyManifestURL.path) {
                    if let parsed = parseManifest(at: legacyManifestURL) {
                        log("MANIFEST_INFO:  ✅ Found manifest using legacy format")
                        return parsed
                    }
                }

                // Final fallback: look for any JSON file in the model directory
                if let contents = try? fileManager.contentsOfDirectory(at: modelDir, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) {
                    for file in contents {
                        if file.pathExtension == "json" || file.lastPathComponent == modelTag {
                            log("MANIFEST_INFO:  -> Attempting fallback file: \(file.path)")
                            if let parsed = parseManifest(at: file) {
                                log("MANIFEST_INFO:  ✅ Found manifest using fallback search")
                                return parsed
                            }
                        }
                    }
                }
            }
        }

        log("MANIFEST_INFO: Direct path failed. Starting fallback enumeration...")
        // Final fallback: search entire manifests tree for any manifest
        let enumerator = fileManager.enumerator(at: manifestsDir, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles])
        while let next = enumerator?.nextObject() as? URL {
            let fileName = next.lastPathComponent
            let modelDir = next.deletingLastPathComponent()
            let modelNameComponent = modelDir.lastPathComponent
            let libraryComponent = modelDir.deletingLastPathComponent().lastPathComponent

            // Check if this could be our manifest (either tag-named or manifest.json)
            let isManifestCandidate = (fileName == "manifest.json" ||
                                      fileName == modelTag ||
                                      (fileName as NSString).pathExtension == "json")

            if isManifestCandidate {
                log("MANIFEST_INFO:  -> Found candidate manifest. Checking if '\(libraryComponent)/\(modelNameComponent)' matches '\(libraryName)/\(modelBaseName)' with file '\(fileName)'")
                if libraryComponent == libraryName && modelNameComponent == modelBaseName {
                    if let parsed = parseManifest(at: next) {
                        log("MANIFEST_INFO:  ✅ Found manifest via enumeration")
                        return parsed
                    }
                }
            }
        }

        log("Manifest for \(modelName) not found")
        return nil
    }

    private static func parseManifest(at url: URL) -> ManifestData? {
        guard let data = try? Data(contentsOf: url) else {
            return nil
        }

        guard let object = try? JSONSerialization.jsonObject(with: data),
              let json = object as? [String: Any] else {
            return nil
        }

        if let layers = json["layers"] as? [[String: Any]], !layers.isEmpty {
            let sorted = layers.sorted { (value(from: $0["size"]) ?? 0) > (value(from: $1["size"]) ?? 0) }

            for layer in sorted {
                if let mediaType = layer["mediaType"] as? String,
                   mediaType.lowercased().contains("gguf"),
                   let digest = layer["digest"] as? String {
                    return ManifestData(digest: digest, size: value(from: layer["size"]))
                }
            }

            if let digest = sorted.first?["digest"] as? String {
                return ManifestData(digest: digest, size: value(from: sorted.first?["size"]))
            }
        }

        if let config = json["config"] as? [String: Any],
           let digest = config["digest"] as? String {
            return ManifestData(digest: digest, size: value(from: config["size"]))
        }

        return nil
    }

    private static func blobFileName(for digest: String) -> String? {
        var trimmed = digest.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return nil }

        if trimmed.hasPrefix("sha256:") {
            trimmed.removeFirst("sha256:".count)
        } else if trimmed.hasPrefix("sha256-") {
            trimmed.removeFirst("sha256-".count)
        }

        trimmed = trimmed.lowercased()

        let allowed = CharacterSet(charactersIn: "0123456789abcdef")
        if trimmed.rangeOfCharacter(from: allowed.inverted) != nil {
            return nil
        }

        guard trimmed.count == 64 else {
            return nil
        }

        return "sha256-\(trimmed)"
    }

    private static func value(from any: Any?) -> Int64? {
        if let number = any as? NSNumber {
            return number.int64Value
        }
        if let string = any as? String, let intValue = Int64(string) {
            return intValue
        }
        return nil
    }
}

@MainActor
final class PythonBridgeService: ObservableObject {
    static let shared = PythonBridgeService()

    @Published var isOllamaRunning: Bool = false
    @Published var installedModels: [String] = []
    @Published var currentModel: String = "llama3.1:8b"
    @Published var setupComplete: Bool = false
    @Published var ollamaLaunchError: String?

    private var cancellables = Set<AnyCancellable>()
    private var isDebugLoggingEnabled = false
    private var ollamaPort: Int32 = 11434
    private var launchedOllamaPID: Int32?
    private var launchedOllamaPort: Int32?
    private var ollamaStartTask: Task<Bool, Never>?
    // XPC removed - CLI subprocess only approach - fail-fast direct execution
    
    // Store active processes by document ID to allow cancellation
    private var activeProcesses: [UUID: Process] = [:]

    
    /// Public getter for the current Ollama host (including dynamic port)
    /// Reads from MARCUT_OLLAMA_HOST environment variable which is set when port changes
    nonisolated var currentOllamaHost: String {
        ProcessInfo.processInfo.environment["MARCUT_OLLAMA_HOST"] ?? "127.0.0.1:11434"
    }

    /// Computed property for Ollama host (alias for currentOllamaHost)
    private var ollamaHost: String {
        currentOllamaHost
    }

    private var promotionsInFlight: Set<String> = []

    // Shared Application Support container (App Group when available)
    // Shared Application Support container (App Group DISABLED for Stability)
    private lazy var appSupportURL: URL = {
        // Force fallback to standard Application Support (Sandbox Safe)
        let fallback = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MarcutApp", isDirectory: true)
        
        do {
            try FileManager.default.createDirectory(at: fallback, withIntermediateDirectories: true)
            bridgeLog("Using Application Support container: \(fallback.path)", component: "STORAGE")
        } catch {
            bridgeLog("Failed to prepare Application Support directory: \(fallback.path) - \(error)", component: "STORAGE")
        }
        return fallback
    }()

    // Local, writable Application Support root for Ollama runtime artifacts
    private lazy var localAppSupportURL: URL = {
        // Align local storage with the shared appSupportURL so XPC helper can access the same paths
        return appSupportURL
    }()

    // Dedicated exec-capable temp dir for Ollama runners (avoid noexec app sandbox tmp)
    private func probeExecCapability(at dir: URL) -> Bool {
        let fm = FileManager.default
        let scriptName = "marcut_exec_probe_\(UUID().uuidString).sh"
        let scriptURL = dir.appendingPathComponent(scriptName)
        let script = "#!/bin/sh\nexit 0\n"

        do {
            try script.write(to: scriptURL, atomically: true, encoding: .utf8)
            try fm.setAttributes([.posixPermissions: NSNumber(value: Int16(0o755))], ofItemAtPath: scriptURL.path)

            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/sh")
            process.arguments = [scriptURL.path]

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            try process.run()
            process.waitUntilExit()
            let status = process.terminationStatus
            try? fm.removeItem(at: scriptURL)

            if status != 0 {
                bridgeLog("⚠️ Exec probe exited with status \(status) for \(dir.path)", component: "Ollama")
                return false
            }
            return true
        } catch {
            try? fm.removeItem(at: scriptURL)
            bridgeLog("⚠️ Exec probe failed for \(dir.path): \(error)", component: "Ollama")
            return false
        }
    }

    private func prepareOllamaTmpDir() -> URL? {
        let fm = FileManager.default

        func validateTmpDir(_ url: URL, label: String) -> URL? {
            do {
                try fm.createDirectory(at: url, withIntermediateDirectories: true, attributes: [.posixPermissions: NSNumber(value: Int16(0o755))])
                try? fm.setAttributes([.posixPermissions: NSNumber(value: Int16(0o755))], ofItemAtPath: url.path)
                // Sandbox often blocks removexattr on system paths; don't fail the whole setup if it fails
                // Sandbox often blocks removexattr on system paths; don't fail the whole setup if it fails
                stripQuarantineAttributes(at: url, recursive: true)
            } catch {
                bridgeLog("⚠️ Failed to prepare \(label) tmp dir (\(url.path)): \(error)", component: "Ollama")
                return nil
            }

            guard probeExecCapability(at: url) else {
                bridgeLog("⚠️ \(label.capitalized) tmp dir is not exec-capable: \(url.path)", component: "Ollama")
                return nil
            }
            return url
        }



        // Use app container temp directory with proper permissions for App Store safety
        // Note: Ollama runners need exec permissions, so we create a special
        // temp directory within our app container and ensure it's executable
        guard let tmpDir = prepareAppContainerTempDir() else {
            let message = "Ollama could not start: cannot create exec-capable temp directory in app container"
            bridgeLog("❌ \(message)", component: "Ollama")
            ollamaLaunchError = message
            return nil
        }
        // De-quarantine Ollama's extracted runner (Ollama extracts embedded runner on every model load)
        stageBundledRunner(into: tmpDir)
        return tmpDir
    }

    private func prepareAppContainerTempDir() -> URL? {
        let fm = FileManager.default
        
        // Candidates for exec-capable temp directory
        // 1. App Group / Application Support (Preferred)
        // 2. System Temp (Fallback for strict sandbox)
        let candidates: [URL] = [
            URL(fileURLWithPath: NSTemporaryDirectory()).appendingPathComponent("OllamaExec", isDirectory: true),
            localAppSupportURL.appendingPathComponent("tmp", isDirectory: true)
        ]
        
        for tmpDir in candidates {
            bridgeLog("Checking Temp Dir Candidate: \(tmpDir.path)", component: "Ollama")
            do {
                try fm.createDirectory(at: tmpDir, withIntermediateDirectories: true, attributes: [.posixPermissions: NSNumber(value: Int16(0o755))])
                try? fm.setAttributes([.posixPermissions: NSNumber(value: Int16(0o755))], ofItemAtPath: tmpDir.path)
                
                // Remove quarantine
                stripQuarantineAttributes(at: tmpDir, recursive: true)
                
                // Verify execution capability
                if probeExecCapability(at: tmpDir) {
                    bridgeLog("✅ Using exec-capable temp dir: \(tmpDir.path)", component: "Ollama")
                    return tmpDir
                } else {
                    bridgeLog("⚠️ Tmp dir not exec-capable: \(tmpDir.path)", component: "Ollama")
                }
            } catch {
                bridgeLog("⚠️ Failed to prepare candidate tmp dir (\(tmpDir.path)): \(error)", component: "Ollama")
            }
        }
        
        return nil
    }

    private var bundledRunnerURL: URL? {
        // Look for 'ollama' executable in Contents/MacOS (sibling to main binary)
        if let executableURL = Bundle.main.executableURL {
             let ollamaURL = executableURL.deletingLastPathComponent().appendingPathComponent("ollama")
             if FileManager.default.fileExists(atPath: ollamaURL.path) {
                 return ollamaURL
             }
        }
        
        // Fallback for legacy locations (though we intend to move it)
        let direct = Bundle.main.resourceURL?
            .appendingPathComponent("ollama_runners/metal/ollama_llama_server", isDirectory: false)
        if let direct, FileManager.default.fileExists(atPath: direct.path) {
            return direct
        }
        return nil
    }

    /// Path to a de-quarantined copy of the bundled Ollama binary staged into the app group.
    private var stagedOllamaBinaryURL: URL {
        localAppSupportURL
            .appendingPathComponent("ollama/bin/ollama", isDirectory: false)
    }

    private func stageBundledRunner(into tmpRoot: URL) {
        guard let runnerSrc = bundledRunnerURL, FileManager.default.fileExists(atPath: runnerSrc.path) else {
            return
        }

        let fm = FileManager.default
        guard let contents = try? fm.contentsOfDirectory(at: tmpRoot, includingPropertiesForKeys: [.isDirectoryKey], options: [.skipsHiddenFiles]) else {
            return
        }

        for entry in contents where entry.lastPathComponent.hasPrefix("ollama") {
            let runnerDir = entry.appendingPathComponent("runners/metal", isDirectory: true)
            let runnerDst = runnerDir.appendingPathComponent("ollama_llama_server", isDirectory: false)
            do {
                try fm.createDirectory(at: runnerDir, withIntermediateDirectories: true, attributes: [.posixPermissions: NSNumber(value: Int16(0o755))])

                // Only replace if missing or size mismatch to avoid unnecessary churn
                var needsCopy = true
                if fm.fileExists(atPath: runnerDst.path),
                   let srcAttrs = try? fm.attributesOfItem(atPath: runnerSrc.path),
                   let dstAttrs = try? fm.attributesOfItem(atPath: runnerDst.path),
                   let srcSize = srcAttrs[.size] as? NSNumber,
                   let dstSize = dstAttrs[.size] as? NSNumber,
                   srcSize == dstSize {
                    needsCopy = false
                }

                if needsCopy {
                    if fm.fileExists(atPath: runnerDst.path) {
                        try fm.removeItem(at: runnerDst)
                    }
                    
                    // Use Data.write instead of copyItem to try and avoid quarantine
                    let data = try Data(contentsOf: runnerSrc)
                    try data.write(to: runnerDst)
                    
                    try fm.setAttributes([.posixPermissions: NSNumber(value: Int16(0o755))], ofItemAtPath: runnerDst.path)
                    
                    // Ad-hoc code sign the binary
                    adHocSign(at: runnerDst)
                    
                    // Still attempt to strip, just in case
                    stripQuarantineAttributes(at: runnerDst)
                    forceRemoveQuarantineWithXattr(at: runnerDst)
                    logRunnerQuarantineState(src: runnerSrc, dst: runnerDst)
                } else {
                    // Ensure existing staged runner is not quarantined
                    stripQuarantineAttributes(at: runnerDst)
                    forceRemoveQuarantineWithXattr(at: runnerDst)
                    logRunnerQuarantineState(src: runnerSrc, dst: runnerDst)
                }
            } catch {
                bridgeLog("⚠️ Failed to stage bundled runner into \(runnerDir.path): \(error)", component: "Ollama")
            }
        }
    }

    private func stripQuarantineAttributes(at url: URL, recursive: Bool = false) {
        let fm = FileManager.default
        func strip(_ target: URL) {
            target.withUnsafeFileSystemRepresentation { pathPtr in
                guard let pathPtr else { return }
                if removexattr(pathPtr, "com.apple.quarantine", 0) != 0 {
                    let err = errno
                    // Ignore ENOATTR (93) which means attribute didn't exist
                    if err != 93 {
                        bridgeLog("⚠️ removexattr failed for \(target.lastPathComponent): error \(err) (\(String(cString: strerror(err))))", component: "Ollama")
                    }
                } else {
                    bridgeLog("✅ removexattr success for \(target.lastPathComponent)", component: "Ollama")
                }
            }
        }

        strip(url)

        if recursive, let contents = try? fm.contentsOfDirectory(at: url, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]) {
            for child in contents {
                stripQuarantineAttributes(at: child, recursive: true)
            }
        }
    }

    private func logRunnerQuarantineState(src: URL, dst: URL) {
        let srcAttrs = (try? quarantineValue(src)) ?? "<none>"
        let dstAttrs = (try? quarantineValue(dst)) ?? "<none>"
        bridgeLog("Runner quarantine status src=\(src.path) qattr=\(srcAttrs) dst=\(dst.path) qattr=\(dstAttrs)", component: "Ollama")
    }

    private func quarantineValue(_ url: URL) throws -> String {
        return try url.withUnsafeFileSystemRepresentation { pathPtr -> String in
            guard let pathPtr else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(EINVAL), userInfo: nil) }
            let size = getxattr(pathPtr, "com.apple.quarantine", nil, 0, 0, 0)
            if size <= 0 { return "<none>" }
            var data = Data(count: size)
            let result = data.withUnsafeMutableBytes { buf in
                getxattr(pathPtr, "com.apple.quarantine", buf.baseAddress, size, 0, 0)
            }
            if result < 0 { return "<error \(errno)>" }
            return String(data: data, encoding: .utf8) ?? "<non-utf8>"
        }
    }

    private func forceRemoveQuarantineWithXattr(at url: URL) {
        guard FileManager.default.fileExists(atPath: url.path) else { return }
        
        // Helper to run xattr and log output
        func runXattr(_ args: [String]) -> Bool {
            let task = Process()
            task.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
            task.arguments = args
            let pipe = Pipe()
            task.standardOutput = pipe
            task.standardError = pipe
            
            do {
                try task.run()
                task.waitUntilExit()
                
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
                
                if task.terminationStatus != 0 {
                    bridgeLog("⚠️ xattr \(args.joined(separator: " ")) failed (code \(task.terminationStatus)): \(output)", component: "Ollama")
                    return false
                } else if !output.isEmpty {
                    bridgeLog("ℹ️ xattr \(args.joined(separator: " ")) output: \(output)", component: "Ollama")
                }
                return true
            } catch {
                bridgeLog("❌ Failed to run xattr: \(error)", component: "Ollama")
                return false
            }
        }

        // 1. Try removing specific attribute
        if !runXattr(["-d", "com.apple.quarantine", url.path]) {
            bridgeLog("⚠️ xattr -d failed, attempting xattr -c (clear all)...", component: "Ollama")
            // 2. Fallback: Clear ALL extended attributes
            _ = runXattr(["-c", url.path])
        } else {
             bridgeLog("✅ xattr -d success for \(url.lastPathComponent)", component: "Ollama")
        }
    }

    private func fixActiveOllamaRunners(in tmpDir: URL) {
        let fm = FileManager.default
        guard let contents = try? fm.contentsOfDirectory(at: tmpDir, includingPropertiesForKeys: [.creationDateKey, .isDirectoryKey], options: [.skipsHiddenFiles]) else {
            bridgeLog("⚠️ Could not list contents of tmpDir for quarantine fix: \(tmpDir.path)", component: "Ollama")
            return
        }

        // Find all ollama* directories
        let runnerDirs = contents.filter { $0.lastPathComponent.hasPrefix("ollama") }
        
        if runnerDirs.isEmpty {
            bridgeLog("⚠️ No ollama runner directories found in \(tmpDir.path)", component: "Ollama")
            return
        }

        bridgeLog("Found \(runnerDirs.count) runner directories. Attempting to de-quarantine all...", component: "Ollama")

        for dir in runnerDirs {
            // Log status before
            let beforeStatus = (try? quarantineValue(dir)) ?? "unknown"
            
            // 1. Recursive strip using system API
            stripQuarantineAttributes(at: dir, recursive: true)
            
            // 2. Force recursive strip using xattr tool (more robust)
            forceRemoveQuarantineWithXattr(at: dir)
            
            // Log status after
            let afterStatus = (try? quarantineValue(dir)) ?? "unknown"
            
            if beforeStatus != "<none>" || afterStatus != "<none>" {
                bridgeLog("🔧 Quarantine fix for \(dir.lastPathComponent): \(beforeStatus) -> \(afterStatus)", component: "Ollama")
            }
            
            // Also explicitly fix the runner binary if we can find it
            let metalRunner = dir.appendingPathComponent("runners/metal/ollama_llama_server")
            if fm.fileExists(atPath: metalRunner.path) {
                forceRemoveQuarantineWithXattr(at: metalRunner)
                // Ad-hoc sign active runners too
                adHocSign(at: metalRunner)
                
                // Ensure executable
                let chmod = Process()
                chmod.executableURL = URL(fileURLWithPath: "/bin/chmod")
                chmod.arguments = ["+x", metalRunner.path]
                try? chmod.run()
                chmod.waitUntilExit()
            }
        }
        
        bridgeLog("✅ Completed quarantine fix for runners", component: "Ollama")
    }

    /// Ensure any extracted runners inside OLLAMA_TMPDIR are executable and de-quarantined.
    private func sanitizeActiveOllamaRunners() {
        guard let tmpDir = lastOllamaTmpDir ?? prepareAppContainerTempDir() else {
            bridgeLog("⚠️ Cannot sanitize Ollama runners: missing exec-capable tmp dir", component: "Ollama")
            return
        }

        bridgeLog("🔧 Sanitizing Ollama runners in \(tmpDir.path)", component: "Ollama")
        fixActiveOllamaRunners(in: tmpDir)
        stageBundledRunner(into: tmpDir)
    }

    private func adHocSign(at url: URL) {
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/usr/bin/codesign")
        task.arguments = ["--force", "--deep", "--sign", "-", url.path]
        
        let pipe = Pipe()
        task.standardOutput = pipe
        task.standardError = pipe
        
        do {
            try task.run()
            task.waitUntilExit()
            
            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            
            if task.terminationStatus == 0 {
                bridgeLog("✅ Code signing successful for \(url.lastPathComponent)", component: "Ollama")
            } else {
                bridgeLog("⚠️ Code signing failed for \(url.lastPathComponent): \(output)", component: "Ollama")
            }
        } catch {
            bridgeLog("❌ Failed to run codesign: \(error)", component: "Ollama")
        }
    }
    
    func dumpOllamaLogs() {
        guard FileManager.default.fileExists(atPath: ollamaLogFileURL.path) else {
            bridgeLog("ℹ️ No ollama log file found at \(ollamaLogFileURL.path)", component: "Ollama")
            return
        }
        
        do {
            let data = try Data(contentsOf: ollamaLogFileURL)
            if let content = String(data: data, encoding: .utf8) {
                let lines = content.components(separatedBy: .newlines)
                let lastLines = lines.suffix(20).joined(separator: "\n")
                bridgeLog("📋 OLLAMA LOG TAIL:\n\(lastLines)", component: "Ollama")
            }
        } catch {
            bridgeLog("⚠️ Failed to read ollama logs: \(error)", component: "Ollama")
        }
    }

    private var ollamaHomeURL: URL {
        localAppSupportURL.appendingPathComponent("ollama", isDirectory: true)
    }

    // Models directory
    private var modelsDirectory: URL {
        return localAppSupportURL.appendingPathComponent("models", isDirectory: true)
    }

    private var workDirectory: URL {
        appSupportURL.appendingPathComponent("Work/Staging", isDirectory: true)
    }

    private var ollamaLogsDirectory: URL {
        // Use standard App Support logs directory to match DebugLogger
        DebugLogger.shared.logURL.deletingLastPathComponent()
    }

    private var ollamaLogFileURL: URL {
        ollamaLogsDirectory.appendingPathComponent("ollama.log")
    }

    var ollamaLogURL: URL {
        try? FileManager.default.createDirectory(at: ollamaLogsDirectory, withIntermediateDirectories: true)
        if !FileManager.default.fileExists(atPath: ollamaLogFileURL.path) {
            FileManager.default.createFile(atPath: ollamaLogFileURL.path, contents: nil)
        }
        bridgeLog("Ollama log file: \(ollamaLogFileURL.path)", component: "Ollama")
        return ollamaLogFileURL
    }

    var modelsDirectoryURL: URL {
        try? FileManager.default.createDirectory(at: modelsDirectory, withIntermediateDirectories: true)
        return modelsDirectory
    }

    func clearOllamaLog() {
        closeOllamaLogHandle()
        let logURL = ollamaLogURL
        try? FileManager.default.removeItem(at: logURL)
        FileManager.default.createFile(atPath: logURL.path, contents: nil)
    }

  
    private let autoStartOllama: Bool
    private let allowOllamaService: Bool
    private var ruleFilterValue: String = RedactionRule.serializedList(from: RedactionRule.defaultSelection)


    init(autoStartOllama: Bool = true, allowOllamaService: Bool = true) {
        self.isDebugLoggingEnabled = UserDefaults.standard.bool(forKey: "MarcutApp_DebugMode")
        self.autoStartOllama = autoStartOllama
        self.allowOllamaService = allowOllamaService
        
        // Dynamic port selection
        self.ollamaPort = PythonBridgeService.findFreePort(start: 11434, maxAttempts: 20)
        bridgeLog("Selected Ollama port: \(self.ollamaPort)", component: "Ollama")
        
        setupEnvironment()
        applyRuleFilter(RedactionRule.defaultSelection)

        checkEnvironment(autoStart: autoStartOllama)
    }
    
    /// Updates the MARCUT_OLLAMA_HOST/OLLAMA_HOST process environment variables with the current port
    private func updateOllamaPortEnvironment() {
        let host = "127.0.0.1:\(ollamaPort)"
        setenv("MARCUT_OLLAMA_HOST", host, 1)          // used by Python clients (expects host:port)
        setenv("OLLAMA_HOST", host, 1)                 // Ollama server/CLI expects host:port (no scheme)
        bridgeLog("Set MARCUT_OLLAMA_HOST/OLLAMA_HOST=\(host)", component: "Ollama")
    }
    
    
    /// Finds a free port starting from `start`, trying up to `maxAttempts` times.
    /// Returns the first available port, or the `start` port if all fail (fallback).
    private static func findFreePort(start: Int32, maxAttempts: Int) -> Int32 {
        for i in 0..<maxAttempts {
            let port = start + Int32(i)
            if isPortFree(port) {
                return port
            }
        }
        // Fallback to default if all else fails, though unlikely
        return start
    }

    private static func isPortFree(_ port: Int32) -> Bool {
        var addr = sockaddr_in()
        addr.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        addr.sin_family = sa_family_t(AF_INET)
        addr.sin_port = in_port_t(port).bigEndian
        addr.sin_addr.s_addr = in_addr_t(INADDR_ANY).bigEndian

        let socketFileDescriptor = socket(AF_INET, SOCK_STREAM, 0)
        if socketFileDescriptor == -1 {
            return false
        }
        defer { close(socketFileDescriptor) }

        var bindResult: Int32 = -1
        // Use withUnsafePointer to pass the address safely
        let result = withUnsafePointer(to: &addr) { pointer -> Int32 in
            return pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPointer in
                return bind(socketFileDescriptor, sockaddrPointer, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        bindResult = result

        return bindResult == 0
    }

    // MARK: - Environment Setup

    private func setupEnvironment() {
        // Create necessary directories
        let fm = FileManager.default
        try? fm.createDirectory(at: ollamaHomeURL, withIntermediateDirectories: true)
        try? fm.createDirectory(at: modelsDirectory, withIntermediateDirectories: true)
        try? fm.createDirectory(
            at: ollamaHomeURL.appendingPathComponent("ollama-data", isDirectory: true),
            withIntermediateDirectories: true
        )
        try? fm.createDirectory(
            at: appSupportURL.appendingPathComponent("Work", isDirectory: true),
            withIntermediateDirectories: true
        )
        try? fm.createDirectory(
            at: appSupportURL.appendingPathComponent("Input", isDirectory: true),
            withIntermediateDirectories: true
        )
        try? fm.createDirectory(
            at: appSupportURL.appendingPathComponent("output", isDirectory: true),
            withIntermediateDirectories: true
        )
        secureEraseWorkDirectory()
    }

    private func canonicalModelURL(for modelName: String) -> URL {
        ModelPromotion.canonicalURL(for: modelName, root: modelsDirectory)
    }

    func updateRuleFilter(_ rules: Set<RedactionRule>) {
        applyRuleFilter(rules)
    }

    private func applyRuleFilter(_ rules: Set<RedactionRule>) {
        let serialized = RedactionRule.serializedList(from: rules)
        ruleFilterValue = serialized
        setenv("MARCUT_RULE_FILTER", serialized, 1)
    }

    func canonicalModelExists(_ modelName: String) -> Bool {
        ModelPromotion.canonicalExists(modelName: modelName, root: modelsDirectory)
    }

    @MainActor
    func ensureOllamaReadyForPythonKit(requiredModel: String? = nil) async -> Bool {
        let started = await ensureOllamaRunning(forceProbe: true)
        guard started else { return false }
        await loadInstalledModels()

        if let modelName = requiredModel {
            await promoteModelIfNeeded(modelName)
            return canonicalModelExists(modelName)
        }

        return true
    }

    private func promoteModelIfNeeded(_ modelName: String) async {
        if promotionsInFlight.contains(modelName) {
            return
        }
        promotionsInFlight.insert(modelName)
        let root = modelsDirectory
        let success = await Task.detached(priority: .utility) {
            ModelPromotion.promoteIfNeeded(modelName: modelName, root: root) { message in
                bridgeLog(message, component: "MODEL_PROMOTION")
            }
        }.value
        if !success {
            bridgeLog("Canonical promotion incomplete for \(modelName)", component: "MODEL_PROMOTION")
        }
        promotionsInFlight.remove(modelName)
    }

    private func ensureCanonicalModels(for models: [String]) async {
        guard !models.isEmpty else { return }
        for model in models {
            await promoteModelIfNeeded(model)
        }
    }

    private func promoteAllExistingModels() async {
        // Discover models in both app container and system directory
        var allModels: Set<String> = []

        // Check app container models first
        let appModels = ModelPromotion.discoverModels(in: modelsDirectory)
        allModels.formUnion(appModels)
        bridgeLog("MODEL_PROMOTION: Found \(appModels.count) models in app container", component: "MODEL_PROMOTION")

        // Check system Ollama models directory
        let systemOllamaDir = URL(fileURLWithPath: "\(NSHomeDirectory())/.ollama/models")
        if FileManager.default.fileExists(atPath: systemOllamaDir.path) {
            let systemModels = ModelPromotion.discoverModels(in: systemOllamaDir)
            allModels.formUnion(systemModels)
            bridgeLog("MODEL_PROMOTION: Found \(systemModels.count) models in system directory", component: "MODEL_PROMOTION")

            // Create symbolic links/copy system models to app container if needed
            for model in systemModels {
                await promoteSystemModelToAppContainer(model, systemDir: systemOllamaDir)
            }
        }

        guard !allModels.isEmpty else {
            bridgeLog("MODEL_PROMOTION: No models found in either app or system directories", component: "MODEL_PROMOTION")
            return
        }

        bridgeLog("MODEL_PROMOTION: Total unique models to promote: \(allModels.count)", component: "MODEL_PROMOTION")
        for model in allModels {
            await promoteModelIfNeeded(model)
        }
    }

    /// Promotes/copies a system model to the app container for sandboxed access
    private func promoteSystemModelToAppContainer(_ modelName: String, systemDir: URL) async {
        // Parse model name to extract registry, library, and tag
        let components = modelName.split(separator: ":")
        guard components.count >= 2 else {
            bridgeLog("MODEL_PROMOTION: Invalid model format: \(modelName)", component: "MODEL_PROMOTION")
            return
        }

        let modelTag = components[1]
        let modelComponents = components[0].split(separator: "/")
        guard modelComponents.count == 2 else {
            bridgeLog("MODEL_PROMOTION: Invalid model components: \(components[0])", component: "MODEL_PROMOTION")
            return
        }

        let registry = String(modelComponents[0])
        let library = String(modelComponents[1])

        // Source paths in system directory
        let systemManifestsDir = systemDir.appendingPathComponent("manifests/\(registry)/\(library)")

        // Destination paths in app container
        let appManifestsDir = modelsDirectory.appendingPathComponent("manifests/\(registry)/\(library)")
        let appBlobsDir = modelsDirectory.appendingPathComponent("blobs")

        do {
            // Create destination directories
            try FileManager.default.createDirectory(at: appManifestsDir, withIntermediateDirectories: true)
            try FileManager.default.createDirectory(at: appBlobsDir, withIntermediateDirectories: true)

            // Copy manifest file
            let modelTagString = String(modelTag)
            let systemManifestPath = systemManifestsDir.appendingPathComponent(modelTagString)
            let appManifestPath = appManifestsDir.appendingPathComponent(modelTagString)

            if FileManager.default.fileExists(atPath: systemManifestPath.path) &&
               !FileManager.default.fileExists(atPath: appManifestPath.path) {
                try FileManager.default.copyItem(at: systemManifestPath, to: appManifestPath)
                bridgeLog("MODEL_PROMOTION: Copied manifest for \(modelName) to app container", component: "MODEL_PROMOTION")
            }

            // Note: We don't copy blobs (model files) as they're large and can be accessed
            // directly by Ollama using the system paths. The manifest is sufficient for discovery.

        } catch {
            bridgeLog("MODEL_PROMOTION: Failed to promote model \(modelName): \(error)", component: "MODEL_PROMOTION")
        }
    }

    private let supportMessage = "Drat! An error occurred. For help, contact Marc at https://www.linkedin.com/in/marcmandel/."

    // MARK: - Ollama Binary Management

    /// Resolves the path to the Ollama executable.
    /// First tries bundled binary, then falls back to system installations.
    private func resolveOllamaPath() -> String? {
        let fileManager = FileManager.default

        // Priority 1: Try bundled Ollama binary in Contents/MacOS (sibling to main executable)
        // This is the correct location for executables in a Mac App Store bundle
        if let executableURL = Bundle.main.executableURL {
            let macosOllamaURL = executableURL.deletingLastPathComponent().appendingPathComponent("ollama", isDirectory: false)
            bridgeLog("Checking for Ollama at: \(macosOllamaURL.path)", component: "Ollama") 
            if fileManager.fileExists(atPath: macosOllamaURL.path) {
                bridgeLog("✅ Found Ollama at Contents/MacOS", component: "Ollama")
                return macosOllamaURL.path
            } else {
                bridgeLog("❌ Ollama NOT found at: \(macosOllamaURL.path)", component: "Ollama")
            }
        }
        
        // Priority 2: Fallback to Resources (legacy location)
        if let resourceURL = Bundle.main.resourceURL {
            let resourceOllamaURL = resourceURL.appendingPathComponent("ollama", isDirectory: false)
            if fileManager.fileExists(atPath: resourceOllamaURL.path) {
                return resourceOllamaURL.path
            } else {
                bridgeLog("Bundled Ollama not found at MacOS or Resources, trying system paths", component: "Ollama")
            }
        } else {
            bridgeLog("❌ Bundle resource path unavailable", component: "Ollama")
        }

        // Priority 2: System Ollama fallback REMOVED to ensure App Store compliance and robustness.
        // We must rely ONLY on the bundled binary.
        
        bridgeLog("❌ CRITICAL: No Ollama executable found in bundled resources.", component: "Ollama")
        return nil
    }
    
    /// Async helper to prepare binary for execution (fix permissions)
    private func prepareOllamaBinary() async -> String? {
        guard let path = resolveOllamaPath() else { return nil }
        await fixBinaryPermissions(at: URL(fileURLWithPath: path))
        
        // After fixing permissions, verify it's executable
        if FileManager.default.isExecutableFile(atPath: path) {
            bridgeLog("Found Ollama binary in Resources and confirmed executable: \(path)", component: "Ollama")
            return path
        } else {
            bridgeLog("Bundled Ollama found but not executable even after fix attempt: \(path)", component: "Ollama")
            return nil
        }
    }

    /// Attempts to remove quarantine attribute and ensure executable permissions
    private func fixBinaryPermissions(at url: URL) async {
        let path = url.path
        
        await Task.detached(priority: .userInitiated) {
            // 1. Remove quarantine attribute
            let xattrProcess = Process()
            xattrProcess.executableURL = URL(fileURLWithPath: "/usr/bin/xattr")
            xattrProcess.arguments = ["-d", "com.apple.quarantine", path]
            try? xattrProcess.run()
            xattrProcess.waitUntilExit()
            
            // 2. Ensure executable permission (chmod +x)
            let chmodProcess = Process()
            chmodProcess.executableURL = URL(fileURLWithPath: "/bin/chmod")
            chmodProcess.arguments = ["+x", path]
            try? chmodProcess.run()
            chmodProcess.waitUntilExit()
        }.value
        
        bridgeLog("Attempted permission fix for: \(path)", component: "Ollama")
    }

    private func sanitizedProcessEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        let proxyKeys = [
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
            "http_proxy", "https_proxy", "all_proxy", "no_proxy"
        ]
        for key in proxyKeys {
            env[key] = nil
        }

        let ollamaKeys = [
            "OLLAMA_HOME", "OLLAMA_MODELS", "OLLAMA_DATA", "OLLAMA_TMPDIR",
            "OLLAMA_HOST", "OLLAMA_LOG", "OLLAMA_ORIG_HOME", "OLLAMA_ORIG_DATA"
        ]
        for key in ollamaKeys {
            env[key] = nil
        }

        let loopbackBypass = "127.0.0.1,localhost"
        env["NO_PROXY"] = loopbackBypass
        env["no_proxy"] = loopbackBypass

        let embeddedRuntimeKeys = [
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONNOUSERSITE",
            "PYTHONDONTWRITEBYTECODE",
            "PYTHONUTF8",
            "DYLD_LIBRARY_PATH",
            "MARCUT_EXCLUDED_WORDS_PATH",
            "MARCUT_SYSTEM_PROMPT_PATH",
            "MARCUT_RULE_FILTER"
        ]
        for key in embeddedRuntimeKeys {
            if let rawValue = getenv(key) {
                let value = String(cString: rawValue)
                env[key] = value
            } else {
                env.removeValue(forKey: key)
            }
        }

        env["MARCUT_RULE_FILTER"] = ruleFilterValue
        return env
    }

    private func getOllamaEnvironment() -> [String: String] {
        var env = sanitizedProcessEnvironment()

        // Keep Ollama runtime fully inside local Application Support to avoid App Group permission issues
        try? FileManager.default.createDirectory(at: ollamaHomeURL, withIntermediateDirectories: true)
        env["OLLAMA_HOME"] = ollamaHomeURL.path
        env["OLLAMA_MODELS"] = modelsDirectory.path
        env["OLLAMA_DATA"] = ollamaHomeURL.appendingPathComponent("ollama-data").path
        env["HOME"] = localAppSupportURL.path

        // Ensure Ollama uses local storage only
        env["OLLAMA_HOST"] = ollamaHost          // server/CLI expects host:port (no scheme)
        env["MARCUT_OLLAMA_HOST"] = ollamaHost   // Python clients expect host:port
        // Use app container temp directory with proper permissions for App Store safety
        // Note: Ollama runners need exec permissions, so we create a special
        // temp directory within our app container and ensure it's executable
        guard let tmpDir = prepareAppContainerTempDir() else {
            let message = "Ollama could not start: cannot create exec-capable temp directory in app container"
            bridgeLog("❌ \(message)", component: "Ollama")
            ollamaLaunchError = message
            return [:]
        }
        ollamaLaunchError = nil
        env["TMPDIR"] = tmpDir.path
        env["OLLAMA_TMPDIR"] = tmpDir.path
        lastOllamaTmpDir = tmpDir
        
        // OLLAMA_RUNNERS_DIR doesn't prevent extraction - Ollama always extracts embedded runner
        // stageBundledRunner handles de-quarantining the extracted runner instead
        /*
        if let runnersDir = Bundle.main.resourceURL?.appendingPathComponent("ollama_runners") {
            env["OLLAMA_RUNNERS_DIR"] = runnersDir.path
            bridgeLog("Set OLLAMA_RUNNERS_DIR=\(runnersDir.path)", component: "Ollama")
        }
        */

        // Disable telemetry and external connections
        env["OLLAMA_NOPRUNE"] = "1"
        env["OLLAMA_FLASH_ATTENTION"] = "1"
        if let debugMode = UserDefaults.standard.object(forKey: "MarcutApp_DebugMode") as? Bool, debugMode {
             env["OLLAMA_DEBUG"] = "1"
        } else {
             env["OLLAMA_DEBUG"] = "1" // Force enabled for debugging session
        }
        env["OLLAMA_MAX_LOADED_MODELS"] = "1" // Reduce memory pressure
        env["OLLAMA_NOHISTORY"] = "1" // Privacy

        if isDebugLoggingEnabled {
            env["OLLAMA_LOG_LEVEL"] = "debug"
        }

        let helperDiagnosticsKey = "MARCUT_HELPER_DIAGNOSTICS"
        if isDebugLoggingEnabled {
            env[helperDiagnosticsKey] = "verbose"
        } else {
            env.removeValue(forKey: helperDiagnosticsKey)
        }

        // Ensure clean terminal output
        env["TERM"] = "dumb"
        env["NO_COLOR"] = "1"

        // Set PYTHONPATH for CLI fallback to find marcut module
        if let pythonSitePath = Bundle.main.resourcePath.map({ "\($0)/python_site" }) {
            env["PYTHONPATH"] = pythonSitePath
        }
        env["MARCUT_RULE_FILTER"] = ruleFilterValue

        // Create data directory if needed
        let dataDir = ollamaHomeURL.appendingPathComponent("ollama-data")
        try? FileManager.default.createDirectory(at: dataDir, withIntermediateDirectories: true)
        if isDebugLoggingEnabled {
            try? FileManager.default.createDirectory(at: ollamaLogsDirectory, withIntermediateDirectories: true)
        }
        
        // Explicitly create models/blobs directory to prevent permission errors
        let modelsDir = modelsDirectory
        let blobsDir = modelsDir.appendingPathComponent("blobs")
        try? FileManager.default.createDirectory(at: blobsDir, withIntermediateDirectories: true)

        return env
    }

    // Remove stale Ollama pid directories that cause subsequent starts to exit immediately
    private func pruneStaleOllamaPidFiles() {
        let tmpDir = ollamaHomeURL.appendingPathComponent("tmp", isDirectory: true)
        guard let contents = try? FileManager.default.contentsOfDirectory(
            at: tmpDir,
            includingPropertiesForKeys: nil
        ) else { return }

        for entry in contents where entry.lastPathComponent.hasPrefix("ollama") {
            let pidFile = entry.appendingPathComponent("ollama.pid")
            guard let pidString = try? String(contentsOf: pidFile).trimmingCharacters(in: .whitespacesAndNewlines),
                  let pid = Int32(pidString) else {
                continue
            }

            // If the pid is still running (or permission denied), leave it alone
            errno = 0
            let alive = (kill(pid, 0) == 0)
            let permissionDenied = errno == EPERM
            if alive || permissionDenied { continue }

            // Safe to remove the stale dir to unblock future launches
            try? FileManager.default.removeItem(at: entry)
        }
    }

    /// Remove stale pid directories at launch; optionally kill our own background process on demand.
    func launchCleanup() {
        pruneStaleOllamaPidFiles()
    }

    // MARK: - Bundled Marcut Executable Management

    private func getBundledMarcutPath() -> String? {
        // Check if marcut executable is bundled with the app
        if let bundledPath = Bundle.main.path(forResource: "marcut_executable", ofType: nil) {
            print("✅ Found bundled marcut at: \(bundledPath)")
            return bundledPath
        }

        // Also check in Resources directory
        if let resourcePath = Bundle.main.resourcePath {
            let marcutPath = "\(resourcePath)/marcut_executable"
            if FileManager.default.fileExists(atPath: marcutPath) {
                print("✅ Found bundled marcut in resources: \(marcutPath)")
                return marcutPath
            }
        }

        print("❌ Bundled marcut executable not found")
        return nil
    }

    // MARK: - Environment Checks

    func checkEnvironment(autoStart: Bool? = nil) {
        print("🔍 ENVIRONMENT_CHECK: Starting environment check...")
        print("🔍 ENVIRONMENT_CHECK: Ollama path: \(resolveOllamaPath() ?? "NOT FOUND")")
        print("🔍 ENVIRONMENT_CHECK: Current models: \(installedModels)")

        // Check system Ollama models directory
        let systemOllamaDir = "\(NSHomeDirectory())/.ollama/models"
        if FileManager.default.fileExists(atPath: systemOllamaDir) {
            print("🔍 ENVIRONMENT_CHECK: System Ollama models dir exists: \(systemOllamaDir)")
            do {
                let contents = try FileManager.default.contentsOfDirectory(atPath: systemOllamaDir)
                print("🔍 ENVIRONMENT_CHECK: System Ollama dir contents: \(contents)")
            } catch {
                print("❌ ENVIRONMENT_CHECK: Could not read system Ollama dir: \(error)")
            }
        } else {
            print("🔍 ENVIRONMENT_CHECK: System Ollama models dir does not exist: \(systemOllamaDir)")
        }

        let shouldAutoStart = autoStart ?? autoStartOllama
        Task {
            await promoteAllExistingModels()
            if shouldAutoStart {
                _ = await ensureOllamaRunning()
            }
            await loadInstalledModels()
        }

        // Log effective environment for diagnostics
        let env = getOllamaEnvironment()
        bridgeLog("ENV OLLAMA_HOME=\(env["OLLAMA_HOME"] ?? "")", component: "ENVIRONMENT_CHECK")
        bridgeLog("ENV OLLAMA_MODELS=\(env["OLLAMA_MODELS"] ?? "")", component: "ENVIRONMENT_CHECK")
        bridgeLog("ENV OLLAMA_DATA=\(env["OLLAMA_DATA"] ?? "")", component: "ENVIRONMENT_CHECK")
        bridgeLog("ENV OLLAMA_HOST=\(env["OLLAMA_HOST"] ?? "")", component: "ENVIRONMENT_CHECK")
        if let path = resolveOllamaPath() { bridgeLog("BIN ollama=\(path)", component: "ENVIRONMENT_CHECK") }
    }

    func refreshEnvironment() async {
        if !prefetchedFromDisk {
            // Offload disk scanning to detached task to avoid blocking main thread
            let dir = modelsDirectory
            let models = await Task.detached(priority: .userInitiated) {
                ModelPromotion.discoverModels(in: dir)
            }.value
            // Update state on MainActor
            let list = Array(models).sorted()
            self.installedModels = list
            self.prefetchedFromDisk = true
        }
        if autoStartOllama && allowOllamaService {
            _ = await ensureOllamaRunning()
        }
        await promoteAllExistingModels()
        await loadInstalledModels()
    }

    // MARK: - Diagnostic Methods

    func testOllamaConnection() async -> Bool {
        print("🔍 Testing Ollama connection...")

        guard let ollamaPath = await prepareOllamaBinary() else {
            print("   ❌ Ollama binary not found")
            return false
        }
        print("   ✅ Ollama binary: \(ollamaPath)")

        // Try to start Ollama if not running
        if !isOllamaRunning {
            print("   ⚠️ Ollama not running, attempting to start...")
            _ = await ensureOllamaRunning()
        }

        // Test with a simple command
        let env = getOllamaEnvironment()
        print("   📂 OLLAMA_HOME: \(env["OLLAMA_HOME"] ?? "not set")")
        print("   📂 OLLAMA_MODELS: \(env["OLLAMA_MODELS"] ?? "not set")")
        print("   🌐 OLLAMA_HOST: \(env["OLLAMA_HOST"] ?? "not set")")

        let result = await runCommand(ollamaPath, arguments: ["list"], environment: env)
        print("   Command result: \(result.success ? "✅" : "❌")")
        if !result.success {
            print("   Error output: \(result.output)")
        }

        return result.success
    }

    func debugDownloadModel(_ modelName: String) async -> Bool {
        print("\n🔧 Debug Download: \(modelName)")
        print("=====================================")

        guard let ollamaPath = await prepareOllamaBinary() else {
            print("❌ Ollama binary not found")
            return false
        }

        // Ensure Ollama is running
        if !isOllamaRunning {
            print("📌 Starting Ollama service...")
            let started = await ensureOllamaRunning()
            if !started {
                print("❌ Failed to start Ollama")
                return false
            }
        }

        print("\n📥 Attempting to download model...")
        let env = getOllamaEnvironment()
        let result = await runCommand(ollamaPath, arguments: ["pull", modelName], environment: env)

        print("\n📊 Final Result:")
        print("   Success: \(result.success)")
        print("   Output: \(result.output)")

        return result.success
    }

    func checkOllamaStatus() async {
        let ok = await probeOllamaHTTP()
        isOllamaRunning = ok
        if ok {
            bridgeLog("Ollama is running (HTTP probe)", component: "Ollama")
            ollamaLaunchError = nil
        } else {
            bridgeLog("Ollama is not running (HTTP probe)", component: "Ollama")
        }
    }

      private func probeExistingOllamaInstance() async -> Bool {
        // Check if any processes are using the Ollama port
        let existingPids = await pidsUsingOllamaPort()
        let hasExistingProcesses = !existingPids.isEmpty

        if hasExistingProcesses {
            bridgeLog("Found existing Ollama processes using port \(ollamaPort): \(existingPids)", component: "Ollama")
        }

        // Also try HTTP probe as a secondary check
        let httpResponding = await probeOllamaHTTP()
        if httpResponding {
            bridgeLog("Existing Ollama HTTP service detected", component: "Ollama")
        }

        return hasExistingProcesses || httpResponding
    }

    // MARK: - Ollama Process Management

    private var ollamaBackgroundProcess: Process?
    // Thread-safe logger (lazy initialized)
    private lazy var logManager: OllamaLogger = {
        OllamaLogger(logURL: self.ollamaLogFileURL)
    }()
    private var lastOllamaCheckTime: TimeInterval = 0
    private let ollamaCheckInterval: TimeInterval = 5.0  // Cache for 5 seconds
    private var prefetchedFromDisk = false
    private var lastOllamaTmpDir: URL?
    private var lastImmediateLaunchFailure = false
    private var ollamaOutputPipe: Pipe?  // Must be stored to prevent premature deallocation

    private func startBundledOllama() async -> Bool {
        guard let ollamaPath = await prepareOllamaBinary() else {
            bridgeLog("Cannot start Ollama - binary not found in app bundle.", component: "Ollama")
            return false
        }

        if let existingProcess = ollamaBackgroundProcess, existingProcess.isRunning {
            bridgeLog("Reusing existing Ollama background process (PID \(existingProcess.processIdentifier)).", component: "Ollama")
            writeOllamaLogEntry("Reusing existing process (PID \(existingProcess.processIdentifier))")
            ollamaLaunchError = nil
            return true
        }

        let process = Process()
        process.executableURL = URL(fileURLWithPath: ollamaPath)
        process.arguments = ["serve"]

        let env = getOllamaEnvironment()
        guard !env.isEmpty else {
            let message = ollamaLaunchError ?? "Ollama env creation failed (missing exec-capable TMPDIR)."
            bridgeLog("❌ \(message) Aborting launch.", component: "Ollama")
            lastImmediateLaunchFailure = true
            ollamaLaunchError = message
            return false
        }
        process.environment = env
        lastOllamaTmpDir = URL(fileURLWithPath: env["OLLAMA_TMPDIR"] ?? "")
        bridgeLog("Launching Ollama: TMPDIR=\(env["TMPDIR"] ?? "nil") OLLAMA_TMPDIR=\(env["OLLAMA_TMPDIR"] ?? "nil") OLLAMA_HOST=\(env["OLLAMA_HOST"] ?? "nil")", component: "Ollama")

        let logURL = ollamaLogURL
        
        // Ensure log file exists and is writable
        let fm = FileManager.default
        if !fm.fileExists(atPath: logURL.path) {
            fm.createFile(atPath: logURL.path, contents: nil)
        }
        
        // Ensure file has write permissions
        try? fm.setAttributes([.posixPermissions: NSNumber(value: Int16(0o644))], ofItemAtPath: logURL.path)

        // Open handle for writing via logManager
        // Ensure log file is ready
        _ = logManager.forceOpen()

        // Write startup entry to log IMMEDIATELY
        let startupEntry = "[Ollama] [\(ISO8601DateFormatter().string(from: Date()))] Ollama serve starting. Binary: \(process.executableURL?.path ?? "unknown")\n"
        logManager.write(startupEntry)
        logManager.flush()
        bridgeLog("✅ Wrote startup entry to ollama.log", component: "Ollama")

        // IMPORTANT: Pipe must be stored as instance property to prevent deallocation
        // If stored as local variable, it can be released when this function returns,
        // which kills the readabilityHandler before any data is received.
        let pipe = Pipe()
        self.ollamaOutputPipe = pipe  // Retain for lifetime of process
        process.standardOutput = pipe
        process.standardError = pipe
        
        // Read data in background to prevent buffer filling
        let outputHandle = pipe.fileHandleForReading
        var outputData = Data()
        // Use a dedicated serial queue for processing logic and file I/O
        let processingQueue = DispatchQueue(label: "com.marclaw.marcut.ollamaOutputProcessing")
        
        // Capture logger reference for safe background use
        let logger = self.logManager
        
        outputHandle.readabilityHandler = { [weak self] handle in
            // Read data immediately, limiting the scope of work on this IO callback
            let data = handle.availableData
            guard !data.isEmpty else { return }
            
            // Dispatch completely asynchronously to avoid blocking this IO callback
            processingQueue.async { [weak self, logger] in
                // Write to log file safely on background thread via thread-safe logger
                logger.write(data)
                
                // Keep buffer size reasonable for internal accumulation
                if outputData.count > 1_000_000 {
                    outputData = Data()
                }
                outputData.append(data)
                
                // Parse for server ready signal
                if let outputStr = String(data: data, encoding: .utf8) {
                    // Check for listening address (standard Ollama startup msg)
                    if outputStr.contains("Listening on") || outputStr.contains("127.0.0.1:11434") {
                        // We can't easily signal the outer async function from here without a continuation or checking a shared state externally,
                        // but we can log it. The outer loop checks the port via HTTP anyway.
                    }
                }
            }
        }



        let launchStart = Date()
        do {
            try process.run()
            // Non-blocking wait for process stability check
            try await Task.sleep(nanoseconds: 150_000_000) // 150ms check
            guard process.isRunning else {
                outputHandle.readabilityHandler = nil
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8) ?? ""
                bridgeLog("❌ Ollama process exited immediately after launch. status=\(process.terminationStatus) stdout/stderr=\(output)", component: "Ollama")
                bridgeLog("❌ Ollama env TMPDIR=\(env["TMPDIR"] ?? "nil") OLLAMA_TMPDIR=\(env["OLLAMA_TMPDIR"] ?? "nil") OLLAMA_HOME=\(env["OLLAMA_HOME"] ?? "nil")", component: "Ollama")
                // Detect port-in-use vs exec/noexec failures
                let lower = output.lowercased()
                let portInUse = lower.contains("address already in use") || lower.contains("bind: address already in use")
                if !portInUse {
                    let logPath = ollamaLogURL.path
                    ollamaLaunchError = "Ollama failed to start. See \(logPath) for runner details."
                }
                lastImmediateLaunchFailure = !portInUse
                return false
            }
            lastImmediateLaunchFailure = false

            ollamaBackgroundProcess = process
            let elapsed = Date().timeIntervalSince(launchStart)
            bridgeLog(
                String(format: "✅ Ollama process started directly (PID: %d) in %.2fs", process.processIdentifier, elapsed),
                component: "Ollama"
            )

            // Use weak self to avoid retain cycle in termination handler
            process.terminationHandler = { [weak self] terminated in
                // Stop reading
                outputHandle.readabilityHandler = nil
                
                Task { @MainActor in
                    bridgeLog(
                        "Ollama process terminated (PID: \(terminated.processIdentifier), code: \(terminated.terminationStatus))",
                        component: "Ollama"
                    )
                    
                    self?.isOllamaRunning = false
                    self?.launchedOllamaPID = nil
                    self?.launchedOllamaPort = nil
                    self?.ollamaBackgroundProcess = nil
                    self?.ollamaOutputPipe = nil  // Release pipe now that process is done
                    // self?.closeOllamaLogHandle() // Cleanup old handle if any - DISABLED to avoid race with readabilityHandler

                    // Log captured output
                    // Log captured output
                    var drained = Data()
                    processingQueue.sync {
                        drained = outputData
                        outputData.removeAll(keepingCapacity: false)
                    }

                    if !drained.isEmpty {
                        let logContent = String(decoding: drained, as: UTF8.self)
                        let lines = logContent.components(separatedBy: .newlines)
                        let lastLines = lines.suffix(20).joined(separator: "\n")
                        bridgeLog("🔍 Last 20 lines of Ollama output:\n\(lastLines)", component: "Ollama")
                        
                        if let self = self {
                            // Do not overwrite the log file here; readabilityHandler streams it.
                            bridgeLog("📝 Ollama process finished. Log saved to \(self.ollamaLogURL.path)", component: "Ollama")
                        }
                    } else {
                        bridgeLog("⚠️ No output captured from Ollama process", component: "Ollama")
                    }
                }
            }

            return true
        } catch {
            bridgeLog("❌ OLLAMA_DIRECT_START_FAILED: \(error.localizedDescription)", component: "Ollama")
            ollamaBackgroundProcess = nil
            closeOllamaLogHandle()
            return false
        }
    }

    private func waitForOllamaHTTP() async -> Bool {
        let maxAttempts = 15  // Increased from 8 for robust startup
        let baseInterval: TimeInterval = 0.5  // More reasonable base interval

        for attempt in 1...maxAttempts {
            bridgeLog("Ollama HTTP probe attempt \(attempt)/\(maxAttempts)", component: "Ollama")

            // Bail out early if the process died during startup instead of sleeping the full backoff window
            if let process = ollamaBackgroundProcess, !process.isRunning {
                bridgeLog("Ollama process exited while waiting for HTTP readiness", component: "Ollama")
                return false
            }

            if await probeOllamaHTTP() {
                bridgeLog("Ollama HTTP endpoint is responding", component: "Ollama")
                return true
            }

            // Optimized backoff: 0.2s, 0.4s, 0.8s, 1.6s, 3.2s (max out at 3.2s)
            let interval = min(baseInterval * pow(2.0, Double(attempt - 1)), 3.2)
            try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
        }

        bridgeLog("Ollama HTTP endpoint failed to respond after \(maxAttempts) attempts", component: "Ollama")
        ollamaLaunchError = "Ollama did not respond on \(ollamaHost). See \(ollamaLogURL.path) for details."
        return false
    }

    @discardableResult
    private func ensureOllamaRunning(forceProbe: Bool = false) async -> Bool {
        // XPC removed - use direct CLI subprocess only
        return await ensureOllamaRunningDirect(forceProbe: forceProbe)
    }

    // XPC functionality removed - now using direct CLI subprocess approach only

    private func probeHTTPWithBackoff() async -> Bool {
        let attempts = 10
        let base: TimeInterval = 0.2
        for i in 0..<attempts {
            if await probeOllamaHTTP() { return true }
            let interval = min(base * pow(2.0, Double(i)), 2.0)
            try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
        }
        return false
    }

    // Existing direct logic preserved here
    private func ensureOllamaRunningDirect(forceProbe: Bool = false) async -> Bool {
        guard allowOllamaService else {
            bridgeLog("Ollama service disabled; skipping ensureOllamaRunning()", component: "Ollama")
            return false
        }
        guard resolveOllamaPath() != nil else {
            bridgeLog("Cannot start Ollama - binary not found", component: "Ollama")
            return false
        }

        let currentTime = Date().timeIntervalSince1970

        // Performance optimization: Skip redundant checks if we recently verified Ollama is running
        if !forceProbe && isOllamaRunning && (currentTime - lastOllamaCheckTime) < ollamaCheckInterval {
            bridgeLog("Ollama status cached - skipping check", component: "Ollama")
            return true
        }

        // If we already have a running bundled process, reuse it and avoid changing ports
            if let process = ollamaBackgroundProcess,
               process.isRunning,
               let launchedPort = launchedOllamaPort {
                // If the temp dir used by the running process differs from the desired exec-capable tmp, restart.
                let currentTmp = prepareOllamaTmpDir()
                if let currentTmp, lastOllamaTmpDir == nil || lastOllamaTmpDir?.path != currentTmp.path {
                    bridgeLog("Ollama temp dir missing/mismatched; restarting to apply exec-capable TMPDIR", component: "Ollama")
                    process.terminate()
                    ollamaBackgroundProcess = nil
                    launchedOllamaPID = nil
                    launchedOllamaPort = nil
                } else {
                    ollamaPort = launchedPort
                    updateOllamaPortEnvironment()
                    if await probeOllamaHTTP() {
                        bridgeLog("Reusing existing bundled Ollama (PID \(process.processIdentifier)) on port \(launchedPort)", component: "Ollama")
                        sanitizeActiveOllamaRunners()
                        isOllamaRunning = true
                        lastOllamaCheckTime = currentTime
                        ollamaLaunchError = nil
                        return true
                    } else {
                    bridgeLog("Cached Ollama process unresponsive; clearing reference", component: "Ollama")
                    ollamaBackgroundProcess = nil
                    launchedOllamaPID = nil
                    launchedOllamaPort = nil
                }
            }
        }

        if let task = ollamaStartTask {
            return await task.value
        }

        let task = Task { [weak self] in
            guard let self else { return false }
            let result = await self.performOllamaStartup(currentTime: currentTime)
            await MainActor.run {
                self.ollamaStartTask = nil
            }
            return result
        }
        ollamaStartTask = task
        return await task.value
    }

    @MainActor
    private func performOllamaStartup(currentTime: TimeInterval) async -> Bool {
        pruneStaleOllamaPidFiles()
        let tmpPath = prepareOllamaTmpDir()?.path ?? "<unavailable>"
        bridgeLog("Starting Ollama with host=\(ollamaHost) tmp=\(tmpPath)", component: "Ollama")

        // Try up to 20 ports starting at 11434; reuse our own instance if healthy
        for offset in 0..<20 {
            let candidatePort = 11434 + Int32(offset)
            let pidsOnPort = await pids(using: candidatePort)

            // If foreign/system processes are using this port, skip it
            if !pidsOnPort.isEmpty {
                if let launchedPort = launchedOllamaPort,
                   let launchedPID = launchedOllamaPID,
                   launchedPort == candidatePort,
                   pidsOnPort.contains(launchedPID),
                   await probeOllamaHTTP() {
                    ollamaPort = launchedPort
                    updateOllamaPortEnvironment()
                    bridgeLog("Reusing bundled Ollama instance (PID \(launchedPID)) on port \(launchedPort)", component: "Ollama")
                    isOllamaRunning = true
                    lastOllamaCheckTime = currentTime
                    return true
                }
                // Foreign process present; do not attempt to bind this port
                bridgeLog("Skipping port \(candidatePort) - already in use by external process(es): \(pidsOnPort)", component: "Ollama")
                // Occupied by non-app process; move to next port
                continue
            }
            
            // SANDBOX FIX: lsof often fails to see other processes in sandbox.
            // Explicitly check if we can connect to this port. If we can, it's occupied.
            if await isPortOccupied(port: candidatePort) {
                bridgeLog("Skipping port \(candidatePort) - TCP connection accepted (ghost/zombie process)", component: "Ollama")
                continue
            }

            // Select this free port and attempt to start
            ollamaPort = candidatePort
            updateOllamaPortEnvironment()
            bridgeLog("🚀 Starting new Ollama instance on port \(candidatePort)", component: "Ollama")
            let started = await startBundledOllama()
            if !started {
                bridgeLog("❌ OLLAMA_PROCESS_START_FAILED: Unable to start Ollama process on port \(candidatePort)", component: "Ollama")
                dumpOllamaLogs()
                // If launch failed immediately (likely exec/noexec), abort further port attempts
                // BUT: If it failed because of "address already in use", we MUST retry!
                if lastImmediateLaunchFailure {
                    // Check if it was a bind error
                    let logContent = (try? String(contentsOf: ollamaLogFileURL)) ?? ""
                    if logContent.contains("address already in use") {
                        bridgeLog("⚠️ Port \(candidatePort) was actually in use (bind failed). Retrying next port...", component: "Ollama")
                        continue
                    }
                    
                    bridgeLog("❌ OLLAMA_LAUNCH_ABORT: Immediate failure (exec/noexec). Not retrying other ports.", component: "Ollama")
                    break
                }
                continue
            }
            sanitizeActiveOllamaRunners()
            launchedOllamaPID = ollamaBackgroundProcess?.processIdentifier
            launchedOllamaPort = ollamaPort

            // Wait for HTTP endpoint to be ready (reasonable timeout - ~60s total)
            bridgeLog("⏳ Waiting for Ollama HTTP endpoint to respond", component: "Ollama")
            let httpReady = await waitForOllamaHTTP()
            if httpReady {
                sanitizeActiveOllamaRunners()
                bridgeLog("✅ Ollama started successfully and is ready on port \(candidatePort)", component: "Ollama")
                isOllamaRunning = true
                lastOllamaCheckTime = currentTime
                ollamaLaunchError = nil
                return true
            }

            bridgeLog("❌ OLLAMA_HTTP_TIMEOUT on port \(candidatePort): Process started but HTTP endpoint not responding", component: "Ollama")
            dumpOllamaLogs()

            // Clean up the failed process immediately
            if let process = ollamaBackgroundProcess {
                bridgeLog("🧹 Cleaning up failed Ollama process on port \(candidatePort)", component: "Ollama")
                process.terminate()
                ollamaBackgroundProcess = nil
                // closeOllamaLogHandle() - DISABLED to allow final logs to flush
            }
            launchedOllamaPID = nil
            launchedOllamaPort = nil
        }

        bridgeLog("❌ No free ports available for bundled Ollama after 20 attempts", component: "Ollama")
        isOllamaRunning = false
        return false
    }

    /// Waits for a specific model to be loadable via /api/show. This helps avoid race conditions where
    /// the server is up but the model is not yet ready to serve generate requests.
    func waitForModelReadiness(modelName: String, maxAttempts: Int = 8) async -> Bool {
        // Ensure service is running first
        guard await ensureOllamaRunning() else {
            bridgeLog("waitForModelReadiness: Ollama not running", component: "Ollama")
            return false
        }

        sanitizeActiveOllamaRunners()

        let baseInterval: TimeInterval = 0.3
        for attempt in 1...maxAttempts {
            bridgeLog("Probing model readiness \(modelName) attempt \(attempt)/\(maxAttempts)", component: "Ollama")
            if await probeModelReady(modelName: modelName) {
                bridgeLog("Model \(modelName) is ready for generation", component: "Ollama")
                return true
            }
            let interval = min(baseInterval * pow(1.6, Double(attempt - 1)), 2.0)
            try? await Task.sleep(nanoseconds: UInt64(interval * 1_000_000_000))
        }
        bridgeLog("Model \(modelName) did not report ready after \(maxAttempts) attempts", component: "Ollama")
        return false
    }

    private func probeOllamaHTTP() async -> Bool {
        do {
            // Use reasonable timeout for local connections (3.0s instead of 0.5s)
            // This allows Ollama sufficient time to respond during startup
            if let (code, data) = try await ollamaHTTP(path: "/api/version", timeout: 3.0) {
                if code == 200 {
                    if let data = data { bridgeLog("✅ HTTP /api/version status=200 body=\(stringSnippet(data))", component: "HTTP") }
                    return true
                } else if code == -1004 {
                    // Connection refused - Ollama not running
                    bridgeLog("🔌 HTTP connection refused - Ollama not running", component: "HTTP")
                    return false
                } else if code == -1001 {
                    // Request timeout - Ollama hanging
                    bridgeLog("⏰ HTTP request timeout - Ollama unresponsive", component: "HTTP")
                    return false
                } else {
                    if let data = data { bridgeLog("⚠️ HTTP /api/version status=\(code) body=\(stringSnippet(data))", component: "HTTP") }
                    return false
                }
            }
        } catch {
            let errorMessage = error.localizedDescription
            if errorMessage.contains("Could not connect") {
                bridgeLog("🔌 HTTP connection failed - Ollama not running", component: "HTTP")
            } else if errorMessage.contains("timed out") {
                bridgeLog("⏰ HTTP request timed out - Ollama unresponsive", component: "HTTP")
            } else {
                bridgeLog("❌ HTTP probe failed: \(errorMessage)", component: "HTTP")
            }
        }
        return false
    }

    private func isPortOccupied(port: Int32) async -> Bool {
        // We use the existing ollamaHTTP probe logic but strictly for connection checking
        // If we get ANY response (even 404, 500, or just a connection), the port is taken.
        // We only consider it free if the connection is REFUSED.
        
        guard let url = URL(string: "http://127.0.0.1:\(port)/") else { return false }
        var req = URLRequest(url: url)
        req.httpMethod = "GET" // Use GET as HEAD might be rejected
        req.timeoutInterval = 1.0 // Increase timeout slightly
        
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 1.0
        config.timeoutIntervalForResource = 1.0
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        
        do {
            let (_, _) = try await session.data(for: req)
            // If we get here, we connected. Port is busy.
            bridgeLog("isPortOccupied: Port \(port) is BUSY (connection accepted)", component: "Ollama")
            return true
        } catch {
            let nsError = error as NSError
            // If connection refused (code -1004), port is likely free.
            if nsError.domain == NSURLErrorDomain && nsError.code == -1004 {
                // bridgeLog("isPortOccupied: Port \(port) is FREE (connection refused)", component: "Ollama")
                return false
            }
            // Any other error (timeout, etc) implies something might be there or network is weird.
            bridgeLog("isPortOccupied: Port \(port) check failed with error: \(error). Assuming BUSY.", component: "Ollama")
            return true 
        }
    }
    private func ollamaHTTP(path: String, timeout: TimeInterval) async throws -> (Int, Data?)? {
        // Build URL from OLLAMA_HOST (host:port)
        guard let url = URL(string: "http://\(ollamaHost)\(path)") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "GET"
        req.cachePolicy = URLRequest.CachePolicy.reloadIgnoringLocalCacheData
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.connectionProxyDictionary = [:]
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        do {
            let (data, resp) = try await session.data(for: req)
            if let http = resp as? HTTPURLResponse { return (http.statusCode, data) }
        } catch {
            bridgeLog("HTTP request failed path=\(path) error=\(error)", component: "HTTP")
            throw error
        }
        return nil
    }

    private func ollamaHTTPPostJSON(path: String, payload: [String: Any], timeout: TimeInterval) async throws -> (Int, Data?)? {
        guard let url = URL(string: "http://\(ollamaHost)\(path)") else { return nil }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.cachePolicy = URLRequest.CachePolicy.reloadIgnoringLocalCacheData
        req.httpBody = try? JSONSerialization.data(withJSONObject: payload, options: [])

        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = timeout
        config.timeoutIntervalForResource = timeout
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.connectionProxyDictionary = [:]

        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        do {
            let (data, resp) = try await session.data(for: req)
            if let http = resp as? HTTPURLResponse { return (http.statusCode, data) }
        } catch {
            bridgeLog("HTTP POST failed path=\(path) error=\(error)", component: "HTTP")
            throw error
        }
        return nil
    }

    private func probeModelReady(modelName: String) async -> Bool {
        do {
            if let (code, data) = try await ollamaHTTPPostJSON(path: "/api/show", payload: ["name": modelName], timeout: 5.0) {
                if code == 200 {
                    if let data = data { bridgeLog("✅ /api/show \(modelName) status=200 body=\(stringSnippet(data))", component: "HTTP") }
                    return true
                } else {
                    if let data = data { bridgeLog("⚠️ /api/show \(modelName) status=\(code) body=\(stringSnippet(data))", component: "HTTP") }
                    return false
                }
            }
        } catch {
            bridgeLog("❌ /api/show probe failed for \(modelName): \(error.localizedDescription)", component: "HTTP")
            return false
        }
        return false
    }

    private struct OllamaTags: Decodable { let models: [OllamaTags.Model]; struct Model: Decodable { let name: String } }

    private func stringSnippet(_ data: Data, limit: Int = 512) -> String {
        if let s = String(data: data.prefix(limit), encoding: .utf8) {
            return s.replacingOccurrences(of: "\n", with: " ").prefix(500).description
        }
        return "<non-utf8 data>"
    }

    private func pidsUsingOllamaPort() async -> [Int32] {
        await pids(using: ollamaPort)
    }

    private func pids(using port: Int32) async -> [Int32] {
        let lsofCandidates = ["/usr/sbin/lsof", "/usr/bin/lsof"]
        guard let lsofPath = lsofCandidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            return []
        }

        return await withCheckedContinuation { continuation in
            let process = Process()
            process.executableURL = URL(fileURLWithPath: lsofPath)
            process.arguments = ["-i", ":\(port)", "-t"]
            
            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = Pipe() // Silence errors
            
            do {
                try process.run()
                process.waitUntilExit()
                
                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                if let output = String(data: data, encoding: .utf8) {
                    let pids = output.components(separatedBy: .newlines)
                        .compactMap { Int32($0.trimmingCharacters(in: .whitespaces)) }
                    continuation.resume(returning: pids)
                } else {
                    continuation.resume(returning: [])
                }
            } catch {
                continuation.resume(returning: [])
            }
        }
    }

    private func isPortInUse(_ port: Int32) async -> Bool {
        !(await pids(using: port)).isEmpty
    }

    private func selectBundledOllamaPort(base: Int32 = 11434, attempts: Int = 20) async -> Int32? {
        var candidate = base
        for _ in 0..<attempts {
            let pidsOnPort = await pids(using: candidate)

            // If this port is occupied by processes other than the bundled one, skip
            if !pidsOnPort.isEmpty {
                if let launchedPort = launchedOllamaPort,
                   let launchedPID = launchedOllamaPID,
                   launchedPort == candidate,
                   pidsOnPort.count == 1,
                   pidsOnPort.contains(launchedPID) {
                    return candidate // Our own instance is already bound here
                }
                candidate += 1
                continue
            }

            return candidate
        }
        return nil
    }

    private func findAvailablePort(startingAt start: Int32 = 11435, attempts: Int = 10) async -> Int32? {
        var port = start
        for _ in 0..<attempts {
            if !(await isPortInUse(port)) {
                return port
            }
            port += 1
        }
        return nil
    }

    private func parseDownloadProgress(_ output: String) -> Double {
        // Clean ANSI escape sequences first
        let cleanOutput = removeANSIEscapeCodes(output)

        // Look for the actual Ollama format: "pulling 667b0c1932bc: 13%"
        // The percentage appears after a colon
        if let percentMatch = cleanOutput.range(of: #":\s*(\d+)%"#, options: .regularExpression) {
            let percentText = String(cleanOutput[percentMatch])
            // Extract just the number from ": 13%"
            if let numMatch = percentText.range(of: #"\d+"#, options: .regularExpression) {
                let percentString = String(percentText[numMatch])
                if let percent = Double(percentString) {
                    return percent
                }
            }
        }

        // Fallback: Try to find any percentage
        if let percentRange = cleanOutput.range(of: #"\d+%"#, options: .regularExpression) {
            let percentString = String(cleanOutput[percentRange]).replacingOccurrences(of: "%", with: "")
            if let percent = Double(percentString) {
                return percent
            }
        }

        // Check for data transfer progress (e.g., "2.1 GB/4.9 GB")
        if let match = cleanOutput.range(of: #"(\d+\.?\d*)\s*[KMGT]B/(\d+\.?\d*)\s*[KMGT]B"#, options: .regularExpression) {
            let progressText = String(cleanOutput[match])
            let components = progressText.components(separatedBy: "/")
            if components.count == 2 {
                let current = parseSize(components[0])
                let total = parseSize(components[1])
                if total > 0 {
                    return (current / total) * 100.0
                }
            }
        }

        // Check for various status indicators
        if cleanOutput.contains("pulling manifest") {
            return 1.0 // Just starting
        } else if cleanOutput.contains("pulling") && cleanOutput.contains("667b0c1932bc") {
            // Model layer is downloading, check for size info
            if cleanOutput.contains("MB/4.9 GB") || cleanOutput.contains("GB/4.9 GB") {
                // Extract current size
                if let sizeMatch = cleanOutput.range(of: #"(\d+\.?\d*)\s*[MG]B/4\.9\s*GB"#, options: .regularExpression) {
                    let sizeText = String(cleanOutput[sizeMatch])
                    let parts = sizeText.components(separatedBy: "/")
                    if let first = parts.first {
                        let current = parseSize(first)
                        let total = 4.9 * 1024 * 1024 * 1024 // 4.9 GB in bytes
                        if current > 0 {
                            return min((current / total) * 100.0, 99.0)
                        }
                    }
                }
            }
            return 2.0 // Downloading but no clear progress
        } else if cleanOutput.contains("verifying") {
            return 95.0 // Almost done
        } else if cleanOutput.contains("success") || cleanOutput.contains("complete") {
            return 100.0
        }

        return 0.0
    }

    private func parseSize(_ sizeString: String) -> Double {
        let cleanedString = sizeString.trimmingCharacters(in: .whitespaces)
        let pattern = #"(\d+\.?\d*)\s*([KMGT]B)"#

        guard let regex = try? NSRegularExpression(pattern: pattern, options: []),
              let match = regex.firstMatch(in: cleanedString, options: [], range: NSRange(cleanedString.startIndex..., in: cleanedString)),
              let valueRange = Range(match.range(at: 1), in: cleanedString),
              let unitRange = Range(match.range(at: 2), in: cleanedString) else {
            return 0
        }

        let value = Double(cleanedString[valueRange]) ?? 0
        let unit = String(cleanedString[unitRange])

        switch unit {
        case "KB": return value * 1024
        case "MB": return value * 1024 * 1024
        case "GB": return value * 1024 * 1024 * 1024
        case "TB": return value * 1024 * 1024 * 1024 * 1024
        default: return value
        }
    }

    private func closeOllamaLogHandle() {
        logManager.close()
        bridgeLog("Closed ollama.log handle", component: "Ollama")
    }
    
    // Removed ensureOllamaLogHandle as it's replaced by logManager internals
    
    /// Force flush any pending ollama log data to disk
    func flushOllamaLog() {
        logManager.flush()
    }
    
    /// Write a timestamped entry to the ollama log (for debugging/status messages)
    func writeOllamaLogEntry(_ message: String) {
        let entry = "[Ollama] [\(ISO8601DateFormatter().string(from: Date()))] \(message)\n"
        logManager.write(entry)
    }

    // MARK: - Unified Subprocess Execution

    /// Primary redaction execution method using subprocess
    /// This is the unified execution pathway for both GUI and CLI modes
    private func runRedaction(
        documentId: UUID,
        inputPath: String,
        outputPath: String,
        reportPath: String,
        model: String,
        mode: String,
        debug: Bool = false,
        onProgress: ((String) -> Void)? = nil
    ) async -> Bool {
        bridgeLog("UNIFIED: Starting redaction execution via subprocess", component: "UNIFIED_EXECUTION")

        guard let launcherPath = Bundle.main.path(forResource: "python_launcher", ofType: "sh") else {
            bridgeLog("UNIFIED: python_launcher.sh not found in bundle", component: "UNIFIED_EXECUTION")
            return false
        }


        // Build Python script based on mode
        // CRITICAL: Use Bundle path, not hardcoded dev path
        // CRITICAL: Escape paths to prevent quote injection
        guard let pythonSitePath = Bundle.main.resourcePath.map({ "\($0)/python_site" }) else {
            bridgeLog("UNIFIED: Could not determine python_site path from bundle", component: "UNIFIED_EXECUTION")
            return false
        }
        
        // Escape single quotes in paths to prevent injection
        func escapePath(_ path: String) -> String {
            return path.replacingOccurrences(of: "'", with: "'\"'\"'")
        }
        
        let safeInputPath = escapePath(inputPath)
        let safeOutputPath = escapePath(outputPath)
        let safeReportPath = escapePath(reportPath)
        let safePythonSitePath = escapePath(pythonSitePath)
        
        let pythonScript: String
        if mode == "enhanced" && model != "mock" {
            pythonScript = """
            import sys;
            sys.path.insert(0, '\(safePythonSitePath)');
            from marcut.unified_redactor import run_unified_redaction;
            result = run_unified_redaction('\(safeInputPath)', '\(safeOutputPath)', '\(safeReportPath)', mode='enhanced', model='\(model)', debug=\(debug ? "True" : "False"));
            exit_code = 0 if result.get('success', False) else 1;
            sys.exit(exit_code)
            """
        } else {
            pythonScript = """
            import sys;
            import traceback;

            sys.path.insert(0, '\(safePythonSitePath)');

            try:
                from marcut.unified_redactor import run_unified_redaction;
                result = run_unified_redaction('\(safeInputPath)', '\(safeOutputPath)', '\(safeReportPath)', mode='rules', model='\(model)', debug=\(debug ? "True" : "False"));
                exit_code = 0 if result.get('success', False) else 1
                sys.exit(exit_code)
            except Exception as e:
                import traceback;
                traceback.print_exc();
                sys.exit(9)
            """
        }

        let cliArguments = ["-c", pythonScript]

        
        // Get environment for subprocess execution
        var cliEnvironment = getOllamaEnvironment()

        // Set PYTHONPATH for marcut module discovery
        if let pythonSitePath = Bundle.main.resourcePath.map({ "\($0)/python_site" }) {
            cliEnvironment["PYTHONPATH"] = pythonSitePath
        }

        // Create process for execution
        let process = Process()
        
        // Track the process for cancellation
        activeProcesses[documentId] = process
        defer {
            activeProcesses.removeValue(forKey: documentId)
        }
        
        process.executableURL = URL(fileURLWithPath: launcherPath)
        process.arguments = cliArguments
        process.environment = cliEnvironment

        // Capture output
        let outputPipe = Pipe()
        process.standardOutput = outputPipe
        process.standardError = outputPipe

        let outputQueue = DispatchQueue(label: "com.marcut.output")
        var outputData = Data()
        var outputBuffer = ""

        outputPipe.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }

            outputQueue.async {
                outputData.append(data)
                guard let chunk = String(data: data, encoding: .utf8) else { return }
                outputBuffer.append(chunk)

                let endsWithNewline = outputBuffer.last?.isNewline == true
                let parts = outputBuffer.split(omittingEmptySubsequences: false, whereSeparator: { $0.isNewline })
                let completeLines = endsWithNewline ? parts : parts.dropLast()

                for line in completeLines {
                    let text = String(line).trimmingCharacters(in: .whitespacesAndNewlines)
                    if !text.isEmpty {
                        onProgress?(text)
                    }
                }

                outputBuffer = endsWithNewline ? "" : String(parts.last ?? "")
            }
        }

        bridgeLog("UNIFIED: Executing subprocess with mode=\(mode), model=\(model)", component: "UNIFIED_EXECUTION")

        do {
            try process.run()
            process.waitUntilExit()
            
            // Clean up handler
            outputPipe.fileHandleForReading.readabilityHandler = nil
            
            // Wait for queue to drain
            outputQueue.sync { }
            
            if !outputBuffer.isEmpty {
                let finalLine = outputBuffer.trimmingCharacters(in: .whitespacesAndNewlines)
                if !finalLine.isEmpty {
                    onProgress?(finalLine)
                }
                outputBuffer = ""
            }

            let output = String(data: outputData, encoding: .utf8) ?? ""
            let exitCode = process.terminationStatus
            let success = exitCode == 0

            bridgeLog("UNIFIED: Process completed with exit code \(exitCode)", component: "UNIFIED_EXECUTION")
            
            // If success, log the final output for debugging
            if !success {
                bridgeLog("UNIFIED: Error output: \(output)", component: "UNIFIED_EXECUTION")
            } else {
                 bridgeLog("UNIFIED: Successfully completed redaction", component: "UNIFIED_EXECUTION")
            }

            return success
        } catch {
            bridgeLog("UNIFIED: Failed to execute subprocess: \(error)", component: "UNIFIED_EXECUTION")
            return false
        }
    }

    // MARK: - Document Processing

    // Note: analyzeDocument function removed as it was PythonKit-dependent
    // Document analysis now handled directly through processDocument

    func processDocument(
        _ item: DocumentItem,
        settings: RedactionSettings,
        outputDirectory: URL,
        heartbeat: ((Int, Int, String?) -> Void)? = nil,
        cliMode: Bool = false
    ) async -> Bool {
        applyRuleFilter(settings.enabledRules)
        // Initialize comprehensive logging
        let logPath = DebugLogger.shared.logPath
        logToFile(logPath, "=== MARCUT PROCESSING START ===")
        logToFile(logPath, "Timestamp: \(Date())")

        item.status = .processing
        item.progress = 0.0

        logToFile(logPath, "Status set to processing")

        // Ensure the environment is ready before invoking the CLI
        let usingMockBackend = settings.backend.lowercased() == "mock"

        // 1) Ensure Ollama service is running (start and wait if needed) — skip for mock backend or rules-only mode
        if !usingMockBackend && settings.mode != .rules && !isOllamaRunning {
            logToFile(logPath, "Ollama not running; attempting to start...")
            let started = await ensureOllamaRunning()
            if !started {
                logToFile(logPath, "❌ Ollama service did not start")
                item.status = .failed
                item.errorMessage = supportMessage
                return false
            }
        }

        // Refresh installed model list once Ollama is reachable so we do not force unnecessary downloads
        if !usingMockBackend && settings.mode != .rules {
            await loadInstalledModels()
        }

        // 2) Ensure required model is present; download on first use — skip for mock backend or rules-only mode
        if !usingMockBackend && settings.mode != .rules && !installedModels.contains(settings.model) {
            logToFile(logPath, "Required model not installed: \(settings.model). Starting download...")
            item.status = .analyzing
            item.progress = 0.0
            let ok = await downloadModel(settings.model, progress: { pct in
                // Map 0..100 to 0..0.3 during model download to differentiate from processing
                item.progress = max(0.0, min(1.0, pct / 100.0 * 0.3))
            })
            if !ok {
                logToFile(logPath, "❌ Model download failed: \(settings.model)")
                item.status = .failed
                item.errorMessage = "Failed to download model \(settings.model)."
                return false
            }
            await loadInstalledModels()
            if !installedModels.contains(settings.model) {
                logToFile(logPath, "❌ Model not available after download: \(settings.model)")
                item.status = .failed
                item.errorMessage = "Model \(settings.model) not available after download."
                return false
            }
            item.status = .processing
            item.progress = 0.0
        }

        // Prepare working directory inside App Support (sandbox-safe for child process)
        let inputURL = URL(fileURLWithPath: item.path)
        let baseName = inputURL.deletingPathExtension().lastPathComponent
        defer {
            removeWorkArtifacts(for: baseName)
        }
        let stagingDir = workDirectory
        try? FileManager.default.createDirectory(at: stagingDir, withIntermediateDirectories: true)

        // Copy input DOCX into working directory on background thread
        let workInputURL = stagingDir.appendingPathComponent("\(baseName)_input.docx")
        if cliMode {
            let standardizedInput = inputURL.standardizedFileURL
            let allowedRoot = appSupportURL.standardizedFileURL.path
            let inputPath = standardizedInput.path
            let hasAccess = inputPath == allowedRoot || inputPath.hasPrefix(allowedRoot + "/")
            if !hasAccess {
                let errorMessage = """
CLI Error: Input file '\(inputPath)' is outside the sandboxed App Group container. Place CLI inputs under \(allowedRoot) (e.g. \(allowedRoot)/Input or \(allowedRoot)/Work) before running.
"""
                logToFile(logPath, "❌ \(errorMessage)")
                item.status = .failed
                item.errorMessage = errorMessage
                return false
            }
        }
        let copySuccess = await Task.detached(priority: .userInitiated) {
            do {
                if FileManager.default.fileExists(atPath: workInputURL.path) {
                    try? FileManager.default.removeItem(at: workInputURL)
                }
                try FileManager.default.copyItem(at: inputURL, to: workInputURL)
                logToFile(logPath, "Copied input to work path: \(workInputURL.path)")
                return true
            } catch {
                let sourceExists = FileManager.default.fileExists(atPath: inputURL.path)
                logToFile(logPath, "❌ Failed to copy input to work path: \(error)")
                logToFile(
                    logPath,
                    "❌ COPY DEBUG: source=\(inputURL.path) exists=\(sourceExists) destination=\(workInputURL.path)"
                )
                logToFile(logPath, "❌ DETAILED ERROR: \(error.localizedDescription)")
                return false
            }
        }.value

        if !copySuccess {
            item.status = .failed
            item.errorMessage = "Cannot prepare input file for processing."
            return false
        }

        // Generate temporary output paths in work dir (child process writes here), then move to destination
        let tempOutputURL = stagingDir.appendingPathComponent("\(baseName)_redacted.docx")
        let tempReportURL = stagingDir.appendingPathComponent("\(baseName)_report.json")

        // Generate timestamp to bypass NSWorkspace/Application caching of same-named files
        // Generate timestamp with user-requested format: 10-2-76 356pm (M-d-yy hmma)
        let timeFormatter = DateFormatter()
        timeFormatter.dateFormat = "M-d-yy hmma"
        timeFormatter.amSymbol = "am"
        timeFormatter.pmSymbol = "pm"
        let timestamp = timeFormatter.string(from: Date())

        // Final paths in user-selected destination
        // Format: "Filename (redacted 10-2-76 356pm).docx"
        let finalOutputURL = outputDirectory.appendingPathComponent("\(baseName) (redacted \(timestamp)).docx")
        let finalReportURL = outputDirectory.appendingPathComponent("\(baseName) (report \(timestamp)).json")

        // Store final paths for UI actions
        item.outputPath = finalOutputURL.path
        item.reportPath = finalReportURL.path

        logToFile(logPath, "Input file: \(item.path)")
        logToFile(logPath, "Temp output: \(tempOutputURL.path)")
        logToFile(logPath, "Temp report: \(tempReportURL.path)")
        logToFile(logPath, "Final output: \(finalOutputURL.path)")
        logToFile(logPath, "Final report: \(finalReportURL.path)")

        // Check if python_launcher.sh exists for subprocess execution
        guard Bundle.main.path(forResource: "python_launcher", ofType: "sh") != nil else {
            logToFile(logPath, "❌ Python launcher script missing")
            item.status = .failed
            item.errorMessage = "Python launcher script missing from application bundle."
            return false
        }

        if !usingMockBackend && settings.mode != .rules {
            let ensured = await ensureOllamaRunning()
            if !ensured {
                logToFile(logPath, "❌ Unable to start Ollama service")
                item.status = .failed
                item.errorMessage = supportMessage
                return false
            }
        } else {
            logToFile(logPath, "Skipping Ollama startup check for mock backend")
        }

        await loadInstalledModels()

        // Update progress stages for UI
        item.beginStage(.preflight)

        // Check environment variable for PythonKit vs CLI fallback preference
        let usePythonKit = ProcessInfo.processInfo.environment["MARCUT_USE_PYTHONKIT"]?.lowercased() != "false"

        if !usePythonKit {
            logToFile(logPath, "[FALLBACK] MARCUT_USE_PYTHONKIT=false, using CLI fallback")
            // Execute via CLI fallback
            item.concludeCurrentStage()
            item.beginStage(.ruleDetection)

            let redactionMode = (usingMockBackend || settings.mode == .rules) ? "rules" : "enhanced"
            let modelId = (usingMockBackend || settings.mode == .rules) ? "mock" : settings.model

            if redactionMode == "enhanced" {
                item.concludeCurrentStage()
                item.beginStage(.llmValidation)
                item.concludeCurrentStage()
                item.beginStage(.enhancedDetection)
            } else {
                item.concludeCurrentStage()
                item.beginStage(.merging)
            }

            let cliSuccess = await runRedaction(
                documentId: item.id,
                inputPath: workInputURL.path,
                outputPath: tempOutputURL.path,
                reportPath: tempReportURL.path,
                model: modelId,
                mode: redactionMode,
                debug: settings.debug,
                onProgress: { [weak item] outputLine in
                    let trimmed = outputLine.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard trimmed.hasPrefix("{") else { return }
                    Task { @MainActor in
                        item?.ingestProgressPayload(trimmed)
                    }
                }
            )

            if cliSuccess {
                // Continue with file moving logic
                if !usingMockBackend && settings.mode != .rules {
                    item.concludeCurrentStage()
                    item.beginStage(.merging)
                }

                let moveSuccess = await Task.detached(priority: .userInitiated) {
                    do {
                        try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
                        if FileManager.default.fileExists(atPath: finalOutputURL.path) {
                            try? FileManager.default.removeItem(at: finalOutputURL)
                        }
                        if FileManager.default.fileExists(atPath: finalReportURL.path) {
                            try? FileManager.default.removeItem(at: finalReportURL)
                        }
                        try FileManager.default.moveItem(at: tempOutputURL, to: finalOutputURL)
                        try FileManager.default.moveItem(at: tempReportURL, to: finalReportURL)
                        logToFile(logPath, "[CLI_FALLBACK] Outputs moved to final destination")
                        return true
                    } catch {
                        logToFile(logPath, "[CLI_FALLBACK] Failed moving outputs: \(error)")
                        return false
                    }
                }.value

                if moveSuccess {
                    item.concludeCurrentStage()
                    item.beginStage(.outputGeneration)
                    item.redactedOutputURL = finalOutputURL
                    item.reportOutputURL = finalReportURL
                    item.markProcessingCompleted()
                    item.status = .completed
                    logToFile(logPath, "=== MARCUT PROCESSING END (CLI_FALLBACK SUCCESS) ===")
                    return true
                } else {
                    item.status = .failed
                    item.errorMessage = "CLI processing succeeded but file operations failed"
                    return false
                }
            } else {
                item.status = .failed
                item.errorMessage = "CLI fallback processing failed"
                logToFile(logPath, "=== MARCUT PROCESSING END (CLI_FALLBACK FAILED) ===")
                return false
            }
        }

        // Execute via unified subprocess execution (fail fast, no fallbacks)
        logToFile(logPath, "[SUB] Executing via unified subprocess execution...")

        item.concludeCurrentStage()
        item.beginStage(.ruleDetection)

        let redactionMode = (usingMockBackend || settings.mode == .rules) ? "rules" : "enhanced"
        let modelId = (usingMockBackend || settings.mode == .rules) ? "mock" : settings.model

        if redactionMode == "enhanced" {
            item.concludeCurrentStage()
            item.beginStage(.llmValidation)
            item.concludeCurrentStage()
            item.beginStage(.enhancedDetection)
        } else {
            item.beginStage(.merging)
        }

        // Run Python processing via subprocess on background thread
        let success = await runRedaction(
            documentId: item.id,
            inputPath: workInputURL.path,
            outputPath: tempOutputURL.path,
            reportPath: tempReportURL.path,
            model: modelId,
            mode: redactionMode,
            debug: settings.debug,
            onProgress: { [weak item] outputLine in
                let trimmed = outputLine.trimmingCharacters(in: .whitespacesAndNewlines)
                guard trimmed.hasPrefix("{") else { return }
                Task { @MainActor in
                    item?.ingestProgressPayload(trimmed)
                }
            }
        )

        if success {
            if !usingMockBackend && settings.mode != .rules {
                item.concludeCurrentStage()
                item.beginStage(.merging)
            }

            // Move file operations to background thread
            let moveSuccess = await Task.detached(priority: .userInitiated) {
                do {
                    try FileManager.default.createDirectory(at: outputDirectory, withIntermediateDirectories: true)
                    if FileManager.default.fileExists(atPath: finalOutputURL.path) {
                        try? FileManager.default.removeItem(at: finalOutputURL)
                    }
                    if FileManager.default.fileExists(atPath: finalReportURL.path) {
                        try? FileManager.default.removeItem(at: finalReportURL)
                    }
                    try FileManager.default.moveItem(at: tempOutputURL, to: finalOutputURL)
                    try? FileManager.default.moveItem(at: tempReportURL, to: finalReportURL)
                    logToFile(logPath, "[PK] Outputs moved to final destination")
                    return true
                } catch {
                    logToFile(logPath, "[PK] Failed moving outputs: \(error)")
                    return false
                }
            }.value

            if moveSuccess {
                item.concludeCurrentStage()
                item.beginStage(.outputGeneration)
                item.redactedOutputURL = finalOutputURL
                item.reportOutputURL = finalReportURL
                item.markProcessingCompleted()
                item.status = .completed
            } else {
                item.status = .failed
                item.errorMessage = "Failed to save output files"
                return false
            }
            logToFile(logPath, "=== MARCUT PROCESSING END (SUCCESS) ===")
            return true
        } else {
            logToFile(logPath, "[SUB] Subprocess execution failed")


            // Original failure handling for non-fallback cases
            if item.status != .cancelled {
                item.status = .failed
                item.errorMessage = "Document processing failed. Please check document format and try again."
            }
            logToFile(logPath, "=== MARCUT PROCESSING END (FAILED) ===")
            return false
        }

    }


    // MARK: - Command Execution

    private func runCommand(
        _ command: String,
        arguments: [String],
        environment: [String: String]? = nil,
        background: Bool = false
    ) async -> (success: Bool, output: String) {
        let env = environment ?? getOllamaEnvironment()
        return await legacyRunCommand(command, arguments: arguments, environment: env)
    }

    // Fallback to direct process execution for non-Ollama commands
    private func legacyRunCommand(
        _ command: String,
        arguments: [String],
        environment: [String: String]
    ) async -> (success: Bool, output: String) {
        bridgeLog("CLI: Executing command: \(command)", component: "CLI_SUBPROCESS")
        bridgeLog("CLI: Arguments: \(arguments)", component: "CLI_SUBPROCESS")
        
        return await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: command)
            process.arguments = arguments
            process.environment = environment.isEmpty ? nil : environment

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            do {
                bridgeLog("CLI: Launching process...", component: "CLI_SUBPROCESS")
                try process.run()
                process.waitUntilExit()
                bridgeLog("CLI: Process finished with exit code: \(process.terminationStatus)", component: "CLI_SUBPROCESS")

                let data = pipe.fileHandleForReading.readDataToEndOfFile()
                let output = String(data: data, encoding: .utf8) ?? ""
                let success = process.terminationStatus == 0
                
                if !success {
                    bridgeLog("CLI: Process failed. Output:\n\(output)", component: "CLI_SUBPROCESS")
                }
                
                return (success, output)
            } catch {
                bridgeLog("CLI: Failed to run command: \(error)", component: "CLI_SUBPROCESS")
                return (false, "Failed to run command: \(error)")
            }
        }.value
    }

    private func runCommandWithProgress(
        _ command: String,
        arguments: [String],
        environment: [String: String]? = nil,
        progressCallback: @escaping (String) -> Void
    ) async -> (success: Bool, output: String) {
        let result = await runCommand(command, arguments: arguments, environment: environment)
        progressCallback(result.output)
        return result
    }

    func downloadModel(_ modelName: String, progress: @escaping (Double) -> Void) async -> Bool {
        var lastProgress = 0.0
        let updateProgress: (Double) -> Void = { value in
            let clipped = min(max(value, 0.0), 100.0)
            guard clipped > lastProgress else { return }
            lastProgress = clipped
            progress(clipped)
        }

        // Immediately surface that we are preparing the download so the UI renders without waiting on startup
        updateProgress(1.0)

        guard await ensureOllamaRunning() else {
            bridgeLog("Failed to ensure Ollama is running for model download", component: "MODEL_DOWNLOAD")
            return false
        }

        updateProgress(3.0)

        if await !probeOllamaHTTP() {
            // Give the daemon a moment to warm up, then retry once
            try? await Task.sleep(nanoseconds: 500_000_000)
            if await !probeOllamaHTTP() {
                bridgeLog("Ollama HTTP endpoint unreachable before download", component: "MODEL_DOWNLOAD")
                return false
            }
        }

        do {
            updateProgress(5.0) // Confirmed server responsiveness
            bridgeLog("Starting download for \(modelName) via HTTP...", component: "MODEL_DOWNLOAD")
            let ok = try await pullModelViaHTTP(modelName: modelName, progress: updateProgress)
            
            if ok {
                updateProgress(99.0)
                bridgeLog("Download reported success, refreshing model list...", component: "MODEL_DOWNLOAD")
                await loadInstalledModels()
                
                // VERIFICATION: Check if the model is actually in the list
                // We check for partial match because "llama3.2" might become "llama3.2:latest"
                let exists = installedModels.contains { $0.contains(modelName) }
                if exists {
                    bridgeLog("✅ Model \(modelName) verified in installed list.", component: "MODEL_DOWNLOAD")
                    updateProgress(100.0)
                    return true
                } else {
                    bridgeLog("❌ Download reported success but model \(modelName) not found in list: \(installedModels)", component: "MODEL_DOWNLOAD")
                    return false
                }
            }
            return false
        } catch {
            bridgeLog("Failed to download model: \(modelName)", component: "MODEL_DOWNLOAD")
            bridgeLog("Error output: \(error.localizedDescription)", component: "MODEL_DOWNLOAD")
            return false
        }
    }

    private struct PullEvent: Decodable {
        let status: String?
        let digest: String?
        let total: Int64?
        let completed: Int64?
        let error: String?
    }

    private func pullModelViaHTTP(modelName: String, progress: @escaping (Double) -> Void) async throws -> Bool {
        guard let url = URL(string: "http://\(ollamaHost)/api/pull") else {
            throw NSError(domain: "Ollama", code: -1, userInfo: [NSLocalizedDescriptionKey: "Invalid pull URL"])
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body = ["name": modelName]
        request.httpBody = try JSONSerialization.data(withJSONObject: body, options: [])

        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 60 * 60
        configuration.timeoutIntervalForResource = 60 * 60
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.connectionProxyDictionary = [:]
        let session = URLSession(configuration: configuration)
        defer { session.invalidateAndCancel() }
        let decoder = JSONDecoder()

        var totalsByDigest: [String: Int64] = [:]
        var completedByDigest: [String: Int64] = [:]

        let (stream, response) = try await session.bytes(for: request)
        guard let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 else {
            throw NSError(domain: "Ollama", code: (response as? HTTPURLResponse)?.statusCode ?? -1, userInfo: [NSLocalizedDescriptionKey: "Unexpected response from Ollama pull"])
        }

        // Show that the HTTP stream is open even before size-based progress is available
        progress(6.0)

        for try await line in stream.lines {
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !trimmed.isEmpty else { continue }

            guard let data = trimmed.data(using: .utf8) else { continue }
            guard let event = try? decoder.decode(PullEvent.self, from: data) else {
                bridgeLog("⚠️ MODEL_DOWNLOAD: Unable to decode pull event: \(trimmed)", component: "MODEL_DOWNLOAD")
                continue
            }

            if let errorMessage = event.error ?? (event.status?.lowercased() == "error" ? event.status : nil) {
                throw NSError(domain: "Ollama", code: -2, userInfo: [NSLocalizedDescriptionKey: errorMessage])
            }

            if let status = event.status {
                // Log status changes for debugging
                if !status.hasPrefix("pulling") && !status.hasPrefix("downloading") {
                     bridgeLog("MODEL_DOWNLOAD: Status update: \(status)", component: "MODEL_DOWNLOAD")
                }
                
                let lowered = status.lowercased()

                if lowered.contains("pulling manifest") || lowered.contains("resolving") {
                    progress(8.0)
                } else if lowered.contains("pulling") || lowered.contains("downloading") {
                    progress(10.0)
                }

                if lowered == "success" {
                    progress(99.0)
                    return true
                } else if lowered.contains("verifying") {
                    progress(97.0)
                } else if lowered.contains("writing manifest") {
                    progress(98.0)
                }
            }

            if let digest = event.digest, let total = event.total {
                totalsByDigest[digest] = total
                if let completed = event.completed {
                    completedByDigest[digest] = completed
                }

                let totalBytes = totalsByDigest.values.reduce(0, +)
                let completedBytes = completedByDigest.values.reduce(0, +)
                if totalBytes > 0 {
                    let fraction = Double(completedBytes) / Double(totalBytes)
                    let scaled = 5.0 + fraction * 92.0 // Reserve headroom for verify/write
                    progress(min(scaled, 96.0))
                }
            }
        }

        bridgeLog("❌ MODEL_DOWNLOAD: Stream ended without 'success' status", component: "MODEL_DOWNLOAD")
        return false
    }

    private func loadInstalledModels() async {
        if let (code, data) = try? await ollamaHTTP(path: "/api/tags", timeout: 2.0),
           code == 200,
           let data = data,
           let names = parseModelList(from: data) {
            installedModels = names
            return
        }

        // If Ollama isn't responding, fall back to on-disk discovery so we don't
        // prompt the user to re-download models that are already present.
        if !prefetchedFromDisk {
            let discovered = ModelPromotion.discoverModels(in: modelsDirectory)
            if !discovered.isEmpty {
                installedModels = Array(discovered).sorted()
                prefetchedFromDisk = true
            }
        }

        guard let ollamaPath = resolveOllamaPath() else {
            installedModels = []
            return
        }

        // Don't try to list models if Ollama isn't running, as it will fail
        if !isOllamaRunning {
            installedModels = installedModels.isEmpty ? [] : installedModels
            return
        }

        let result = await runCommand(ollamaPath, arguments: ["list"], environment: getOllamaEnvironment())
        installedModels = result.success ? parseModelList(result.output) : []
    }

    private func parseModelList(from data: Data) -> [String]? {
        guard let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let models = object["models"] as? [[String: Any]] else {
            return nil
        }
        return models.compactMap { $0["name"] as? String }
    }

    private func parseModelList(_ output: String) -> [String] {
        var models: [String] = []
        for line in output.split(whereSeparator: { $0.isNewline }) {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty { continue }
            if trimmed.lowercased().hasPrefix("name") { continue }
            let components = trimmed.split(separator: " ", omittingEmptySubsequences: true)
            if let first = components.first {
                models.append(String(first))
            }
        }
        return models
    }

    func cancelModelDownload() {
        // No-op: downloads run via XPC helper
    }


    func cancelProcess(for documentId: UUID) {
        if let process = activeProcesses[documentId] {
            bridgeLog("Cancelling active process for document ID: \(documentId) (PID: \(process.processIdentifier))", component: "Cancellation")
            process.terminate()
            activeProcesses.removeValue(forKey: documentId)
        } else {
            bridgeLog("No active process found to cancel for document ID: \(documentId)", component: "Cancellation")
        }
    }

    func cancelAllProcesses() {
        bridgeLog("All processes cancellation requested", component: "Cancellation")

        // Clean up Ollama background process
        if let process = ollamaBackgroundProcess {
            bridgeLog("Terminating Ollama background process", component: "Ollama")
            process.terminate()
            ollamaBackgroundProcess = nil
            closeOllamaLogHandle()
            launchedOllamaPID = nil
            launchedOllamaPort = nil
        }
    }

    deinit {
        // Capture process reference weakly to avoid retain cycle
        let processToTerminate = ollamaBackgroundProcess
        ollamaBackgroundProcess = nil

        // Log cleanup handled by OllamaLogger's own deinit

        // Schedule cleanup on main actor to avoid concurrency issues
        Task { @MainActor [weak self] in
            guard let self else { return }
            if let process = processToTerminate {
                bridgeLog("Deinit: Terminating Ollama background process", component: "Ollama")
                process.terminate()
            }
            launchedOllamaPID = nil
            launchedOllamaPort = nil
        }
    }

    func updateLoggingPreference(_ enabled: Bool) {
        isDebugLoggingEnabled = enabled
        UserDefaults.standard.set(enabled, forKey: "MarcutApp_DebugMode")
    }

    /// Populate installedModels from on-disk manifests/blobs without requiring Ollama to be running.
    /// Returns true if any models were discovered.
    /// Performs File I/O on background thread, updates state on MainActor.
    @MainActor
    @discardableResult
    func populateInstalledModelsFromDisk() async -> Bool {
        let modelsDir = modelsDirectory
        let discovered = await Task.detached {
            ModelPromotion.discoverModels(in: modelsDir)
        }.value
        
        if !discovered.isEmpty {
            installedModels = Array(discovered).sorted()
            prefetchedFromDisk = true
            return true
        }
        return false
    }

    private func secureRemoveFile(at url: URL) {
        let fm = FileManager.default
        guard fm.fileExists(atPath: url.path) else { return }

        if let attributes = try? fm.attributesOfItem(atPath: url.path),
           let fileSize = attributes[.size] as? Int64,
           fileSize > 0,
           let handle = try? FileHandle(forWritingTo: url) {
            do {
                try handle.seek(toOffset: 0)
                let chunkSize = 1_048_576
                let zeroChunk = Data(repeating: 0, count: chunkSize)
                var remaining = fileSize
                while remaining > 0 {
                    let writeSize = Int(min(Int64(chunkSize), remaining))
                    if writeSize < chunkSize {
                        handle.write(zeroChunk.prefix(writeSize))
                    } else {
                        handle.write(zeroChunk)
                    }
                    remaining -= Int64(writeSize)
                }
                try handle.close()
            } catch {
                try? handle.close()
            }
        }

        try? fm.removeItem(at: url)
    }

    private func secureEraseWorkDirectory() {
        let fm = FileManager.default
        let dir = workDirectory
        if fm.fileExists(atPath: dir.path) {
            if let enumerator = fm.enumerator(at: dir, includingPropertiesForKeys: [.isDirectoryKey], options: [], errorHandler: nil) {
                for case let fileURL as URL in enumerator {
                    var isDirectory: ObjCBool = false
                    if fm.fileExists(atPath: fileURL.path, isDirectory: &isDirectory) {
                        if isDirectory.boolValue {
                            continue
                        } else {
                            secureRemoveFile(at: fileURL)
                        }
                    }
                }
            }
            if let contents = try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) {
                for entry in contents {
                    try? fm.removeItem(at: entry)
                }
            }
            try? fm.removeItem(at: dir)
        }
        try? fm.createDirectory(at: dir, withIntermediateDirectories: true)
    }

    func removeWorkArtifacts(for baseName: String) {
        let candidates = [
            workDirectory.appendingPathComponent("\(baseName)_input.docx"),
            workDirectory.appendingPathComponent("\(baseName)_redacted.docx"),
            workDirectory.appendingPathComponent("\(baseName)_report.json")
        ]
        for url in candidates {
            secureRemoveFile(at: url)
        }
    }
}

// MARK: - CLI Subprocess Implementation (Hybrid Approach)

extension PythonBridgeService {

    /// Run redaction using CLI subprocess with MARCUT_PROGRESS protocol for non-blocking execution
    /// This provides true non-blocking behavior while using the same pipeline as CLI
    func runRedactionWithCLI(
        inputPath: String,
        outputPath: String,
        reportPath: String,
        scrubReportPath: String? = nil,
        model: String = "llama3.1:8b",
        mode: String = "enhanced",
        debug: Bool = false,
        progressUpdater: @escaping (PythonRunnerProgressUpdate) -> Void,
        completion: @escaping (Bool) -> Void
    ) {
        bridgeLog("Starting CLI subprocess redaction", component: "CLI_SUBPROCESS")

        // Get the CLI launcher script path - handle both debug and production builds
        let scriptPath: String
        if let appResourcesPath = Bundle.main.resourcePath {
            scriptPath = appResourcesPath.appending("/marcut_cli_launcher.sh")
        } else {
            // Development fallback - try different possible locations
            let bundlePath = Bundle.main.bundlePath
            let possiblePaths = [
                "\(bundlePath)/Contents/Resources/marcut_cli_launcher.sh",
                "\(bundlePath)/../MarcutApp/Contents/Resources/marcut_cli_launcher.sh",
                "\(bundlePath)/../../MarcutApp/Contents/Resources/marcut_cli_launcher.sh"
            ]

            scriptPath = possiblePaths.first { FileManager.default.fileExists(atPath: $0) } ?? possiblePaths[0]
        }

        // Verify script exists
        guard FileManager.default.fileExists(atPath: scriptPath) else {
            bridgeLog("CLI launcher script not found at: \(scriptPath)", component: "CLI_SUBPROCESS")
            completion(false)
            return
        }

        // Set up environment for subprocess
        var environment = ProcessInfo.processInfo.environment
        environment["MARCUT_RULE_FILTER"] = ruleFilterValue
        environment["PYTHONUNBUFFERED"] = "1"
        environment["MARCUT_LOG_PATH"] = DebugLogger.shared.logPath
        if let scrubReportPath, !scrubReportPath.isEmpty {
            environment["MARCUT_SCRUB_REPORT_PATH"] = scrubReportPath
        }

        // CRITICAL FIX: Ensure valid TMPDIR for subprocess
        // "Clear" button wipes the default marcut_py, so we must ensure a valid directory exists
        if let robustTmpDir = prepareAppContainerTempDir() {
             environment["TMPDIR"] = robustTmpDir.path
             environment["OLLAMA_TMPDIR"] = robustTmpDir.path
             bridgeLog("CLI: Enforced robust TMPDIR: \(robustTmpDir.path)", component: "CLI_SUBPROCESS")
        } else {
             bridgeLog("CLI: ⚠️ Failed to prepare robust TMPDIR, fallback to inherited", component: "CLI_SUBPROCESS")
        }

        // Prepare subprocess
        let process = Process()
        process.executableURL = URL(fileURLWithPath: scriptPath)
        let normalizedMode = mode.lowercased()
        let resolvedBackend = normalizedMode == "rules" ? "mock" : "ollama"
        let resolvedModel = normalizedMode == "rules" ? "mock" : model
        process.arguments = [
            "--with-progress",
            "redact",
            "--in", inputPath,
            "--out", outputPath,
            "--report", reportPath,
            "--mode", mode,
            "--backend", resolvedBackend,
            "--model", resolvedModel
        ]

        if debug {
            process.arguments?.append("--debug")
        }

        process.environment = environment
        process.currentDirectoryURL = URL(fileURLWithPath: FileManager.default.currentDirectoryPath)

        // Set up pipes for stdout and stderr
        let stdoutPipe = Pipe()
        let stderrPipe = Pipe()
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe

        // Log subprocess details for debugging
        bridgeLog("CLI subprocess command: \(process.executableURL!.path) \(process.arguments!.joined(separator: " "))", component: "CLI_SUBPROCESS")
        bridgeLog("Working directory: \(process.currentDirectoryURL!.path)", component: "CLI_SUBPROCESS")

        // Start a background task to handle process execution and output parsing
        Task.detached(priority: .userInitiated) {
            do {
                // Start the process
                try process.run()
                bridgeLog("CLI subprocess started with PID: \(process.processIdentifier)", component: "CLI_SUBPROCESS")

                // Read stdout in real-time for progress updates
                let stdoutHandle = stdoutPipe.fileHandleForReading
                var buffer = Data()

                while process.isRunning {
                    let availableData = stdoutHandle.availableData
                    if !availableData.isEmpty {
                        buffer.append(availableData)

                        // Process complete lines
                        if let dataString = String(data: buffer, encoding: .utf8) {
                            let lines = dataString.components(separatedBy: .newlines)

                            // Process all complete lines
                            for line in lines.dropLast() {
                                await MainActor.run {
                                    self.parseMARCUTProgress(line.trimmingCharacters(in: .whitespacesAndNewlines), progressUpdater: progressUpdater)
                                }
                            }

                            // Keep the incomplete line (if any) in buffer
                            if let lastLine = lines.last {
                                buffer = lastLine.data(using: .utf8) ?? Data()
                            }
                        }
                    }

                    // Small delay to prevent busy waiting
                    try? await Task.sleep(nanoseconds: 10_000_000) // 10ms
                }

                // Wait for process to complete
                process.waitUntilExit()

                // Read any remaining output
                let remainingData = stdoutHandle.readDataToEndOfFile()
                if !remainingData.isEmpty, let remainingString = String(data: remainingData, encoding: .utf8) {
                    await MainActor.run {
                        for line in remainingString.components(separatedBy: .newlines) {
                            self.parseMARCUTProgress(line.trimmingCharacters(in: .whitespacesAndNewlines), progressUpdater: progressUpdater)
                        }
                    }
                }

                // Read and log stderr if needed
                let stderrData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
                if !stderrData.isEmpty, let stderrString = String(data: stderrData, encoding: .utf8), debug {
                    bridgeLog("CLI subprocess stderr: \(stderrString)", component: "CLI_SUBPROCESS")
                }

                let success = process.terminationStatus == 0
                bridgeLog("CLI subprocess completed with status: \(process.terminationStatus)", component: "CLI_SUBPROCESS")

                // Call completion on main actor
                await MainActor.run {
                    completion(success)
                }

            } catch {
                bridgeLog("CLI subprocess failed: \(error)", component: "CLI_SUBPROCESS")
                await MainActor.run {
                    completion(false)
                }
            }
        }
    }

    /// Parse MARCUT_PROGRESS protocol messages from CLI output
    private func parseMARCUTProgress(_ line: String, progressUpdater: (PythonRunnerProgressUpdate) -> Void) {
        // Be defensive about any ANSI/control sequences
        let cleanLine = removeANSIEscapeCodes(line)
        guard cleanLine.hasPrefix("MARCUT_PROGRESS:") || cleanLine.hasPrefix("MARCUT_STATUS:") else {
            return // Not a progress message
        }

        if cleanLine.hasPrefix("MARCUT_STATUS:") {
            let message = cleanLine.replacingOccurrences(of: "MARCUT_STATUS:", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !message.isEmpty else { return }

            var chunkValue: Int?
            var totalValue: Int?

            if let match = message.range(of: #"Processing chunk\s+(\d+)/(\d+)"#, options: .regularExpression) {
                let matched = String(message[match])
                let numbers = matched.replacingOccurrences(of: "Processing chunk", with: "").trimmingCharacters(in: .whitespaces)
                let parts = numbers.split(separator: "/").map { String($0).trimmingCharacters(in: .whitespaces) }
                if parts.count == 2, let c = Int(parts[0]), let t = Int(parts[1]), t > 0 {
                    chunkValue = c
                    totalValue = t
                }
            }

            progressUpdater(
                PythonRunnerProgressUpdate(
                    chunk: chunkValue,
                    total: totalValue,
                    message: message
                )
            )
        } else if cleanLine.hasPrefix("MARCUT_PROGRESS:") {
            let progressLine = cleanLine.replacingOccurrences(of: "MARCUT_PROGRESS:", with: "").trimmingCharacters(in: .whitespacesAndNewlines)
            let components = progressLine.components(separatedBy: "|")

            let phaseName = components.first?.trimmingCharacters(in: .whitespacesAndNewlines)
            var phaseProgress: Double?
            var overallProgress: Double?

            for component in components {
                let trimmed = component.trimmingCharacters(in: .whitespacesAndNewlines)

                if let range = trimmed.range(of: #"Stage:\s*([0-9]+(?:\.[0-9]+)?)%"#, options: .regularExpression) {
                    let token = String(trimmed[range])
                        .replacingOccurrences(of: "Stage:", with: "")
                        .replacingOccurrences(of: "%", with: "")
                        .trimmingCharacters(in: .whitespaces)
                    if let percentVal = Double(token) {
                        phaseProgress = percentVal / 100.0
                    }
                }

                if let range = trimmed.range(of: #"Overall:\s*([0-9]+(?:\.[0-9]+)?)%"#, options: .regularExpression) {
                    let token = String(trimmed[range])
                        .replacingOccurrences(of: "Overall:", with: "")
                        .replacingOccurrences(of: "%", with: "")
                        .trimmingCharacters(in: .whitespaces)
                    if let percentVal = Double(token) {
                        overallProgress = percentVal / 100.0
                    }
                }
            }

            progressUpdater(
                PythonRunnerProgressUpdate(
                    phaseIdentifier: phaseName?.lowercased(),
                    phaseDisplayName: phaseName,
                    phaseProgress: phaseProgress,
                    overallProgress: overallProgress,
                    message: progressLine
                )
            )
        }
    }
}

// MARK: - Placeholder implementations for demo
// These would be replaced with actual processing logic

extension PythonBridgeService {
    private func parseStructuredProgress(_ line: String, for item: DocumentItem) {
        // Simplified progress parsing for demo
        if let match = line.range(of: #"\d+%"#, options: .regularExpression) {
            let percentString = String(line[match]).replacingOccurrences(of: "%", with: "")
            if let percent = Double(percentString) {
                item.progress = percent / 100.0
            }
        }
    }

}

// MARK: - Helper Classes

/// Thread-safe logger for Ollama output that avoids MainActor isolation issues
/// and prevents blocking the main thread with file I/O
private class OllamaLogger: @unchecked Sendable {
    private let logURL: URL
    private var fileHandle: FileHandle?
    private let lock = NSLock()
    
    init(logURL: URL) {
        self.logURL = logURL
    }
    
    func write(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        
        ensureHandleOpen()
        
        if let handle = fileHandle {
            try? handle.write(contentsOf: data)
        }
    }
    
    func write(_ string: String) {
        guard let data = string.data(using: .utf8) else { return }
        write(data)
    }
    
    func flush() {
        lock.lock()
        defer { lock.unlock() }
        try? fileHandle?.synchronize()
    }
    
    func close() {
        lock.lock()
        defer { lock.unlock() }
        
        if let handle = fileHandle {
            try? handle.synchronize()
            if #available(macOS 10.15.4, *) {
                try? handle.close()
            } else {
                handle.closeFile()
            }
            fileHandle = nil
        }
    }
    
    deinit {
        // Ensure file handle is closed when logger is deallocated
        close()
    }
    
    // Note: Caller usually ensures directory exists, but we double check file existence
    private func ensureHandleOpen() {
        if fileHandle != nil { return }
        
        let fm = FileManager.default
        if !fm.fileExists(atPath: logURL.path) {
            fm.createFile(atPath: logURL.path, contents: nil)
        }
        
        do {
            let handle = try FileHandle(forWritingTo: logURL)
            handle.seekToEndOfFile()
            fileHandle = handle
        } catch {
            print("[OllamaLogger] Failed to open log handle: \(error)")
        }
    }
    
    // Explicitly open/reopen (useful for startup sequence)
    func forceOpen() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        ensureHandleOpen()
        return fileHandle != nil
    }
}
