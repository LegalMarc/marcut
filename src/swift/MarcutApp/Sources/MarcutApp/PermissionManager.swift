import Foundation
import SwiftUI
import UserNotifications

@MainActor class PermissionManager: NSObject, ObservableObject {
    static let shared = PermissionManager()

    @Published var isAuthorized = false
    @Published var authorizationStep = "Initializing..."
    @Published var isAuthorizing = false

    @Published var authorizationError: String?
    @Published var notificationStatus: UNAuthorizationStatus = .notDetermined
    
    // Local preference: Should we send notifications?
    // This allows the user to "Disable" them in-app without revoking OS permission.
    @Published var userEnabledNotifications: Bool {
        didSet {
            UserDefaults.standard.set(userEnabledNotifications, forKey: "MarcutApp_UserEnabledNotifications")
        }
    }

    private let userDefaults = UserDefaults.standard
    private let authorizationCompletedKey = "MarcutApp_AuthorizationCompleted"
    private let documentAccessBookmarkKey = "MarcutApp_DocumentAccessBookmark"

    private override init() {
        // Init local preference (Default to TRUE if not set)
        let savedPref = UserDefaults.standard.object(forKey: "MarcutApp_UserEnabledNotifications") as? Bool
        self.userEnabledNotifications = savedPref ?? true
        
        super.init()
        
        // CRITICAL FIX: Ensure notification delegate is set immediately.
        // This allows banners to appear even if the app is in the foreground.
        UNUserNotificationCenter.current().delegate = self

        // DEFERRED: We no longer check automatically on init to avoid startup prompts.
        // checkExistingAuthorization()
    }

    public func checkExistingAuthorization() {
        // Check both the new and old authorization systems
        let fileCoordinator = FileAccessCoordinator.shared
        isAuthorized = userDefaults.bool(forKey: authorizationCompletedKey) && fileCoordinator.isOnboardingCompleted

        if isAuthorized {
            restoreSecurityScopedResources()
            
            // CRITICAL FIX: Ensure notification delegate is set even if already authorized
            // Otherwise, foreground notifications will be silenced
            Task {
                try? await requestNotificationPermission()
            }
        }
    }

    @MainActor
    func requestAllPermissions() async -> Bool {
        isAuthorizing = true
        authorizationError = nil

        do {
            // Use the new unified permission system
            let fileCoordinator = FileAccessCoordinator.shared

            // Step 1: Unified Permission Setup (FileAccessCoordinator handles all file permissions)
            authorizationStep = "Setting up file access permissions..."
            let permissionSuccess = await fileCoordinator.performPermissionSetupIfNeeded()

            guard permissionSuccess else {
                throw PermissionError.filePermissionDenied
            }

            // Step 1.5: Notification Permissions
            authorizationStep = "Enabling system notifications..."
            // We ignore failure here to not block the app, just log it
            try? await requestNotificationPermission()

            // Step 2: Network Server Permission (Ollama) - existing logic
            authorizationStep = "Initializing local AI server..."
            try await requestNetworkPermission()

            // Step 3: Final validation
            authorizationStep = "Finalizing setup..."
            try await validatePermissions()

            // Mark authorization as completed in both systems
            userDefaults.set(true, forKey: authorizationCompletedKey)
            isAuthorized = true
            isAuthorizing = false

            DebugLogger.shared.log("✅ Unified permission authorization completed successfully", component: "PermissionManager")
            return true

        } catch {
            authorizationError = error.localizedDescription
            isAuthorizing = false
            DebugLogger.shared.log("❌ Permission authorization failed: \(error)", component: "PermissionManager")
            return false
        }
    }

    private func requestFileSystemAccess() async {
        // Use FileAccessCoordinator to authorize common directories
        let fileCoordinator = FileAccessCoordinator.shared
        await fileCoordinator.authorizeCommonDirectories()
        DebugLogger.shared.log("✅ File system access authorized via FileAccessCoordinator", component: "PermissionManager")

        // Small delay to ensure permission is recorded
        try? await Task.sleep(nanoseconds: 500_000_000) // 0.5 seconds
    }

    private func requestDocumentDirectoryAccess() async throws {
        // Use FileAccessCoordinator to ensure document directories are accessible
        let fileCoordinator = FileAccessCoordinator.shared
        await fileCoordinator.authorizeCommonDirectories()

        // Verify we have at least one authorized directory
        if fileCoordinator.authorizedDocumentsURL == nil &&
           fileCoordinator.authorizedDownloadsURL == nil &&
           fileCoordinator.authorizedDesktopURL == nil {
            throw PermissionError.documentAccessDenied
        }

        DebugLogger.shared.log("✅ Document directory access authorized", component: "PermissionManager")
    }

    @MainActor
    private func requestNetworkPermission() async throws {
        // Use shared PythonBridgeService to check Ollama (MainActor-isolated)
        let isAlreadyRunning = await PythonBridgeService.shared.testOllamaConnection()
        if isAlreadyRunning {
            DebugLogger.shared.log("✅ Network permission already granted (Ollama accessible)", component: "PermissionManager")
            return
        }

        DebugLogger.shared.log("📍 Requesting network server permission through Ollama check", component: "PermissionManager")

        await PythonBridgeService.shared.checkOllamaStatus()

        // Give the system time to show any permission dialogs
        try await Task.sleep(nanoseconds: 2_000_000_000) // 2 seconds

        DebugLogger.shared.log("✅ Network permission request completed", component: "PermissionManager")
    }

    private func requestDocumentAccess() async throws {
        // Check if we already have a bookmark
        if let existingBookmark = userDefaults.data(forKey: documentAccessBookmarkKey) {
            if validateBookmark(existingBookmark) {
                DebugLogger.shared.log("✅ Document access already authorized", component: "PermissionManager")
                return
            } else {
                // Remove stale bookmark
                userDefaults.removeObject(forKey: documentAccessBookmarkKey)
            }
        }

        // Request document access through file picker
        return try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.main.async {
                let panel = NSOpenPanel()
                panel.message = "MarcutApp needs permission to access your documents. Grant access to your Documents folder to enable redaction of Word files. This permission is only requested once."
                panel.prompt = "Grant Access"
                panel.canChooseDirectories = true
                panel.canChooseFiles = false
                panel.allowsMultipleSelection = false
                panel.allowedContentTypes = [.folder]

                // Default to Documents directory
                if let documentsURL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first {
                    panel.directoryURL = documentsURL
                }

                // Capture values locally to avoid capturing 'self' in @Sendable closure
                let bookmarkKey = self.documentAccessBookmarkKey
                let defaults = self.userDefaults

                panel.begin { response in
                    Task { @MainActor in
                        if response == .OK, let url = panel.url {
                            do {
                                let bookmark = try url.bookmarkData(options: [.withSecurityScope, .securityScopeAllowOnlyReadAccess])
                                let success = url.startAccessingSecurityScopedResource()
                                if success {
                                    defaults.set(bookmark, forKey: bookmarkKey)
                                    defaults.set(true, forKey: "DocumentAccessOnboardingCompleted")
                                    DebugLogger.shared.log("✅ Document access permission granted", component: "PermissionManager")
                                } else {
                                    DebugLogger.shared.log("❌ Failed to start accessing security scoped resource", component: "PermissionManager")
                                }
                                continuation.resume()
                            } catch {
                                DebugLogger.shared.log("❌ Failed to create document access bookmark: \(error)", component: "PermissionManager")
                                continuation.resume(throwing: error)
                            }
                        } else {
                            continuation.resume(throwing: PermissionError.documentAccessDenied)
                        }
                    }
                }
            }
        }
    }

    private func validatePermissions() async throws {
        // Validate that we can access all required resources
        let fileManager = FileManager.default

        // Test Application Support directory access
        let appSupportURL = fileManager.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MarcutApp")

        guard fileManager.isReadableFile(atPath: appSupportURL.path) else {
            throw PermissionError.fileSystemAccessDenied
        }

        // Test document access bookmark
        guard let bookmark = userDefaults.data(forKey: documentAccessBookmarkKey),
              validateBookmark(bookmark) else {
            throw PermissionError.documentAccessInvalid
        }

        DebugLogger.shared.log("✅ All permissions validated successfully", component: "PermissionManager")
    }

    private func validateBookmark(_ bookmark: Data) -> Bool {
        do {
            var isStale = false
            let url = try URL(resolvingBookmarkData: bookmark,
                             options: .withSecurityScope,
                             relativeTo: nil,
                             bookmarkDataIsStale: &isStale)

            if isStale {
                return false
            }

            // Test if we can access the resource
            let hasAccess = url.startAccessingSecurityScopedResource()
            let isReadable = FileManager.default.isReadableFile(atPath: url.path)
            if hasAccess {
                url.stopAccessingSecurityScopedResource()
            }

            return isReadable
        } catch {
            return false
        }
    }

    private func restoreSecurityScopedResources() {
        guard let bookmark = userDefaults.data(forKey: documentAccessBookmarkKey) else { return }

        do {
            var isStale = false
            let url = try URL(resolvingBookmarkData: bookmark,
                             options: .withSecurityScope,
                             relativeTo: nil,
                             bookmarkDataIsStale: &isStale)

            if !isStale {
                let success = url.startAccessingSecurityScopedResource()
                if success {
                    DebugLogger.shared.log("✅ Security scoped resources restored", component: "PermissionManager")
                } else {
                    DebugLogger.shared.log("❌ Failed to restore security scoped resources", component: "PermissionManager")
                }
            } else {
                DebugLogger.shared.log("⚠️ Security scoped bookmark is stale", component: "PermissionManager")
                userDefaults.removeObject(forKey: documentAccessBookmarkKey)
                isAuthorized = false
            }
        } catch {
            DebugLogger.shared.log("❌ Failed to restore security scoped resources: \(error)", component: "PermissionManager")
            userDefaults.removeObject(forKey: documentAccessBookmarkKey)
            isAuthorized = false
        }
    }

    func resetAuthorization() {
        userDefaults.removeObject(forKey: authorizationCompletedKey)
        userDefaults.removeObject(forKey: documentAccessBookmarkKey)
        isAuthorized = false
        DebugLogger.shared.log("🔄 Authorization reset", component: "PermissionManager")
    }

    func getAuthorizedDocumentsURL() -> URL? {
        guard let bookmark = userDefaults.data(forKey: documentAccessBookmarkKey) else { return nil }

        do {
            var isStale = false
            let url = try URL(resolvingBookmarkData: bookmark,
                             options: .withSecurityScope,
                             relativeTo: nil,
                             bookmarkDataIsStale: &isStale)

            guard !isStale else { return nil }
            return url
        } catch {
            return nil
        }
    }
}

enum PermissionError: LocalizedError {
    case fileSystemAccessDenied
    case documentAccessDenied
    case documentAccessInvalid
    case networkPermissionFailed
    case filePermissionDenied
    case notificationPermissionDenied

    var errorDescription: String? {
        switch self {
        case .fileSystemAccessDenied:
            return "File system access was denied"
        case .documentAccessDenied:
            return "Document access was denied"
        case .documentAccessInvalid:
            return "Document access is no longer valid"
        case .networkPermissionFailed:
            return "Network permission could not be established"
        case .filePermissionDenied:
            return "File access permission was denied by the user"
        case .notificationPermissionDenied:
             return "Notification permission was denied"
        }
    }
}



extension PermissionManager: UNUserNotificationCenterDelegate {
    
    // Step 1.5: Request Notification Permissions
    func requestNotificationPermission() async throws {
        let center = UNUserNotificationCenter.current()
        // Delegate needed to show notifications while app is in foreground
        center.delegate = self
        
        let settings = await center.notificationSettings()
        
        // If already authorized, just return success (no nag)
        // Also update the published status
        await MainActor.run { self.notificationStatus = settings.authorizationStatus }

        if settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional {
            DebugLogger.shared.log("✅ Notifications already authorized", component: "PermissionManager")
            return
        }
        
        // If explicitly denied, do not pester the user
        if settings.authorizationStatus == .denied {
            DebugLogger.shared.log("⚠️ Notification permission was previously denied", component: "PermissionManager")
            throw PermissionError.notificationPermissionDenied
        }
        
        // Only request if status is .notDetermined
        let granted = try await center.requestAuthorization(options: [.alert, .sound, .badge])
        
        // Update status again after request
        let newSettings = await center.notificationSettings()
        await MainActor.run { self.notificationStatus = newSettings.authorizationStatus }

        if granted {
            DebugLogger.shared.log("✅ Notification permission granted", component: "PermissionManager")
        } else {
            DebugLogger.shared.log("⚠️ Notification permission denied", component: "PermissionManager")
            throw PermissionError.notificationPermissionDenied
        }
    }
    
    // Helper to send notifications
    // Helper to send notifications
    func sendSystemNotification(title: String, body: String, force: Bool = false) {
        // 1. Check Local Preference first (unless forced)
        guard userEnabledNotifications || force else {
            DebugLogger.shared.log("🔕 Notification suppressed by user preference", component: "PermissionManager")
            return
        }

        let content = UNMutableNotificationContent()
        content.title = title
        content.body = body
        content.sound = UNNotificationSound.default
        
        // Create a unique ID or reuse? Unique for history.
        let request = UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
        
        UNUserNotificationCenter.current().add(request) { error in
            if let error = error {
                DebugLogger.shared.log("❌ Failed to schedule notification: \(error.localizedDescription)", component: "PermissionManager")
            } else {
                 DebugLogger.shared.log("✅ Notification successfully scheduled into UNUserNotificationCenter", component: "PermissionManager")
            }
        }
    }
    
    // Force request without checks (User triggered)
    func forceRequestNotificationPermission() async throws {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        
        DebugLogger.shared.log("🚨 Force-requesting notification permission...", component: "PermissionManager")
        
        // Always request, ignoring previous status
        let granted = try await center.requestAuthorization(options: [.alert, .sound, .badge])
        
        // Update status immediately
        let newSettings = await center.notificationSettings()
        await MainActor.run { self.notificationStatus = newSettings.authorizationStatus }

        if granted {
            DebugLogger.shared.log("✅ Force-request granted!", component: "PermissionManager")
        } else {
            DebugLogger.shared.log("❌ Force-request denied by system.", component: "PermissionManager")
            // Even if denied, usually this attempt puts the app into System Settings
            throw PermissionError.notificationPermissionDenied
        }
    }
    
    // Explicit refresh of status (called on view appear)
    func refreshNotificationStatus() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        await MainActor.run {
             self.notificationStatus = settings.authorizationStatus
        }
    }
    
    // Delegate method: Present notification even if app is in foreground
    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .sound, .list])
    }
}
