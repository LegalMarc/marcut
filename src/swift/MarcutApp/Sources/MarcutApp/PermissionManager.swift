import Foundation
import SwiftUI
import UserNotifications

@MainActor class PermissionManager: NSObject, ObservableObject {
    static let shared = PermissionManager()

    @Published var notificationStatus: UNAuthorizationStatus = .notDetermined
    
    // Local preference: Should we send notifications?
    // This allows the user to "Disable" them in-app without revoking OS permission.
    @Published var userEnabledNotifications: Bool {
        didSet {
            UserDefaults.standard.set(userEnabledNotifications, forKey: "MarcutApp_UserEnabledNotifications")
        }
    }

    private override init() {
        // Init local preference (Default to TRUE if not set)
        let savedPref = UserDefaults.standard.object(forKey: "MarcutApp_UserEnabledNotifications") as? Bool
        self.userEnabledNotifications = savedPref ?? true
        
        super.init()
        
        // CRITICAL FIX: Ensure notification delegate is set immediately.
        // This allows banners to appear even if the app is in the foreground.
        UNUserNotificationCenter.current().delegate = self

        // DEFERRED: We no longer check automatically on init to avoid startup prompts.
    }

}

enum PermissionError: LocalizedError {
    case notificationPermissionDenied

    var errorDescription: String? {
        switch self {
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
