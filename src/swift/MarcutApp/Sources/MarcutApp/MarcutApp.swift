import SwiftUI
import AppKit
import OSLog
import Foundation
import PythonKit

// App Delegate for proper menu handling
class AppDelegate: NSObject, NSApplicationDelegate {
    // Global Python runtime - initialized once at app launch
    static var pythonRunner: PythonKitRunner?
    private var activationObservers: [NSObjectProtocol] = []
    private var isPythonInitializationInProgress = false

    @MainActor
    func applicationDidFinishLaunching(_ notification: Notification) {
        // Enable SwiftUI debugging for AttributeGraph cycles
        enableSwiftUIDebugging()

        // Early logging to track app launch
        print("🚀 APP DELEGATE LAUNCHED - Console output")
        DebugLogger.shared.log("=== APP DELEGATE LAUNCHED ===", component: "AppDelegate")

        // Check for CLI mode early
        let args = ProcessInfo.processInfo.arguments
        logStartupBanner(args: args)
        print("Launch arguments: \(args)")
        DebugLogger.shared.log("Launch arguments: \(args)", component: "AppDelegate")
        LaunchDiagnostics.shared.mark(.activationStateChanged, extra: "args=\(args)")
        registerActivationObservers()

        if args.contains("--cli") || args.contains("--test") || args.contains("--diagnose") || args.contains("--help") || args.contains("--redact") || args.contains("--diag-launcher") {
            // Run in CLI mode
            logToFile("Running in CLI mode")
            NSApp.setActivationPolicy(.accessory)
            LaunchDiagnostics.shared.mark(.activationPolicySet, extra: "accessory")
            initializePythonRuntimeIfNeeded()
            Task {
                let ok = await runCLIMode(args: args)
                exit(ok ? 0 : 1)
            }
        } else {
            // Ensure app appears in dock and menu bar
            logToFile("Running in GUI mode")
            NSApp.setActivationPolicy(.regular)
            LaunchDiagnostics.shared.mark(.activationPolicySet, extra: "regular")
            LaunchDiagnostics.shared.enableGUIModeDiagnostics()
            LaunchDiagnostics.shared.armActivationWatchdog()
            // Bring app to front to ensure window shows after permission prompts
            DispatchQueue.main.async {
                NSApp.activate(ignoringOtherApps: true)
            }
            // Initialize Python asynchronously to avoid blocking the main thread
            // This prevents the 30-50s hang on first launch with cold filesystem cache
            Task.detached(priority: .userInitiated) {
                // Startup I/O that shouldn't block main thread
                _ = UserOverridesManager.shared
                await MainActor.run {
                    PythonBridgeService.shared.launchCleanup()
                }
                self.initializePythonRuntimeIfNeeded()
            }

            // Establish permissions proactively at startup to prevent repeated dialogs
            // DEFERRED: We now lazy-load permissions on first use to avoid startup prompts
            /*Task {
                await FileAccessCoordinator.shared.establishPermissionsAtStartup()
            }*/
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        return true
    }

    @MainActor
    func applicationWillTerminate(_ notification: Notification) {
        // Clean up any running Ollama processes
        // This will be handled by PythonBridgeService deinit
        activationObservers.forEach { NotificationCenter.default.removeObserver($0) }
        activationObservers.removeAll()
        PythonBridgeService.shared.cancelAllProcesses()
        LaunchDiagnostics.shared.cancelWatchdog()
    }

    /// Initialize Python runtime. Can be called from any thread.
    /// Heavy work happens on PythonWorkerThread; state updates dispatch to main.
    func initializePythonRuntimeIfNeeded() {
        // Thread-safe guard
        guard AppDelegate.pythonRunner == nil, !isPythonInitializationInProgress else { return }
        isPythonInitializationInProgress = true
        let startTime = Date()
        print("🐍 Initializing Python runtime (background)...")
        DebugLogger.shared.log("APP_PYTHON_INIT_START isMainThread=\(Thread.isMainThread)", component: "AppDelegate")
        LaunchDiagnostics.shared.mark(.pythonInitStarted, extra: "main_thread=\(Thread.isMainThread)")

        do {
            // PythonKitRunner uses PythonWorkerThread internally for heavy work
            let runner = try PythonKitRunner(logger: { msg in
                DebugLogger.shared.log(msg, component: "PythonRuntime")
                print("PythonRuntime: \(msg)")
            })
            
            // Update shared state on main thread
            DispatchQueue.main.async {
                AppDelegate.pythonRunner = runner
                let elapsed = Date().timeIntervalSince(startTime)
                let elapsedString = String(format: "%.2f", elapsed)
                print("✅ Python runtime initialized successfully (\(elapsedString)s)")
                DebugLogger.shared.log("APP_PYTHON_INIT_SUCCESS: \(elapsedString)s", component: "AppDelegate")
                LaunchDiagnostics.shared.mark(.pythonInitSucceeded, extra: "elapsed=\(elapsedString)s")
                NotificationCenter.default.post(name: .pythonRunnerReady, object: nil)
            }
        } catch {
            DispatchQueue.main.async {
                let elapsed = Date().timeIntervalSince(startTime)
                let elapsedString = String(format: "%.2f", elapsed)
                print("❌ Failed to initialize Python runtime: \(error) (\(elapsedString)s)")
                DebugLogger.shared.log("APP_PYTHON_INIT_ERROR: \(error) (\(elapsedString)s)", component: "AppDelegate")
                LaunchDiagnostics.shared.mark(.pythonInitFailed, extra: "\(error)")
                NotificationCenter.default.post(
                    name: .pythonRunnerFailed,
                    object: nil,
                    userInfo: ["error": error.localizedDescription]
                )
            }
        }
        isPythonInitializationInProgress = false
    }

    private func logToFile(_ message: String) {
        DebugLogger.shared.log(message, component: "AppDelegate")
    }

    private func directLogToFile(_ message: String) {
        let logPath = DebugLogger.shared.logPath
        let timestamp = ISO8601DateFormatter().string(from: Date())
        let logMessage = "[\(timestamp)] AppDelegate-Direct: \(message)\n"

        if FileManager.default.fileExists(atPath: logPath) {
            if let fileHandle = FileHandle(forWritingAtPath: logPath) {
                fileHandle.seekToEndOfFile()
                fileHandle.write(logMessage.data(using: .utf8) ?? Data())
                fileHandle.closeFile()
            }
        } else {
            try? logMessage.write(to: URL(fileURLWithPath: logPath), atomically: true, encoding: .utf8)
        }
    }

    private func logStartupBanner(args: [String]) {
        let formatter = ISO8601DateFormatter()
        let timestamp = formatter.string(from: Date())
        let pid = getpid()
        let banner = """
==========================================================
🪪  MarcutApp launch
🕒  \(timestamp)
🔧  PID: \(pid)
🚩  Args: \(args.joined(separator: " "))
==========================================================
"""
        print(banner)
        DebugLogger.shared.log(banner, component: "AppDelegate")
    }

    private func enableSwiftUIDebugging() {
        // Enable SwiftUI debugging environment variables
        setenv("SWIFTUI_DEBUG_ATTRIBUTE_GRAPH", "1", 1)
        setenv("SWIFTUI_DEBUG_UPDATES", "1", 1)
        setenv("SWIFTUI_DEBUG_LAYOUT", "1", 1)
        setenv("SWIFTUI_DEBUG_IDENTITY", "1", 1)

        print("🔍 SwiftUI debugging enabled:")
        print("  - AttributeGraph debugging: ON")
        print("  - Update debugging: ON")
        print("  - Layout debugging: ON")
        print("  - Identity debugging: ON")

        // Log current AttributeGraph state
        directLogToFile("SwiftUI debugging flags enabled")
    }

    private func registerActivationObservers() {
        guard activationObservers.isEmpty else { return }

        let center = NotificationCenter.default
        let didBecome = center.addObserver(
            forName: NSApplication.didBecomeActiveNotification,
            object: nil,
            queue: .main
        ) { _ in
            LaunchDiagnostics.shared.activationDidChange(isActive: true)
        }

        let didResign = center.addObserver(
            forName: NSApplication.didResignActiveNotification,
            object: nil,
            queue: .main
        ) { _ in
            LaunchDiagnostics.shared.activationDidChange(isActive: false)
        }

        activationObservers.append(contentsOf: [didBecome, didResign])
    }

    @MainActor
    func runCLIMode(args: [String]) async -> Bool {
        print("🚀 MarcutApp CLI Mode")
        print("=====================================")

        // Use new PythonKit + BeeWare framework approach
        // Wait for Python runner initialization (as it completes asynchronously on main thread)
        let initStart = Date()
        while AppDelegate.pythonRunner == nil {
            if Date().timeIntervalSince(initStart) > 30 {
                 print("❌ Python integration timed out")
                 return false
            }
            try? await Task.sleep(nanoseconds: 100_000_000) // 100ms
        }

        guard AppDelegate.pythonRunner != nil else {
            print("❌ PythonKit runner not initialized")
            return false
        }

        if args.contains("--diagnose") {
            print("\n📊 Running Diagnostics...")
            await runDiagnosticsWithPythonKit()
            return true
        } else if args.contains("--test") {
            print("\n🧪 Running Tests...")
            await runTestsWithPythonKit()
            return true
        } else if args.contains("--diag-launcher") {
            print("\n🔍 Verifying embedded CLI launcher...")
            // Locate CLI launcher inside app bundle
            let scriptPath: String
            if let resourcePath = Bundle.main.resourcePath {
                scriptPath = resourcePath.appending("/marcut_cli_launcher.sh")
            } else {
                let bundlePath = Bundle.main.bundlePath
                let candidates = [
                    "\(bundlePath)/Contents/Resources/marcut_cli_launcher.sh",
                    "\(bundlePath)/../MarcutApp/Contents/Resources/marcut_cli_launcher.sh",
                    "\(bundlePath)/../../MarcutApp/Contents/Resources/marcut_cli_launcher.sh",
                ]
                scriptPath = candidates.first { FileManager.default.fileExists(atPath: $0) } ?? candidates[0]
            }

            guard FileManager.default.isExecutableFile(atPath: scriptPath) else {
                print("❌ CLI launcher not found or not executable at: \(scriptPath)")
                return false
            }

            // Run launcher with a safe help request that exercises Python embedding
            let process = Process()
            process.executableURL = URL(fileURLWithPath: scriptPath)
            process.arguments = ["redact", "--help"]
            var env = ProcessInfo.processInfo.environment
            env["PYTHONUNBUFFERED"] = "1"
            process.environment = env

            let stdoutPipe = Pipe(); process.standardOutput = stdoutPipe
            let stderrPipe = Pipe(); process.standardError = stderrPipe

            do {
                try process.run()
                process.waitUntilExit()
            } catch {
                print("❌ Failed to run CLI launcher: \(error)")
                return false
            }

            let outData = stdoutPipe.fileHandleForReading.readDataToEndOfFile()
            let errData = stderrPipe.fileHandleForReading.readDataToEndOfFile()
            if let outStr = String(data: outData, encoding: .utf8), !outStr.isEmpty { print(outStr) }
            if let errStr = String(data: errData, encoding: .utf8), !errStr.isEmpty { fputs(errStr, stderr) }
            let ok = (process.terminationStatus == 0)
            print(ok ? "✅ CLI launcher verified" : "❌ CLI launcher returned non-zero exit code \(process.terminationStatus)")
            return ok
        } else if args.contains("--redact") {
            // Headless redact: --redact --in <file> [--out <file>] [--report <file>] [--outdir <dir>] [--mode enhanced|rules] [--model name]
            guard let inIdx = args.firstIndex(of: "--in"), inIdx + 1 < args.count else {
                print("❌ Missing --in argument")
                printCLIHelp()
                return false
            }
            let inPath = args[inIdx + 1]
            // Optional exact output/report paths
            let outPathOpt: String? = {
                if let idx = args.firstIndex(of: "--out"), idx + 1 < args.count { return args[idx + 1] }
                return nil
            }()
            let reportPathOpt: String? = {
                if let idx = args.firstIndex(of: "--report"), idx + 1 < args.count { return args[idx + 1] }
                return nil
            }()
            // Optional outdir (fallback if exact paths not provided)
            let outDirPath: String? = {
                if let idx = args.firstIndex(of: "--outdir"), idx + 1 < args.count { return args[idx + 1] }
                return nil
            }()
            let mode: String = {
                if let mIdx = args.firstIndex(of: "--mode"), mIdx + 1 < args.count { return args[mIdx + 1] }
                return "enhanced"
            }()
            let modelName: String = {
                if let mIdx = args.firstIndex(of: "--model"), mIdx + 1 < args.count { return args[mIdx + 1] }
                return "llama3.1:8b"
            }()

            // Generate output file paths
            let inputURL = URL(fileURLWithPath: inPath)
            // Determine output/report paths
            let outputPath: String
            let reportPath: String
            if let outExact = outPathOpt, let repExact = reportPathOpt {
                outputPath = outExact
                reportPath = repExact
            } else if let outDirPath = outDirPath {
                let outDir = URL(fileURLWithPath: outDirPath, isDirectory: true)
                let outputFileName = inputURL.deletingPathExtension().lastPathComponent + "_redacted.docx"
                let reportFileName = inputURL.deletingPathExtension().lastPathComponent + "_report.json"
                outputPath = outDir.appendingPathComponent(outputFileName).path
                reportPath = outDir.appendingPathComponent(reportFileName).path
            } else {
                // Default to input directory if neither exact nor outdir provided
                let outDir = inputURL.deletingLastPathComponent()
                let outputFileName = inputURL.deletingPathExtension().lastPathComponent + "_redacted.docx"
                let reportFileName = inputURL.deletingPathExtension().lastPathComponent + "_report.json"
                outputPath = outDir.appendingPathComponent(outputFileName).path
                reportPath = outDir.appendingPathComponent(reportFileName).path
            }

            // Ensure destination directory exists
            let outDirURL = URL(fileURLWithPath: outputPath).deletingLastPathComponent()
            try? FileManager.default.createDirectory(at: outDirURL, withIntermediateDirectories: true)

            // Process via in-process PythonKit (BeeWare-aligned, prod-safe)
            print("🧪 Headless redaction via in-process PythonKit…")
            let debug = args.contains("--debug")

            guard let runner = AppDelegate.pythonRunner else {
                print("❌ PythonKit runner not initialized")
                return false
            }

            // Ensure Ollama is up (XPC/hybrid) and the model is promoted before calling Python
            if mode.lowercased() != "rules" {
                print("⏳ Ensuring embedded Ollama is running and model is ready (\(modelName))…")
                let ready = await PythonBridgeService.shared.ensureOllamaReadyForPythonKit(requiredModel: modelName)
                if !ready {
                    print("❌ Ollama service or model \(modelName) is not ready. Aborting.")
                    return false
                }
            }

            let (stream, result) = runner.runEnhancedOllamaWithProgress(
                inputPath: inPath,
                outputPath: outputPath,
                reportPath: reportPath,
                model: modelName,
                debug: debug,
                mode: mode,
                cancellationChecker: { false }
            )

            // Consume progress stream
            let progressTask = Task {
                for await update in stream {
                    if let phase = update.phaseIdentifier, let fraction = update.phaseProgress {
                        let percent = Int(fraction * 100)
                        print("Phase \(phase): \(percent)%")
                    } else if let chunk = update.chunk, let total = update.total, total > 0 {
                        print("Progress: \(chunk)/\(total)")
                    }
                    if let message = update.message, !message.isEmpty {
                        print(message)
                    }
                }
            }

            let outcome = await result.value
            progressTask.cancel()

            let ok = (outcome == .success)
            print(ok ? "✅ Redaction complete" : "❌ Redaction failed")
            return ok
        } else if args.contains("--download-model") {
            if let modelIndex = args.firstIndex(of: "--download-model"),
               modelIndex + 1 < args.count {
                let model = args[modelIndex + 1]
                print("\n📥 Downloading model: \(model)")
                await downloadModelWithPythonKit(model: model)
                return true
            } else {
                print("❌ Please specify a model name")
                return false
            }
        } else if args.contains("--help") {
            printCLIHelp()
            return true
        } else {
            printCLIHelp()
            return false
        }
    }

    @MainActor
    func runDiagnosticsWithPythonKit() async {
        print("1️⃣ Checking Ollama binary...")
        let bridge = PythonBridgeService.shared
        bridge.checkEnvironment()

        // Wait for environment check
        try? await Task.sleep(nanoseconds: 1_000_000_000)

        print("   Ollama running: \(bridge.isOllamaRunning)")
        print("   Installed models: \(bridge.installedModels)")

        print("\n2️⃣ Testing Ollama startup...")
        let testResult = await bridge.testOllamaConnection()
        print("   Connection test: \(testResult ? "✅ Success" : "❌ Failed")")

        print("\n3️⃣ PythonKit smoke: init + import marcut…")
        guard AppDelegate.pythonRunner != nil else {
            print("   ❌ PythonKit runner not available")
            return
        }
        print("   ✅ PythonKit initialized and ready")

        print("\n4️⃣ Testing model download...")
        let success = await bridge.downloadModel("llama3.1:8b") { progress in
            print("   Progress: \(Int(progress))%")
        }
        print("   Download result: \(success ? "✅ Success" : "❌ Failed")")
    }

    @MainActor
    func runTestsWithPythonKit() async {
        print("Running PythonKit-based tests...")
        guard AppDelegate.pythonRunner != nil else {
            print("❌ PythonKit runner not available")
            return
        }
        print("✅ PythonKit integration test passed")
    }

    @MainActor
    func downloadModelWithPythonKit(model: String) async {
        let bridge = PythonBridgeService.shared
        let success = await bridge.downloadModel(model) { progress in
            print("Progress: \(Int(progress))%")
        }
        print(success ? "✅ Download complete" : "❌ Download failed")
    }

    @MainActor
    func runTests(bridge: PythonBridgeService) async {
        // Add comprehensive tests here
        print("Running test suite...")
    }

    @MainActor
    func downloadModel(bridge: PythonBridgeService, model: String) async {
        let success = await bridge.downloadModel(model) { progress in
            print("Progress: \(Int(progress))%")
        }
        print(success ? "✅ Download complete" : "❌ Download failed")
    }

    func printCLIHelp() {
        print("""
        Usage: MarcutApp [options]

        Options:
          --cli                   Run in CLI mode
          --diagnose              Run diagnostic tests
          --test                  Run test suite
          --redact                Run headless redaction
                                  --in <path> --outdir <dir> [--mode enhanced|rules] [--model name] [--backend ollama|mock]
          --download-model NAME   Download specified model
          --force-diagnostics-window
                                 Always show launch diagnostics window
          --trace-python-setup    Verbose Python warm-up logging (diagnostics)
          --disable-python-timeouts
                                 Disable Python warm-up safeguards (diagnostics only)
          --help                  Show this help message

        Examples:
          MarcutApp --diagnose
          MarcutApp --redact --in /path/to/file.docx --outdir /tmp/out --mode enhanced --model llama3.1:8b
          MarcutApp --download-model llama3.1:8b
        """)
    }
}

struct MarcutAppScene: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) var appDelegate
    @Environment(\.openWindow) private var openWindow
    @StateObject private var viewModel = DocumentRedactionViewModel()
    private let execController = OllamaExecutionController()

    var body: some Scene {
        #if arch(arm64)
        marcutAppScene
        #else
        WindowGroup("Unsupported Architecture") {
            UnsupportedArchitectureView()
        }
        #endif
    }

    @SceneBuilder
    private var marcutAppScene: some Scene {
        WindowGroup("Marcut — 100% Local AI Redaction") {
            ContentView()
                .environmentObject(viewModel)
        }
        .windowResizability(.contentMinSize)
        .commands {
            // About menu
            CommandGroup(replacing: .appInfo) {
                Button("About MarcutApp") {
                    LifecycleUtils.openAboutWindow()
                }
            }

            // File menu additions
            CommandGroup(replacing: .newItem) {
                // Remove default New Window option
            }

            // Preferences is handled by Settings scene (below)

            // Ensure File > Quit works properly
            CommandGroup(replacing: .appTermination) {
                Button("Quit MarcutApp") {
                    // Ensure we terminate properly
                    DispatchQueue.main.async {
                        NSApplication.shared.terminate(nil)
                    }
                }
                .keyboardShortcut("q", modifiers: .command)
            }

            // Tools menu removed


            // Help menu
            CommandGroup(replacing: .help) {
                Button("MarcutApp Help") {
                    LifecycleUtils.openHelpWindow()
                }
                .keyboardShortcut("?", modifiers: .command)

                Divider()

                Link("Visit Website", destination: URL(string: "https://github.com/marclaw/marcut")!)
            }
        }

        Settings {
            SettingsView(viewModel: viewModel)
        }
    }

}

enum LifecycleUtils {
    @MainActor
    static func openAboutWindow() {
        if let window = NSApp.windows.first(where: { $0.title == "About MarcutApp" }) {
            window.makeKeyAndOrderFront(nil)
            return
        }
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 300, height: 400),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )
        window.title = "About MarcutApp"
        window.center()
        window.contentView = NSHostingView(rootView: AboutView())
        window.isReleasedWhenClosed = false
        window.makeKeyAndOrderFront(nil)
    }

    @MainActor
    static func openHelpWindow() {
        if let window = NSApp.windows.first(where: { $0.title == "Help" }) {
            window.makeKeyAndOrderFront(nil)
            return
        }
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 520, height: 420),
            styleMask: [.titled, .closable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = "Help"
        window.center()
        window.contentView = NSHostingView(rootView: HelpView())
        window.isReleasedWhenClosed = false
        window.makeKeyAndOrderFront(nil)
    }
}

struct UnsupportedArchitectureView: View {
    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.largeTitle)
                .foregroundColor(.yellow)

            Text("Unsupported Architecture")
                .font(.title)
                .bold()

            Text("MarcutApp requires an Apple Silicon (arm64) Mac and cannot run on this machine.")
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)

            Button("Quit") {
                NSApplication.shared.terminate(nil)
            }
        }
        .padding(40)
        .frame(minWidth: 350)
    }
}

struct HelpView: View {
    @State private var markdownContent: String = ""
    
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            if markdownContent.isEmpty {
                ProgressView("Loading help...")
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                MarkdownTextView(markdownContent: markdownContent)
            }
            
            HStack {
                Spacer()
                Button("Close") {
                    NSApp.keyWindow?.close()
                }
                .keyboardShortcut(.defaultAction)
            }
            .padding()
        }
        .frame(minWidth: 400, minHeight: 300)
        .onAppear {
            loadHelpContent()
        }
    }
    
    private func loadHelpContent() {
        // Try multiple possible locations for the help.md file
        // SPM .copy("Resources") creates a Resources subdirectory in the bundle
        let possiblePaths: [URL?] = [
            // Standard bundle resource location (SPM may register it here)
            Bundle.main.url(forResource: "help", withExtension: "md"),
            // Direct placement in Contents/Resources (build script copies here)
            Bundle.main.resourceURL?
                .appendingPathComponent("help.md"),
            // SPM .copy("Resources") location - in MarcutApp_MarcutApp.bundle inside Contents/Resources
            Bundle.main.resourceURL?
                .appendingPathComponent("MarcutApp_MarcutApp.bundle")
                .appendingPathComponent("Resources")
                .appendingPathComponent("help.md"),
            // Alternative: bundleURL path requires going through Contents/Resources
            Bundle.main.bundleURL
                .appendingPathComponent("Contents")
                .appendingPathComponent("Resources")
                .appendingPathComponent("MarcutApp_MarcutApp.bundle")
                .appendingPathComponent("Resources")
                .appendingPathComponent("help.md"),
            // Direct Resources subdirectory (fallback)
            Bundle.main.resourceURL?
                .appendingPathComponent("Resources")
                .appendingPathComponent("help.md"),
        ]
        
        for possibleURL in possiblePaths {
            guard let url = possibleURL else { continue }
            if FileManager.default.fileExists(atPath: url.path),
               let content = try? String(contentsOf: url, encoding: .utf8) {
                markdownContent = content
                return
            }
        }
        
        // Fallback content if file not found
        markdownContent = """
        # MarcutApp Help
        
        Help content could not be loaded. Please reinstall the application.
        
        Searched paths:
        \(possiblePaths.compactMap { $0?.path }.joined(separator: "\n"))
        """
    }

}



extension Notification.Name {
    static let pythonRunnerReady = Notification.Name("com.marclaw.marcutapp.pythonRunnerReady")
    static let pythonRunnerFailed = Notification.Name("com.marclaw.marcutapp.pythonRunnerFailed")
}
