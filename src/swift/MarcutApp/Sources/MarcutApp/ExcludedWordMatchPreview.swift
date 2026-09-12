import SwiftUI

/// Live "does this phrase match an excluded-word entry" preview shown in the
/// excluded-words `OverrideEditorSheet`. Matches against the same rule the redaction
/// pipeline uses (`ExcludedWordMatcher`, ported from `marcut.rules._is_excluded`),
/// evaluated against the sheet's in-progress (possibly unsaved) text.
struct ExcludedWordMatchPreview: View {
    let excludedWordsText: String

    @State private var testPhrase: String = ""
    @State private var debouncedPhrase: String = ""
    @State private var debounceTask: Task<Void, Never>?
    @Environment(\.colorScheme) private var colorScheme

    /// Small debounce so a fast typist doesn't recompile/match on every keystroke.
    private static let debounceNanoseconds: UInt64 = 150_000_000

    private var compiledEntries: [ExcludedWordMatcher.CompiledEntry] {
        ExcludedWordMatcher.compileAllEntries(editorText: excludedWordsText)
    }

    private var result: ExcludedWordMatcher.MatchResult? {
        guard !debouncedPhrase.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            return nil
        }
        return ExcludedWordMatcher.match(debouncedPhrase, entries: compiledEntries)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text("Test a Phrase")
                .font(.system(size: 13, weight: .medium))
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))

            HStack(spacing: 10) {
                TextField("Type a phrase to test against the terms above…", text: $testPhrase)
                    .textFieldStyle(.roundedBorder)
                    .accessibilityIdentifier("settings.override.matchPreview.input")
                    .onChange(of: testPhrase) { _, newValue in
                        debounceTask?.cancel()
                        debounceTask = Task {
                            try? await Task.sleep(nanoseconds: Self.debounceNanoseconds)
                            guard !Task.isCancelled else { return }
                            await MainActor.run {
                                debouncedPhrase = newValue
                            }
                        }
                    }

                matchIndicator
                    .accessibilityIdentifier("settings.override.matchPreview.result")
            }
        }
        .onAppear {
            debouncedPhrase = testPhrase
        }
    }

    @ViewBuilder
    private var matchIndicator: some View {
        if let result {
            if result.matched {
                Label(
                    result.matchedEntry.map { "Matches: \($0)" } ?? "Matches",
                    systemImage: "checkmark.circle.fill"
                )
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.green)
                .lineLimit(1)
                .truncationMode(.tail)
            } else {
                Label("No match", systemImage: "xmark.circle")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }
        } else {
            Color.clear.frame(width: 1, height: 1)
        }
    }
}
