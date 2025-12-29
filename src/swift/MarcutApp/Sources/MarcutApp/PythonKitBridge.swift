import Foundation
import PythonKit
import Darwin
import Network

struct PythonRunnerProgressUpdate {
    let phaseIdentifier: String?
    let phaseDisplayName: String?
    let phaseProgress: Double?
    let overallProgress: Double?
    let chunk: Int?
    let total: Int?
    let message: String?

    init(
        phaseIdentifier: String? = nil,
        phaseDisplayName: String? = nil,
        phaseProgress: Double? = nil,
        overallProgress: Double? = nil,
        chunk: Int? = nil,
        total: Int? = nil,
        message: String? = nil
    ) {
        self.phaseIdentifier = phaseIdentifier
        self.phaseDisplayName = phaseDisplayName
        self.phaseProgress = phaseProgress
        self.overallProgress = overallProgress
        self.chunk = chunk
        self.total = total
        self.message = message
    }
}

private extension String {
    func nilIfEmptyOrNone() -> String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty || trimmed == "None" {
            return nil
        }
        return trimmed
    }
}

private extension PythonObject {
    func toOptionalString() -> String? {
        let value = String(self)
        return value == "None" ? nil : value
    }

    func toOptionalDouble() -> Double? {
        Double(self)
    }
}

private typealias PyGILState_STATE = UnsafeMutableRawPointer?

private func loadPythonSymbol<T>(
    _ name: String,
    as type: T.Type
) -> T {
    guard let symbol = dlsym(UnsafeMutableRawPointer(bitPattern: -2), name) else {
        fatalError("Missing CPython symbol: \(name)")
    }
    return unsafeBitCast(symbol, to: type)
}

private func Py_IsInitialized() -> Int32 {
    let fn: @convention(c) () -> Int32 = loadPythonSymbol("Py_IsInitialized", as: (@convention(c) () -> Int32).self)
    return fn()
}

private func Py_Initialize() {
    let fn: @convention(c) () -> Void = loadPythonSymbol("Py_Initialize", as: (@convention(c) () -> Void).self)
    fn()
}

private func PyGILState_Ensure() -> PyGILState_STATE {
    let fn: @convention(c) () -> PyGILState_STATE = loadPythonSymbol("PyGILState_Ensure", as: (@convention(c) () -> PyGILState_STATE).self)
    return fn()
}

private func PyGILState_Release(_ state: PyGILState_STATE) {
    let fn: @convention(c) (PyGILState_STATE) -> Void = loadPythonSymbol("PyGILState_Release", as: (@convention(c) (PyGILState_STATE) -> Void).self)
    fn(state)
}

private func PyErr_SetInterrupt() {
    let fn: @convention(c) () -> Void = loadPythonSymbol("PyErr_SetInterrupt", as: (@convention(c) () -> Void).self)
    fn()
}

private func PyErr_CheckSignals() -> Int32 {
    let fn: @convention(c) () -> Int32 = loadPythonSymbol("PyErr_CheckSignals", as: (@convention(c) () -> Int32).self)
    return fn()
}

private func PyErr_Clear() {
    let fn: @convention(c) () -> Void = loadPythonSymbol("PyErr_Clear", as: (@convention(c) () -> Void).self)
    fn()
}

public enum PythonRuntimeSource: String {
    case beewareFramework
}

public struct PythonRuntimeConfig {
    public let source: PythonRuntimeSource
    public let libPath: String
    public let pyHome: String
    public let pyPaths: [String]
}

enum PythonInitError: Error {
    case notFound
    case loadFailed(String)
    case timeout(String)
    case ollamaUnavailable(String)
}

struct PythonDocumentAnalysis {
    let wordCount: Int
    let paragraphCount: Int
    let characterCount: Int
}

public enum PythonRunOutcome {
    case success
    case cancelled
    case failure
}

private enum PythonTimeoutOverrides {
    private static func env() -> [String: String] {
        ProcessInfo.processInfo.environment
    }

    static func step(for operation: String, default defaultValue: TimeInterval) -> TimeInterval {
        let key = "MARCUT_\(operation.uppercased())_STEP_TIMEOUT"
        return value(for: key, default: defaultValue)
    }

    static func total(for operation: String, default defaultValue: TimeInterval) -> TimeInterval {
        let key = "MARCUT_\(operation.uppercased())_TOTAL_TIMEOUT"
        return value(for: key, default: defaultValue)
    }

    static func disable(for operation: String) -> Bool {
        let envVars = env()
        if envVars["MARCUT_DISABLE_PY_TIMEOUTS"] == "1" { return true }
        if envVars["MARCUT_DISABLE_\(operation.uppercased())_TIMEOUT"] == "1" { return true }
        return false
    }

    private static func value(for key: String, default defaultValue: TimeInterval) -> TimeInterval {
        guard let raw = env()[key], let parsed = TimeInterval(raw), parsed > 0 else {
            return defaultValue
        }
        return parsed
    }
}

private final class PythonWorkerThread: Thread {
    private let condition = NSCondition()
    private var tasks: [() -> Void] = []
    private var running = true
    private let readySemaphore = DispatchSemaphore(value: 0)

    override init() {
        super.init()
        name = "PythonWorkerThread"
    }

    override func main() {
        readySemaphore.signal()
        while true {
            var task: (() -> Void)?
            condition.lock()
            while tasks.isEmpty && running {
                condition.wait()
            }
            if !running && tasks.isEmpty {
                condition.unlock()
                return
            }
            task = tasks.isEmpty ? nil : tasks.removeFirst()
            condition.unlock()
            task?()
        }
    }

    func waitUntilReady() {
        readySemaphore.wait()
    }

    func stop() {
        condition.lock()
        running = false
        condition.signal()
        condition.unlock()
    }

    private func enqueue(_ work: @escaping () -> Void) {
        condition.lock()
        tasks.append(work)
        condition.signal()
        condition.unlock()
    }

    func perform<T>(_ work: @escaping () throws -> T) throws -> T {
        let semaphore = DispatchSemaphore(value: 0)
        var result: Result<T, Error>!
        enqueue {
            do {
                result = .success(try work())
            } catch {
                result = .failure(error)
            }
            semaphore.signal()
        }
        semaphore.wait()
        return try result.get()
    }

    func performAsync(_ work: @escaping () -> Void) {
        enqueue(work)
    }
}

private func pythonSetupTracingEnabled() -> Bool {
    ProcessInfo.processInfo.environment["MARCUT_TRACE_PY_SETUP"] == "1"
}

public final class PythonRuntime {
    static func resolvedOllamaHost() -> String {
        ProcessInfo.processInfo.environment["MARCUT_OLLAMA_HOST"] ?? "127.0.0.1:11434"
    }

    static func checkOllamaPort(_ port: UInt16 = 11434) -> Bool {
        let hostString = resolvedOllamaHost()
        let components = hostString.split(separator: ":")
        let resolvedPort: UInt16
        if components.count == 2, let parsed = UInt16(components[1]) {
            resolvedPort = parsed
        } else {
            resolvedPort = port
        }

        let group = DispatchGroup()
        var isAvailable = false
        var hasLeftGroup = false

        group.enter()
        let connection = NWConnection(host: "127.0.0.1", port: NWEndpoint.Port(rawValue: resolvedPort)!, using: .tcp)
        connection.stateUpdateHandler = { state in
            switch state {
            case .ready:
                isAvailable = true
            case .failed, .cancelled:
                break
            default:
                return
            }

            if !hasLeftGroup {
                hasLeftGroup = true
                connection.cancel()
                group.leave()
            }
        }
        connection.start(queue: DispatchQueue.global())

        let result = group.wait(timeout: .now() + 1.0)
        if result == .timedOut {
            connection.cancel()
            isAvailable = false
        }

        return isAvailable
    }

    static func killOllamaProcesses(logger: (String) -> Void) {
        let task = Process()
        task.launchPath = "/usr/bin/killall"
        task.arguments = ["ollama"]

        do {
            try task.run()
            task.waitUntilExit()
            if task.terminationStatus == 0 {
                logger("PK_OLLAMA_CLEANUP: Killed existing ollama processes")
            }
        } catch {
            logger("PK_OLLAMA_CLEANUP_ERROR: \(error)")
        }
    }

    static func fastEnvironmentCheck(logger: (String) -> Void) -> Bool {
        let start = Date()
        let hostString = resolvedOllamaHost()

        guard locateFramework() != nil else {
            logger("PK_FAST_CHECK: Framework missing")
            return false
        }

        let frameworkTime = Date().timeIntervalSince(start)
        logger("PK_FAST_CHECK: Framework found (\(String(format: "%.0f", frameworkTime * 1000))ms)")

        let isOllamaRunning = checkOllamaPort()
        let checkTime = Date().timeIntervalSince(start)
        logger("PK_FAST_CHECK: Ollama \(isOllamaRunning ? "running" : "not running") host=\(hostString) (\(String(format: "%.0f", checkTime * 1000))ms total)")

        return isOllamaRunning
    }

    public static func locateFramework() -> PythonRuntimeConfig? {
        // BeeWare Python.framework location varies by build type
        let bundleURL = Bundle.main.bundleURL
        let fileManager = FileManager.default

        var frameworkURL: URL?
        var attempted: [String] = []

        typealias Candidate = (label: String, url: URL)
        var candidates: [Candidate] = []

        func appendCandidate(label: String, provider: () -> URL?) {
            guard let url = provider() else { return }
            if !candidates.contains(where: { $0.url == url }) {
                candidates.append((label, url))
            }
        }

        appendCandidate(label: "private frameworks") { Bundle.main.privateFrameworksURL?.appendingPathComponent("Python.framework") }
        appendCandidate(label: "app/Contents/Frameworks") {
            bundleURL
                .appendingPathComponent("Contents", isDirectory: true)
                .appendingPathComponent("Frameworks", isDirectory: true)
                .appendingPathComponent("Python.framework", isDirectory: true)
        }
        appendCandidate(label: "bundle/Frameworks") {
            bundleURL
                .appendingPathComponent("Frameworks", isDirectory: true)
                .appendingPathComponent("Python.framework", isDirectory: true)
        }
        appendCandidate(label: "resource bundle") {
            bundleURL
                .appendingPathComponent("Contents", isDirectory: true)
                .appendingPathComponent("Resources", isDirectory: true)
                .appendingPathComponent("MarcutApp_MarcutApp.bundle", isDirectory: true)
                .appendingPathComponent("Frameworks", isDirectory: true)
                .appendingPathComponent("Python.framework", isDirectory: true)
        }
        appendCandidate(label: "resourceURL/Frameworks") {
            Bundle.main.resourceURL?
                .appendingPathComponent("Frameworks", isDirectory: true)
                .appendingPathComponent("Python.framework", isDirectory: true)
        }

        for candidate in candidates {
            let pythonLib = candidate.url.appendingPathComponent("Python")
            attempted.append("\(candidate.label): \(candidate.url.path)")
            if fileManager.fileExists(atPath: pythonLib.path) {
                frameworkURL = candidate.url
                break
            }
        }

        guard let fwRoot = frameworkURL else {
            print("❌ Python.framework not found. Tried: \(attempted.joined(separator: "; "))")
            print("❌ Bundle URL: \(bundleURL.path)")
            if let resourceURL = Bundle.main.resourceURL {
                print("❌ Resource URL: \(resourceURL.path)")
            }
            return nil
        }

        let pythonLib = fwRoot.appendingPathComponent("Python")

        // Resolve the active Python version via the "Current" symlink to avoid hardcoding 3.11/3.10
        let versionsDir = fwRoot.appendingPathComponent("Versions")
        let currentLink = versionsDir.appendingPathComponent("Current")

        var pythonVersionDir = currentLink
        if let resolved = try? FileManager.default.destinationOfSymbolicLink(atPath: currentLink.path) {
            pythonVersionDir = URL(fileURLWithPath: resolved, relativeTo: versionsDir)
        } else if let firstVersion = try? FileManager.default.contentsOfDirectory(at: versionsDir, includingPropertiesForKeys: nil, options: [.skipsHiddenFiles]).first(where: { $0.lastPathComponent.contains(".") }) {
            pythonVersionDir = firstVersion
        } else {
            pythonVersionDir = versionsDir.appendingPathComponent("3.10")
        }

        let versionComponent = pythonVersionDir.lastPathComponent
        let libDir = pythonVersionDir.appendingPathComponent("lib")
        let stdlibPath = libDir.appendingPathComponent("python\(versionComponent)")
        let sitePackagesPath = stdlibPath.appendingPathComponent("site-packages")

        // Verify framework structure exists
        guard FileManager.default.fileExists(atPath: stdlibPath.path) else {
            return nil
        }

        // Setup Python paths - prioritize app python_site, then framework site-packages, then stdlib
        var pyPaths: [String] = []

        // First priority: app-specific site packages (our installed dependencies)
        var siteCandidates: [URL] = []

        if let resourcePath = Bundle.main.resourcePath {
            siteCandidates.append(URL(fileURLWithPath: resourcePath).appendingPathComponent("python_site", isDirectory: true))
        }

        siteCandidates.append(
            bundleURL
                .appendingPathComponent("Contents", isDirectory: true)
                .appendingPathComponent("Resources", isDirectory: true)
                .appendingPathComponent("python_site", isDirectory: true)
        )

        siteCandidates.append(
            bundleURL
                .appendingPathComponent("Contents", isDirectory: true)
                .appendingPathComponent("Resources", isDirectory: true)
                .appendingPathComponent("MarcutApp_MarcutApp.bundle", isDirectory: true)
                .appendingPathComponent("python_site", isDirectory: true)
        )

        // Production build: nested Resources/Resources/python_site
        siteCandidates.append(
            bundleURL
                .appendingPathComponent("Contents", isDirectory: true)
                .appendingPathComponent("Resources", isDirectory: true)
                .appendingPathComponent("Resources", isDirectory: true)
                .appendingPathComponent("python_site", isDirectory: true)
        )

        for siteCandidate in siteCandidates {
            if fileManager.fileExists(atPath: siteCandidate.path) {
                pyPaths.append(siteCandidate.path)
                break
            }
        }

        // Second priority: framework site-packages
        if fileManager.fileExists(atPath: sitePackagesPath.path) {
            pyPaths.append(sitePackagesPath.path)
        }

        // Third priority: standard library
        pyPaths.append(stdlibPath.path)

        return PythonRuntimeConfig(
            source: .beewareFramework,
            libPath: pythonLib.path,
            pyHome: pythonVersionDir.path,
            pyPaths: pyPaths
        )
    }


    private static func sanitizeProcessEnvironment(logger: (String) -> Void) {
        let keysToUnset = [
            "PYTHONHOME",
            "PYTHONPATH",
            "PYTHONSTARTUP",
            "PYTHONEXECUTABLE",
            "PYTHONUSERBASE",
            "PYTHONWARNINGS",
            "PYTHONNOUSERSITE",
            "PYTHONINSPECT",
            "PYENV_VERSION",
            "PYENV_ROOT",
            "CONDA_PREFIX",
            "CONDA_DEFAULT_ENV",
            "VIRTUAL_ENV"
        ]

        for key in keysToUnset {
            if getenv(key) != nil {
                unsetenv(key)
                logger("PK_SANITIZE_ENV_UNSET: \(key)")
            }
        }

        // Isolate temporary directory
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent("marcut_py", isDirectory: true)
        do {
            // Startup Wipe: Always clean up previous session/crash data
            if FileManager.default.fileExists(atPath: tempDir.path) {
                try? FileManager.default.removeItem(at: tempDir)
                logger("PK_SANITIZE_ENV_TMPDIR_WIPE_STARTUP: \(tempDir.path)")
            }

            try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true, attributes: nil)
            setenv("TMPDIR", tempDir.path, 1)
            logger("PK_SANITIZE_ENV_TMPDIR_SET: \(tempDir.path)")
        } catch {
            logger("PK_SANITIZE_ENV_TMPDIR_ERROR: \(error)")
        }
    }

    @discardableResult
    public static func initialize(logger: (String) -> Void) throws -> PythonRuntimeConfig {
        let startTime = Date()
        let totalTimeout: TimeInterval = 30.0  // 30s total

        func checkTimeout(step: String) throws {
            let elapsed = Date().timeIntervalSince(startTime)
            if elapsed > totalTimeout {
                throw PythonInitError.timeout("Total timeout exceeded (\(elapsed)s > \(totalTimeout)s) at step: \(step)")
            }
        }

        logger("PK_INIT_START")
        sanitizeProcessEnvironment(logger: logger)
        try checkTimeout(step: "locate")

        guard let cfg = locateFramework() else {
            throw PythonInitError.notFound
        }

        logger("PK_FRAMEWORK_FOUND: \(cfg.source.rawValue) lib=\(cfg.libPath)")
        logger("PK_PYTHONHOME: \(cfg.pyHome)")
        logger("PK_PYTHONPATH: \(cfg.pyPaths.joined(separator: ":"))")
        try checkTimeout(step: "env_setup")

        // Env setup with timeout check
        setenv("PYTHONHOME", cfg.pyHome, 1)
        let path = cfg.pyPaths.joined(separator: ":")
        setenv("PYTHONPATH", path, 1)
        setenv("PYTHONNOUSERSITE", "1", 1)
        setenv("PYTHONDONTWRITEBYTECODE", "1", 1)

        logger("PK_ENV_SET")
        try checkTimeout(step: "library_load")

        // Load libpython with timeout
        PythonLibrary.useLibrary(at: cfg.libPath)

        logger("PK_LIB_LOADED")
        try checkTimeout(step: "smoke_test")

        // Smoke test with timeout - fail fast if Python can't be initialized
        do {
            let sys = try Python.attemptImport("sys")
            _ = sys.version
            logger("PK_IMPORT_OK")
        } catch {
            throw PythonInitError.loadFailed("Python import test failed: \(error)")
        }

        let elapsed = Date().timeIntervalSince(startTime)
        logger("PK_INIT_COMPLETE: \(String(format: "%.2f", elapsed))s")

        return cfg
    }

    public static func cleanupTempDir(logger: (String) -> Void = { _ in }) {
        let tempDir = FileManager.default.temporaryDirectory.appendingPathComponent("marcut_py", isDirectory: true)
        do {
            if FileManager.default.fileExists(atPath: tempDir.path) {
                try FileManager.default.removeItem(at: tempDir)
                // Re-create it immediately so it's ready for next use, or just leave it gone? 
                // Leaving it gone is fine, but if we run another job, does it need it?
                // The environment variable TMPDIR is still set to this path for the process.
                // It is safer to re-create the empty directory so subsequent calls don't fail if they assume existence.
                try FileManager.default.createDirectory(at: tempDir, withIntermediateDirectories: true, attributes: nil)
                logger("PK_CLEANUP_TEMP: Wiped and recreated \(tempDir.path)")
            }
        } catch {
            logger("PK_CLEANUP_TEMP_ERROR: \(error)")
        }
    }
}

public final class PythonKitRunner {
    let logger: (String) -> Void
    private let cfg: PythonRuntimeConfig
    private let worker: PythonWorkerThread
    private var externalCancellationChecker: (() -> Bool)?
    private let stateLock = NSLock()
    private var isCancellationRequested = false
    private var activeRunToken = UUID()
    private var ruleFilterValue: String = RedactionRule.serializedList(from: RedactionRule.defaultSelection)

    init(logger: @escaping (String) -> Void) throws {
        self.logger = logger
        self.worker = PythonWorkerThread()
        worker.start()
        worker.waitUntilReady()

        let config: PythonRuntimeConfig = try worker.perform {
            try PythonRuntime.initialize(logger: logger)
        }
        self.cfg = config

        do {
            try worker.perform {
                try Self.warmupPythonEnvironment(logger: logger)
            }
            logger("PK_WARMUP_OK")
            propagateRuleFilter(ruleFilterValue)
        } catch {
            logger("PK_WARMUP_ERROR: \(error)")
            throw error
        }
    }

    deinit {
        worker.stop()
    }

    func cancelCurrentOperation(source: String = "unknown") {
        stateLock.lock()
        isCancellationRequested = true
        stateLock.unlock()

        worker.performAsync { [logger] in
            if Py_IsInitialized() != 0 {
                PyErr_SetInterrupt()
            }
            logger("PK_CANCEL_REQUESTED: source=\(source)")
        }
    }

    func clearCancellationRequest() {
        stateLock.lock()
        let wasCancelled = isCancellationRequested
        isCancellationRequested = false
        stateLock.unlock()
        if wasCancelled {
            logger("PK_CANCEL_CLEARED: was_cancelled=true")
        }
    }

    private func startNewRunToken() -> UUID {
        stateLock.lock()
        let token = UUID()
        activeRunToken = token
        isCancellationRequested = false
        stateLock.unlock()
        return token
    }

    private func currentRunToken() -> UUID {
        stateLock.lock()
        let token = activeRunToken
        stateLock.unlock()
        return token
    }

    private func isActiveRunToken(_ token: UUID) -> Bool {
        stateLock.lock()
        let match = activeRunToken == token
        stateLock.unlock()
        return match
    }

    func updateRuleFilter(_ rules: Set<RedactionRule>) {
        let serialized = RedactionRule.serializedList(from: rules)
        ruleFilterValue = serialized
        propagateRuleFilter(serialized)
    }

    private func propagateRuleFilter(_ serialized: String) {
        // Ensure future child processes inherit the latest filter
        setenv("MARCUT_RULE_FILTER", serialized, 1)
        logger("PK_RULE_FILTER_SET: \(serialized)")

        // Also push the change into the already-initialized Python interpreter.
        worker.performAsync { [serialized, logger] in
            guard Py_IsInitialized() != 0 else {
                logger("PK_RULE_FILTER_SYNC_SKIPPED: interpreter not initialized")
                return
            }

            let state = PyGILState_Ensure()
            defer { PyGILState_Release(state) }

            do {
                let os = try Python.attemptImport("os")
                os.environ["MARCUT_RULE_FILTER"] = PythonObject(serialized)
                logger("PK_RULE_FILTER_OS_SET: \(serialized)")
            } catch {
                logger("PK_RULE_FILTER_OS_ERROR: \(error)")
            }
        }
    }

    private func cancellationRequested() -> Bool {
        stateLock.lock()
        let flag = isCancellationRequested
        stateLock.unlock()
        if flag {
            logger("PK_CANCEL_CHECK: internal_flag=true")
            return true
        }
        if let externalCancellationChecker, externalCancellationChecker() {
            logger("PK_CANCEL_CHECK: external_checker=true")
            return true
        }
        return false
    }

    private func checkCancellation() throws {
        if cancellationRequested() {
            logger("PK_CANCEL_THROWING: CancellationError")
            throw CancellationError()
        }
    }

    private static func warmupPythonEnvironment(logger: @escaping (String) -> Void) throws {
        let warmupStart = Date()
        logger("PK_WARMUP_IMPORT_CORE_START")

        if Py_IsInitialized() == 0 {
            Py_Initialize()
        }
        let state = PyGILState_Ensure()
        defer { PyGILState_Release(state) }

        let modules = [
            "sys",
            "os",
            "lxml",
            "docx",
            "marcut.pipeline"
        ]

        for name in modules {
            let label = name.replacingOccurrences(of: ".", with: "_").uppercased()
            logger("PK_WARMUP_IMPORT_\(label)_BEGIN")
            do {
                _ = try Python.attemptImport(name)
                logger("PK_WARMUP_IMPORT_\(label)_DONE")
            } catch {
                logger("PK_WARMUP_IMPORT_\(label)_ERROR: \(error)")
                throw error
            }
        }

        let elapsed = Date().timeIntervalSince(warmupStart)
        logger("PK_WARMUP_IMPORT_CORE_END: \(String(format: "%.2f", elapsed))s")
    }

    private func withGIL<T>(_ operation: () throws -> T) rethrows -> T {
        if Py_IsInitialized() == 0 {
            Py_Initialize()
        }
        let threadID = pthread_mach_thread_np(pthread_self())
        logger("PK_GIL_REQUEST: thread=\(threadID)")
        let state = PyGILState_Ensure()
        logger("PK_GIL_ACQUIRED: thread=\(threadID)")
        defer {
            PyGILState_Release(state)
            logger("PK_GIL_RELEASED: thread=\(threadID)")
        }
        return try operation()
    }

    private func withTimeout<T>(
        operation: String,
        stepTimeout: TimeInterval = 20.0,
        totalTimeout: TimeInterval = 60.0,
        startTime: Date,
        disableTimeouts: Bool = false,
        work: () throws -> T
    ) throws -> T {
        let operationKey = operation.uppercased()
        let runToken = currentRunToken()
        try checkCancellation()
        let elapsed = Date().timeIntervalSince(startTime)
        let timersEnabled = !disableTimeouts

        if timersEnabled && elapsed > totalTimeout {
            throw PythonInitError.timeout("Total timeout exceeded (\(elapsed)s > \(totalTimeout)s) during: \(operation)")
        }

        if pythonSetupTracingEnabled() || operationKey == "ENV_SETUP" {
            let configDescription = timersEnabled
                ? "step=\(String(format: "%.0f", stepTimeout))s total=\(String(format: "%.0f", totalTimeout))s"
                : "timeouts=disabled"
            logger("PK_\(operationKey)_CONFIG: \(configDescription)")
        }

        logger("PK_\(operationKey)_START")
        let operationStart = Date()

        // Execute work with a cancellable timeout
        let result: T
        var timeoutTask: Task<Void, Never>?
        if timersEnabled {
            timeoutTask = scheduleTimeout(for: operationKey, seconds: stepTimeout, runToken: runToken)
        }
        defer { timeoutTask?.cancel() }

        do {
            logger("PK_\(operationKey)_GIL_ENTER")
            result = try withGIL {
                logger("PK_\(operationKey)_GIL_ACQUIRED")
                try checkCancellation()
                logger("PK_\(operationKey)_CHECKED_CANCELLATION")
                logger("PK_\(operationKey)_WORK_BEGIN")
                let value = try work()
                logger("PK_\(operationKey)_WORK_END")
                return value
            }
            logger("PK_\(operationKey)_GIL_EXIT")
        } catch is CancellationError {
            let operationElapsed = Date().timeIntervalSince(operationStart)
            logger("PK_\(operationKey)_CANCELLED: \(String(format: "%.2f", operationElapsed))s")
            throw CancellationError()
        } catch {
            let operationElapsed = Date().timeIntervalSince(operationStart)
            logger("PK_\(operationKey)_ERROR: \(error) (\(String(format: "%.2f", operationElapsed))s)")
            throw error
        }

        let operationElapsed = Date().timeIntervalSince(operationStart)
        if timersEnabled && operationElapsed > stepTimeout {
            logger("PK_\(operationKey)_TIMEOUT: \(String(format: "%.2f", operationElapsed))s > \(stepTimeout)s")
            throw PythonInitError.timeout("Step timeout: \(operation) took \(operationElapsed)s > \(stepTimeout)s")
        }

        try checkCancellation()
        logger("PK_\(operationKey)_OK: \(String(format: "%.2f", operationElapsed))s")
        return result
    }

    func runRulesMock(
        inputPath: String,
        outputPath: String,
        reportPath: String,
        debug: Bool,
        cancellationChecker: @escaping () -> Bool
    ) -> PythonRunOutcome {
        let startTime = Date()
        _ = startNewRunToken()
        logger("PK_RULES_MOCK_START")

        if !PythonRuntime.fastEnvironmentCheck(logger: logger) {
            logger("PK_RULES_MOCK_ERROR: Fast environment check failed")
            return .failure
        }

        do {
            try checkCancellation()
            // Phase 1: Environment setup
            let envSetupStepTimeout = PythonTimeoutOverrides.step(for: "ENV_SETUP", default: 300.0)
            let envSetupTotalTimeout = PythonTimeoutOverrides.total(for: "ENV_SETUP", default: 600.0)
            let envSetupDisableTimeouts = PythonTimeoutOverrides.disable(for: "ENV_SETUP")
            let py_os = try withTimeout(
                operation: "env_setup",
                stepTimeout: envSetupStepTimeout,
                totalTimeout: envSetupTotalTimeout,
                startTime: startTime,
                disableTimeouts: envSetupDisableTimeouts
            ) {
                logger("PK_ENV_SETUP_IMPORT_OS_BEGIN")
                let module = try Python.attemptImport("os")
                logger("PK_ENV_SETUP_IMPORT_OS_DONE")
                return module
            }
            logger("PK_ENV_SETUP_ENV_VARS_APPLY")
            py_os.environ["NO_COLOR"] = "1"
            logger("PK_ENV_SETUP_READY")

            // Phase 2: Heavy imports
            let importsStepTimeout = PythonTimeoutOverrides.step(for: "IMPORTS", default: 180.0)
            let importsTotalTimeout = PythonTimeoutOverrides.total(for: "IMPORTS", default: 600.0)
            let importsDisableTimeouts = PythonTimeoutOverrides.disable(for: "IMPORTS")
            try withTimeout(
                operation: "imports",
                stepTimeout: importsStepTimeout,
                totalTimeout: importsTotalTimeout,
                startTime: startTime,
                disableTimeouts: importsDisableTimeouts
            ) {
                _ = try? Python.attemptImport("lxml")
                _ = try? Python.attemptImport("docx")
                return ()
            }

            // Phase 3: Pipeline import
            let pipelineStepTimeout = PythonTimeoutOverrides.step(for: "PIPELINE_IMPORT", default: 180.0)
            let pipelineTotalTimeout = PythonTimeoutOverrides.total(for: "PIPELINE_IMPORT", default: 600.0)
            let pipelineDisableTimeouts = PythonTimeoutOverrides.disable(for: "PIPELINE_IMPORT")
            let pipeline = try withTimeout(
                operation: "pipeline_import",
                stepTimeout: pipelineStepTimeout,
                totalTimeout: pipelineTotalTimeout,
                startTime: startTime,
                disableTimeouts: pipelineDisableTimeouts
            ) {
                try Python.attemptImport("marcut.pipeline")
            }

            try checkCancellation()
            // Phase 4: Processing
            let processingStepTimeout = PythonTimeoutOverrides.step(for: "PROCESSING", default: 180.0)
            let processingTotalTimeout = PythonTimeoutOverrides.total(for: "PROCESSING", default: 1200.0)
            let processingDisableTimeouts = PythonTimeoutOverrides.disable(for: "PROCESSING")
            let code: Int = try withTimeout(
                operation: "processing",
                stepTimeout: processingStepTimeout,
                totalTimeout: processingTotalTimeout,
                startTime: startTime,
                disableTimeouts: processingDisableTimeouts
            ) {
                try checkCancellation()
                let rawResult = pipeline.run_redaction(
                    input_path: inputPath,
                    output_path: outputPath,
                    report_path: reportPath,
                    mode: "strict",
                    backend: "mock",
                    model_id: "mock",
                    llama_gguf: "",
                    threads: 4,
                    chunk_tokens: 500,
                    overlap: 120,
                    temperature: 0.1,
                    seed: 42,
                    do_qa: true,
                    debug: debug
                )
                // Handle tuple return (code, timings)
                if Bool(Python.isinstance(rawResult, Python.tuple)) == true {
                    return Int(rawResult[0]) ?? 1
                }
                return Int(rawResult) ?? 1
            }

            let totalElapsed = Date().timeIntervalSince(startTime)
            logger("PK_RULES_MOCK_COMPLETE: exit_code=\(code) total=\(String(format: "%.2f", totalElapsed))s")
            return code == 0 ? .success : .failure
        } catch is CancellationError {
            let totalElapsed = Date().timeIntervalSince(startTime)
            logger("PK_RULES_MOCK_CANCELLED total=\(String(format: "%.2f", totalElapsed))s")
            return .cancelled
        } catch {
            let totalElapsed = Date().timeIntervalSince(startTime)
            logger("PK_RULES_MOCK_ERROR: \(error) total=\(String(format: "%.2f", totalElapsed))s")
            if case PythonError.exception(let exc, _) = error,
               let description = String(exc),
               description.contains("KeyboardInterrupt") {
                return .cancelled
            }
            return .failure
        }
    }

    func runEnhancedOllama(
        inputPath: String,
        outputPath: String,
        reportPath: String,
        model: String,
        debug: Bool,
        mode: String,
        chunkTokens: Int = 500,
        overlap: Int = 120,
        temperature: Double = 0.1,
        seed: Int = 42,
        processingStepTimeout: TimeInterval? = nil,
        cancellationChecker: @escaping () -> Bool,
        heartbeat: ((PythonRunnerProgressUpdate) -> Void)? = nil
    ) -> PythonRunOutcome {
        let startTime = Date()
        _ = startNewRunToken()
        let normalizedMode = mode.lowercased()
        let needsOllama = !(["rules", "rules-only", "strict"].contains(normalizedMode))
        logger("PK_ENHANCED_OLLAMA_START: model=\(model) mode=\(normalizedMode) needs_ollama=\(needsOllama)")

        // Skip environment check for rules-only mode
        if needsOllama && !PythonRuntime.fastEnvironmentCheck(logger: logger) {
            let host = PythonRuntime.resolvedOllamaHost()
            logger("PK_ENHANCED_OLLAMA_ERROR: Fast environment check failed host=\(host)")
            return .failure
        }

        do {
            try checkCancellation()
            // Phase 1: Environment setup (configurable timeout)
            let envSetupStepTimeout = PythonTimeoutOverrides.step(for: "ENV_SETUP", default: 300.0)
            let envSetupTotalTimeout = PythonTimeoutOverrides.total(for: "ENV_SETUP", default: 600.0)
            let envSetupDisableTimeouts = PythonTimeoutOverrides.disable(for: "ENV_SETUP")
            let py_os = try withTimeout(
                operation: "env_setup",
                stepTimeout: envSetupStepTimeout,
                totalTimeout: envSetupTotalTimeout,
                startTime: startTime,
                disableTimeouts: envSetupDisableTimeouts
            ) {
                logger("PK_ENV_SETUP_IMPORT_OS_BEGIN")
                let module = try Python.attemptImport("os")
                logger("PK_ENV_SETUP_IMPORT_OS_DONE")
                return module
            }
        logger("PK_ENV_SETUP_ENV_VARS_APPLY")
        let host = PythonRuntime.resolvedOllamaHost()
        py_os.environ["OLLAMA_HOST"] = PythonObject(host)
        py_os.environ["MARCUT_OLLAMA_HOST"] = PythonObject(host)
        logger("PK_ENV_SETUP_RESOLVED_HOST: \(host)")
        py_os.environ["HTTP_PROXY"] = ""
        py_os.environ["HTTPS_PROXY"] = ""
        py_os.environ["ALL_PROXY"] = ""
        py_os.environ["NO_PROXY"] = "127.0.0.1,localhost"
        py_os.environ["http_proxy"] = ""
            py_os.environ["https_proxy"] = ""
            py_os.environ["all_proxy"] = ""
            py_os.environ["no_proxy"] = "127.0.0.1,localhost"
            py_os.environ["NO_COLOR"] = "1"
           logger("PK_ENV_SETUP_READY")

            // Phase 2: Heavy imports
            let importsStepTimeout = PythonTimeoutOverrides.step(for: "IMPORTS", default: 180.0)
            let importsTotalTimeout = PythonTimeoutOverrides.total(for: "IMPORTS", default: 600.0)
            let importsDisableTimeouts = PythonTimeoutOverrides.disable(for: "IMPORTS")
            try withTimeout(
                operation: "imports",
                stepTimeout: importsStepTimeout,
                totalTimeout: importsTotalTimeout,
                startTime: startTime,
                disableTimeouts: importsDisableTimeouts
            ) {
                _ = try? Python.attemptImport("lxml")
                _ = try? Python.attemptImport("docx")
                return ()
            }

            // Phase 3: Pipeline import
            let pipelineStepTimeout = PythonTimeoutOverrides.step(for: "PIPELINE_IMPORT", default: 180.0)
            let pipelineTotalTimeout = PythonTimeoutOverrides.total(for: "PIPELINE_IMPORT", default: 600.0)
            let pipelineDisableTimeouts = PythonTimeoutOverrides.disable(for: "PIPELINE_IMPORT")
            let pipeline = try withTimeout(
                operation: "pipeline_import",
                stepTimeout: pipelineStepTimeout,
                totalTimeout: pipelineTotalTimeout,
                startTime: startTime,
                disableTimeouts: pipelineDisableTimeouts
            ) {
                try Python.attemptImport("marcut.pipeline")
            }

            try checkCancellation()
            // Phase 4: Enhanced processing (longer timeout for LLM)
            let defaultProcessingStepTimeout = PythonTimeoutOverrides.step(for: "PROCESSING", default: 600.0)
            let resolvedProcessingStepTimeout = processingStepTimeout ?? defaultProcessingStepTimeout
            let processingTotalTimeout = max(
                PythonTimeoutOverrides.total(for: "PROCESSING", default: 3600.0),
                resolvedProcessingStepTimeout
            )
            let processingDisableTimeouts = PythonTimeoutOverrides.disable(for: "PROCESSING")
            let code: Int = try withTimeout(
                operation: "processing",
                stepTimeout: resolvedProcessingStepTimeout,
                totalTimeout: processingTotalTimeout,
                startTime: startTime,
                disableTimeouts: processingDisableTimeouts
            ) {
                try checkCancellation()
                let progressCallback: PythonObject = {
                    guard let heartbeat = heartbeat else { return Python.None }
                    let function = PythonFunction { args, kwargs in
                        guard let firstArg = args.first else {
                            return Python.None
                        }

                        // Rich ProgressUpdate object path
                        if args.count == 1 {
                            let update = firstArg
                            let identifier = update.phase.toOptionalString()?.nilIfEmptyOrNone()
                            let displayName = update.phase_name.toOptionalString()?.nilIfEmptyOrNone()
                            let phaseProgress = update.phase_progress.toOptionalDouble()
                            let overall = update.overall_progress.toOptionalDouble()
                            let message = update.message.toOptionalString()?.nilIfEmptyOrNone()
                            let payload = PythonRunnerProgressUpdate(
                                phaseIdentifier: identifier,
                                phaseDisplayName: displayName,
                                phaseProgress: phaseProgress,
                                overallProgress: overall,
                                message: message
                            )
                            heartbeat(payload)
                        } else {
                            let chunk = Int(args[0]) ?? 0
                            let total = args.count > 1 ? Int(args[1]) ?? 0 : 0
                            let message = args.count > 2 ? args[2].toOptionalString()?.nilIfEmptyOrNone() : nil
                            heartbeat(
                                PythonRunnerProgressUpdate(
                                    chunk: chunk,
                                    total: total,
                                    message: message
                                )
                            )
                        }
                        return Python.None
                    }
                    return PythonObject(function)
                }()
                let rawResult = pipeline.run_redaction(
                    input_path: inputPath,
                    output_path: outputPath,
                    report_path: reportPath,
                    mode: mode,
                    model_id: model,
                    chunk_tokens: chunkTokens,
                    overlap: overlap,
                    temperature: temperature,
                    seed: seed,
                    debug: debug,
                    progress_callback: progressCallback
                )
                // Handle tuple return (code, timings)
                if Bool(Python.isinstance(rawResult, Python.tuple)) == true {
                    return Int(rawResult[0]) ?? 1
                }
                return Int(rawResult) ?? 1
            }

            let totalElapsed = Date().timeIntervalSince(startTime)
            logger("PK_ENHANCED_OLLAMA_COMPLETE: exit_code=\(code) total=\(String(format: "%.2f", totalElapsed))s")
            return code == 0 ? .success : .failure
        } catch is CancellationError {
            let totalElapsed = Date().timeIntervalSince(startTime)
            logger("PK_ENHANCED_OLLAMA_CANCELLED total=\(String(format: "%.2f", totalElapsed))s")
            return .cancelled
        } catch {
            let totalElapsed = Date().timeIntervalSince(startTime)
            if case PythonError.exception(let exc, _) = error {
                let typeName = (exc.__class__.__name__).toOptionalString() ?? "UnknownPythonException"
                let message = exc.toOptionalString() ?? "n/a"
                var tracebackSummary = ""
                if let tracebackModule = try? Python.attemptImport("traceback") {
                    let formatted = tracebackModule.format_exception(exc.__class__, exc, exc.__traceback__)
                    let parts = Array(formatted).compactMap { String($0) }
                    let joined = parts.joined()
                    tracebackSummary = String(joined.prefix(2000))
                }
                logger("PK_ENHANCED_OLLAMA_PYERROR: type=\(typeName) message=\(message) traceback=\(tracebackSummary)")
            }
            logger("PK_ENHANCED_OLLAMA_ERROR: \(error) total=\(String(format: "%.2f", totalElapsed))s")
            if case PythonError.exception(let exc, _) = error,
               let description = String(exc),
               description.contains("KeyboardInterrupt") {
                return .cancelled
            }
            return .failure
        }
    }

    private func scheduleTimeout(for operationKey: String, seconds: TimeInterval, runToken: UUID) -> Task<Void, Never>? {
        guard seconds > 0 else { return nil }
        // Capture handler to avoid Sendable warnings
        let handler = self.handleTimeoutTrigger
        return Task.detached {
            do {
                try await Task.sleep(nanoseconds: UInt64(seconds * 1_000_000_000))
                try Task.checkCancellation()
                await MainActor.run {
                    handler(operationKey, runToken)
                }
            } catch {
                // If the task was cancelled or sleep failed, just exit.
            }
        }
    }

    private func handleTimeoutTrigger(_ operationKey: String, _ runToken: UUID) {
        guard isActiveRunToken(runToken) else {
            logger("PK_\(operationKey)_TIMEOUT_IGNORED: stale run")
            return
        }
        logger("PK_\(operationKey)_TIMEOUT_TRIGGER")
        cancelCurrentOperation(source: "timeout_\(operationKey)")
    }

    func runEnhancedOllamaWithProgress(
        inputPath: String,
        outputPath: String,
        reportPath: String,
        model: String,
        debug: Bool,
        mode: String,
        chunkTokens: Int = 500,
        overlap: Int = 120,
        temperature: Double = 0.1,
        seed: Int = 42,
        processingStepTimeout: TimeInterval? = nil,
        cancellationChecker: @escaping () -> Bool
    ) -> (stream: AsyncStream<PythonRunnerProgressUpdate>, result: Task<PythonRunOutcome, Never>) {
        let streamContinuation = AsyncStream<PythonRunnerProgressUpdate>.makeStream()

        // Run processing off the main actor to avoid UI blocking
        let processingTask = Task.detached(priority: .userInitiated) { [weak self] in
            guard let self else { return PythonRunOutcome.failure }
            let outcome: PythonRunOutcome
            do {
                outcome = try self.worker.perform {
                    self.externalCancellationChecker = cancellationChecker
                    defer {
                        self.externalCancellationChecker = nil
                        self.clearCancellationRequest()
                    }
                    return self.runEnhancedOllama(
                        inputPath: inputPath,
                        outputPath: outputPath,
                        reportPath: reportPath,
                        model: model,
                        debug: debug,
                        mode: mode,
                        chunkTokens: chunkTokens,
                        overlap: overlap,
                        temperature: temperature,
                        seed: seed,
                        processingStepTimeout: processingStepTimeout,
                        cancellationChecker: cancellationChecker,
                        heartbeat: { update in
                            DebugLogger.shared.log(
                                "💓 Heartbeat called: phase=\(update.phaseIdentifier ?? "n/a") progress=\(String(format: "%.2f", update.phaseProgress ?? -1)) chunk=\(update.chunk ?? -1)/\(update.total ?? -1) msg=\(update.message ?? "nil")",
                                component: "PythonKitBridge"
                            )
                            streamContinuation.continuation.yield(update)
                        }
                    )
                }
            } catch {
                self.logger("PK_ENHANCED_OLLAMA_EXCEPTION: \(error)")
                streamContinuation.continuation.finish()
                return .failure
            }

            streamContinuation.continuation.finish()
            return outcome
        }

        return (stream: streamContinuation.stream, result: processingTask)
    }

    func runRulesWithProgress(
        inputPath: String,
        outputPath: String,
        reportPath: String,
        debug: Bool,
        cancellationChecker: @escaping () -> Bool
    ) -> (stream: AsyncStream<(chunk: Int, total: Int, message: String?)>, result: Task<PythonRunOutcome, Never>) {
        let streamContinuation = AsyncStream<(chunk: Int, total: Int, message: String?)>.makeStream()

        // Run processing on background thread to avoid blocking UI
        let processingTask = Task.detached(priority: .userInitiated) { [weak self] in
            guard let self else { return PythonRunOutcome.failure }
            // Simulated progress for deterministic mode
            let totalSteps = 5
            for step in 1...totalSteps {
                if cancellationChecker() {
                    streamContinuation.continuation.finish()
                    return .cancelled
                }
                let message = step == totalSteps ? "Finalizing rules-based redaction..." : "Applying redaction rules..."
                streamContinuation.continuation.yield((chunk: step, total: totalSteps, message: message))
                try? await Task.sleep(nanoseconds: 200_000_000)
            }

            let outcome: PythonRunOutcome
            do {
                outcome = try self.worker.perform {
                    self.externalCancellationChecker = cancellationChecker
                    defer {
                        self.externalCancellationChecker = nil
                        self.clearCancellationRequest()
                    }
                    return self.runRulesMock(
                        inputPath: inputPath,
                        outputPath: outputPath,
                        reportPath: reportPath,
                        debug: debug,
                        cancellationChecker: cancellationChecker
                    )
                }
            } catch {
                self.logger("PK_RULES_EXCEPTION: \(error)")
                streamContinuation.continuation.finish()
                return .failure
            }

            streamContinuation.continuation.finish()
            return outcome
        }

        return (stream: streamContinuation.stream, result: processingTask)
    }

func analyzeDocument(inputPath: String) -> PythonDocumentAnalysis? {
        externalCancellationChecker = nil
        clearCancellationRequest()
        let startTime = Date()
        logger("PK_ANALYZE_START")

        if !PythonRuntime.fastEnvironmentCheck(logger: logger) {
            logger("PK_ANALYZE_ERROR: Fast environment check failed")
            return nil
        }

        do {
            let analysis = try withTimeout(operation: "analyze", startTime: startTime) { () -> PythonDocumentAnalysis in
                let docxIO = try Python.attemptImport("marcut.docx_io")
                let doc = docxIO.DocxMap.load(inputPath)
                let textObject = PythonObject(doc.text)
                let swiftText = String(textObject) ?? ""
                let charCount = swiftText.count
                let words = swiftText.split(whereSeparator: { $0.isWhitespace || $0.isNewline }).count
                let paragraphs = max(1, swiftText.split(separator: "\n", omittingEmptySubsequences: false).count)
                return PythonDocumentAnalysis(
                    wordCount: words,
                    paragraphCount: paragraphs,
                    characterCount: charCount
                )
            }

            let totalElapsed = Date().timeIntervalSince(startTime)
            logger("PK_ANALYZE_OK total=\(String(format: "%.2f", totalElapsed))s")
            return analysis
        } catch {
            let totalElapsed = Date().timeIntervalSince(startTime)
            logger("PK_ANALYZE_ERROR: \(error) total=\(String(format: "%.2f", totalElapsed))s")
            return nil
        }
    }
    
    /// Scrub metadata only - no rules or LLM redaction
    /// This is a fast operation that uses the Python pipeline's scrub_metadata_only function
    func scrubMetadataOnlyAsync(
        inputPath: String,
        outputPath: String
    ) async throws -> (success: Bool, error: String?, report: [String: Any]?) {
        let startTime = Date()
        logger("PK_METADATA_SCRUB_START: \(inputPath)")
        
        // Perform Python call on worker thread
        let result: (Bool, String?, [String: Any]?) = try worker.perform { [logger] in
            let state = PyGILState_Ensure()
            defer { PyGILState_Release(state) }

            let signalStatus = PyErr_CheckSignals()
            if signalStatus != 0 {
                PyErr_Clear()
                logger("PK_METADATA_SCRUB_SIGNAL_CLEARED")
            } else {
                PyErr_Clear()
            }
            
            do {
                let pipeline = try Python.attemptImport("marcut.pipeline")
                let rawResult = pipeline.scrub_metadata_only(
                    input_path: inputPath,
                    output_path: outputPath,
                    debug: false
                )
                
                // Parse tuple result (success: bool, error: str, report: dict)
                if Bool(Python.isinstance(rawResult, Python.tuple)) == true {
                    let success = Bool(rawResult[0]) == true
                    let errorMsg = String(rawResult[1]) ?? ""
                    
                    // Extract report dictionary (full payload with groups) via JSON serialization
                    var reportDict: [String: Any]? = nil
                    let pyReport = rawResult[2]
                    if Bool(Python.isinstance(pyReport, Python.dict)) == true {
                        do {
                            let json = try Python.attemptImport("json")
                            let jsonString = String(json.dumps(pyReport)) ?? ""
                            if let data = jsonString.data(using: .utf8),
                               let obj = try JSONSerialization.jsonObject(with: data) as? [String: Any] {
                                reportDict = obj
                            }
                        } catch {
                            reportDict = nil
                        }
                    }
                    
                    return (success, errorMsg.isEmpty ? nil : errorMsg, reportDict)
                }
                return (false, "Unexpected result from Python", nil)
            } catch {
                logger("PK_METADATA_SCRUB_PYTHON_ERROR: \(error)")
                return (false, "Python error: \(error)", nil)
            }
        }
        
        let totalElapsed = Date().timeIntervalSince(startTime)
        if result.0 {
            logger("PK_METADATA_SCRUB_OK total=\(String(format: "%.2f", totalElapsed))s")
            if let report = result.2, let summary = report["summary"] as? [String: Any] {
                let cleaned = summary["total_cleaned"] as? Int ?? 0
                let preserved = summary["total_preserved"] as? Int ?? 0
                let embedded = summary["embedded_docs_count"] as? Int ?? 0
                logger("PK_METADATA_REPORT: cleaned=\(cleaned) preserved=\(preserved) embedded=\(embedded)")
            }
        } else {
            logger("PK_METADATA_SCRUB_FAILED: \(result.1 ?? "Unknown") total=\(String(format: "%.2f", totalElapsed))s")
        }
        
        return result
    }
}
