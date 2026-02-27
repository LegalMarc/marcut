import SwiftUI
import WebKit

struct HelpHTMLView: NSViewRepresentable {
    let htmlContent: String
    @Binding var scrollToAnchor: String?

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.setValue(false, forKey: "drawsBackground")
        context.coordinator.webView = webView
        context.coordinator.load(html: htmlContent, baseURL: Bundle.main.resourceURL)
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastHTML != htmlContent {
            context.coordinator.load(html: htmlContent, baseURL: Bundle.main.resourceURL)
        }
        if let anchor = scrollToAnchor {
            context.coordinator.scrollTo(anchor: anchor)
            DispatchQueue.main.async {
                scrollToAnchor = nil
            }
        }
    }

    class Coordinator: NSObject, WKNavigationDelegate {
        weak var webView: WKWebView?
        var lastHTML: String = ""
        var pendingAnchor: String?

        func load(html: String, baseURL: URL?) {
            lastHTML = html
            pendingAnchor = nil
            webView?.loadHTMLString(html, baseURL: baseURL)
        }

        func scrollTo(anchor: String) {
            guard let webView else {
                return
            }
            pendingAnchor = anchor
            if webView.isLoading {
                return
            }
            let js = "var el=document.getElementById('\(anchor)'); if(el){ el.scrollIntoView(true); }"
            webView.evaluateJavaScript(js, completionHandler: nil)
            pendingAnchor = nil
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            if let anchor = pendingAnchor {
                scrollTo(anchor: anchor)
            }
        }

        func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction, decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            guard let url = navigationAction.request.url else {
                decisionHandler(.allow)
                return
            }

            if url.scheme == "http" || url.scheme == "https" {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
                return
            }

            decisionHandler(.allow)
        }
    }
}
