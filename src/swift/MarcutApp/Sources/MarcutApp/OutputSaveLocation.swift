import Foundation

enum OutputSaveLocation: Int, CaseIterable, Identifiable {
    case downloads = 0
    case sameAsOriginal = 1
    case alwaysAsk = 2

    var id: Int { rawValue }

    var label: String {
        switch self {
        case .downloads:
            return "Downloads"
        case .sameAsOriginal:
            return "Same as Original"
        case .alwaysAsk:
            return "Always Ask"
        }
    }

    var requiresPrompt: Bool {
        self == .alwaysAsk
    }
}
