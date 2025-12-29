import Foundation
import SwiftUI

/// Manages all file access operations to ensure they work within authorized directories
class FileAccessCoordinator: ObservableObject {
    static let shared = FileAccessCoordinator()

    private let userDefaults = UserDefaults.standard
    private let documentsBookmarkKey = "MarcutApp_DocumentsBookmark"
    private let downloadsBookmarkKey = "MarcutApp_DownloadsBookmark"
    private let desktopBookmarkKey = "MarcutApp_DesktopBookmark"

    // MARK: - Permission State Management
    private let permissionVersionKey = "MarcutApp_PermissionVersion"
    private let onboardingCompletedKey = "MarcutApp_OnboardingCompleted"
    private let comprehensivePermissionKey = "MarcutApp_ComprehensivePermission"
    private let permissionRequestDateKey = "MarcutApp_PermissionRequestDate"

    @Published var isOnboardingCompleted: Bool = false
    @Published var needsPermissionRequest: Bool = false

    @Published var authorizedDocumentsURL: URL?
    @Published var authorizedDownloadsURL: URL?
    @Published var authorizedDesktopURL: URL?

    // MARK: - Session Permission Management
    private var hasRequestedPermissionsThisSession = false
    private var sessionPermissionsEstablished = false
    private let permissionSessionKey = "MarcutApp_PermissionSessionUUID"
    private var hasAttemptedRestoration = false

    private init() {
        initializePermissionState()     // Initialize state first
        initializeSessionTracking()     // Track new app session
        // DEFERRED: restoreAuthorizedDirectories() // Then restore bookmarks (may update state)
    }

    // MARK: - Permission State Management

    /// Initializes permission state tracking
    private func initializePermissionState() {
        isOnboardingCompleted = userDefaults.bool(forKey: onboardingCompletedKey)
        needsPermissionRequest = shouldRequestPermissions()
        DebugLogger.shared.log("🔐 Permission state - Onboarding: \(isOnboardingCompleted), Needs Request: \(needsPermissionRequest)", component: "FileAccessCoordinator")
    }

    /// Initializes session-based permission tracking to detect new app launches
    private func initializeSessionTracking() {
        let currentSessionUUID = UUID().uuidString
        let storedSessionUUID = userDefaults.string(forKey: permissionSessionKey)

        if storedSessionUUID != currentSessionUUID {
            // New app session - reset permission request tracking
            hasRequestedPermissionsThisSession = false
            sessionPermissionsEstablished = false
            userDefaults.set(currentSessionUUID, forKey: permissionSessionKey)
            DebugLogger.shared.log("🆔 New app session detected: \(currentSessionUUID)", component: "FileAccessCoordinator")
        } else {
            DebugLogger.shared.log("🆔 Continuing existing session: \(currentSessionUUID)", component: "FileAccessCoordinator")
        }
    }

    /// Checks if permissions should be requested based on version and state
    private func shouldRequestPermissions() -> Bool {
        // If onboarding never completed, always request
        guard isOnboardingCompleted else {
            DebugLogger.shared.log("🔐 Onboarding not completed - permission request needed", component: "FileAccessCoordinator")
            return true
        }

        // Check if we have a valid permission for current app version
        let currentVersion = getCurrentAppVersion()
        let storedVersion = userDefaults.string(forKey: permissionVersionKey)

        if currentVersion != storedVersion {
            DebugLogger.shared.log("🔐 Version mismatch - current: \(currentVersion), stored: \(storedVersion ?? "none")", component: "FileAccessCoordinator")
            return true
        }

        // Check if we have valid bookmarks
        guard hasValidBookmarks() else {
            DebugLogger.shared.log("🔐 Invalid or missing bookmarks - permission request needed", component: "FileAccessCoordinator")
            return true
        }

        return false
    }

    /// Gets the current app version
    private func getCurrentAppVersion() -> String {
        return Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "unknown"
    }

    /// Establish permissions proactively at app startup (optional, can be called once)
    func establishPermissionsAtStartup() async {
        DebugLogger.shared.log("🚀 Startup permission establishment check", component: "FileAccessCoordinator")

        // If permissions are already valid from previous sessions, just mark session as established
        if !needsPermissionRequest && (hasValidBookmarks() || hasEntitlementAccess()) {
            sessionPermissionsEstablished = true
            DebugLogger.shared.log("✅ Startup: Existing permissions are valid, session established", component: "FileAccessCoordinator")
            return
        }

        DebugLogger.shared.log("⚠️ Startup: No existing permissions found, will request on first file access", component: "FileAccessCoordinator")
    }

    /// Checks if we have valid bookmarks and accessible directories
    private func hasValidBookmarks() -> Bool {
        // Check if we have any bookmark data
        let documentsBookmark = userDefaults.data(forKey: documentsBookmarkKey)
        let downloadsBookmark = userDefaults.data(forKey: downloadsBookmarkKey)
        let desktopBookmark = userDefaults.data(forKey: desktopBookmarkKey)
        let comprehensiveBookmark = userDefaults.data(forKey: comprehensivePermissionKey)

        let hasAnyBookmark = documentsBookmark != nil || downloadsBookmark != nil ||
                           desktopBookmark != nil || comprehensiveBookmark != nil

        guard hasAnyBookmark else {
            DebugLogger.shared.log("🔐 No bookmarks found", component: "FileAccessCoordinator")
            return false
        }

        // Check if currently authorized directories are actually accessible
        let fileManager = FileManager.default
        var accessibleDirectories = 0

        if let docsURL = authorizedDocumentsURL, fileManager.isReadableFile(atPath: docsURL.path) {
            accessibleDirectories += 1
        }

        if let downloadsURL = authorizedDownloadsURL, fileManager.isReadableFile(atPath: downloadsURL.path) {
            accessibleDirectories += 1
        }

        if let desktopURL = authorizedDesktopURL, fileManager.isReadableFile(atPath: desktopURL.path) {
            accessibleDirectories += 1
        }

        let isValid = accessibleDirectories > 0
        DebugLogger.shared.log("🔐 Bookmark validation: \(accessibleDirectories) directories accessible", component: "FileAccessCoordinator")

        return isValid
    }

    /// Marks onboarding as completed for current version
    func markOnboardingCompleted() {
        userDefaults.set(true, forKey: onboardingCompletedKey)
        userDefaults.set(getCurrentAppVersion(), forKey: permissionVersionKey)
        userDefaults.set(Date(), forKey: permissionRequestDateKey)

        isOnboardingCompleted = true
        needsPermissionRequest = false

        DebugLogger.shared.log("✅ Onboarding completed for version \(getCurrentAppVersion())", component: "FileAccessCoordinator")
    }

    /// Checks if silent entitlement access works
    func testSilentEntitlementAccess() -> [FileManager.SearchPathDirectory: Bool] {
        let fileManager = FileManager.default
        var results: [FileManager.SearchPathDirectory: Bool] = [:]

        let testDirectories: [FileManager.SearchPathDirectory] = [.documentDirectory, .downloadsDirectory, .desktopDirectory]

        for directory in testDirectories {
            if let url = fileManager.urls(for: directory, in: .userDomainMask).first {
                // Test read access without file creation
                let isReadable = fileManager.isReadableFile(atPath: url.path)
                results[directory] = isReadable
                DebugLogger.shared.log("🔍 Entitlement test for \(directory): \(isReadable ? "✅ PASS" : "❌ FAIL")", component: "FileAccessCoordinator")
            }
        }

        return results
    }

    // MARK: - Unified Permission Management

    /// Main permission orchestration - tries silent entitlement first, then unified request
    func performPermissionSetupIfNeeded() async -> Bool {
        DebugLogger.shared.log("🚀 Starting permission setup", component: "FileAccessCoordinator")

        // First, test if our enhanced entitlements work silently
        let entitlementResults = testSilentEntitlementAccess()
        let hasEntitlementAccess = entitlementResults.values.allSatisfy { $0 }

        if hasEntitlementAccess {
            DebugLogger.shared.log("✅ All directories accessible via enhanced entitlements", component: "FileAccessCoordinator")
            await setupFromEntitlements()
            markOnboardingCompleted()
            return true
        }

        DebugLogger.shared.log("⚠️ Entitlements insufficient, requesting comprehensive permission", component: "FileAccessCoordinator")

        // Fall back to unified permission request
        let success = await requestComprehensivePermission()
        if success {
            markOnboardingCompleted()
        }

        return success
    }

    /// Ensures permissions are available for file operations (session-aware, no repeated dialogs)
    /// Ensures permissions are available for file operations (session-aware, no repeated dialogs)
    func ensurePermissionsForFileAccess() async -> Bool {
        // LAZY RESTORATION: If we haven't tried to restore bookmarks yet, do it now.
        if !hasAttemptedRestoration {
            DebugLogger.shared.log("💤 Lazy-loading bookmarks for first access...", component: "FileAccessCoordinator")
            restoreAuthorizedDirectories()
            hasAttemptedRestoration = true
        }

        // If permissions are already established for this session, trust them
        if sessionPermissionsEstablished && (hasValidBookmarks() || hasEntitlementAccess()) {
            return true
        }

        // If we already tried to get permissions this session and failed, don't try again
        if hasRequestedPermissionsThisSession {
            DebugLogger.shared.log("🔐 Permissions already requested this session - returning cached result", component: "FileAccessCoordinator")
            return hasValidBookmarks() || hasEntitlementAccess()
        }

        // If we already have valid permissions from previous sessions, use them immediately
        if !needsPermissionRequest && (hasValidBookmarks() || hasEntitlementAccess()) {
            sessionPermissionsEstablished = true
            DebugLogger.shared.log("✅ Using existing valid permissions for this session", component: "FileAccessCoordinator")
            return true
        }

        DebugLogger.shared.log("🔐 First file access request this session - establishing permissions", component: "FileAccessCoordinator")

        // Mark that we're requesting permissions for this session
        hasRequestedPermissionsThisSession = true

        // Setup permissions only when actually needed (once per session)
        let success = await performPermissionSetupIfNeeded()

        if success {
            sessionPermissionsEstablished = true
            DebugLogger.shared.log("✅ File access permissions established for this session", component: "FileAccessCoordinator")
        } else {
            DebugLogger.shared.log("❌ File access permissions denied for this session", component: "FileAccessCoordinator")
        }

        return success
    }

    /// Quick check for entitlement access without setup
    private func hasEntitlementAccess() -> Bool {
        let fileManager = FileManager.default
        let testDirectories: [FileManager.SearchPathDirectory] = [.documentDirectory, .downloadsDirectory, .desktopDirectory]

        for directory in testDirectories {
            if let url = fileManager.urls(for: directory, in: .userDomainMask).first {
                if fileManager.isReadableFile(atPath: url.path) {
                    return true
                }
            }
        }
        return false
    }

    /// Sets up directories from successful entitlement access
    private func setupFromEntitlements() async {
        let fileManager = FileManager.default

        if let docsURL = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first {
            authorizedDocumentsURL = docsURL
        }

        if let downloadsURL = fileManager.urls(for: .downloadsDirectory, in: .userDomainMask).first {
            authorizedDownloadsURL = downloadsURL
        }

        if let desktopURL = fileManager.urls(for: .desktopDirectory, in: .userDomainMask).first {
            authorizedDesktopURL = desktopURL
        }

        DebugLogger.shared.log("✅ Directory access established via entitlements", component: "FileAccessCoordinator")
    }

    /// Requests comprehensive permission in a single dialog
    private func requestComprehensivePermission() async -> Bool {
        return await withCheckedContinuation { continuation in
            DispatchQueue.main.async { [weak self] in
                guard let self else {
                    continuation.resume(returning: false)
                    return
                }
                let panel = NSOpenPanel()
                panel.message = "Marcut needs access to your documents folder to process DOCX files"
                panel.prompt = "Grant Access"
                panel.canChooseDirectories = true
                panel.canChooseFiles = false
                panel.allowsMultipleSelection = false
                panel.directoryURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first

                panel.begin { response in
                    if response == .OK, let selectedURL = panel.url {
                        Task { @MainActor [weak self] in
                            guard let self else {
                                continuation.resume(returning: false)
                                return
                            }
                            await self.createComprehensiveBookmark(for: selectedURL)
                            continuation.resume(returning: true)
                        }
                    } else {
                        DebugLogger.shared.log("❌ User denied comprehensive permission request", component: "FileAccessCoordinator")
                        continuation.resume(returning: false)
                    }
                }
            }
        }
    }

    /// Creates a comprehensive bookmark that covers all common directories
    private func createComprehensiveBookmark(for baseURL: URL) async {
        do {
            let bookmark = try baseURL.bookmarkData(options: [.withSecurityScope])
            userDefaults.set(bookmark, forKey: comprehensivePermissionKey)

            let success = baseURL.startAccessingSecurityScopedResource()
            if success {
                // Set this as the base for Documents access
                authorizedDocumentsURL = baseURL

                // Try to derive Downloads and Desktop from the base
                await deriveRelatedDirectories(from: baseURL)

                DebugLogger.shared.log("✅ Created comprehensive bookmark for base directory: \(baseURL.lastPathComponent)", component: "FileAccessCoordinator")
            } else {
                DebugLogger.shared.log("❌ Failed to access comprehensive bookmark", component: "FileAccessCoordinator")
            }
        } catch {
            DebugLogger.shared.log("❌ Failed to create comprehensive bookmark: \(error)", component: "FileAccessCoordinator")
        }
    }

    /// Attempts to derive Downloads and Desktop access from Documents bookmark
    private func deriveRelatedDirectories(from baseURL: URL) async {
        let fileManager = FileManager.default

        // Try to access Downloads directory
        if let downloadsURL = fileManager.urls(for: .downloadsDirectory, in: .userDomainMask).first {
            if fileManager.isReadableFile(atPath: downloadsURL.path) {
                authorizedDownloadsURL = downloadsURL
                DebugLogger.shared.log("✅ Downloads access derived from comprehensive permission", component: "FileAccessCoordinator")
            }
        }

        // Try to access Desktop directory
        if let desktopURL = fileManager.urls(for: .desktopDirectory, in: .userDomainMask).first {
            if fileManager.isReadableFile(atPath: desktopURL.path) {
                authorizedDesktopURL = desktopURL
                DebugLogger.shared.log("✅ Desktop access derived from comprehensive permission", component: "FileAccessCoordinator")
            }
        }
    }

    // MARK: - Directory Authorization (Legacy - kept for compatibility)

    /// Authorizes common directories without triggering user dialogs (legacy method)
    func authorizeCommonDirectories() async {
        // Try to access standard directories that should be covered by entitlements
        let fileManager = FileManager.default

        // Documents Directory (covered by entitlement)
        if let docsURL = fileManager.urls(for: .documentDirectory, in: .userDomainMask).first {
            do {
                try fileManager.createDirectory(at: docsURL.appendingPathComponent(".marcut_test"),
                                              withIntermediateDirectories: true)
                try fileManager.removeItem(at: docsURL.appendingPathComponent(".marcut_test"))
                authorizedDocumentsURL = docsURL
                DebugLogger.shared.log("✅ Documents directory authorized via entitlement", component: "FileAccessCoordinator")
            } catch {
                DebugLogger.shared.log("⚠️ Documents directory requires explicit authorization", component: "FileAccessCoordinator")
                // Fall back to bookmark system
                await createBookmarkForDirectory(.documentDirectory, key: documentsBookmarkKey)
            }
        }

        // Downloads Directory (covered by entitlement)
        if let downloadsURL = fileManager.urls(for: .downloadsDirectory, in: .userDomainMask).first {
            do {
                try fileManager.createDirectory(at: downloadsURL.appendingPathComponent(".marcut_test"),
                                              withIntermediateDirectories: true)
                try fileManager.removeItem(at: downloadsURL.appendingPathComponent(".marcut_test"))
                authorizedDownloadsURL = downloadsURL
                DebugLogger.shared.log("✅ Downloads directory authorized via entitlement", component: "FileAccessCoordinator")
            } catch {
                DebugLogger.shared.log("⚠️ Downloads directory requires explicit authorization", component: "FileAccessCoordinator")
                await createBookmarkForDirectory(.downloadsDirectory, key: downloadsBookmarkKey)
            }
        }

        // Desktop Directory (covered by entitlement)
        if let desktopURL = fileManager.urls(for: .desktopDirectory, in: .userDomainMask).first {
            do {
                try fileManager.createDirectory(at: desktopURL.appendingPathComponent(".marcut_test"),
                                              withIntermediateDirectories: true)
                try fileManager.removeItem(at: desktopURL.appendingPathComponent(".marcut_test"))
                authorizedDesktopURL = desktopURL
                DebugLogger.shared.log("✅ Desktop directory authorized via entitlement", component: "FileAccessCoordinator")
            } catch {
                DebugLogger.shared.log("⚠️ Desktop directory requires explicit authorization", component: "FileAccessCoordinator")
                await createBookmarkForDirectory(.desktopDirectory, key: desktopBookmarkKey)
            }
        }
    }

    /// Creates a security scoped bookmark for a directory
    private func createBookmarkForDirectory(_ directory: FileManager.SearchPathDirectory, key: String) async {
        guard let url = FileManager.default.urls(for: directory, in: .userDomainMask).first else { return }

        return await withCheckedContinuation { continuation in
            DispatchQueue.main.async {
                let panel = NSOpenPanel()
                panel.message = "Authorize access to \(directory == .documentDirectory ? "Documents" : directory == .downloadsDirectory ? "Downloads" : "Desktop") folder"
                panel.prompt = "Authorize"
                panel.canChooseDirectories = true
                panel.canChooseFiles = false
                panel.allowsMultipleSelection = false
                panel.directoryURL = url

                panel.begin { response in
                    if response == .OK, let selectedURL = panel.url {
                        Task { @MainActor [weak self] in
                            guard let self else {
                                continuation.resume()
                                return
                            }
                            do {
                                let bookmark = try selectedURL.bookmarkData(options: [.withSecurityScope])
                                let userDefaults = self.userDefaults
                                let bookmarkKey = key
                                userDefaults.set(bookmark, forKey: bookmarkKey)
                                let success = selectedURL.startAccessingSecurityScopedResource()

                                switch directory {
                                case .documentDirectory:
                                    self.authorizedDocumentsURL = selectedURL
                                case .downloadsDirectory:
                                    self.authorizedDownloadsURL = selectedURL
                                case .desktopDirectory:
                                    self.authorizedDesktopURL = selectedURL
                                default:
                                    break
                                }

                                if success {
                                    DebugLogger.shared.log("✅ Created bookmark for \(directory)", component: "FileAccessCoordinator")
                                }
                                continuation.resume()
                            } catch {
                                DebugLogger.shared.log("❌ Failed to create bookmark for \(directory): \(error)", component: "FileAccessCoordinator")
                                continuation.resume()
                            }
                        }
                    } else {
                        continuation.resume()
                    }
                }
            }
        }
    }

    /// Restores authorized directories from stored bookmarks
    private func restoreAuthorizedDirectories() {
        // First, try to restore comprehensive permission bookmark
        if let comprehensiveBookmark = userDefaults.data(forKey: comprehensivePermissionKey) {
            restoreFromComprehensiveBookmark(comprehensiveBookmark)
            updatePermissionStateAfterRestoration()
            return
        }

        // Fall back to individual directory bookmarks
        var restoredAny = false

        restoreDirectoryFromBookmark(documentsBookmarkKey) { url in
            authorizedDocumentsURL = url
            restoredAny = true
        }

        restoreDirectoryFromBookmark(downloadsBookmarkKey) { url in
            authorizedDownloadsURL = url
            restoredAny = true
        }

        restoreDirectoryFromBookmark(desktopBookmarkKey) { url in
            authorizedDesktopURL = url
            restoredAny = true
        }

        if restoredAny {
            updatePermissionStateAfterRestoration()
        }
    }

    /// Updates permission state after bookmark restoration
    private func updatePermissionStateAfterRestoration() {
        // Re-evaluate permission state after restoration
        let newState = shouldRequestPermissions()
        if needsPermissionRequest != newState {
            needsPermissionRequest = newState
            DebugLogger.shared.log("🔐 Permission state updated after restoration: needsRequest=\(newState)", component: "FileAccessCoordinator")
        }
    }

    /// Restores directory access from comprehensive bookmark
    private func restoreFromComprehensiveBookmark(_ bookmark: Data) {
        do {
            var isStale = false
            let url = try URL(resolvingBookmarkData: bookmark,
                             options: .withSecurityScope,
                             relativeTo: nil,
                             bookmarkDataIsStale: &isStale)

            guard !isStale else {
                userDefaults.removeObject(forKey: comprehensivePermissionKey)
                DebugLogger.shared.log("⚠️ Comprehensive bookmark stale, removed", component: "FileAccessCoordinator")
                return
            }

            let success = url.startAccessingSecurityScopedResource()
            if success {
                authorizedDocumentsURL = url

                // Try to derive other directory access
                Task {
                    await deriveRelatedDirectories(from: url)
                }

                DebugLogger.shared.log("✅ Restored comprehensive permission from bookmark: \(url.lastPathComponent)", component: "FileAccessCoordinator")
            } else {
                DebugLogger.shared.log("❌ Failed to access comprehensive bookmark", component: "FileAccessCoordinator")
            }
        } catch {
            DebugLogger.shared.log("❌ Failed to restore comprehensive bookmark: \(error)", component: "FileAccessCoordinator")
            // Remove invalid bookmark
            userDefaults.removeObject(forKey: comprehensivePermissionKey)
        }
    }

    /// Restores a directory from a bookmark
    private func restoreDirectoryFromBookmark(_ key: String, completion: (URL) -> Void) {
        guard let bookmark = userDefaults.data(forKey: key) else { return }

        do {
            var isStale = false
            let url = try URL(resolvingBookmarkData: bookmark,
                             options: .withSecurityScope,
                             relativeTo: nil,
                             bookmarkDataIsStale: &isStale)

            guard !isStale else {
                userDefaults.removeObject(forKey: key)
                return
            }

            let success = url.startAccessingSecurityScopedResource()
            if success {
                completion(url)
                DebugLogger.shared.log("✅ Restored directory access from bookmark: \(url.lastPathComponent)", component: "FileAccessCoordinator")
            }
        } catch {
            DebugLogger.shared.log("❌ Failed to restore directory from bookmark: \(error)", component: "FileAccessCoordinator")
        }
    }

    // MARK: - App Group Container Usage

    /// Gets the app group container URL for secure file processing
    private func getAppGroupContainer() -> URL? {
        return FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.marclaw.marcutapp")
    }

    /// Prepares a file for processing by copying it to the app group container (just-in-time permission)
    func prepareFileForProcessing(_ originalURL: URL) async throws -> URL {
        // Ensure we have permissions before processing
        guard await ensurePermissionsForFileAccess() else {
            throw FileAccessError.unauthorizedLocation(originalURL.path)
        }

        guard let container = getAppGroupContainer() else {
            throw FileAccessError.appGroupContainerUnavailable
        }

        let processingDir = container.appendingPathComponent("processing", isDirectory: true)
        try FileManager.default.createDirectory(at: processingDir, withIntermediateDirectories: true)

        let localCopy = processingDir.appendingPathComponent(originalURL.lastPathComponent)
        try FileManager.default.copyItem(at: originalURL, to: localCopy)

        DebugLogger.shared.log("✅ Copied file to app group container: \(originalURL.lastPathComponent)", component: "FileAccessCoordinator")
        return localCopy
    }

    /// Gets the output directory for processed files
    func getProcessingOutputDirectory() throws -> URL {
        guard let container = getAppGroupContainer() else {
            throw FileAccessError.appGroupContainerUnavailable
        }

        let outputDir = container.appendingPathComponent("output", isDirectory: true)
        try FileManager.default.createDirectory(at: outputDir, withIntermediateDirectories: true)

        return outputDir
    }

    /// Copies processed file back to user-selected location
    func copyProcessedFileToUserLocation(_ processedURL: URL, userURL: URL) throws {
        guard canAccessFile(at: userURL.deletingLastPathComponent()) else {
            throw FileAccessError.unauthorizedLocation(userURL.path)
        }

        try FileManager.default.copyItem(at: processedURL, to: userURL)
        DebugLogger.shared.log("✅ Copied processed file to user location: \(userURL.path)", component: "FileAccessCoordinator")
    }

    /// Cleans up temporary files from the app group container
    func cleanupProcessingFiles() {
        guard let container = getAppGroupContainer() else { return }

        let processingDir = container.appendingPathComponent("processing", isDirectory: true)
        let outputDir = container.appendingPathComponent("output", isDirectory: true)

        let cleanupDirectory = { (url: URL) in
            do {
                if FileManager.default.fileExists(atPath: url.path) {
                    try FileManager.default.removeItem(at: url)
                    DebugLogger.shared.log("🧹 Cleaned up directory: \(url.lastPathComponent)", component: "FileAccessCoordinator")
                }
            } catch {
                DebugLogger.shared.log("⚠️ Failed to cleanup directory \(url.lastPathComponent): \(error)", component: "FileAccessCoordinator")
            }
        }

        cleanupDirectory(processingDir)
        cleanupDirectory(outputDir)
    }

    // MARK: - File Access Methods

    /// Safe file access that checks authorization
    func canAccessFile(at url: URL) -> Bool {
        let fileManager = FileManager.default

        // Check if file is in an authorized directory
        if let authorizedURL = authorizedDocumentsURL, url.path.hasPrefix(authorizedURL.path) {
            return fileManager.isReadableFile(atPath: url.path)
        }

        if let authorizedURL = authorizedDownloadsURL, url.path.hasPrefix(authorizedURL.path) {
            return fileManager.isReadableFile(atPath: url.path)
        }

        if let authorizedURL = authorizedDesktopURL, url.path.hasPrefix(authorizedURL.path) {
            return fileManager.isReadableFile(atPath: url.path)
        }

        // Try direct access (might trigger permission dialog)
        return fileManager.isReadableFile(atPath: url.path)
    }

    /// Get safe default directory for file operations
    func getDefaultFileDirectory() -> URL {
        return authorizedDocumentsURL ??
               authorizedDownloadsURL ??
               FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first!
    }

    /// Safe directory creation within authorized directories
    func createDirectory(at url: URL) throws {
        guard canAccessFile(at: url) else {
            throw FileAccessError.unauthorizedLocation(url.path)
        }

        try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
        DebugLogger.shared.log("✅ Created directory: \(url.path)", component: "FileAccessCoordinator")
    }

    /// Safe file copy within authorized directories
    func copyItem(from source: URL, to destination: URL) throws {
        guard canAccessFile(at: source) else {
            throw FileAccessError.unauthorizedLocation(source.path)
        }

        guard canAccessFile(at: destination.deletingLastPathComponent()) else {
            throw FileAccessError.unauthorizedLocation(destination.path)
        }

        try FileManager.default.copyItem(at: source, to: destination)
        DebugLogger.shared.log("✅ Copied file: \(source.path) -> \(destination.path)", component: "FileAccessCoordinator")
    }

    /// Safe file move within authorized directories
    func moveItem(from source: URL, to destination: URL) throws {
        guard canAccessFile(at: source) else {
            throw FileAccessError.unauthorizedLocation(source.path)
        }

        guard canAccessFile(at: destination.deletingLastPathComponent()) else {
            throw FileAccessError.unauthorizedLocation(destination.path)
        }

        try FileManager.default.moveItem(at: source, to: destination)
        DebugLogger.shared.log("✅ Moved file: \(source.path) -> \(destination.path)", component: "FileAccessCoordinator")
    }

    /// Safe file removal within authorized directories
    func removeItem(at url: URL) throws {
        guard canAccessFile(at: url) else {
            throw FileAccessError.unauthorizedLocation(url.path)
        }

        try FileManager.default.removeItem(at: url)
        DebugLogger.shared.log("✅ Removed file: \(url.path)", component: "FileAccessCoordinator")
    }

    /// Find DOCX files in authorized directories (just-in-time permission)
    func findDocxFiles() async -> [URL] {
        // Ensure we have permissions before searching
        guard await ensurePermissionsForFileAccess() else {
            DebugLogger.shared.log("❌ Cannot find DOCX files - permissions not available", component: "FileAccessCoordinator")
            return []
        }

        var docxFiles: [URL] = []
        let fileManager = FileManager.default

        let searchDirectories = [authorizedDocumentsURL, authorizedDownloadsURL, authorizedDesktopURL]
            .compactMap { $0 }

        for directory in searchDirectories {
            if let enumerator = fileManager.enumerator(at: directory, includingPropertiesForKeys: nil) {
                let entries = enumerator.allObjects.compactMap { $0 as? URL }
                for fileURL in entries where fileURL.pathExtension.lowercased() == "docx" {
                    docxFiles.append(fileURL)
                }
            }
        }

        DebugLogger.shared.log("📄 Found \(docxFiles.count) DOCX files in authorized directories", component: "FileAccessCoordinator")
        return docxFiles
    }
}

enum FileAccessError: LocalizedError {
    case unauthorizedLocation(String)
    case appGroupContainerUnavailable

    var errorDescription: String? {
        switch self {
        case .unauthorizedLocation(let path):
            return "Access to location not authorized: \(path)"
        case .appGroupContainerUnavailable:
            return "App group container is not available. Please check your app configuration."
        }
    }
}
