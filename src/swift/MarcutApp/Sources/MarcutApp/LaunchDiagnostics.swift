import SwiftUI
import AppKit
import OSLog

enum LaunchStage: String {
    case delegateLaunched = "delegate_launched"
    case activationPolicySet = "activation_policy_set"
    case activationWatchdogArmed = "activation_watchdog_armed"
    case activationStateChanged = "activation_state_changed"
    case pythonInitStarted = "python_init_started"
    case pythonInitSucceeded = "python_init_succeeded"
    case pythonInitFailed = "python_init_failed"
    case contentViewAppeared = "content_view_appeared"
    case watchdogTick = "watchdog_tick"
    case watchdogEscalated = "watchdog_escalated"
}

final class LaunchDiagnostics: ObservableObject {
    static let shared = LaunchDiagnostics()

    private let logger = Logger(subsystem: "com.marclaw.marcutapp", category: "Launch")
    @Published private(set) var statusLines: [String] = []

    private var forceDiagnosticWindow = false
    private var diagnosticsEnabled = false
    private var guiModeEnabled = false
    private var watchdogTimer: DispatchSourceTimer?
    private var watchdogTickCount = 0
    private let watchdogInterval: TimeInterval = 2.0
    private let watchdogEscalationThreshold = 5
    private var contentViewConfirmed = false

    private init() {}

    func configure(forceDiagnosticWindow: Bool) {
        self.forceDiagnosticWindow = forceDiagnosticWindow
        self.diagnosticsEnabled = forceDiagnosticWindow || DebugPreferences.isEnabled()
        guard diagnosticsEnabled else { return }
        mark(.activationStateChanged, extra: "configure forceWindow=\(forceDiagnosticWindow)")
    }

    func enableGUIModeDiagnostics() {
        guard diagnosticsEnabled else { return }
        guiModeEnabled = true
        if forceDiagnosticWindow {
            LaunchDiagnosticsWindow.shared.present(reason: "Force flag")
            LaunchDiagnosticsWindow.shared.update(statusLines: statusLines)
        }
    }

    func mark(_ stage: LaunchStage, extra: String? = nil) {
        guard diagnosticsEnabled else { return }
        let message = "[\(stage.rawValue)]\(extra.map { " \($0)" } ?? "")"
        logger.log("LaunchDiag: \(message, privacy: .private)")
        DebugLogger.shared.log("LaunchDiag: \(message)", component: "Launch")

        DispatchQueue.main.async {
            self.statusLines.append(message)
            LaunchDiagnosticsWindow.shared.update(statusLines: self.statusLines)
            if self.forceDiagnosticWindow && self.guiModeEnabled {
                LaunchDiagnosticsWindow.shared.present(reason: "Force flag")
            }
        }
    }

    func setLogPath(_ path: String) {
        guard diagnosticsEnabled else { return }
        let message = "[log_path] \(path)"
        logger.log("LaunchDiag: \(message, privacy: .private)")
        DispatchQueue.main.async {
            self.statusLines.append(message)
            LaunchDiagnosticsWindow.shared.update(statusLines: self.statusLines)
        }
    }

    func armActivationWatchdog() {
        guard diagnosticsEnabled else { return }
        guard guiModeEnabled else { return }
        guard watchdogTimer == nil else { return }
        mark(.activationWatchdogArmed, extra: "interval=\(watchdogInterval)s")

        let timer = DispatchSource.makeTimerSource(queue: DispatchQueue.main)
        timer.schedule(deadline: .now() + watchdogInterval, repeating: watchdogInterval)
        timer.setEventHandler { [weak self] in
            guard let self else { return }
            guard !self.contentViewConfirmed else { return }
            self.watchdogTickCount += 1
            self.mark(.watchdogTick, extra: "tick=\(self.watchdogTickCount)")

            NSApp.activate(ignoringOtherApps: true)
            if let window = NSApp.windows.first {
                window.center()
                window.makeKeyAndOrderFront(nil)
                window.orderFrontRegardless()
            }

            LaunchDiagnosticsWindow.shared.present(reason: "Watchdog tick \(self.watchdogTickCount)")

            if self.watchdogTickCount >= self.watchdogEscalationThreshold {
                self.mark(.watchdogEscalated, extra: "ticks=\(self.watchdogTickCount)")
            }
        }
        timer.resume()
        watchdogTimer = timer
    }

    func cancelWatchdog() {
        watchdogTimer?.cancel()
        watchdogTimer = nil
    }

    func activationDidChange(isActive: Bool) {
        guard diagnosticsEnabled else { return }
        mark(.activationStateChanged, extra: "active=\(isActive)")
        if guiModeEnabled && isActive && !contentViewConfirmed {
            LaunchDiagnosticsWindow.shared.present(reason: "Activation changed")
        }
    }

    func markContentViewAppeared() {
        guard !contentViewConfirmed else { return }
        contentViewConfirmed = true
        guard diagnosticsEnabled else { return }
        mark(.contentViewAppeared)
        cancelWatchdog()
        DispatchQueue.main.async {
            LaunchDiagnosticsWindow.shared.dismiss()
        }
    }
}

final class LaunchDiagnosticsWindow {
    static let shared = LaunchDiagnosticsWindow()

    private var window: NSWindow?

    private init() {}

    func present(reason: String) {
        DispatchQueue.main.async {
            if self.window == nil {
                let window = NSWindow(
                    contentRect: NSRect(x: 0, y: 0, width: 420, height: 260),
                    styleMask: [.titled, .closable, .utilityWindow],
                    backing: .buffered,
                    defer: false
                )
                window.isReleasedWhenClosed = false
                window.level = .floating
                window.title = "Marcut Launch Diagnostics"
                let hosting = NSHostingView(rootView: LaunchDiagnosticsPanel(statusProvider: LaunchDiagnostics.shared))
                window.contentView = hosting
                self.window = window
            }

            self.window?.makeKeyAndOrderFront(nil)
            self.window?.orderFrontRegardless()
            DebugLogger.shared.log("LaunchDiagnosticsWindow presented: \(reason)", component: "Launch")
        }
    }

    func update(statusLines: [String]) {
        DispatchQueue.main.async {
            if let hosting = self.window?.contentView as? NSHostingView<LaunchDiagnosticsPanel> {
                hosting.rootView = LaunchDiagnosticsPanel(statusProvider: LaunchDiagnostics.shared)
            }
        }
    }

    func dismiss() {
        DispatchQueue.main.async {
            self.window?.close()
            self.window = nil
        }
    }
}

struct LaunchDiagnosticsPanel: View {
    @ObservedObject var statusProvider: LaunchDiagnostics

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Launch Status")
                .font(.headline)
            ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(Array(statusProvider.statusLines.enumerated()), id: \.offset) { entry in
                        Text(entry.element)
                            .font(.system(size: 12, weight: .regular, design: .monospaced))
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
            }
            .frame(maxHeight: .infinity)

            HStack {
                Button("Open Logs Folder") {
                    let path = DebugLogger.shared.logURL.deletingLastPathComponent()
                    // NSWorkspace.shared.open(path) // REMOVED: Triggers "Access data from other apps" prompt
                    print("Log path: \(path)") // safe alternative
                }
                .accessibilityIdentifier("diagnostics.openLogs")
                Spacer()
                Button("Dismiss") {
                    LaunchDiagnosticsWindow.shared.dismiss()
                }
                .accessibilityIdentifier("diagnostics.dismiss")
            }
        }
        .padding(16)
        .frame(minWidth: 380, minHeight: 240)
    }
}
