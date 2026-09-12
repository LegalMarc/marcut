import Foundation

enum UnsavedReportQuitBehavior: Int, CaseIterable, Identifiable {
    case warn = 0
    case alwaysQuit = 1
    case alwaysCancel = 2

    var id: Int {
        rawValue
    }

    var label: String {
        switch self {
        case .warn:
            "Warn"
        case .alwaysQuit:
            "Always Quit"
        case .alwaysCancel:
            "Always Cancel"
        }
    }
}
