import Foundation

/// Pure-Swift port of the excluded-word matching rule used at redaction time by
/// `marcut.rules._is_excluded` (via `marcut.model._normalize_for_exclusion` /
/// `_matches_exclusion_literal` / `get_exclusion_data`).
///
/// This intentionally mirrors the production Python matching behavior term-for-term
/// (including its quirks, e.g. entries like "U.S." being treated as regex because of
/// the special character heuristic, and the double leading-determiner strip in
/// `_is_excluded` that matches phrases like "all such Notices") so a live preview in
/// Settings cannot diverge from what the redaction pipeline actually does. See
/// `src/python/marcut/model.py` and `src/python/marcut/rules.py` for the source of
/// truth this ports.
enum ExcludedWordMatcher {
    /// Leading determiners stripped before matching, in the same order/set as
    /// `marcut.model._DETERMINER_PREFIXES`.
    private static let determinerPrefixes = [
        "the", "a", "an", "this", "that", "such", "each", "any", "certain",
        "both", "all", "these", "those", "every", "either", "neither",
    ]

    private static let determinerPrefixRegex: NSRegularExpression = {
        let alternation = determinerPrefixes.joined(separator: "|")
        // Mirrors `_DETERMINER_PREFIX_RE = re.compile(rf"^(?:...)\s+", re.IGNORECASE)`
        let pattern = "^(?:\(alternation))\\s+"
        return try! NSRegularExpression(pattern: pattern, options: [.caseInsensitive])
    }()

    /// Characters stripped from a normalized phrase's trailing edge, mirroring
    /// Python's `text.rstrip(".,;:!?\"'")`.
    private static let trailingPunctuation = CharacterSet(charactersIn: ".,;:!?\"'")

    private static let whitespaceRunRegex = try! NSRegularExpression(pattern: "\\s+")

    /// A single compiled excluded-word entry: either a literal (already normalized
    /// for comparison) or a regex pattern (compiled case-insensitively, matched from
    /// the start of the determiner-stripped candidate text — mirrors `pattern.match`).
    struct CompiledEntry {
        let rawLine: String
        let literal: String?
        let pattern: NSRegularExpression?
    }

    struct MatchResult {
        let matched: Bool
        /// The original excluded-words.txt line that matched, if any.
        let matchedEntry: String?
    }

    /// Base terms that are ALWAYS excluded, regardless of the user's excluded-words
    /// file contents. Mirrors `marcut.model._get_base_excluded_literals` /
    /// `_BASE_EXCLUDED_LITERALS`, which `get_exclusion_data()` unconditionally merges
    /// into every lookup. These never appear in the editable sheet text, so the
    /// preview must still honor them or it will report "no match" for phrases (e.g.
    /// "Company", "the Board of Directors") the pipeline actually treats as excluded.
    private static let baseExcludedTerms = [
        "agreement", "section", "article", "recital", "exhibit", "schedule", "appendix", "annex",
        "notice", "resolution", "minutes", "consent", "meeting", "vote", "bylaws", "charter",
        "company", "corporation", "board", "board of directors", "stockholder", "stockholders",
        "member", "members", "party", "parties", "purchaser", "seller", "target", "counterparty",
        "dgcl", "act", "law", "statute", "code", "regulation", "ccpa",
    ]

    /// Compiled entries for `baseExcludedTerms`, including auto-generated plurals for
    /// terms not already ending in "s" (mirrors `_get_base_excluded_literals`).
    static let baseEntries: [CompiledEntry] = {
        var seen = Set<String>()
        var entries: [CompiledEntry] = []
        for term in baseExcludedTerms {
            let normalized = normalizeForExclusion(term)
            if seen.insert(normalized).inserted {
                entries.append(CompiledEntry(rawLine: term, literal: normalized, pattern: nil))
            }
            if !normalized.hasSuffix("s") {
                let plural = normalized + "s"
                if seen.insert(plural).inserted {
                    entries.append(CompiledEntry(rawLine: term, literal: plural, pattern: nil))
                }
            }
        }
        return entries
    }()

    /// Mirrors `marcut.model._is_regex_pattern`: a line is treated as regex if it
    /// contains any regex metacharacter.
    static func isRegexPattern(_ line: String) -> Bool {
        line.range(of: "[\\\\^$.*+?{}()\\[\\]|]", options: .regularExpression) != nil
    }

    /// Compile the lines of an excluded-words file (one term/pattern per line,
    /// blank lines and `#`-comments ignored) into matchable entries. Invalid regex
    /// lines are skipped, mirroring the Python loader's `except re.error` handling.
    static func compileEntries(fromLines lines: [String]) -> [CompiledEntry] {
        var entries: [CompiledEntry] = []
        entries.reserveCapacity(lines.count)
        for rawLine in lines {
            let line = rawLine.trimmingCharacters(in: .whitespaces)
            if line.isEmpty || line.hasPrefix("#") {
                continue
            }
            if isRegexPattern(line) {
                if let regex = try? NSRegularExpression(pattern: line, options: [.caseInsensitive]) {
                    entries.append(CompiledEntry(rawLine: line, literal: nil, pattern: regex))
                }
                // Invalid regex: silently skipped, matching Python's warn-and-continue.
            } else {
                entries.append(CompiledEntry(rawLine: line, literal: normalizeForExclusion(line), pattern: nil))
            }
        }
        return entries
    }

    static func compileEntries(fromFileContents contents: String) -> [CompiledEntry] {
        compileEntries(fromLines: contents.components(separatedBy: .newlines))
    }

    /// Compile the entries a live preview should match against: the always-on base
    /// terms plus whatever is currently in the (possibly unsaved) editor text.
    static func compileAllEntries(editorText: String) -> [CompiledEntry] {
        baseEntries + compileEntries(fromFileContents: editorText)
    }

    /// Strip a single leading determiner (e.g. "the", "a", "certain") and its
    /// following whitespace. Mirrors `marcut.model._strip_leading_determiner`.
    static func stripLeadingDeterminer(_ text: String) -> String {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        let range = NSRange(trimmed.startIndex..., in: trimmed)
        guard let match = determinerPrefixRegex.firstMatch(in: trimmed, options: [], range: range),
              let matchRange = Range(match.range, in: trimmed)
        else {
            return trimmed
        }
        return String(trimmed[matchRange.upperBound...])
    }

    /// Normalize a phrase for exclusion comparison: strip leading determiner,
    /// lowercase, strip trailing punctuation, collapse internal whitespace.
    /// Mirrors `marcut.model._normalize_for_exclusion`.
    static func normalizeForExclusion(_ text: String) -> String {
        var result = stripLeadingDeterminer(text)
        result = result.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        while let last = result.unicodeScalars.last, trailingPunctuation.contains(last) {
            result.removeLast()
        }
        let range = NSRange(result.startIndex..., in: result)
        result = whitespaceRunRegex.stringByReplacingMatches(in: result, options: [], range: range, withTemplate: " ")
        return result
    }

    /// Compute the singular candidate used for simple plural equivalence, mirroring
    /// `marcut.model._matches_exclusion_literal`'s singularization branches. Returns
    /// `nil` when no singularization rule applies.
    private static func singularCandidate(for normalized: String) -> String? {
        if normalized.range(of: "\\(s\\)\\s*$", options: .regularExpression) != nil {
            return normalized
                .replacingOccurrences(of: "\\(s\\)\\s*$", with: "", options: .regularExpression)
                .trimmingCharacters(in: .whitespaces)
        } else if normalized.hasSuffix("ies"), normalized.count > 3 {
            return String(normalized.dropLast(3)) + "y"
        } else if normalized.hasSuffix("s"), normalized.count > 1 {
            return String(normalized.dropLast()).trimmingTrailingWhitespace()
        }
        return nil
    }

    /// Find the literal entry (if any) whose normalized literal equals `normalized`
    /// exactly, or equals its singularized form. Mirrors
    /// `marcut.model._matches_exclusion_literal`.
    private static func matchingLiteralEntry(for normalized: String, entries: [CompiledEntry]) -> CompiledEntry? {
        if let exact = entries.first(where: { $0.literal == normalized }) {
            return exact
        }
        if let singular = singularCandidate(for: normalized) {
            return entries.first(where: { $0.literal == singular })
        }
        return nil
    }

    /// Core matching entry point: does `text` match any compiled excluded-word
    /// entry (literal — including simple plural/singular equivalence — or regex)?
    /// Mirrors `marcut.rules._is_excluded`.
    static func match(_ text: String, entries: [CompiledEntry]) -> MatchResult {
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return MatchResult(matched: false, matchedEntry: nil)
        }

        let textClean = stripLeadingDeterminer(text)
        let normalized = normalizeForExclusion(text)

        if let hit = matchingLiteralEntry(for: normalized, entries: entries) {
            return MatchResult(matched: true, matchedEntry: hit.rawLine)
        }

        // A determiner was stripped from `text` to produce `textClean`. Mirrors
        // `rules.py:112-117`: re-normalize the already-stripped `textClean` (which
        // strips a SECOND leading determiner if present, e.g. "all such Notices" ->
        // "such Notices" -> "Notices") and run the literal match again before
        // falling through to the regex slow path.
        if textClean != text {
            let normalizedClean = normalizeForExclusion(textClean)
            if let hit = matchingLiteralEntry(for: normalizedClean, entries: entries) {
                return MatchResult(matched: true, matchedEntry: hit.rawLine)
            }
        }

        // Slow path: regex patterns, matched from the start of the
        // determiner-stripped (but not case/whitespace-normalized) text.
        let cleanRange = NSRange(textClean.startIndex..., in: textClean)
        for entry in entries {
            guard let pattern = entry.pattern else { continue }
            // `.anchored` restricts the match to start exactly at `cleanRange.location`,
            // mirroring Python's `pattern.match()` (start-anchored, not full-string).
            if pattern.firstMatch(in: textClean, options: [.anchored], range: cleanRange) != nil {
                return MatchResult(matched: true, matchedEntry: entry.rawLine)
            }
        }

        return MatchResult(matched: false, matchedEntry: nil)
    }
}

private extension String {
    func trimmingTrailingWhitespace() -> String {
        var result = self
        while let last = result.last, last.isWhitespace {
            result.removeLast()
        }
        return result
    }
}
