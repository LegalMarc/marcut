import AppKit
import Foundation
import UniformTypeIdentifiers

/// Output-directory resolution and report open/save/export collaborator, extracted from
/// `DocumentRedactionViewModel` (`docs/design/view_controller_decomposition.md` §2.1, slice 7).
/// The largest mechanical slice -- mostly `FileManager`/`NSWorkspace`/`NSOpenPanel`/`NSSavePanel`
/// calls keyed off `DocumentItem` URL properties. `metadataReportErrorMessage`/
/// `metadataReportNeedsPermissionRetry`/`reportErrorMessage` stay `@Published` on the view model
/// (set here via the `setGlobalMetadataReportError`/`setGlobalReportError` constructor closures)
/// since they're read directly by `ContentView.swift`; every item-scoped error
/// (`DocumentItem.metadataReportErrorMessage` etc.) is set directly since `DocumentItem` is
/// itself an `ObservableObject` reference passed in, the same way `DocumentShareService` sets
/// `item.errorMessage` directly. The view model keeps thin forwarding methods for every call site
/// -- both its own remaining `processAllDocuments`/`scrubMetadataOnly`/`retryDocument`/
/// `generateMetadataReportsInPlace`/`generateMetadataReport`/`scrubDocumentMetadataOnly` (which
/// stay on the view model until #110/#111) and `ContentView.swift`'s direct calls -- so none
/// of those call sites changed.
@MainActor
final class OutputArtifactManager {
    /// Injected `UserDefaults` suite, mirroring `DocumentRedactionViewModel.defaults`.
    private let defaults: UserDefaults
    /// Resolves the embedded-Python runner, mirroring `DocumentRedactionViewModel.runnerProvider`.
    private let runnerProvider: () -> (any RedactionRunning)?
    /// A live snapshot of `DocumentRedactionViewModel.items`, needed only by
    /// `clearMetadataReportErrorsNeedingPermissionRetry()` to sweep every item's retry flag.
    private let itemsProvider: () -> [DocumentItem]
    /// Applies to the view model's `@Published metadataReportErrorMessage`/
    /// `metadataReportNeedsPermissionRetry` -- the non-item-scoped error slot.
    private let setGlobalMetadataReportError: (String?, Bool) -> Void
    /// Applies to the view model's `@Published reportErrorMessage`.
    private let setGlobalReportError: (String?) -> Void

    init(
        defaults: UserDefaults,
        runnerProvider: @escaping () -> (any RedactionRunning)?,
        itemsProvider: @escaping () -> [DocumentItem],
        setGlobalMetadataReportError: @escaping (String?, Bool) -> Void,
        setGlobalReportError: @escaping (String?) -> Void
    ) {
        self.defaults = defaults
        self.runnerProvider = runnerProvider
        self.itemsProvider = itemsProvider
        self.setGlobalMetadataReportError = setGlobalMetadataReportError
        self.setGlobalReportError = setGlobalReportError
    }

    /// Every other member of this file reads the runner through here, mirroring
    /// `DocumentRedactionViewModel.pythonRunner`.
    private var pythonRunner: (any RedactionRunning)? {
        runnerProvider()
    }

    func metadataReportErrorPayload(for item: DocumentItem,
                                    error: String) -> (message: String, needsPermissionRetry: Bool)
    {
        let lowercased = error.lowercased()
        let isPermissionIssue = lowercased.contains("operation not permitted") ||
            lowercased.contains("permission denied") ||
            lowercased.contains("not authorized") ||
            lowercased.contains("unauthorized")
        if isPermissionIssue {
            return (metadataReportPermissionMessage(for: item), true)
        }
        // `error` here can be raw bridge text (e.g. `"Python error: \(error)"` from
        // `metadataReportOnlyAsync`); callers already log it, so the alert only gets the
        // mapped, friendly message -- see `FailureMessagePresenter`.
        return ("\(item.url.lastPathComponent): \(FailureMessagePresenter.message(forCode: nil))", false)
    }

    func setMetadataReportError(_ message: String, needsPermissionRetry: Bool, item: DocumentItem? = nil) {
        if let item {
            item.metadataReportErrorMessage = message
            item.metadataReportNeedsPermissionRetry = needsPermissionRetry
            return
        }
        setGlobalMetadataReportError(message, needsPermissionRetry)
    }

    func setReportError(_ message: String) {
        setGlobalReportError(message)
    }

    private func metadataReportPermissionMessage(for item: DocumentItem) -> String {
        "\(item.url.lastPathComponent): Couldn't save the metadata report. Retry file access permissions."
    }

    var outputSaveLocationPreference: OutputSaveLocation {
        let rawValue = defaults
            .object(forKey: DefaultsKey.outputSaveLocationPreference.key) as? Int ?? OutputSaveLocation.alwaysAsk
            .rawValue
        return OutputSaveLocation(rawValue: rawValue) ?? .alwaysAsk
    }

    func outputLocationErrorMessage() -> String {
        "Output location unavailable. Retry file access permissions or choose another output location."
    }

    func setOutputAccessError(
        _ message: String,
        isMetadataOperation: Bool,
        needsPermissionRetry: Bool,
        item: DocumentItem? = nil
    ) {
        if isMetadataOperation {
            setMetadataReportError(message, needsPermissionRetry: needsPermissionRetry, item: item)
        } else {
            setReportError(message)
        }
    }

    func resolveTemporaryReportDirectory() -> URL? {
        let fm = FileManager.default
        guard let cacheDir = FileAccessCoordinator.shared.metadataReportCacheDirectory() else {
            DebugLogger.shared.log(
                "❌ Failed to resolve metadata report cache directory",
                component: "DocumentRedactionViewModel"
            )
            return nil
        }
        do {
            try fm.createDirectory(at: cacheDir, withIntermediateDirectories: true)
            try? fm.setAttributes([.posixPermissions: NSNumber(value: Int16(0o700))], ofItemAtPath: cacheDir.path)
            return cacheDir
        } catch {
            DebugLogger.shared.log(
                "❌ Failed to create temporary report directory: \(error)",
                component: "DocumentRedactionViewModel"
            )
            return nil
        }
    }

    func resolveOutputDirectory(
        for item: DocumentItem,
        baseDestination: URL?,
        isMetadataOperation: Bool
    ) async -> URL? {
        let preference = outputSaveLocationPreference
        let estimatedBytesNeeded = estimatedOutputBytes(for: item, isMetadataOperation: isMetadataOperation)
        switch preference {
        case .alwaysAsk:
            guard let baseDestination else {
                setOutputAccessError(
                    outputLocationErrorMessage(),
                    isMetadataOperation: isMetadataOperation,
                    needsPermissionRetry: false,
                    item: item
                )
                return nil
            }
            if let error = validateDestination(baseDestination, estimatedBytesNeeded: estimatedBytesNeeded) {
                setOutputAccessError(
                    error,
                    isMetadataOperation: isMetadataOperation,
                    needsPermissionRetry: false,
                    item: item
                )
                return nil
            }
            return baseDestination
        case .sameAsOriginal:
            let destination = item.url.deletingLastPathComponent()
            if let error = validateDestination(destination, estimatedBytesNeeded: estimatedBytesNeeded) {
                setOutputAccessError(
                    error,
                    isMetadataOperation: isMetadataOperation,
                    needsPermissionRetry: false,
                    item: item
                )
                return nil
            }
            return destination
        case .downloads:
            let granted = await FileAccessCoordinator.shared.requestDownloadsAccessForReports()
            guard granted, let downloadsURL = FileAccessCoordinator.shared.downloadsDirectoryForReports() else {
                setOutputAccessError(
                    outputLocationErrorMessage(),
                    isMetadataOperation: isMetadataOperation,
                    needsPermissionRetry: true,
                    item: item
                )
                return nil
            }
            if let error = validateDestination(downloadsURL, estimatedBytesNeeded: estimatedBytesNeeded) {
                setOutputAccessError(
                    error,
                    isMetadataOperation: isMetadataOperation,
                    needsPermissionRetry: false,
                    item: item
                )
                return nil
            }
            return downloadsURL
        }
    }

    func clearMetadataReportError() {
        setGlobalMetadataReportError(nil, false)
    }

    func clearMetadataReportError(for item: DocumentItem) {
        item.metadataReportErrorMessage = nil
        item.metadataReportNeedsPermissionRetry = false
    }

    private func clearMetadataReportErrorsNeedingPermissionRetry() {
        for item in itemsProvider() where item.metadataReportNeedsPermissionRetry {
            item.metadataReportErrorMessage = nil
            item.metadataReportNeedsPermissionRetry = false
        }
        clearMetadataReportError()
    }

    private func requestMetadataOutputAccess() async -> Bool {
        switch outputSaveLocationPreference {
        case .downloads:
            FileAccessCoordinator.shared.resetDownloadsAccessPromptState()
            return await FileAccessCoordinator.shared.requestDownloadsAccessForReports()
        case .sameAsOriginal, .alwaysAsk:
            return await FileAccessCoordinator.shared.retryFileAccessPermissions()
        }
    }

    func retryFileAccessPermissionsFromBanner() async {
        let ok = await requestMetadataOutputAccess()
        if ok {
            clearMetadataReportErrorsNeedingPermissionRetry()
        } else {
            setMetadataReportError("File access permissions not granted.", needsPermissionRetry: true)
        }
    }

    func retryFileAccessPermissions(for item: DocumentItem) async {
        let ok = await requestMetadataOutputAccess()
        if ok {
            clearMetadataReportErrorsNeedingPermissionRetry()
        } else {
            setMetadataReportError("File access permissions not granted.", needsPermissionRetry: true, item: item)
        }
    }

    func clearReportError() {
        setGlobalReportError(nil)
    }

    func applyOutputArtifacts(
        to item: DocumentItem,
        outputPath: String,
        reportPath: String,
        scrubReportPath: String
    ) {
        item.redactedOutputURL = URL(fileURLWithPath: outputPath)
        item.reportOutputURL = URL(fileURLWithPath: reportPath)

        let reportHTMLURL = URL(fileURLWithPath: reportPath).deletingPathExtension().appendingPathExtension("html")
        if FileManager.default.fileExists(atPath: reportHTMLURL.path) {
            item.reportHTMLOutputURL = reportHTMLURL
        }

        let metadataSettings = MetadataCleaningSettings.load(defaults: defaults)
        if metadataSettings != .none {
            let scrubReportURL = URL(fileURLWithPath: scrubReportPath)
            if FileManager.default.fileExists(atPath: scrubReportURL.path) {
                item.scrubReportOutputURL = scrubReportURL
                item.metadataReportOutputURL = scrubReportURL
                let htmlURL = scrubReportURL.deletingPathExtension().appendingPathExtension("html")
                if FileManager.default.fileExists(atPath: htmlURL.path) {
                    item.scrubReportHTMLOutputURL = htmlURL
                    item.metadataReportHTMLOutputURL = htmlURL
                }
            } else {
                let directory = URL(fileURLWithPath: outputPath).deletingLastPathComponent()
                let baseName = item.url.deletingPathExtension().lastPathComponent
                if let foundScrubReport = findScrubReport(in: directory, matching: baseName) {
                    item.scrubReportOutputURL = foundScrubReport
                    item.metadataReportOutputURL = foundScrubReport
                    let htmlURL = foundScrubReport.deletingPathExtension().appendingPathExtension("html")
                    if FileManager.default.fileExists(atPath: htmlURL.path) {
                        item.scrubReportHTMLOutputURL = htmlURL
                        item.metadataReportHTMLOutputURL = htmlURL
                    }
                    DebugLogger.shared.log(
                        "📄 Found scrub report at alternate path: \(foundScrubReport.path)",
                        component: "DocumentRedactionViewModel"
                    )
                } else {
                    DebugLogger.shared.log(
                        "⚠️ Scrub report missing: \(scrubReportPath)",
                        component: "DocumentRedactionViewModel"
                    )
                }
            }
        } else {
            DebugLogger.shared.log(
                "ℹ️ Metadata cleaning disabled; skipping scrub report lookup.",
                component: "DocumentRedactionViewModel"
            )
        }

        DebugLogger.shared.log(
            "📄 Set output URLs - DOCX: \(outputPath), JSON: \(reportPath)",
            component: "DocumentRedactionViewModel"
        )
    }

    // MARK: - Output Management

    @discardableResult
    func openReport(_ item: DocumentItem) -> Bool {
        let title = "Audit Report — \(item.url.lastPathComponent)"
        if let htmlURL = item.reportHTMLOutputURL, FileManager.default.fileExists(atPath: htmlURL.path) {
            return presentReport(url: htmlURL, title: title)
        }
        if item.reportOutputURL != nil {
            let message = "Audit report HTML is missing. Please regenerate the report."
            item.errorMessage = message
            setGlobalReportError(message)
        }
        return false
    }

    @discardableResult
    func openScrubReport(_ item: DocumentItem) -> Bool {
        let title = "Scrub Report — \(item.url.lastPathComponent)"
        if item.scrubReportOutputURL == nil {
            let baseName = item.url.deletingPathExtension().lastPathComponent
            let searchDir = item.reportOutputURL?.deletingLastPathComponent() ?? item.redactedOutputURL?
                .deletingLastPathComponent()
            if let directory = searchDir, let found = findScrubReport(in: directory, matching: baseName) {
                item.scrubReportOutputURL = found
                item.metadataReportOutputURL = found
                let htmlURL = found.deletingPathExtension().appendingPathExtension("html")
                if FileManager.default.fileExists(atPath: htmlURL.path) {
                    item.scrubReportHTMLOutputURL = htmlURL
                    item.metadataReportHTMLOutputURL = htmlURL
                }
            }
        }
        if let htmlURL = resolvedHTMLURL(preferred: item.scrubReportHTMLOutputURL, from: item.scrubReportOutputURL) {
            return presentReport(url: htmlURL, title: title)
        }
        if let jsonURL = item.scrubReportOutputURL {
            Task { [weak self] in
                guard let self else { return }
                let htmlURL = await self.generateScrubHTMLIfMissing(at: jsonURL)
                await MainActor.run {
                    if let htmlURL {
                        item.scrubReportHTMLOutputURL = htmlURL
                        _ = self.presentReport(url: htmlURL, title: title)
                    } else {
                        let message = "Scrub report HTML is unavailable. Please regenerate the report."
                        item.errorMessage = message
                        self.setGlobalReportError(message)
                    }
                }
            }
            return true
        }
        if let htmlURL = resolvedHTMLURL(
            preferred: item.metadataReportHTMLOutputURL,
            from: item.metadataReportOutputURL
        ) {
            return presentReport(url: htmlURL, title: "Metadata Report — \(item.url.lastPathComponent)")
        }
        if let jsonURL = item.metadataReportOutputURL {
            Task { [weak self] in
                guard let self else { return }
                let htmlURL = await self.generateScrubHTMLIfMissing(at: jsonURL)
                await MainActor.run {
                    if let htmlURL {
                        item.metadataReportHTMLOutputURL = htmlURL
                        _ = self.presentReport(url: htmlURL, title: "Metadata Report — \(item.url.lastPathComponent)")
                    } else {
                        let message = "Metadata report HTML is unavailable. Please regenerate the report."
                        item.errorMessage = message
                        self.setMetadataReportError(message, needsPermissionRetry: false, item: item)
                    }
                }
            }
            return true
        }
        return false
    }

    @discardableResult
    func openMetadataReport(_ item: DocumentItem) -> Bool {
        let title = "Metadata Report — \(item.url.lastPathComponent)"
        if let htmlURL = resolvedHTMLURL(
            preferred: item.metadataReportHTMLOutputURL,
            from: item.metadataReportOutputURL
        ) {
            return presentReport(url: htmlURL, title: title)
        }
        if let jsonURL = item.metadataReportOutputURL {
            Task { [weak self] in
                guard let self else { return }
                let htmlURL = await self.generateScrubHTMLIfMissing(at: jsonURL)
                await MainActor.run {
                    if let htmlURL {
                        item.metadataReportHTMLOutputURL = htmlURL
                        _ = self.presentReport(url: htmlURL, title: title)
                    } else {
                        let message = "Metadata report HTML is unavailable. Please regenerate the report."
                        item.errorMessage = message
                        self.setMetadataReportError(message, needsPermissionRetry: false, item: item)
                    }
                }
            }
            return true
        }
        return false
    }

    private func presentReport(url: URL, title: String) -> Bool {
        LifecycleUtils.openReportWindow(report: ReportViewerItem(url: url, title: title))
        return true
    }

    private func resolvedHTMLURL(preferred: URL?, from jsonURL: URL?) -> URL? {
        if let preferred, FileManager.default.fileExists(atPath: preferred.path) {
            return preferred
        }
        guard let jsonURL else { return nil }
        let derived = jsonURL.deletingPathExtension().appendingPathExtension("html")
        return FileManager.default.fileExists(atPath: derived.path) ? derived : nil
    }

    @discardableResult
    func saveMetadataReport(_ item: DocumentItem) -> Bool {
        guard let jsonURL = item.metadataReportOutputURL, FileManager.default.fileExists(atPath: jsonURL.path) else {
            return false
        }

        let existingHTML = item.metadataReportHTMLOutputURL
        let htmlURL = (existingHTML != nil && FileManager.default.fileExists(atPath: existingHTML!.path)) ?
            existingHTML : nil

        switch outputSaveLocationPreference {
        case .downloads:
            Task {
                let granted = await FileAccessCoordinator.shared.requestDownloadsAccessForReports()
                guard granted else {
                    await MainActor.run {
                        setMetadataReportError(outputLocationErrorMessage(), needsPermissionRetry: true, item: item)
                    }
                    return
                }
                await saveMetadataReportToDownloads(htmlURL: htmlURL, jsonURL: jsonURL, item: item)
            }
            return true
        case .sameAsOriginal:
            let destinationDir = item.url.deletingLastPathComponent()
            Task { [weak self] in
                await self?.saveMetadataReportToDirectory(
                    destinationDir,
                    htmlURL: htmlURL,
                    jsonURL: jsonURL,
                    item: item
                )
            }
            return true
        case .alwaysAsk:
            break
        }

        if let htmlURL {
            let panel = NSOpenPanel()
            panel.title = "Choose Folder for Metadata Report"
            panel.canChooseDirectories = true
            panel.canChooseFiles = false
            panel.canCreateDirectories = true
            panel.prompt = "Save Here"
            panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            if panel.runModal() == .OK, let destinationDir = panel.url {
                let destinationURL = destinationDir.appendingPathComponent(htmlURL.lastPathComponent)
                Task { [weak self] in
                    await self?.exportMetadataReport(
                        htmlURL: htmlURL,
                        jsonURL: jsonURL,
                        destinationURL: destinationURL,
                        securityScopedURL: destinationDir,
                        item: item
                    )
                }
            }
        } else {
            let panel = NSSavePanel()
            panel.title = "Save Metadata Report"
            panel.nameFieldStringValue = jsonURL.lastPathComponent
            panel.allowedContentTypes = [UTType.json]
            panel.canCreateDirectories = true
            panel.directoryURL = FileManager.default.urls(for: .downloadsDirectory, in: .userDomainMask).first
            if panel.runModal() == .OK, let destinationURL = panel.url {
                Task { [weak self] in
                    await self?.exportMetadataReport(
                        htmlURL: nil,
                        jsonURL: jsonURL,
                        destinationURL: destinationURL,
                        securityScopedURL: destinationURL.deletingLastPathComponent(),
                        item: item
                    )
                }
            }
        }

        return true
    }

    private func saveMetadataReportToDownloads(htmlURL: URL?, jsonURL: URL, item: DocumentItem) async {
        let granted = await FileAccessCoordinator.shared.requestDownloadsAccessForReports()
        guard granted else {
            await MainActor.run {
                setMetadataReportError(outputLocationErrorMessage(), needsPermissionRetry: true, item: item)
            }
            return
        }

        guard let downloadsURL = FileAccessCoordinator.shared.downloadsDirectoryForReports() else {
            await MainActor.run {
                setMetadataReportError(outputLocationErrorMessage(), needsPermissionRetry: true, item: item)
            }
            return
        }

        await saveMetadataReportToDirectory(downloadsURL, htmlURL: htmlURL, jsonURL: jsonURL, item: item)
    }

    private func saveMetadataReportToDirectory(
        _ destinationDir: URL,
        htmlURL: URL?,
        jsonURL: URL,
        item: DocumentItem
    ) async {
        let estimatedBytesNeeded = estimatedOutputBytes(for: item, isMetadataOperation: true)
        if let error = validateDestination(destinationDir, estimatedBytesNeeded: estimatedBytesNeeded) {
            await MainActor.run {
                setMetadataReportError(error, needsPermissionRetry: false, item: item)
            }
            return
        }

        let destinationURL = destinationDir.appendingPathComponent((htmlURL ?? jsonURL).lastPathComponent)
        await exportMetadataReport(
            htmlURL: htmlURL,
            jsonURL: jsonURL,
            destinationURL: destinationURL,
            securityScopedURL: destinationDir,
            item: item
        )
    }

    private func exportMetadataReport(
        htmlURL: URL?,
        jsonURL: URL,
        destinationURL: URL,
        securityScopedURL: URL?,
        item: DocumentItem
    ) async {
        let fm = FileManager.default
        let didStartAccess = securityScopedURL?.startAccessingSecurityScopedResource() ?? false
        defer {
            if didStartAccess {
                securityScopedURL?.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let destinationDir = destinationURL.deletingLastPathComponent()
            let finalHTMLURL = htmlURL != nil ? destinationURL : nil

            // 1. Copy HTML if requested
            if let finalHTMLURL, let htmlURL {
                guard fm.fileExists(atPath: htmlURL.path) else {
                    throw NSError(
                        domain: "MarcutApp",
                        code: 404,
                        userInfo: [NSLocalizedDescriptionKey: "Source HTML report not found at \(htmlURL.path)"]
                    )
                }

                if htmlURL.standardizedFileURL == finalHTMLURL.standardizedFileURL {
                    DebugLogger.shared.log(
                        "⚠️ Skip copy: source and destination HTML are identical (\(htmlURL.path))",
                        component: "DocumentRedactionViewModel"
                    )
                } else {
                    if fm.fileExists(atPath: finalHTMLURL.path) {
                        try fm.removeItem(at: finalHTMLURL)
                    }
                    try fm.copyItem(at: htmlURL, to: finalHTMLURL)
                }
                DocumentRedactionViewModel.makeSensitiveReportFilePrivate(finalHTMLURL)
            }

            // 2. Copy JSON
            let destinationJSONURL = htmlURL != nil
                ? destinationDir.appendingPathComponent(jsonURL.lastPathComponent)
                : destinationURL

            guard fm.fileExists(atPath: jsonURL.path) else {
                throw NSError(
                    domain: "MarcutApp",
                    code: 404,
                    userInfo: [NSLocalizedDescriptionKey: "Source JSON report not found at \(jsonURL.path)"]
                )
            }

            if jsonURL.standardizedFileURL == destinationJSONURL.standardizedFileURL {
                DebugLogger.shared.log(
                    "⚠️ Skip copy: source and destination JSON are identical (\(jsonURL.path))",
                    component: "DocumentRedactionViewModel"
                )
            } else {
                if fm.fileExists(atPath: destinationJSONURL.path) {
                    try fm.removeItem(at: destinationJSONURL)
                }
                try fm.copyItem(at: jsonURL, to: destinationJSONURL)
            }
            DocumentRedactionViewModel.makeSensitiveReportFilePrivate(destinationJSONURL)

            DebugLogger.shared.log(
                "✅ Saved metadata report to \(destinationURL.path)",
                component: "DocumentRedactionViewModel"
            )
            await MainActor.run {
                item.metadataReportErrorMessage = nil
                item.metadataReportNeedsPermissionRetry = false
            }
        } catch {
            DebugLogger.shared.log("❌ Save metadata report failed: \(error)", component: "DocumentRedactionViewModel")
            await MainActor.run {
                setMetadataReportError(
                    "Save failed: \(error.localizedDescription)",
                    needsPermissionRetry: false,
                    item: item
                )
            }
        }
    }

    @discardableResult
    func revealInFinder(_ item: DocumentItem) -> Bool {
        if let url = item.redactedOutputURL ?? item.reportOutputURL ?? item.scrubReportOutputURL ?? item
            .metadataReportOutputURL
        {
            return NSWorkspace.shared.selectFile(url.path, inFileViewerRootedAtPath: "")
        }
        return false
    }

    // MARK: - Pre-flight Validation

    /// Rough multiplier applied to an input document's size to estimate the disk space a full
    /// redaction run needs (redacted DOCX output + JSON/HTML audit reports). Generous on
    /// purpose -- track-changes XML and report JSON can each individually run larger than the
    /// source text -- so this errs toward failing a cheap preflight check rather than a
    /// multi-minute run's final write.
    private static let outputSizeSafetyFactor: Double = 3.0

    /// Smaller multiplier for metadata-report-only exports (no redacted DOCX output written),
    /// where the report is typically much smaller than the source file.
    private static let reportOnlySizeSafetyFactor: Double = 1.0

    /// Estimates the disk space, in bytes, that processing `item` will need at its destination,
    /// as a multiple of the source file's own size. Returns 0 (i.e. "don't check") if the
    /// source file's size can't be determined.
    private func estimatedOutputBytes(for item: DocumentItem, isMetadataOperation: Bool) -> Int64 {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: item.url.path),
              let sizeNumber = attributes[.size] as? NSNumber
        else {
            return 0
        }
        let inputBytes = sizeNumber.int64Value
        guard inputBytes > 0 else { return 0 }
        let factor = isMetadataOperation ? Self.reportOnlySizeSafetyFactor : Self.outputSizeSafetyFactor
        return Int64(Double(inputBytes) * factor)
    }

    /// Preflight-validates a candidate output destination: confirms it's actually writable (a
    /// small create+delete test file, not just an existence check) and, when
    /// `estimatedBytesNeeded` is provided, that there's likely enough free space for the run.
    /// `freeSpaceProvider` is injectable so tests can simulate a full disk without filling one.
    func validateDestination(
        _ url: URL,
        estimatedBytesNeeded: Int64 = 0,
        freeSpaceProvider: (URL) -> Int64? = DiskSpaceCheck.availableBytes
    ) -> String? {
        // Check write permissions
        let testFileURL = url.appendingPathComponent(".marcut-writetest")
        do {
            try "test".data(using: .utf8)?.write(to: testFileURL)
            try FileManager.default.removeItem(at: testFileURL)
        } catch {
            return "Cannot write to selected destination - please choose a different folder"
        }

        if let error = DiskSpaceCheck.insufficientSpaceMessage(
            estimatedBytesNeeded: estimatedBytesNeeded,
            directory: url,
            subject: "process this document",
            freeSpaceProvider: freeSpaceProvider
        ) {
            return error
        }

        return nil
    }

    func generateScrubHTMLIfMissing(at jsonURL: URL) async -> URL? {
        guard FileManager.default.fileExists(atPath: jsonURL.path) else { return nil }
        guard let runner = pythonRunner else { return nil }

        if let htmlPath = await runner.generateScrubHTML(from: jsonURL.path), !htmlPath.isEmpty {
            let htmlURL = URL(fileURLWithPath: htmlPath)
            if FileManager.default.fileExists(atPath: htmlURL.path) {
                return htmlURL
            }
        }

        let fallback = jsonURL.deletingPathExtension().appendingPathExtension("html")
        return FileManager.default.fileExists(atPath: fallback.path) ? fallback : nil
    }

    /// Search for scrub report file in directory matching document basename
    /// Handles both naming conventions: "(scrub-report DATE).json" and "_scrub_report.json"
    /// Find scrub report file in directory matching the document base name.
    /// Uses strict matching to avoid opening wrong report for similar filenames.
    /// Runs synchronously but callers should invoke from background context.
    nonisolated func findScrubReport(in directory: URL, matching baseName: String) -> URL? {
        let fm = FileManager.default
        guard let contents = try? fm.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil) else {
            return nil
        }

        func normalizeForMatch(_ value: String) -> String {
            value.lowercased()
                .replacingOccurrences(of: " ", with: "_")
                .replacingOccurrences(of: "-", with: "_")
        }

        let normalizedBaseName = normalizeForMatch(baseName)

        for fileURL in contents {
            guard fileURL.pathExtension.lowercased() == "json" else { continue }

            let stem = fileURL.deletingPathExtension().lastPathComponent.lowercased()

            if let range = stem.range(of: " (scrub-report") {
                let prefix = String(stem[..<range.lowerBound])
                if normalizeForMatch(prefix) == normalizedBaseName {
                    return fileURL
                }
                continue
            }

            if let range = stem.range(of: " (scrub report") {
                let prefix = String(stem[..<range.lowerBound])
                if normalizeForMatch(prefix) == normalizedBaseName {
                    return fileURL
                }
                continue
            }

            if let range = stem.range(of: "_scrub_report") {
                let prefix = String(stem[..<range.lowerBound])
                if normalizeForMatch(prefix) == normalizedBaseName {
                    return fileURL
                }
            }
        }

        return nil
    }
}
