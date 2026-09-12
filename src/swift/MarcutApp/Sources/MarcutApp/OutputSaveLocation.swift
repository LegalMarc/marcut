import Foundation

enum OutputSaveLocation: Int, CaseIterable, Identifiable {
    case downloads = 0
    case sameAsOriginal = 1
    case alwaysAsk = 2

    var id: Int {
        rawValue
    }

    var label: String {
        switch self {
        case .downloads:
            "Downloads"
        case .sameAsOriginal:
            "Same as Original"
        case .alwaysAsk:
            "Always Ask"
        }
    }

    var requiresPrompt: Bool {
        self == .alwaysAsk
    }
}
