import SwiftUI
import AppKit

@main
struct MarcutMain {
    static func main() async {
        let args = ProcessInfo.processInfo.arguments
        if args.contains("--trace-python-setup") {
            setenv("MARCUT_TRACE_PY_SETUP", "1", 1)
        }
        if args.contains("--disable-python-timeouts") {
            setenv("MARCUT_DISABLE_PY_TIMEOUTS", "1", 1)
        }
        let forceDiagnosticsWindow = args.contains("--force-diagnostics-window")
            || ProcessInfo.processInfo.environment["MARCUT_FORCE_DIAGNOSTIC_WINDOW"] == "1"

        LaunchDiagnostics.shared.configure(forceDiagnosticWindow: forceDiagnosticsWindow)
        LaunchDiagnostics.shared.mark(.delegateLaunched, extra: "args=\(args)")

        let cliFlags: Set<String> = [
            "--cli",
            "--test",
            "--diagnose",
            "--help",
            "--redact",
            "--download-model"
        ]
        let isCLIMode = args.contains { cliFlags.contains($0) }

        if isCLIMode {
            let appDelegate = AppDelegate()
            // Initialize Python runtime before running CLI mode
            await MainActor.run {
                appDelegate.initializePythonRuntimeIfNeeded()
            }
            let success = await appDelegate.runCLIMode(args: args)
            exit(success ? 0 : 1)
        } else {
            MarcutAppScene.main()
        }
    }
}
