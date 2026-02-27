import SwiftUI
import AppKit

/// Custom attribute key for anchor IDs
private extension NSAttributedString.Key {
    static let anchorID = NSAttributedString.Key("anchorID")
}

/// A SwiftUI wrapper around NSTextView that renders Markdown content with rich text and clickable links.
struct MarkdownTextView: NSViewRepresentable {
    let markdownContent: String
    @Binding var scrollToAnchor: String?
    
    func makeNSView(context: Context) -> NSScrollView {
        let scrollView = NSScrollView()
        scrollView.hasVerticalScroller = true
        scrollView.hasHorizontalScroller = false
        scrollView.autohidesScrollers = true
        scrollView.borderType = .noBorder
        scrollView.drawsBackground = false
        
        let textView = NSTextView()
        textView.isEditable = false
        textView.isSelectable = true
        textView.drawsBackground = false
        textView.textContainerInset = NSSize(width: 16, height: 16)
        textView.isAutomaticLinkDetectionEnabled = false  // We handle links manually
        textView.delegate = context.coordinator
        
        // Enable Find panel (Cmd+F)
        textView.isIncrementalSearchingEnabled = true
        textView.usesFindPanel = true
        textView.usesFindBar = true // Potentially fixes in-window search
        
        // Set up text container for proper wrapping
        textView.textContainer?.widthTracksTextView = true
        textView.textContainer?.containerSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
        textView.isHorizontallyResizable = false
        textView.isVerticallyResizable = true
        textView.autoresizingMask = [.width]
        
        scrollView.documentView = textView
        
        // Set the attributed string content
        let anchorPositions = updateContent(textView: textView)
        context.coordinator.anchorPositions = anchorPositions
        context.coordinator.textView = textView
        context.coordinator.scrollView = scrollView
        if let anchor = scrollToAnchor {
            context.coordinator.scrollToAnchor(anchor)
            DispatchQueue.main.async {
                scrollToAnchor = nil
            }
        }
        
        return scrollView
    }
    
    func updateNSView(_ scrollView: NSScrollView, context: Context) {
        guard let textView = scrollView.documentView as? NSTextView else { return }
        let anchorPositions = updateContent(textView: textView)
        context.coordinator.anchorPositions = anchorPositions
        context.coordinator.textView = textView
        context.coordinator.scrollView = scrollView
        if let anchor = scrollToAnchor {
            context.coordinator.scrollToAnchor(anchor)
            DispatchQueue.main.async {
                scrollToAnchor = nil
            }
        }
    }
    
    /// Generate an anchor ID from header text (GitHub-style slugification)
    private func generateAnchorID(from text: String) -> String {
        return text
            .lowercased()
            .replacingOccurrences(of: " ", with: "-")
            .replacingOccurrences(of: "(", with: "")
            .replacingOccurrences(of: ")", with: "")
            .replacingOccurrences(of: ":", with: "")
            .replacingOccurrences(of: ",", with: "")
            .replacingOccurrences(of: "'", with: "")
            .replacingOccurrences(of: "\"", with: "")
    }
    
    @discardableResult
    private func updateContent(textView: NSTextView) -> [String: Int] {
        // Build styled attributed string from markdown
        let result = NSMutableAttributedString()
        var anchorPositions: [String: Int] = [:]
        
        let paragraphStyle = NSMutableParagraphStyle()
        paragraphStyle.lineSpacing = 4
        paragraphStyle.paragraphSpacing = 8
        
        let baseFont = NSFont.systemFont(ofSize: 14)
        let boldFont = NSFont.boldSystemFont(ofSize: 14)
        let h1Font = NSFont.boldSystemFont(ofSize: 24)
        let h2Font = NSFont.boldSystemFont(ofSize: 20)
        let h3Font = NSFont.boldSystemFont(ofSize: 16)
        let codeFont = NSFont.monospacedSystemFont(ofSize: 13, weight: .regular)
        
        let baseAttributes: [NSAttributedString.Key: Any] = [
            .font: baseFont,
            .foregroundColor: NSColor.textColor,
            .paragraphStyle: paragraphStyle
        ]
        
        let lines = markdownContent.components(separatedBy: "\n")
        var inCodeBlock = false
        var codeBlockContent = ""
        
        for (index, line) in lines.enumerated() {
            // Handle code blocks
            if line.hasPrefix("```") {
                if inCodeBlock {
                    // End code block - render accumulated content
                    let codeStyle = NSMutableParagraphStyle()
                    codeStyle.paragraphSpacing = 4
                    let codeAttrs: [NSAttributedString.Key: Any] = [
                        .font: codeFont,
                        .foregroundColor: NSColor.textColor,
                        .backgroundColor: NSColor.textBackgroundColor.withAlphaComponent(0.3),
                        .paragraphStyle: codeStyle
                    ]
                    result.append(NSAttributedString(string: codeBlockContent + "\n\n", attributes: codeAttrs))
                    codeBlockContent = ""
                    inCodeBlock = false
                } else {
                    inCodeBlock = true
                }
                continue
            }
            
            if inCodeBlock {
                codeBlockContent += line + "\n"
                continue
            }
            
            // Handle headers - record anchor positions
            if line.hasPrefix("# ") {
                let text = String(line.dropFirst(2))
                let anchorID = generateAnchorID(from: text)
                anchorPositions[anchorID] = result.length
                
                var attrs = baseAttributes
                attrs[.font] = h1Font
                attrs[.anchorID] = anchorID
                result.append(NSAttributedString(string: text + "\n\n", attributes: attrs))
            } else if line.hasPrefix("## ") {
                let text = String(line.dropFirst(3))
                let anchorID = generateAnchorID(from: text)
                anchorPositions[anchorID] = result.length
                
                var attrs = baseAttributes
                attrs[.font] = h2Font
                attrs[.anchorID] = anchorID
                result.append(NSAttributedString(string: text + "\n\n", attributes: attrs))
            } else if line.hasPrefix("### ") {
                let text = String(line.dropFirst(4))
                let anchorID = generateAnchorID(from: text)
                anchorPositions[anchorID] = result.length
                
                var attrs = baseAttributes
                attrs[.font] = h3Font
                attrs[.anchorID] = anchorID
                result.append(NSAttributedString(string: text + "\n\n", attributes: attrs))
            } else if line.hasPrefix("- ") {
                // Bullet list - process inline markdown for the content
                let bulletContent = String(line.dropFirst(2))
                let processed = processInlineMarkdown(bulletContent, baseAttributes: baseAttributes, boldFont: boldFont, codeFont: codeFont)
                let bulletResult = NSMutableAttributedString(string: "• ", attributes: baseAttributes)
                bulletResult.append(processed)
                bulletResult.append(NSAttributedString(string: "\n", attributes: baseAttributes))
                result.append(bulletResult)
            } else if line.isEmpty {
                result.append(NSAttributedString(string: "\n", attributes: baseAttributes))
            } else {
                // Regular paragraph - process inline markdown
                let processed = processInlineMarkdown(line, baseAttributes: baseAttributes, boldFont: boldFont, codeFont: codeFont)
                result.append(processed)
                // Add newline unless next line continues paragraph
                if index < lines.count - 1 {
                    result.append(NSAttributedString(string: "\n", attributes: baseAttributes))
                }
            }
        }
        
        textView.textStorage?.setAttributedString(result)
        return anchorPositions
    }
    
    private func processInlineMarkdown(_ text: String, baseAttributes: [NSAttributedString.Key: Any], boldFont: NSFont, codeFont: NSFont) -> NSAttributedString {
        let result = NSMutableAttributedString(string: text, attributes: baseAttributes)
        
        // Process markdown links: [text](url) - including anchor links [text](#anchor)
        let linkPattern = #"\[([^\]]+)\]\(([^)]+)\)"#
        if let regex = try? NSRegularExpression(pattern: linkPattern) {
            let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
            // Process in reverse to preserve indices
            for match in matches.reversed() {
                guard match.numberOfRanges >= 3,
                      let textRange = Range(match.range(at: 1), in: text),
                      let urlRange = Range(match.range(at: 2), in: text),
                      let fullRange = Range(match.range, in: text) else { continue }
                
                let linkText = String(text[textRange])
                let urlString = String(text[urlRange])
                
                var linkAttrs = baseAttributes
                linkAttrs[.foregroundColor] = NSColor.linkColor
                linkAttrs[.underlineStyle] = NSUnderlineStyle.single.rawValue
                
                // Handle anchor links (#section-name) vs external URLs
                if urlString.hasPrefix("#") {
                    // Internal anchor link
                    linkAttrs[.link] = URL(string: "marcut-anchor:\(urlString.dropFirst())")
                } else if let url = URL(string: urlString) {
                    linkAttrs[.link] = url
                }
                
                let replacement = NSAttributedString(string: linkText, attributes: linkAttrs)
                result.replaceCharacters(in: NSRange(fullRange, in: text), with: replacement)
            }
        }
        
        // Process plain URLs (https:// or http://) - but only in current text, not modified result
        let urlPattern = #"https?://[^\s\)\]\>]+"#
        if let regex = try? NSRegularExpression(pattern: urlPattern) {
            let currentText = result.string
            let matches = regex.matches(in: currentText, range: NSRange(currentText.startIndex..., in: currentText))
            // Process in reverse to preserve indices
            for match in matches.reversed() {
                guard let range = Range(match.range, in: currentText) else { continue }
                let urlString = String(currentText[range])
                
                // Check if this URL is already a link (to avoid double-processing)
                var isAlreadyLink = false
                result.enumerateAttribute(.link, in: match.range, options: []) { value, _, stop in
                    if value != nil {
                        isAlreadyLink = true
                        stop.pointee = true
                    }
                }
                
                if !isAlreadyLink, let url = URL(string: urlString) {
                    var linkAttrs = baseAttributes
                    linkAttrs[.link] = url
                    linkAttrs[.foregroundColor] = NSColor.linkColor
                    linkAttrs[.underlineStyle] = NSUnderlineStyle.single.rawValue
                    
                    result.setAttributes(linkAttrs, range: match.range)
                }
            }
        }
        
        // Process bold: **text** or __text__
        let boldPattern = #"\*\*([^*]+)\*\*|__([^_]+)__"#
        if let regex = try? NSRegularExpression(pattern: boldPattern) {
            var offset = 0
            let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
            for match in matches {
                let captureIdx = match.range(at: 1).location != NSNotFound ? 1 : 2
                guard let contentRange = Range(match.range(at: captureIdx), in: text) else { continue }
                
                let boldText = String(text[contentRange])
                var boldAttrs = baseAttributes
                boldAttrs[.font] = boldFont
                
                let nsFullRange = NSRange(location: match.range.location + offset, length: match.range.length)
                if nsFullRange.location + nsFullRange.length <= result.length {
                    result.replaceCharacters(in: nsFullRange, with: NSAttributedString(string: boldText, attributes: boldAttrs))
                    offset -= (match.range.length - boldText.count)
                }
            }
        }
        
        // Process inline code: `text`
        let codePattern = #"`([^`]+)`"#
        if let regex = try? NSRegularExpression(pattern: codePattern) {
            var offset = 0
            let matches = regex.matches(in: text, range: NSRange(text.startIndex..., in: text))
            for match in matches {
                guard let contentRange = Range(match.range(at: 1), in: text) else { continue }
                
                let codeText = String(text[contentRange])
                var codeAttrs = baseAttributes
                codeAttrs[.font] = codeFont
                codeAttrs[.backgroundColor] = NSColor.textBackgroundColor.withAlphaComponent(0.3)
                
                let nsFullRange = NSRange(location: match.range.location + offset, length: match.range.length)
                if nsFullRange.location + nsFullRange.length <= result.length {
                    result.replaceCharacters(in: nsFullRange, with: NSAttributedString(string: codeText, attributes: codeAttrs))
                    offset -= (match.range.length - codeText.count)
                }
            }
        }
        
        return result
    }
    
    func makeCoordinator() -> Coordinator {
        Coordinator()
    }
    
    class Coordinator: NSObject, NSTextViewDelegate {
        var anchorPositions: [String: Int] = [:]
        weak var textView: NSTextView?
        weak var scrollView: NSScrollView?
        
        func textView(_ textView: NSTextView, clickedOnLink link: Any, at charIndex: Int) -> Bool {
            if let url = link as? URL {
                // Handle internal anchor links
                if url.scheme == "marcut-anchor" {
                    let anchorID = url.host ?? url.path
                    scrollToAnchor(anchorID)
                    return true
                }
                // External URL
                NSWorkspace.shared.open(url)
                return true
            } else if let urlString = link as? String {
                if urlString.hasPrefix("marcut-anchor:") {
                    let anchorID = String(urlString.dropFirst("marcut-anchor:".count))
                    scrollToAnchor(anchorID)
                    return true
                }
                if let url = URL(string: urlString) {
                    NSWorkspace.shared.open(url)
                    return true
                }
            }
            return false
        }
        
        func scrollToAnchor(_ anchorID: String) {
            guard let textView = textView,
                  let position = anchorPositions[anchorID] else {
                return
            }
            
            // Get the rect for this character position
            let layoutManager = textView.layoutManager!
            let textContainer = textView.textContainer!
            let glyphRange = layoutManager.glyphRange(forCharacterRange: NSRange(location: position, length: 1), actualCharacterRange: nil)
            let rect = layoutManager.boundingRect(forGlyphRange: glyphRange, in: textContainer)
            
            // Scroll to the position with some padding at the top
            let scrollPoint = NSPoint(x: 0, y: rect.origin.y - 20)
            textView.scroll(scrollPoint)
        }
    }
}

/// Preview provider for MarkdownTextView
#if DEBUG
struct MarkdownTextView_Previews: PreviewProvider {
    static var previews: some View {
        MarkdownTextView(markdownContent: """
        # Sample Markdown
        
        This is **bold** and this is *italic*.
        
        - [Jump to section](#another-section)
        - Item 2
        
        [Link](https://example.com)
        
        ## Another Section
        
        This is the section we jumped to.
        """, scrollToAnchor: .constant(nil))
        .frame(width: 400, height: 300)
    }
}
#endif
