import SwiftUI
import UniformTypeIdentifiers
import Foundation

// MARK: - Data Models

struct ReportViewerItem: Identifiable {
    let id = UUID()
    let url: URL
    let title: String
}

@MainActor
final class DocumentItem: Identifiable, ObservableObject {
    let id = UUID()
    let url: URL
    @Published var status: RedactionStatus = .checking
    @Published var errorMessage: String? = nil
    @Published var progress: Double = 0.0
    @Published var redactedOutputURL: URL? = nil
    @Published var reportOutputURL: URL? = nil
    @Published var reportHTMLOutputURL: URL? = nil
    
    // Metadata scrubbing results
    @Published var scrubOutputURL: URL? = nil
    @Published var scrubReportOutputURL: URL? = nil
    @Published var scrubReportHTMLOutputURL: URL? = nil
    @Published var metadataReportOutputURL: URL? = nil
    @Published var metadataReportHTMLOutputURL: URL? = nil
    @Published var metadataReport: [String: Any]? = nil
    @Published var metadataReportErrorMessage: String? = nil
    @Published var metadataReportNeedsPermissionRetry: Bool = false
    @Published var lastOperation: DocumentOperation? = nil

    // File paths for Python processing
    var outputPath: String? = nil
    var reportPath: String? = nil

    // Enhanced progress tracking
    @Published var currentStage: ProcessingStage = .preflight
    @Published var stageProgress: Double = 0.0
    @Published var estimatedTimeRemaining: TimeInterval = 0.0
    @Published var startTime: Date? = nil
    @Published var documentComplexity: DocumentComplexity = .unknown
    @Published var lastTimeUpdate: Date = Date()
    @Published var allStages: [ProcessingStage] = ProcessingStage.allCases
    private var stageStartTime: Date? = nil
    private var stageExpectedDuration: TimeInterval = 0.0
    private var stageBaseDuration: TimeInterval = 0.0
    private var progressRange: ClosedRange<Double> = 0.0...1.0
    @Published var wordCount: Int? = nil
    @Published var lastHeartbeat: Date? = nil
    @Published var lastHeartbeatChunk: Int = 0
    @Published var totalHeartbeatChunks: Int = 0
    @Published var lastDestinationURL: URL? = nil
    
    // Mass-based progress tracking
    @Published var totalMass: Int = 0
    @Published var processedMass: Int = 0
    private var currentChunkMass: Int = 0
    private var massStartTime: Date? = nil
    private var pendingTotalMass: Int? = nil
    private var chunkStartTime: Date? = nil
    private var smoothedCharsPerSecond: Double? = nil

    // File access management
    private(set) var hasSecurityScope: Bool = false

    // MARK: - Smooth Progress Animation Properties
    private var smoothProgressTimer: Timer?
    private var targetProgress: Double = 0.0
    private var currentVelocity: Double = 0.0
    private var lastProgressUpdate: Date = Date()
    private var microProgressActive: Bool = false
    private var microProgressTimer: Timer?

    // Animation parameters
    private let smoothingFactor: Double = 0.15      // Higher = smoother but slower response
    private let maxVelocity: Double = 0.8             // Max progress units per second
    private let acceleration: Double = 0.3            // Acceleration rate
    private let microProgressSpeed: Double = 0.02     // Small forward movement per tick
    private let microProgressInterval: TimeInterval = 0.1  // 100ms micro-updates

    // Computed property for file path
    var path: String {
        return url.path
    }

    init(url: URL) {
        self.url = url
        self.startTime = Date()
        self.lastTimeUpdate = Date()
    }

    deinit {
        if hasSecurityScope {
            url.stopAccessingSecurityScopedResource()
        }
    }
    
    // Smart time estimation that can adjust up or down
    func updateTimeEstimate(_ newEstimate: TimeInterval) {
        let now = Date()
        let clampedEstimate = max(0.0, newEstimate)
        let delta = now.timeIntervalSince(lastTimeUpdate)

        // Less aggressive smoothing to reduce visual noise
        let smoothing = min(1.0, max(0.05, delta / 5.0))

        // Only update if there's a significant change to reduce noise
        let timeDiff = abs(estimatedTimeRemaining - clampedEstimate)
        if timeDiff > 2.0 || delta > 1.0 {
            if estimatedTimeRemaining <= 0.0 {
                estimatedTimeRemaining = clampedEstimate
            } else {
                estimatedTimeRemaining = (1 - smoothing) * estimatedTimeRemaining + smoothing * clampedEstimate
            }
        }

        lastTimeUpdate = now
    }
    
    func beginStage(_ stage: ProcessingStage) {
        // Stop any existing animations before stage transition
        stopMicroProgress()

        if stage == .preflight {
            resetMassTracking()
        }

        currentStage = stage
        stageProgress = 0.0
        progressRange = stage.progressRange
        // Apply complexity multiplier to stage duration
        stageBaseDuration = stage.expectedDuration * documentComplexity.multiplier
        stageExpectedDuration = stageBaseDuration
        stageStartTime = Date()
        lastTimeUpdate = Date()
        lastHeartbeat = Date()
        lastHeartbeatChunk = 0
        totalHeartbeatChunks = 0
        let totalRemaining = stageExpectedDuration + remainingDuration(after: stage)
        estimatedTimeRemaining = totalRemaining
        updateTimeEstimate(totalRemaining)

        // Animate to new stage start position
        setTargetProgress(progressRange.lowerBound, isChunkUpdate: false)

        if stage == .enhancedDetection, let pending = pendingTotalMass {
            applyMassTotal(pending)
            pendingTotalMass = nil
        }
    }

    func concludeCurrentStage() {
        stopMicroProgress()
        stageProgress = 1.0
        stageStartTime = nil
        let remaining = remainingDuration(after: currentStage)
        estimatedTimeRemaining = remaining
        updateTimeEstimate(remaining)

        // Animate smoothly to stage completion
        setTargetProgress(progressRange.upperBound, isChunkUpdate: false)
    }

    func recordHeartbeat(chunkIndex: Int, totalChunks: Int) {
        lastHeartbeat = Date()
        lastHeartbeatChunk = chunkIndex
        totalHeartbeatChunks = totalChunks

        guard totalChunks > 0 else { return }

        let chunkFraction = min(max(Double(chunkIndex) / Double(totalChunks), 0.0), 1.0)
        stageProgress = max(stageProgress, chunkFraction)

        let stageLower = progressRange.lowerBound
        let stageUpper = progressRange.upperBound
        let absoluteProgress = stageLower + (chunkFraction * (stageUpper - stageLower))

        if absoluteProgress > targetProgress {
            setTargetProgress(absoluteProgress, isChunkUpdate: true)
        }

        startMicroProgress()
    }

    func recordHeartbeatOnly(chunkIndex: Int, totalChunks: Int) {
        lastHeartbeat = Date()
        lastHeartbeatChunk = chunkIndex
        totalHeartbeatChunks = totalChunks
    }

    /// Applies fractional progress within the current stage without altering chunk counters.
    func applyStageProgressFraction(_ fraction: Double) {
        let clamped = min(max(fraction, 0.0), 1.0)
        stageProgress = clamped
        let targetStageProgress = progressRange.lowerBound + clamped * (progressRange.upperBound - progressRange.lowerBound)
        setTargetProgress(targetStageProgress, isChunkUpdate: false)
        startMicroProgress()
    }

    /// Applies an explicit overall progress value from the backend (0.0–1.0).
    func setExplicitProgress(_ value: Double) {
        let clamped = min(max(value, progressRange.lowerBound), progressRange.upperBound)
        if clamped > targetProgress {
            setTargetProgress(clamped, isChunkUpdate: false)
        }
        lastHeartbeat = Date()
        startMicroProgress()
    }

    // MARK: - Smooth Progress Animation Methods

    /// Applies angular easing to create natural acceleration/deceleration curves
    @MainActor
    private func applyAngularEasing(_ t: Double) -> Double {
        // Angular easing with smooth acceleration and deceleration
        // t: 0.0 -> 1.0
        let adjustedT = min(max(t, 0.0), 1.0)

        if adjustedT < 0.5 {
            // Acceleration phase: smooth cubic curve
            return 2.0 * adjustedT * adjustedT * adjustedT
        } else {
            // Deceleration phase: inverted cubic curve
            let f = 2.0 * (1.0 - adjustedT)
            return 1.0 - f * f * f
        }
    }

    /// Sets target progress and starts smooth animation
    private func setTargetProgress(_ newTarget: Double, isChunkUpdate: Bool = false) {
        targetProgress = min(max(newTarget, 0.0), 1.0)
        lastProgressUpdate = Date()

        // Stop existing timers
        smoothProgressTimer?.invalidate()

        // If this is a significant jump (chunk update), use momentum-based animation
        if isChunkUpdate {
            let progressDelta = abs(targetProgress - progress)

            // Calculate appropriate velocity based on distance
            let targetVelocity = min(maxVelocity, progressDelta * 2.0) // Faster for bigger jumps
            currentVelocity = targetVelocity

            // Start momentum-based animation
            startMomentumAnimation()
        } else {
            // For small adjustments, use direct smooth interpolation
            startSmoothAnimation()
        }
    }

    /// Starts momentum-based animation for chunk updates
    @MainActor
    private func startMomentumAnimation() {
        smoothProgressTimer = Timer.scheduledTimer(withTimeInterval: 0.016, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            Task { @MainActor in
                self.updateMomentumProgress()
            }
        }
    }

    /// Updates progress using controlled interpolation (no backward progress)
    @MainActor
    private func updateMomentumProgress() {
        let now = Date()
        let deltaTime = now.timeIntervalSince(lastProgressUpdate)
        lastProgressUpdate = now

        let progressDelta = targetProgress - progress

        // Prevent backward progress - only move forward
        guard progressDelta > 0.001 else {
            // We're at or very close to target
            progress = targetProgress
            currentVelocity = 0.0
            smoothProgressTimer?.invalidate()
            smoothProgressTimer = nil
            return
        }

        // Calculate appropriate velocity based on distance
        let targetVelocity = min(maxVelocity, progressDelta * 2.0) // Faster for bigger jumps
        let velocityDelta = (targetVelocity - currentVelocity) * smoothingFactor

        // Update velocity with smoothing
        currentVelocity += velocityDelta * deltaTime
        currentVelocity = min(maxVelocity, currentVelocity) // Clamp to max

        // Update progress (always forward)
        let newProgress = progress + currentVelocity * deltaTime

        // Check if we've reached or overshot the target
        if newProgress >= targetProgress {
            progress = targetProgress
            currentVelocity = 0.0
            smoothProgressTimer?.invalidate()
            smoothProgressTimer = nil
        } else {
            progress = newProgress
        }
    }

    /// Starts smooth interpolation for small adjustments
    @MainActor
    private func startSmoothAnimation() {
        let initialProgress = progress
        let startTime = Date()

        smoothProgressTimer = Timer.scheduledTimer(withTimeInterval: 0.016, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            Task { @MainActor in
                let elapsed = Date().timeIntervalSince(startTime)
                let progress = min(elapsed * 3.0, 1.0) // 0.33 second animation

                self.progress = initialProgress + (self.targetProgress - initialProgress) * self.applyAngularEasing(progress)

                if progress >= 1.0 {
                    self.progress = self.targetProgress
                    self.smoothProgressTimer?.invalidate()
                    self.smoothProgressTimer = nil
                }
            }
        }
    }

    /// Starts micro-progress to show activity during chunk processing
    @MainActor
    private func startMicroProgress() {
        guard !microProgressActive else { return }

        microProgressActive = true
        microProgressTimer?.invalidate()

        microProgressTimer = Timer.scheduledTimer(withTimeInterval: microProgressInterval, repeats: true) { [weak self] timer in
            guard let self = self else {
                timer.invalidate()
                return
            }
            Task { @MainActor in
                // Only add forward movement, never backward
                let forwardSpace = self.targetProgress - self.progress
                if forwardSpace > 0.001 {
                    // Take smaller steps as we get closer to target
                    let microIncrement = min(self.microProgressSpeed, forwardSpace * 0.5)
                    let newProgress = self.progress + microIncrement

                    // Ensure we don't exceed target
                    if newProgress < self.targetProgress {
                        self.progress = newProgress
                    } else {
                        self.progress = self.targetProgress
                        self.stopMicroProgress()
                    }
                } else {
                    // We're at or very close to target
                    self.progress = self.targetProgress
                    self.stopMicroProgress()
                }
            }
        }
    }

    /// Stops micro-progress animation
    private func stopMicroProgress() {
        microProgressActive = false
        microProgressTimer?.invalidate()
        microProgressTimer = nil
    }

    /// Cleans up animation timers
    func cleanupProgressAnimations() {
        smoothProgressTimer?.invalidate()
        smoothProgressTimer = nil
        microProgressTimer?.invalidate()
        microProgressTimer = nil
        microProgressActive = false
        currentVelocity = 0.0
    }

    /// Marks processing as complete with smooth final animation
    func markProcessingComplete(success: Bool) {
        stopMicroProgress()
        cleanupProgressAnimations()

        if success {
            // Animate to 100% completion
            setTargetProgress(1.0)
        } else {
            // Reset progress for retry
            setTargetProgress(progress) // This will animate to current position then stop
        }
    }

    func updateEstimatesForCurrentTime() {
        // If using mass-based tracking during extraction phase, use specialized logic
        if currentStage == .enhancedDetection && totalMass > 0 {
            updateMassBasedEstimate()
            return
        }
    
        guard let start = stageStartTime else { return }

        let elapsed = Date().timeIntervalSince(start)

        let minDuration = max(stageExpectedDuration, 1.0)
        if elapsed > minDuration {
            stageExpectedDuration = elapsed * 1.2
        }

        let timeFraction = min(elapsed / stageExpectedDuration, 0.95)
        stageProgress = max(stageProgress, timeFraction)

        let stageLower = progressRange.lowerBound
        let stageUpper = progressRange.upperBound
        let estimatedGlobalProgress = stageLower + (timeFraction * (stageUpper - stageLower))

        if estimatedGlobalProgress > targetProgress + 0.001 {
            setTargetProgress(estimatedGlobalProgress, isChunkUpdate: false)
        }

        let remainingCurrentStage = max(stageExpectedDuration - elapsed, 0.0)
        let totalRemaining = remainingCurrentStage + remainingDuration(after: currentStage)
        updateTimeEstimate(totalRemaining)
    }

    var isMassTrackingActive: Bool {
        currentStage == .enhancedDetection && totalMass > 0
    }

    @MainActor
    func ingestProgressPayload(_ payload: String) -> Bool {
        let trimmed = payload.trimmingCharacters(in: .whitespacesAndNewlines)
        guard trimmed.hasPrefix("{"),
              let data = trimmed.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else {
            return false
        }

        if currentStage != .enhancedDetection && type == "mass_total" {
            pendingTotalMass = intValue(from: json["value"])
            return true
        }

        if currentStage != .enhancedDetection {
            return true
        }

        switch type {
        case "mass_total":
            if let value = intValue(from: json["value"]) {
                applyMassTotal(value)
            }
            return true
        case "chunk_start":
            let size = intValue(from: json["size"]) ?? 0
            let estimated = doubleValue(from: json["estimated_time"]) ?? 0.0
            applyChunkStart(size: size, estimatedTime: estimated)
            return true
        case "chunk_end":
            if let size = intValue(from: json["size"]) {
                applyChunkEnd(size: size)
            }
            return true
        case "keepalive":
            // Keep-alive signals carry chunk info for progress updates during LLM calls
            // This ensures the progress bar advances even when waiting on long LLM responses
            if let chunk = intValue(from: json["chunk"]),
               let total = intValue(from: json["total"]) {
                lastHeartbeat = Date()
                lastHeartbeatChunk = chunk
                totalHeartbeatChunks = total
                
                // Update progress based on chunk ratio if we don't have mass tracking
                // or if mass tracking underestimates progress
                if totalMass == 0 && total > 0 {
                    let chunkFraction = min(max(Double(chunk) / Double(total), 0.0), 1.0)
                    let stageLower = progressRange.lowerBound
                    let stageUpper = progressRange.upperBound
                    let chunkProgress = stageLower + (chunkFraction * (stageUpper - stageLower))
                    if chunkProgress > targetProgress {
                        setTargetProgress(chunkProgress, isChunkUpdate: true)
                    }
                }
            }
            return true
        default:
            return false
        }
    }

    private func updateMassBasedEstimate() {
        guard totalMass > 0 else { return }
        
        if massStartTime == nil {
            massStartTime = Date()
        }

        let now = Date()
        let overallElapsed = max(now.timeIntervalSince(massStartTime ?? now), 0.0)
        let chunkContribution = Double(currentChunkMass)
        var progressThroughChunk = 0.0
        var interpolatedChunkMass = 0.0

        // Add time-interpolated progress for current chunk
        if currentChunkMass > 0, let start = chunkStartTime {
            let chunkElapsed = max(now.timeIntervalSince(start), 0.0)
            // Asymptotically approach 95% of the chunk
            let expected = max(stageExpectedDuration, 1.0)
            progressThroughChunk = min(chunkElapsed / expected, 0.95)
            interpolatedChunkMass = chunkContribution * progressThroughChunk
        }
        
        let effectiveProcessed = Double(processedMass) + interpolatedChunkMass
        let totalFraction = min(max(effectiveProcessed / Double(totalMass), 0.0), 1.0)
        
        // Apply to valid range for this stage
        let stageLower = progressRange.lowerBound
        let stageUpper = progressRange.upperBound
        let globalProgress = stageLower + (totalFraction * (stageUpper - stageLower))
        
        if globalProgress > targetProgress {
            setTargetProgress(globalProgress, isChunkUpdate: false)
        }
        
        if overallElapsed > 0.0 && effectiveProcessed > 0.0 {
            let rate = effectiveProcessed / overallElapsed
            let remainingMass = max(Double(totalMass) - effectiveProcessed, 0.0)
            let remainingCurrentStage = remainingMass / max(rate, 1.0)
            let totalRemaining = remainingCurrentStage + remainingDuration(after: currentStage)
            updateTimeEstimate(totalRemaining)
        }
    }

    private func applyMassTotal(_ value: Int) {
        totalMass = max(value, 0)
        processedMass = 0
        currentChunkMass = 0
        massStartTime = Date()
        chunkStartTime = nil
        smoothedCharsPerSecond = nil
        stageProgress = 0.0
        setTargetProgress(progressRange.lowerBound, isChunkUpdate: true)
    }

    private func applyChunkStart(size: Int, estimatedTime: Double) {
        currentChunkMass = max(size, 0)
        chunkStartTime = Date()
        let minDuration = 1.0
        let maxDuration = 240.0
        if let rate = smoothedCharsPerSecond, rate > 0, currentChunkMass > 0 {
            let inferred = Double(currentChunkMass) / rate
            stageExpectedDuration = min(max(inferred, minDuration), maxDuration)
        } else if estimatedTime > 0 {
            stageExpectedDuration = min(max(estimatedTime, minDuration), maxDuration)
        }
        updateMassBasedEstimate()
    }

    private func applyChunkEnd(size: Int) {
        if let start = chunkStartTime, size > 0 {
            let duration = max(Date().timeIntervalSince(start), 0.5)
            let rate = Double(size) / duration
            if rate.isFinite && rate > 0 {
                if let existing = smoothedCharsPerSecond {
                    smoothedCharsPerSecond = existing * 0.7 + rate * 0.3
                } else {
                    smoothedCharsPerSecond = rate
                }
            }
        }
        let adjustedSize = max(size, 0)
        if totalMass > 0 {
            processedMass = min(processedMass + adjustedSize, totalMass)
        } else {
            processedMass += adjustedSize
        }
        currentChunkMass = 0
        chunkStartTime = nil
        updateMassBasedEstimate()
    }

    private func resetMassTracking() {
        totalMass = 0
        processedMass = 0
        currentChunkMass = 0
        massStartTime = nil
        pendingTotalMass = nil
        chunkStartTime = nil
        smoothedCharsPerSecond = nil
    }

    private func intValue(from value: Any?) -> Int? {
        if let intValue = value as? Int {
            return intValue
        }
        if let number = value as? NSNumber {
            return number.intValue
        }
        if let string = value as? String, let intValue = Int(string) {
            return intValue
        }
        return nil
    }

    private func doubleValue(from value: Any?) -> Double? {
        if let doubleValue = value as? Double {
            return doubleValue
        }
        if let number = value as? NSNumber {
            return number.doubleValue
        }
        if let string = value as? String, let doubleValue = Double(string) {
            return doubleValue
        }
        return nil
    }

    func markProcessingCompleted() {
        stageProgress = 1.0
        progress = 1.0
        stageStartTime = nil
        estimatedTimeRemaining = 0.0
        lastTimeUpdate = Date()
        lastHeartbeat = Date()
    }

    private func remainingDuration(after stage: ProcessingStage) -> TimeInterval {
        guard let index = allStages.firstIndex(of: stage) else { return 0 }
        let remainingStages = allStages.suffix(from: index + 1)
        // Apply complexity multiplier to remaining durations
        return remainingStages.reduce(0.0) { $0 + ($1.expectedDuration * documentComplexity.multiplier) }
    }

    // MARK: - Security Scope Management

    /// Acquire security-scoped resource access if needed
    func acquireSecurityScope() -> Bool {
        guard !hasSecurityScope else { return true }

        // Try to access the file with security-scoped resource if needed
        hasSecurityScope = url.startAccessingSecurityScopedResource()
        return hasSecurityScope
    }

    /// Release security-scoped resource access
    func releaseSecurityScope() {
        guard hasSecurityScope else { return }

        url.stopAccessingSecurityScopedResource()
        hasSecurityScope = false
    }

    /// Ensure file is accessible, acquiring security scope if needed
    func ensureFileAccess() -> Bool {
        if !hasSecurityScope {
            _ = acquireSecurityScope()
        }
        return FileManager.default.isReadableFile(atPath: url.path)
    }
}

enum ProcessingStage: CaseIterable {
    case preflight
    case ruleDetection
    case llmValidation
    case enhancedDetection
    case merging
    case outputGeneration
    
    var displayName: String {
        switch self {
        case .preflight: return "Loading Document"
        case .ruleDetection: return "Detecting Data"
        case .llmValidation: return "Validating Entities"
        case .enhancedDetection: return "AI Analysis"
        case .merging: return "Merging Results"
        case .outputGeneration: return "Creating Output"
        }
    }

    var expectedDuration: TimeInterval {
        switch self {
        case .preflight: return 5
        case .ruleDetection: return 15
        case .llmValidation: return 20
        case .enhancedDetection: return 120  // Most time-consuming
        case .merging: return 12
        case .outputGeneration: return 18
        }
    }

    var icon: String {
        switch self {
        case .preflight: return "checkmark.shield"
        case .ruleDetection: return "text.magnifyingglass"
        case .llmValidation: return "brain"
        case .enhancedDetection: return "sparkles"
        case .merging: return "arrow.triangle.merge"
        case .outputGeneration: return "doc.badge.gearshape"
        }
    }

    var progressRange: ClosedRange<Double> {
        switch self {
        case .preflight: return 0.0...0.12
        case .ruleDetection: return 0.12...0.25
        case .llmValidation: return 0.25...0.40
        case .enhancedDetection: return 0.40...0.80
        case .merging: return 0.80...0.92
        case .outputGeneration: return 0.92...1.0
        }
    }
}

enum DocumentComplexity {
    case unknown
    case simple     // < 10 pages
    case moderate   // 10-50 pages  
    case complex    // 50-100 pages
    case massive    // 100+ pages

    var multiplier: Double {
        switch self {
        case .unknown: return 1.0
        case .simple: return 0.5
        case .moderate: return 1.0
        case .complex: return 2.0
        case .massive: return 4.0
        }
    }

    static func fromAnalysis(wordCount: Int, paragraphCount: Int) -> DocumentComplexity {
        let normalizedWordCount = max(0, wordCount)
        let normalizedParagraphs = max(1, paragraphCount)
        let wordsPerParagraph = Double(normalizedWordCount) / Double(normalizedParagraphs)

        switch normalizedWordCount {
        case ..<800:
            return .simple
        case ..<3000:
            return wordsPerParagraph > 250 ? .complex : .moderate
        case ..<6000:
            return .complex
        default:
            return .massive
        }
    }

    static func fallback(forFileSize size: Int64) -> DocumentComplexity {
        switch size {
        case ..<150_000: // <150 KB
            return .simple
        case ..<600_000: // <600 KB
            return .moderate
        case ..<2_500_000: // <2.5 MB
            return .complex
        default:
            return .massive
        }
    }
}

struct AlertInfo: Identifiable {
    let id = UUID()
    let title: String
    let message: String
}

enum RedactionStatus: Sendable {
    case checking
    case validDocument
    case invalidDocument
    case processing
    case analyzing
    case redacting
    case completed
    case failed
    case cancelled
    
    var displayText: String {
        switch self {
        case .checking: return "[Checking...]"
        case .validDocument: return "[Valid DOCX]"
        case .invalidDocument: return "[Invalid File]"
        case .processing: return "[Processing...]"
        case .analyzing: return "[Analyzing...]"
        case .redacting: return "[Redacting...]"
        case .completed: return "[Completed]"
        case .failed: return "[Failed]"
        case .cancelled: return "[Cancelled]"
        }
    }
    
    var isProcessing: Bool {
        switch self {
        case .checking, .processing, .analyzing, .redacting:
            return true
        default:
            return false
        }
    }
    
    var isComplete: Bool {
        switch self {
        case .completed:
            return true
        default:
            return false
        }
    }
    
    var isPendingReview: Bool {
        switch self {
        case .validDocument, .checking:
            return true
        default:
            return false
        }
    }
    
    var canRetry: Bool {
        switch self {
        case .failed, .cancelled:
            return true
        default:
            return false
        }
    }
}

enum DocumentOperation: String, Sendable {
    case redaction
    case scrub
}

enum RedactionMode: String, CaseIterable {
    case rules = "rules"
    case rulesOverride = "rules_override"
    case constrainedOverrides = "constrained_overrides"
    case llmOverrides = "llm_overrides"

    var displayName: String {
        switch self {
        case .rules:
            return "Rules Only"
        case .rulesOverride:
            return "Rules + AI (Rules Override)"
        case .constrainedOverrides:
            return "Rules + AI (Constrained LLM Overrides)"
        case .llmOverrides:
            return "Rules + AI (LLM Overrides)"
        }
    }

    var description: String {
        switch self {
        case .rules:
            return "Fast rule-based detection for structured PII"
        case .rulesOverride:
            return "AI expands coverage, but deterministic rules always win"
        case .constrainedOverrides:
            return "LLM can veto rules for ORG/NAME/LOC with high confidence"
        case .llmOverrides:
            return "LLM can override any rule when confident"
        }
    }

    var usesLLM: Bool {
        self != .rules
    }
}

enum RedactionRule: String, CaseIterable, Identifiable, Codable, Hashable {
    case email = "EMAIL"
    case phone = "PHONE"
    case ssn = "SSN"
    case money = "MONEY"
    case percent = "PERCENT"
    case number = "NUMBER"
    case date = "DATE"
    case account = "ACCOUNT"
    case swift = "SWIFT"
    case card = "CARD"
    case url = "URL"
    case ip = "IP"
    case org = "ORG"
    case loc = "LOC"
    case signatureNames = "SIGNATURE"
    case images = "IMAGES"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .email: return "EMAIL"
        case .phone: return "PHONE"
        case .ssn: return "SSN"
        case .money: return "MONEY"
        case .percent: return "PERCENT"
        case .number: return "NUMBER"
        case .date: return "DATE"
        case .account: return "ACCOUNT"
        case .swift: return "SWIFT/BIC"
        case .card: return "CARD"
        case .url: return "URL"
        case .ip: return "IP"
        case .org: return "ORG"
        case .loc: return "Address (LOC)"
        case .signatureNames: return "Signature Names"
        case .images: return "IMAGES"
        }
    }

    var description: String {
        switch self {
        case .email:
            return "RFC-like email addresses: sample123@domain.tld (case-insensitive)."
        case .phone:
            return "U.S./international phone numbers with country codes, separators, or parentheses."
        case .ssn:
            return "U.S. Social Security numbers in ###-##-#### format."
        case .money:
            return "Currency amounts, ISO codes, bracketed dollars, or spelled-out figures."
        case .percent:
            return "Numeric percentages (0.06%) and spelled-out (six-hundredths of one percent)."
        case .number:
            return "Bracketed numeric quantities like [1,200] when not preceded by currency."
        case .date:
            return "Numeric, ISO, written date formats, plus placeholders like \"June ___, 2025\"."
        case .account:
            return "Bank/account-style digit sequences (8–20 digits)."
        case .swift:
            return "SWIFT/BIC codes (8 or 11 characters)."
        case .card:
            return "Credit/debit card numbers (13–19 digits) with Luhn validation."
        case .url:
            return "HTTP/HTTPS/FTP URLs, mailto links, www hosts, bare domains with paths."
        case .ip:
            return "IPv4 addresses."
        case .org:
            return "Company names ending with legal suffixes (Inc., LLC, Ltd., etc.)."
        case .loc:
            return "Street addresses (US/Intl) including PO Boxes and explicit address labels."
        case .signatureNames:
            return "Names extracted from signature blocks (Name: John Q. Public …)."
        case .images:
            return "Delete ALL images in the document (if disabled, only thumbnails are deleted)."
        }
    }

    static var defaultSelection: Set<RedactionRule> {
        Set(allCases).subtracting([.images])
    }

    static func serializedList(from set: Set<RedactionRule>) -> String {
        set.sorted { $0.rawValue < $1.rawValue }
            .map { $0.rawValue }
            .joined(separator: ",")
    }
}

struct RedactionSettings {
    static let standardNormalMode: RedactionMode = .rulesOverride
    static let standardNormalModeConfidence: Int = 99
    static let standardNormalModeTemperature: Double = 0.0
    static let standardNormalModeChunkTokens: Int = 1400
    static let standardNormalModeOverlap: Int = 200

    var mode: RedactionMode = RedactionSettings.standardNormalMode
    var model: String = "llama3.1:8b"
    var backend: String = "ollama" // 'ollama' or 'mock' (for fast tests)
    var debug: Bool = false  // Default to false for production
    var temperature: Double = RedactionSettings.standardNormalModeTemperature
    var seed: Int = 42
    var chunkTokens: Int = RedactionSettings.standardNormalModeChunkTokens
    var overlap: Int = RedactionSettings.standardNormalModeOverlap
    var processingTimeoutSeconds: Int = 7200  // 120 minutes
    var enabledRules: Set<RedactionRule> = RedactionRule.defaultSelection
    var llmConfidenceThreshold: Int = RedactionSettings.standardNormalModeConfidence

    mutating func applyStandardNormalModeDefaults(keepingMode: Bool = false) {
        if !keepingMode {
            mode = Self.standardNormalMode
        }
        llmConfidenceThreshold = Self.standardNormalModeConfidence
        temperature = Self.standardNormalModeTemperature
        chunkTokens = Self.standardNormalModeChunkTokens
        overlap = Self.standardNormalModeOverlap
    }

    var llmConfidenceThresholdValue: Double {
        Double(llmConfidenceThreshold) / 100.0
    }
}

// MARK: - Debug Logging System

enum DebugPreferences {
    static let debugLoggingKey = "MarcutApp_DebugMode"
    static let legacyDebugLoggingKey = "MarcutApp.DebugLoggingEnabled"

    static func hasStoredValue(_ defaults: UserDefaults = .standard) -> Bool {
        defaults.object(forKey: debugLoggingKey) != nil
            || defaults.object(forKey: legacyDebugLoggingKey) != nil
    }

    static func isEnabled(_ defaults: UserDefaults = .standard) -> Bool {
        if let value = defaults.object(forKey: debugLoggingKey) as? Bool {
            return value
        }
        if let value = defaults.object(forKey: legacyDebugLoggingKey) as? Bool {
            defaults.set(value, forKey: debugLoggingKey)
            defaults.removeObject(forKey: legacyDebugLoggingKey)
            return value
        }
        return false
    }

    static func setEnabled(_ enabled: Bool, defaults: UserDefaults = .standard) {
        defaults.set(enabled, forKey: debugLoggingKey)
        defaults.removeObject(forKey: legacyDebugLoggingKey)
    }
}

class DebugLogger {
    static let shared = DebugLogger()

    private var isDebugEnabled: Bool = false  // Default to false for production
    private let logDirectoryURL: URL
    private let writeQueue = DispatchQueue(label: "com.marclaw.marcutapp.debuglogger", qos: .utility)

    // Centralized log location under Application Support
    // ~/Library/Application Support/MarcutApp/logs/marcut.log
    var logURL: URL { logDirectoryURL.appendingPathComponent("marcut.log") }
    var logPath: String { logURL.path }

    private init() {
        logDirectoryURL = DebugLogger.resolveLogDirectory()
        // Initialize log asynchronously to avoid blocking main thread
        writeQueue.async { [logURL = logDirectoryURL.appendingPathComponent("marcut.log")] in
            DebugLogger.ensureLogInitializedAsync(logURL: logURL, logDirectoryURL: self.logDirectoryURL)
        }
        LaunchDiagnostics.shared.setLogPath(logPath)
    }

    private static func resolveLogDirectory() -> URL {
        let fm = FileManager.default
        if let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask).first {
            let dir = base.appendingPathComponent("MarcutApp/logs", isDirectory: true)
            if ensureDirectoryExists(dir, fileManager: fm) {
                return dir
            }
        }

        if let groupBase = fm.containerURL(forSecurityApplicationGroupIdentifier: "QG85EMCQ75.group.com.marclaw.marcutapp") {
            let dir = groupBase
                .appendingPathComponent("Library", isDirectory: true)
                .appendingPathComponent("Application Support", isDirectory: true)
                .appendingPathComponent("MarcutApp/logs", isDirectory: true)
            if ensureDirectoryExists(dir, fileManager: fm) {
                return dir
            }
        }

        // Use Temporary Directory as a safe fallback
        // Attempting to write to home directory root in sandbox can trigger permission prompts
        let tempDir = FileManager.default.temporaryDirectory
        let fallback = tempDir.appendingPathComponent("MarcutApp_Logs", isDirectory: true)
        _ = ensureDirectoryExists(fallback, fileManager: fm)
        return fallback
    }

    private static func ensureDirectoryExists(_ url: URL, fileManager: FileManager) -> Bool {
        do {
            try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
            return true
        } catch {
            print("DebugLogger: Failed to create log directory \(url.path): \(error)")
            return false
        }
    }

    public func ensureLogInitialized() {
        writeQueue.async { [logURL = self.logURL, logDirectoryURL = self.logDirectoryURL] in
            DebugLogger.ensureLogInitializedAsync(logURL: logURL, logDirectoryURL: logDirectoryURL)
        }
    }

    private static func ensureLogInitializedAsync(logURL: URL, logDirectoryURL: URL) {
        let bundle = Bundle.main
        let version = bundle.infoDictionary?["CFBundleShortVersionString"] as? String ?? "?"
        let build = bundle.infoDictionary?["CFBundleVersion"] as? String ?? "?"
        let header = "=== MarcutApp Log Started (v\(version) b\(build)) ===\n"
        
        // Ensure directory exists first
        if !FileManager.default.fileExists(atPath: logDirectoryURL.path) {
            _ = ensureDirectoryExists(logDirectoryURL, fileManager: FileManager.default)
        }
        
        if !FileManager.default.fileExists(atPath: logURL.path) {
            try? header.write(to: logURL, atomically: true, encoding: .utf8)
        }
    }

    func updateDebugSetting(_ enabled: Bool) {
        isDebugEnabled = enabled
    }

    private var emptyEntryCount = 0
    private let maxEmptyEntries = 3

    func log(_ message: String, component: String) {
        guard isDebugEnabled else { return }

        // Filter out empty or whitespace-only messages
        let trimmed = message.trimmingCharacters(in: .whitespacesAndNewlines)

        // Handle empty messages
        if trimmed.isEmpty || trimmed == "STDOUT:" || trimmed == "STDERR:" {
            emptyEntryCount += 1
            // Only log a summary if we've accumulated multiple empty entries
            if emptyEntryCount == maxEmptyEntries {
                let timestamp = ISO8601DateFormatter().string(from: Date())
                let summaryMessage = "[\(timestamp)] \(component): [\(emptyEntryCount) empty log entries suppressed]\n"
                writeLogMessage(summaryMessage)
                emptyEntryCount = 0
            }
            return
        }

        // Reset empty count if we have a real message
        if emptyEntryCount > 0 {
            let timestamp = ISO8601DateFormatter().string(from: Date())
            let summaryMessage = "[\(timestamp)] \(component): [\(emptyEntryCount) empty log entries suppressed]\n"
            writeLogMessage(summaryMessage)
            emptyEntryCount = 0
        }

        let timestamp = ISO8601DateFormatter().string(from: Date())
        let logMessage = "[\(timestamp)] \(component): \(message)\n"
        writeLogMessage(logMessage)
    }

    private func writeLogMessage(_ logMessage: String) {
        let logURL = self.logURL
        writeQueue.async {
            // Ensure directory exists before writing
            try? FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)

            if FileManager.default.fileExists(atPath: logURL.path) {
                if let fileHandle = try? FileHandle(forWritingTo: logURL) {
                    defer { try? fileHandle.close() }
                    _ = try? fileHandle.seekToEnd()
                    try? fileHandle.write(contentsOf: logMessage.data(using: .utf8) ?? Data())
                }
            } else {
                try? logMessage.write(to: logURL, atomically: true, encoding: .utf8)
            }
        }
    }

    func clearLog() {
        try? FileManager.default.removeItem(at: logURL)
    }
}
