import SwiftUI
import WebKit
import AppKit
import Security
import Foundation

struct ReportViewer: View {
    let report: ReportViewerItem
    @StateObject private var webViewState = ReportWebViewState()
    @State private var showBurnConfirm = false
    @State private var burnErrorMessage: String?
    @State private var openBinaryErrorMessage: String?

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Text(report.title)
                    .font(.system(size: 14, weight: .semibold))
                    .lineLimit(1)
                Spacer()
                Button {
                    navigateBack()
                } label: {
                    Label("Back", systemImage: "chevron.left")
                }
                .buttonStyle(.bordered)
                .controlSize(.regular)
                .frame(width: 100, height: 32)
                .disabled(!webViewState.canGoBack)

                Button {
                    printReport()
                } label: {
                    Label("Print", systemImage: "printer")
                }
                .buttonStyle(.bordered)
                .controlSize(.regular)
                .frame(width: 100, height: 32)
                
                SharePickerButton(url: report.url)
                    .frame(width: 100, height: 32)
                
                Button {
                    showBurnConfirm = true
                } label: {
                    Label("Burn", systemImage: "flame")
                }
                .buttonStyle(.bordered)
                .controlSize(.regular)
                .frame(width: 100, height: 32)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color(NSColor.windowBackgroundColor))
            Divider()

            if FileManager.default.fileExists(atPath: report.url.path) {
                ReportWebView(
                    url: report.url,
                    state: webViewState,
                    onPrintRequest: { printReport() },
                    onShareRequest: { shareReport() },
                    onBurnRequest: { showBurnConfirm = true },
                    onOpenBinary: { openBinary(at: $0) }
                )
            } else {
                VStack(spacing: 12) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundColor(.orange)
                    Text("Report file not found.")
                        .font(.system(size: 14, weight: .medium))
                    Text(report.url.path)
                        .font(.system(size: 11, weight: .regular, design: .monospaced))
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 24)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 900, minHeight: 650)
        .background(ReportWindowKeyHandler(windowURL: report.url))
        .alert("Burn Report?", isPresented: $showBurnConfirm) {
            Button("Burn", role: .destructive) {
                burnReport()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This permanently deletes the report files (HTML/JSON and extracted binaries).")
        }
        .alert("Burn Failed", isPresented: Binding(
            get: { burnErrorMessage != nil },
            set: { if !$0 { burnErrorMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(burnErrorMessage ?? "Unable to securely erase the report.")
        }
        .alert("File Not Found", isPresented: Binding(
            get: { openBinaryErrorMessage != nil },
            set: { if !$0 { openBinaryErrorMessage = nil } }
        )) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(openBinaryErrorMessage ?? "The selected file could not be found.")
        }
    }

    private func printReport() {
        guard let webView = webViewState.webView else { return }
        webView.evaluateJavaScript("try { snapshotCollapseState(); expandAllGroups(); } catch (e) {}") { _, _ in
            let printInfo = NSPrintInfo.shared
            let operation = webView.printOperation(with: printInfo)
            operation.showsPrintPanel = true
            operation.showsProgressPanel = true
            operation.run()
            webView.evaluateJavaScript("try { restoreCollapseState(); } catch (e) {}")
        }
    }

    private func navigateBack() {
        guard let webView = webViewState.webView else { return }
        guard webView.canGoBack else { return }
        webView.goBack()
    }

    private func shareReport() {
        let picker = NSSharingServicePicker(items: [report.url])
        if let window = reportWindow(), let contentView = window.contentView {
            picker.show(relativeTo: contentView.bounds, of: contentView, preferredEdge: .minY)
        } else {
            picker.show(relativeTo: .zero, of: NSView(), preferredEdge: .minY)
        }
    }

    private func openBinary(at path: String) {
        let reportRoot = report.url.deletingLastPathComponent().standardizedFileURL
        let resolvedURL = reportRoot.appendingPathComponent(path).standardizedFileURL
        let resolvedPath = resolvedURL.path
        let rootPath = reportRoot.path
        let withinRoot = resolvedPath == rootPath || resolvedPath.hasPrefix(rootPath + "/")
        guard withinRoot else {
            DispatchQueue.main.async {
                openBinaryErrorMessage = "Blocked opening file outside this report folder."
            }
            return
        }

        guard FileManager.default.fileExists(atPath: resolvedURL.path) else {
            DispatchQueue.main.async {
                openBinaryErrorMessage = resolvedURL.path
            }
            return
        }

        DispatchQueue.main.async {
            NSWorkspace.shared.open(resolvedURL)
        }
    }

    private func burnReport() {
        let reportURL = report.url
        let reportDir = reportURL.deletingLastPathComponent()
        let didStartScope = reportDir.startAccessingSecurityScopedResource()
        defer {
            if didStartScope {
                reportDir.stopAccessingSecurityScopedResource()
            }
        }

        do {
            let jsonURL = reportURL.pathExtension.lowercased() == "json"
                ? reportURL
                : reportURL.deletingPathExtension().appendingPathExtension("json")
            let binaryURLs = collectBinaryExportURLs(from: jsonURL)
            let relatedURLs = try reportRelatedFiles(for: reportURL)
            for url in relatedURLs {
                try secureEraseFile(at: url)
            }
            for url in binaryURLs {
                try secureEraseFile(at: url)
            }
            secureEraseDirectory(at: reportDir.appendingPathComponent("forensic_explorer", isDirectory: true))
            cleanupBinaryExportsDirectory(for: jsonURL)
            closeReportWindow()
        } catch {
            burnErrorMessage = error.localizedDescription
        }
    }

    private func reportRelatedFiles(for url: URL) throws -> [URL] {
        let baseURL = url.deletingPathExtension()
        let htmlURL = baseURL.appendingPathExtension("html")
        let jsonURL = baseURL.appendingPathExtension("json")
        var candidates = [URL]()
        candidates.append(htmlURL)
        candidates.append(jsonURL)
        if url.pathExtension.lowercased() == "html" || url.pathExtension.lowercased() == "json" {
            candidates.append(url)
        }
        return Array(Set(candidates)).filter { FileManager.default.fileExists(atPath: $0.path) }
    }

    private func collectBinaryExportURLs(from jsonURL: URL) -> [URL] {
        guard FileManager.default.fileExists(atPath: jsonURL.path) else { return [] }
        guard let data = try? Data(contentsOf: jsonURL),
              let json = try? JSONSerialization.jsonObject(with: data, options: []),
              let payload = json as? [String: Any] else {
            return []
        }
        let reportDir = jsonURL.deletingLastPathComponent()
        var urls = Set<URL>()
        let exportKeys = ["binary_exports", "large_exports"]
        for key in exportKeys {
            guard let entries = payload[key] as? [[String: Any]] else { continue }
            for entry in entries {
                guard let relPath = entry["path"] as? String, !relPath.isEmpty else { continue }
                let candidate = reportDir.appendingPathComponent(relPath).standardizedFileURL
                let rootPath = reportDir.standardizedFileURL.path
                let candidatePath = candidate.path
                let withinRoot = candidatePath == rootPath || candidatePath.hasPrefix(rootPath + "/")
                if withinRoot {
                    urls.insert(candidate)
                }
            }
        }
        return Array(urls)
    }

    private func cleanupBinaryExportsDirectory(for jsonURL: URL) {
        let binariesDir = jsonURL
            .deletingLastPathComponent()
            .appendingPathComponent("binaries", isDirectory: true)
        let fm = FileManager.default
        var isDirectory: ObjCBool = false
        guard fm.fileExists(atPath: binariesDir.path, isDirectory: &isDirectory),
              isDirectory.boolValue else {
            return
        }
        if let contents = try? fm.contentsOfDirectory(at: binariesDir, includingPropertiesForKeys: nil),
           contents.isEmpty {
            try? fm.removeItem(at: binariesDir)
        }
    }

    private func secureEraseFile(at url: URL) throws {
        let fm = FileManager.default
        guard fm.fileExists(atPath: url.path) else { return }
        let attributes = try fm.attributesOfItem(atPath: url.path)
        let fileSize = (attributes[.size] as? NSNumber)?.intValue ?? 0
        if fileSize > 0 {
            let handle = try FileHandle(forWritingTo: url)
            defer { try? handle.close() }
            var remaining = fileSize
            let chunkSize = 1024 * 1024
            while remaining > 0 {
                let size = min(chunkSize, remaining)
                let data = secureRandomData(count: size)
                try handle.write(contentsOf: data)
                remaining -= size
            }
            try? handle.synchronize()
        }
        try fm.removeItem(at: url)
    }

    private func secureEraseDirectory(at url: URL) {
        let fm = FileManager.default
        var isDirectory: ObjCBool = false
        guard fm.fileExists(atPath: url.path, isDirectory: &isDirectory), isDirectory.boolValue else {
            return
        }
        if let enumerator = fm.enumerator(at: url, includingPropertiesForKeys: [.isRegularFileKey], options: [], errorHandler: nil) {
            for case let fileURL as URL in enumerator {
                let isRegular = (try? fileURL.resourceValues(forKeys: [.isRegularFileKey]))?.isRegularFile ?? false
                if isRegular {
                    try? secureEraseFile(at: fileURL)
                }
            }
        }
        try? fm.removeItem(at: url)
    }

    private func secureRandomData(count: Int) -> Data {
        var buffer = [UInt8](repeating: 0, count: count)
        let status = SecRandomCopyBytes(kSecRandomDefault, buffer.count, &buffer)
        if status != errSecSuccess {
            var generator = SystemRandomNumberGenerator()
            for i in 0..<buffer.count {
                buffer[i] = UInt8.random(in: 0...255, using: &generator)
            }
        }
        return Data(buffer)
    }

    private func closeReportWindow() {
        if let window = reportWindow() {
            window.performClose(nil)
        }
    }

    private func reportWindow() -> NSWindow? {
        let targetURL = report.url.standardizedFileURL
        if let window = NSApp.windows.first(where: { window in
            guard let representedURL = window.representedURL?.standardizedFileURL else {
                return false
            }
            return representedURL == targetURL
        }) {
            return window
        }
        return NSApp.windows.first { $0.title == report.title }
    }
}

struct ReportWindowKeyHandler: NSViewRepresentable {
    let windowURL: URL

    func makeCoordinator() -> Coordinator {
        Coordinator(windowURL: windowURL)
    }

    func makeNSView(context: Context) -> NSView {
        let view = NSView()
        if context.coordinator.monitor == nil {
            context.coordinator.monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
                if event.keyCode == 53,
                   NSApp.keyWindow?.representedURL?.standardizedFileURL == context.coordinator.windowURL.standardizedFileURL {
                    NSApp.keyWindow?.performClose(nil)
                    return nil
                }
                return event
            }
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        context.coordinator.windowURL = windowURL
    }

    final class Coordinator {
        var monitor: Any?
        var windowURL: URL

        init(windowURL: URL) {
            self.windowURL = windowURL
        }

        deinit {
            if let monitor {
                NSEvent.removeMonitor(monitor)
            }
        }
    }
}

final class ReportWebViewState: ObservableObject {
    weak var webView: WKWebView?
    var lastLoadedURL: URL?
    @Published var canGoBack = false
}

struct ReportWebView: NSViewRepresentable {
    let url: URL
    @ObservedObject var state: ReportWebViewState
    let onPrintRequest: () -> Void
    let onShareRequest: () -> Void
    let onBurnRequest: () -> Void
    let onOpenBinary: (String) -> Void

    func makeCoordinator() -> Coordinator {
        Coordinator(state: state, onPrintRequest: onPrintRequest, onShareRequest: onShareRequest, onBurnRequest: onBurnRequest, onOpenBinary: onOpenBinary)
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.userContentController.add(context.coordinator, name: Coordinator.reportActionHandlerName)
        let scriptSource = """
        if (!window.__marcutPrintHook) {
            window.__marcutPrintHook = true;
            window.__marcutOriginalPrint = window.print;
            window.print = function() {
                if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.reportAction) {
                    window.webkit.messageHandlers.reportAction.postMessage({action: 'print'});
                } else if (window.__marcutOriginalPrint) {
                    window.__marcutOriginalPrint();
                }
            };
        }
        document.addEventListener('click', function(event) {
            var card = event.target.closest('.binary-card');
            if (!card) {
                return;
            }
            var fullPath = card.getAttribute('data-file-path');
            if (!fullPath) {
                return;
            }
            event.preventDefault();
            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.reportAction) {
                window.webkit.messageHandlers.reportAction.postMessage({action: 'openBinary', path: fullPath});
            } else {
                window.open(fullPath, '_blank');
            }
        });
        """
        let script = WKUserScript(source: scriptSource, injectionTime: .atDocumentStart, forMainFrameOnly: false)
        config.userContentController.addUserScript(script)
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.uiDelegate = context.coordinator
        webView.navigationDelegate = context.coordinator
        webView.setValue(false, forKey: "drawsBackground")
        state.webView = webView
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {
        let accessRoot = url.deletingLastPathComponent()
        context.coordinator.readAccessRootURL = accessRoot
        let normalizedURL = url.standardizedFileURL
        let currentURL = nsView.url?.standardizedFileURL
        if state.lastLoadedURL != normalizedURL || currentURL != normalizedURL {
            nsView.loadFileURL(url, allowingReadAccessTo: accessRoot)
            state.lastLoadedURL = normalizedURL
        }
        state.webView = nsView
    }

    final class Coordinator: NSObject, WKUIDelegate, WKScriptMessageHandler, WKNavigationDelegate {
        static let reportActionHandlerName = "reportAction"
        private let state: ReportWebViewState
        private let onPrintRequest: () -> Void
        private let onShareRequest: () -> Void
        private let onBurnRequest: () -> Void
        private let onOpenBinary: (String) -> Void
        var readAccessRootURL: URL?

        init(state: ReportWebViewState, onPrintRequest: @escaping () -> Void, onShareRequest: @escaping () -> Void, onBurnRequest: @escaping () -> Void, onOpenBinary: @escaping (String) -> Void) {
            self.state = state
            self.onPrintRequest = onPrintRequest
            self.onShareRequest = onShareRequest
            self.onBurnRequest = onBurnRequest
            self.onOpenBinary = onOpenBinary
        }

        func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
            guard message.name == Coordinator.reportActionHandlerName else { return }
            if let body = message.body as? [String: Any],
               let action = body["action"] as? String {
                switch action {
                case "print":
                    onPrintRequest()
                    return
                case "share":
                    onShareRequest()
                    return
                case "burn":
                    onBurnRequest()
                    return
                case "openBinary":
                    if let path = body["path"] as? String {
                        onOpenBinary(path)
                    }
                    return
                default:
                    break
                }
            }
            if let action = message.body as? String, action == "print" {
                onPrintRequest()
            }
        }

        func webView(
            _ webView: WKWebView,
            createWebViewWith configuration: WKWebViewConfiguration,
            for navigationAction: WKNavigationAction,
            windowFeatures: WKWindowFeatures
        ) -> WKWebView? {
            if navigationAction.targetFrame == nil {
                if let targetURL = navigationAction.request.url, targetURL.isFileURL {
                    let accessRoot = readAccessRootURL ?? targetURL.deletingLastPathComponent()
                    webView.loadFileURL(targetURL, allowingReadAccessTo: accessRoot)
                } else {
                    webView.load(navigationAction.request)
                }
            }
            return nil
        }

        func webView(_ webView: WKWebView, didStartProvisionalNavigation navigation: WKNavigation!) {
            state.canGoBack = webView.canGoBack
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            state.canGoBack = webView.canGoBack
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            state.canGoBack = webView.canGoBack
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            state.canGoBack = webView.canGoBack
        }
    }
}

struct SharePickerButton: NSViewRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator {
        Coordinator(url: url)
    }

    func makeNSView(context: Context) -> NSButton {
        let button = NSButton(title: "Share", target: context.coordinator, action: #selector(Coordinator.share(_:)))
        button.image = NSImage(systemSymbolName: "square.and.arrow.up", accessibilityDescription: "Share")
        button.imagePosition = .imageLeading
        button.bezelStyle = .rounded
        button.setButtonType(.momentaryPushIn)
        button.controlSize = .regular
        button.font = NSFont.systemFont(ofSize: 13, weight: .semibold)
        button.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            button.heightAnchor.constraint(equalToConstant: 32),
            button.widthAnchor.constraint(equalToConstant: 100),
        ])
        return button
    }

    func updateNSView(_ nsView: NSButton, context: Context) {
        context.coordinator.url = url
    }

    final class Coordinator: NSObject {
        var url: URL

        init(url: URL) {
            self.url = url
        }

        @objc func share(_ sender: NSButton) {
            let picker = NSSharingServicePicker(items: [url])
            picker.show(relativeTo: sender.bounds, of: sender, preferredEdge: .minY)
        }
    }
}
