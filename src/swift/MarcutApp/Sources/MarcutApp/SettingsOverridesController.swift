import Foundation

/// Excluded-words / system-prompt override-editing glue, extracted from `SettingsView`
/// (`docs/design/view_controller_decomposition.md` §2.2, slice 6). `@State`-driven UI glue
/// backed by `UserOverridesManager` (already a singleton service, so this mostly moves
/// draft/baseline state and open/save/cancel/restore functions rather than logic). An
/// `ObservableObject` -- unlike the view-model collaborators extracted in prior slices, which
/// keep `@Published` state on `DocumentRedactionViewModel` and take closures -- because
/// `SettingsView` itself has no separate model object to hold that state; the view binds
/// directly to this controller's published drafts/baselines/flags via `@StateObject`.
@MainActor
final class SettingsOverridesController: ObservableObject {
    @Published var isCustomExcludedWords: Bool
    @Published var isCustomSystemPrompt: Bool
    @Published var showingExcludedWordsEditor = false
    @Published var showingSystemPromptEditor = false
    @Published var excludedWordsDraft = ""
    @Published var excludedWordsBaseline = ""
    @Published var systemPromptDraft = ""
    @Published var systemPromptBaseline = ""
    @Published var overrideErrorMessage: String?

    private let overridesManager: UserOverridesManager

    init(overridesManager: UserOverridesManager = .shared) {
        self.overridesManager = overridesManager
        isCustomExcludedWords = overridesManager.hasCustomExcludedWords
        isCustomSystemPrompt = overridesManager.hasCustomSystemPrompt
    }

    // MARK: - Excluded Words

    func openExcludedWordsEditor() {
        do {
            let text = try overridesManager.loadExcludedWords()
            excludedWordsBaseline = text
            excludedWordsDraft = text
            showingExcludedWordsEditor = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    func saveExcludedWords() {
        do {
            try overridesManager.saveExcludedWords(excludedWordsDraft)
            excludedWordsBaseline = excludedWordsDraft
            showingExcludedWordsEditor = false
            isCustomExcludedWords = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    func resetExcludedWordsToDefault() {
        overridesManager.restoreDefaultExcludedWords()
        isCustomExcludedWords = false
    }

    func cancelExcludedWordsEditing() {
        excludedWordsDraft = excludedWordsBaseline
        showingExcludedWordsEditor = false
    }

    func restoreExcludedWordsDefaults() {
        do {
            excludedWordsDraft = try overridesManager.defaultExcludedWords()
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    // MARK: - System Prompt

    func openSystemPromptEditor() {
        do {
            let text = try overridesManager.loadSystemPrompt()
            systemPromptBaseline = text
            systemPromptDraft = text
            showingSystemPromptEditor = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    func saveSystemPrompt() {
        do {
            try overridesManager.saveSystemPrompt(systemPromptDraft)
            systemPromptBaseline = systemPromptDraft
            showingSystemPromptEditor = false
            isCustomSystemPrompt = true
        } catch {
            overrideErrorMessage = error.localizedDescription
        }
    }

    func resetSystemPromptToDefault() {
        overridesManager.restoreDefaultSystemPrompt()
        isCustomSystemPrompt = false
    }

    func cancelSystemPromptEditing() {
        systemPromptDraft = systemPromptBaseline
        showingSystemPromptEditor = false
    }

    func restoreSystemPromptDefaults() {
        systemPromptDraft = overridesManager.defaultSystemPromptText()
    }
}
