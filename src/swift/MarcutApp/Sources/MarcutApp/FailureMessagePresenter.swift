import Foundation

/// Maps a processing failure to a short, plain-English message with a suggested next action --
/// the single place that decides what a user sees in an alert when redaction or metadata
/// processing fails.
///
/// Before this existed, several call sites interpolated raw bridge/pipeline error text directly
/// into `DocumentItem.errorMessage` (e.g. `"Processing failed (\(code)): \(message)"` built
/// straight from the failure-report JSON's `error_code`/`message` fields, or the
/// `"Python error: \(error)"` strings `PythonKitBridge`'s `scrubMetadataOnlyAsync`/
/// `metadataReportOnlyAsync` produce when they catch a raw `PythonError`). That is exactly the
/// kind of bridge/traceback text ticket #46 (B4) asks to keep out of the alert headline.
///
/// Every call site continues to log the raw code/message/technical-details via `DebugLogger`
/// immediately alongside the friendly message produced here, so nothing is lost -- it just no
/// longer doubles as the primary, user-facing text. The in-app Log Viewer (Settings) is where
/// that detail lives.
enum FailureMessagePresenter {
    /// Appended to every message so a user who wants more detail knows exactly where to look.
    static let logHint = "See App Log in Settings for technical details."

    /// Generic fallback for an unknown or absent error code -- never a bare traceback as the
    /// headline.
    static let genericMessage = "Document processing failed."

    /// Known pipeline `error_code` values (see `RedactionError.error_code` / `_write_failure_report`
    /// in `marcut/pipeline.py`) mapped to a short, plain-English message with a suggested action.
    /// Codes not present here -- including bridge-level failures that never had a structured
    /// code to begin with -- fall back to `genericMessage`.
    private static let knownMessages: [String: String] = [
        "AI_SERVICE_UNAVAILABLE": "The AI service isn't reachable. Make sure Ollama is running, then try again.",
        "AI_MODEL_UNAVAILABLE": "The AI model isn't available. Try re-downloading it in Settings.",
        "AI_PROCESSING_TIMEOUT": "The AI model stopped responding in time. Try again, use a smaller document, or increase the Processing Timeout in Settings.",
        "AI_PROCESSING_FAILED": "The AI model stopped responding. Try again or re-download the model.",
        "AI_CHUNK_EXTRACTION_INCOMPLETE": "The AI could not fully scan this document, so it was not redacted. Try again or use a different model.",
        "DOC_LOAD_FAILED": "Marcut couldn't open this document. Confirm it's a valid, uncorrupted .docx file.",
        "RULES_ENGINE_FAILED": "The rules-based detector hit an error while scanning this document.",
        "OUTPUT_SAVE_FAILED": "Marcut couldn't save the redacted output. Check available disk space and folder permissions.",
        "ARTIFACT_FINALIZE_FAILED": "Marcut couldn't finalize the redacted output. Check available disk space and folder permissions.",
        "REPORT_SAVE_FAILED": "Marcut couldn't save the redaction report. Check available disk space and folder permissions.",
        "INVALID_MODE": "An unsupported redaction mode was requested.",
        "UNEXPECTED_FAILURE": "Something unexpected went wrong while processing this document.",
    ]

    /// - Parameter code: the pipeline's `error_code` when a structured failure report was
    ///   available, or `nil` for bridge-level failures that don't carry one.
    /// - Returns: a short, user-facing message ending in a pointer to the log for detail.
    static func message(forCode code: String?) -> String {
        let friendly = code.flatMap { knownMessages[$0] } ?? genericMessage
        return "\(friendly) \(logHint)"
    }
}
