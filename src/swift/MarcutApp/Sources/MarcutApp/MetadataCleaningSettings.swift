import SwiftUI

/// Represents the preset cleaning profiles for metadata
enum MetadataCleaningPreset: String, CaseIterable, Identifiable {
    case maximum = "maximum"
    case balanced = "balanced"
    case none = "none"
    case custom = "custom"
    
    var id: String { rawValue }
    
    var displayName: String {
        switch self {
        case .maximum: return "Maximum Privacy"
        case .balanced: return "Balanced"
        case .none: return "None"
        case .custom: return "Custom"
        }
    }
    
    var description: String {
        switch self {
        case .maximum: return "Clears all metadata fields for maximum privacy"
        case .balanced: return "Clears identifying info while preserving document formatting"
        case .none: return "No metadata cleaning (keep all original metadata)"
        case .custom: return "Use your custom selection below"
        }
    }
}

/// Settings for controlling which metadata fields are cleaned during redaction
struct MetadataCleaningSettings: Codable, Equatable {
    // MARK: - App Properties (docProps/app.xml)
    var cleanCompany: Bool = true
    var cleanManager: Bool = true
    var cleanTotalEditingTime: Bool = true
    var cleanApplication: Bool = true
    var cleanAppVersion: Bool = true
    var cleanTemplate: Bool = true
    var cleanHyperlinkBase: Bool = true
    var cleanStatistics: Bool = true // chars, words, lines, paragraphs, pages
    var cleanDocSecurity: Bool = true
    var cleanScaleCrop: Bool = true
    var cleanLinksUpToDate: Bool = true
    var cleanSharedDoc: Bool = true
    var cleanHyperlinksChanged: Bool = true
    
    // MARK: - Core Properties (docProps/core.xml)
    var cleanAuthor: Bool = true
    var cleanLastModifiedBy: Bool = true
    var cleanTitle: Bool = true
    var cleanSubject: Bool = true
    var cleanKeywords: Bool = true
    var cleanComments: Bool = true
    var cleanCategory: Bool = true
    var cleanContentStatus: Bool = true
    var cleanCreatedDate: Bool = false // Default OFF per user request
    var cleanModifiedDate: Bool = false // Default OFF per user request
    var cleanLastPrinted: Bool = true
    var cleanRevisionNumber: Bool = true
    var cleanIdentifier: Bool = true
    var cleanLanguage: Bool = true
    var cleanVersion: Bool = true
    
    // MARK: - Custom Properties
    var cleanCustomProperties: Bool = true
    
    // MARK: - Document Structure
    var cleanReviewComments: Bool = true
    var cleanTrackChanges: Bool = true
    var cleanRSIDs: Bool = true
    var cleanDocumentGUID: Bool = true
    var cleanSpellGrammarState: Bool = true
    var cleanDocumentVariables: Bool = true
    var cleanMailMerge: Bool = true
    var cleanDataBindings: Bool = true
    var cleanDocumentVersions: Bool = true
    var cleanInkAnnotations: Bool = true
    var cleanHiddenText: Bool = true
    var cleanInvisibleObjects: Bool = true
    var cleanHeadersFooters: Bool = true
    var cleanWatermarks: Bool = true
    
    // MARK: - Embedded Content
    var cleanThumbnail: Bool = true
    var cleanHyperlinkURLs: Bool = true
    var cleanAltText: Bool = true
    var cleanOLEObjects: Bool = true
    var cleanVBAMacros: Bool = true
    var cleanDigitalSignatures: Bool = true
    var cleanPrinterSettings: Bool = true
    var cleanEmbeddedFonts: Bool = true
    var cleanGlossary: Bool = true
    var cleanFastSaveData: Bool = true
    
    // MARK: - Advanced Hardening (Path Leakage)
    var cleanExternalLinks: Bool = true
    var cleanUNCPaths: Bool = true
    var cleanUserPaths: Bool = true
    var cleanInternalURLs: Bool = true
    var cleanOLESources: Bool = true
    
    // MARK: - Image EXIF
    var cleanImageEXIF: Bool = true
    
    // MARK: - Style and Formatting (can affect document appearance)
    var cleanStyleNames: Bool = true
    var cleanChartLabels: Bool = true
    var cleanFormDefaults: Bool = true
    var cleanLanguageSettings: Bool = true
    
    // MARK: - ActiveX and Controls
    var cleanActiveX: Bool = true
    
    // MARK: - Preset Application

    init() {}
    
    /// Returns settings for the Maximum Privacy preset (all ON)
    static var maximumPrivacy: MetadataCleaningSettings {
        var settings = MetadataCleaningSettings()
        settings.cleanCreatedDate = true
        settings.cleanModifiedDate = true
        return settings
    }
    
    /// Returns settings for the Balanced preset
    /// Clears identifying metadata but preserves document formatting/hierarchy
    static var balanced: MetadataCleaningSettings {
        var settings = MetadataCleaningSettings()
        
        // === KEEP OFF (preserve document formatting) ===
        settings.cleanStatistics = false
        settings.cleanCreatedDate = false
        settings.cleanModifiedDate = false
        settings.cleanLinksUpToDate = false
        settings.cleanHyperlinksChanged = false
        
        // Preserve visual formatting
        settings.cleanAltText = false  // Accessibility
        settings.cleanEmbeddedFonts = false  // Document appearance
        settings.cleanStyleNames = false  // Style hierarchy
        settings.cleanChartLabels = false  // Chart readability
        settings.cleanFormDefaults = false  // Form functionality
        settings.cleanLanguageSettings = false  // Locale/proofing
        settings.cleanHyperlinkURLs = false  // Link functionality
        settings.cleanLanguage = false  // Proofing language
        
        // Keep structure intact
        settings.cleanGlossary = false  // Building blocks
        settings.cleanScaleCrop = false // Visual appearance
        settings.cleanSharedDoc = false // Document state
        settings.cleanSpellGrammarState = false // Proofing state
        settings.cleanDocumentVariables = false // Functionality
        settings.cleanMailMerge = false // Avoid altering field content
        settings.cleanHeadersFooters = false // Visible content
        settings.cleanWatermarks = false // Visible content
        settings.cleanInkAnnotations = false // Visible markup
        settings.cleanHiddenText = false // Hidden content
        settings.cleanInvisibleObjects = false // Hidden objects
        
        // === LEAVE ON (identify info - cleaned) ===
        // Author, company, manager, last modified by - ON (cleaned)
        // Custom properties, GUID, RSIDs - ON (cleaned)
        // Track changes, review comments - ON (cleaned)
        // Digital signatures, VBA macros - ON (cleaned)
        // EXIF data, external links, UNC paths - ON (cleaned)
        // User paths, internal URLs - ON (cleaned)
        
        return settings
    }
    
    /// Returns settings for the None preset (all OFF - no metadata cleaning)
    static var none: MetadataCleaningSettings {
        var settings = MetadataCleaningSettings()
        // Set all fields to false
        settings.cleanCompany = false
        settings.cleanManager = false
        settings.cleanTotalEditingTime = false
        settings.cleanApplication = false
        settings.cleanAppVersion = false
        settings.cleanTemplate = false
        settings.cleanHyperlinkBase = false
        settings.cleanStatistics = false
        settings.cleanDocSecurity = false
        settings.cleanScaleCrop = false
        settings.cleanLinksUpToDate = false
        settings.cleanSharedDoc = false
        settings.cleanHyperlinksChanged = false
        settings.cleanAuthor = false
        settings.cleanLastModifiedBy = false
        settings.cleanTitle = false
        settings.cleanSubject = false
        settings.cleanKeywords = false
        settings.cleanComments = false
        settings.cleanCategory = false
        settings.cleanContentStatus = false
        settings.cleanCreatedDate = false
        settings.cleanModifiedDate = false
        settings.cleanLastPrinted = false
        settings.cleanRevisionNumber = false
        settings.cleanIdentifier = false
        settings.cleanLanguage = false
        settings.cleanVersion = false
        settings.cleanCustomProperties = false
        settings.cleanReviewComments = false
        settings.cleanTrackChanges = false
        settings.cleanRSIDs = false
        settings.cleanDocumentGUID = false
        settings.cleanSpellGrammarState = false
        settings.cleanDocumentVariables = false
        settings.cleanMailMerge = false
        settings.cleanDataBindings = false
        settings.cleanDocumentVersions = false
        settings.cleanInkAnnotations = false
        settings.cleanHiddenText = false
        settings.cleanInvisibleObjects = false
        settings.cleanHeadersFooters = false
        settings.cleanWatermarks = false
        settings.cleanThumbnail = false
        settings.cleanHyperlinkURLs = false
        settings.cleanAltText = false
        settings.cleanOLEObjects = false
        settings.cleanVBAMacros = false
        settings.cleanDigitalSignatures = false
        settings.cleanPrinterSettings = false
        settings.cleanEmbeddedFonts = false
        settings.cleanGlossary = false
        settings.cleanFastSaveData = false
        settings.cleanExternalLinks = false
        settings.cleanUNCPaths = false
        settings.cleanUserPaths = false
        settings.cleanInternalURLs = false
        settings.cleanOLESources = false
        settings.cleanImageEXIF = false
        settings.cleanStyleNames = false
        settings.cleanChartLabels = false
        settings.cleanFormDefaults = false
        settings.cleanLanguageSettings = false
        settings.cleanActiveX = false
        return settings
    }
    
    /// Default settings - Balanced preset (identifying info ON, dates/stats OFF)
    static var `default`: MetadataCleaningSettings {
        return .balanced
    }
    
    /// Detects which preset matches the current settings
    func detectPreset() -> MetadataCleaningPreset {
        if self == .maximumPrivacy {
            return .maximum
        } else if self == .balanced {
            return .balanced
        } else if self == .none {
            return .none
        } else {
            return .custom
        }
    }

    enum CodingKeys: String, CodingKey {
        case cleanCompany
        case cleanManager
        case cleanTotalEditingTime
        case cleanApplication
        case cleanAppVersion
        case cleanTemplate
        case cleanHyperlinkBase
        case cleanStatistics
        case cleanDocSecurity
        case cleanScaleCrop
        case cleanLinksUpToDate
        case cleanSharedDoc
        case cleanHyperlinksChanged
        case cleanAuthor
        case cleanLastModifiedBy
        case cleanTitle
        case cleanSubject
        case cleanKeywords
        case cleanComments
        case cleanCategory
        case cleanContentStatus
        case cleanCreatedDate
        case cleanModifiedDate
        case cleanLastPrinted
        case cleanRevisionNumber
        case cleanIdentifier
        case cleanLanguage
        case cleanVersion
        case cleanCustomProperties
        case cleanReviewComments
        case cleanTrackChanges
        case cleanRSIDs
        case cleanDocumentGUID
        case cleanSpellGrammarState
        case cleanDocumentVariables
        case cleanMailMerge
        case cleanDataBindings
        case cleanDocumentVersions
        case cleanInkAnnotations
        case cleanHiddenText
        case cleanInvisibleObjects
        case cleanHeadersFooters
        case cleanWatermarks
        case cleanThumbnail
        case cleanHyperlinkURLs
        case cleanAltText
        case cleanOLEObjects
        case cleanVBAMacros
        case cleanDigitalSignatures
        case cleanPrinterSettings
        case cleanEmbeddedFonts
        case cleanGlossary
        case cleanFastSaveData
        case cleanExternalLinks
        case cleanUNCPaths
        case cleanUserPaths
        case cleanInternalURLs
        case cleanOLESources
        case cleanImageEXIF
        case cleanStyleNames
        case cleanChartLabels
        case cleanFormDefaults
        case cleanLanguageSettings
        case cleanActiveX
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let defaults = MetadataCleaningSettings()

        cleanCompany = try container.decodeIfPresent(Bool.self, forKey: .cleanCompany) ?? defaults.cleanCompany
        cleanManager = try container.decodeIfPresent(Bool.self, forKey: .cleanManager) ?? defaults.cleanManager
        cleanTotalEditingTime = try container.decodeIfPresent(Bool.self, forKey: .cleanTotalEditingTime) ?? defaults.cleanTotalEditingTime
        cleanApplication = try container.decodeIfPresent(Bool.self, forKey: .cleanApplication) ?? defaults.cleanApplication
        cleanAppVersion = try container.decodeIfPresent(Bool.self, forKey: .cleanAppVersion) ?? defaults.cleanAppVersion
        cleanTemplate = try container.decodeIfPresent(Bool.self, forKey: .cleanTemplate) ?? defaults.cleanTemplate
        cleanHyperlinkBase = try container.decodeIfPresent(Bool.self, forKey: .cleanHyperlinkBase) ?? defaults.cleanHyperlinkBase
        cleanStatistics = try container.decodeIfPresent(Bool.self, forKey: .cleanStatistics) ?? defaults.cleanStatistics
        cleanDocSecurity = try container.decodeIfPresent(Bool.self, forKey: .cleanDocSecurity) ?? defaults.cleanDocSecurity
        cleanScaleCrop = try container.decodeIfPresent(Bool.self, forKey: .cleanScaleCrop) ?? defaults.cleanScaleCrop
        cleanLinksUpToDate = try container.decodeIfPresent(Bool.self, forKey: .cleanLinksUpToDate) ?? defaults.cleanLinksUpToDate
        cleanSharedDoc = try container.decodeIfPresent(Bool.self, forKey: .cleanSharedDoc) ?? defaults.cleanSharedDoc
        cleanHyperlinksChanged = try container.decodeIfPresent(Bool.self, forKey: .cleanHyperlinksChanged) ?? defaults.cleanHyperlinksChanged

        cleanAuthor = try container.decodeIfPresent(Bool.self, forKey: .cleanAuthor) ?? defaults.cleanAuthor
        cleanLastModifiedBy = try container.decodeIfPresent(Bool.self, forKey: .cleanLastModifiedBy) ?? defaults.cleanLastModifiedBy
        cleanTitle = try container.decodeIfPresent(Bool.self, forKey: .cleanTitle) ?? defaults.cleanTitle
        cleanSubject = try container.decodeIfPresent(Bool.self, forKey: .cleanSubject) ?? defaults.cleanSubject
        cleanKeywords = try container.decodeIfPresent(Bool.self, forKey: .cleanKeywords) ?? defaults.cleanKeywords
        cleanComments = try container.decodeIfPresent(Bool.self, forKey: .cleanComments) ?? defaults.cleanComments
        cleanCategory = try container.decodeIfPresent(Bool.self, forKey: .cleanCategory) ?? defaults.cleanCategory
        cleanContentStatus = try container.decodeIfPresent(Bool.self, forKey: .cleanContentStatus) ?? defaults.cleanContentStatus
        cleanCreatedDate = try container.decodeIfPresent(Bool.self, forKey: .cleanCreatedDate) ?? defaults.cleanCreatedDate
        cleanModifiedDate = try container.decodeIfPresent(Bool.self, forKey: .cleanModifiedDate) ?? defaults.cleanModifiedDate
        cleanLastPrinted = try container.decodeIfPresent(Bool.self, forKey: .cleanLastPrinted) ?? defaults.cleanLastPrinted
        cleanRevisionNumber = try container.decodeIfPresent(Bool.self, forKey: .cleanRevisionNumber) ?? defaults.cleanRevisionNumber
        cleanIdentifier = try container.decodeIfPresent(Bool.self, forKey: .cleanIdentifier) ?? defaults.cleanIdentifier
        cleanLanguage = try container.decodeIfPresent(Bool.self, forKey: .cleanLanguage) ?? defaults.cleanLanguage
        cleanVersion = try container.decodeIfPresent(Bool.self, forKey: .cleanVersion) ?? defaults.cleanVersion

        cleanCustomProperties = try container.decodeIfPresent(Bool.self, forKey: .cleanCustomProperties) ?? defaults.cleanCustomProperties

        cleanReviewComments = try container.decodeIfPresent(Bool.self, forKey: .cleanReviewComments) ?? defaults.cleanReviewComments
        cleanTrackChanges = try container.decodeIfPresent(Bool.self, forKey: .cleanTrackChanges) ?? defaults.cleanTrackChanges
        cleanRSIDs = try container.decodeIfPresent(Bool.self, forKey: .cleanRSIDs) ?? defaults.cleanRSIDs
        cleanDocumentGUID = try container.decodeIfPresent(Bool.self, forKey: .cleanDocumentGUID) ?? defaults.cleanDocumentGUID
        cleanSpellGrammarState = try container.decodeIfPresent(Bool.self, forKey: .cleanSpellGrammarState) ?? defaults.cleanSpellGrammarState
        cleanDocumentVariables = try container.decodeIfPresent(Bool.self, forKey: .cleanDocumentVariables) ?? defaults.cleanDocumentVariables
        cleanMailMerge = try container.decodeIfPresent(Bool.self, forKey: .cleanMailMerge) ?? defaults.cleanMailMerge
        cleanDataBindings = try container.decodeIfPresent(Bool.self, forKey: .cleanDataBindings) ?? defaults.cleanDataBindings
        cleanDocumentVersions = try container.decodeIfPresent(Bool.self, forKey: .cleanDocumentVersions) ?? defaults.cleanDocumentVersions
        cleanInkAnnotations = try container.decodeIfPresent(Bool.self, forKey: .cleanInkAnnotations) ?? defaults.cleanInkAnnotations
        cleanHiddenText = try container.decodeIfPresent(Bool.self, forKey: .cleanHiddenText) ?? defaults.cleanHiddenText
        cleanInvisibleObjects = try container.decodeIfPresent(Bool.self, forKey: .cleanInvisibleObjects) ?? defaults.cleanInvisibleObjects
        cleanHeadersFooters = try container.decodeIfPresent(Bool.self, forKey: .cleanHeadersFooters) ?? defaults.cleanHeadersFooters
        cleanWatermarks = try container.decodeIfPresent(Bool.self, forKey: .cleanWatermarks) ?? defaults.cleanWatermarks

        cleanThumbnail = try container.decodeIfPresent(Bool.self, forKey: .cleanThumbnail) ?? defaults.cleanThumbnail
        cleanHyperlinkURLs = try container.decodeIfPresent(Bool.self, forKey: .cleanHyperlinkURLs) ?? defaults.cleanHyperlinkURLs
        cleanAltText = try container.decodeIfPresent(Bool.self, forKey: .cleanAltText) ?? defaults.cleanAltText
        cleanOLEObjects = try container.decodeIfPresent(Bool.self, forKey: .cleanOLEObjects) ?? defaults.cleanOLEObjects
        cleanVBAMacros = try container.decodeIfPresent(Bool.self, forKey: .cleanVBAMacros) ?? defaults.cleanVBAMacros
        cleanDigitalSignatures = try container.decodeIfPresent(Bool.self, forKey: .cleanDigitalSignatures) ?? defaults.cleanDigitalSignatures
        cleanPrinterSettings = try container.decodeIfPresent(Bool.self, forKey: .cleanPrinterSettings) ?? defaults.cleanPrinterSettings
        cleanEmbeddedFonts = try container.decodeIfPresent(Bool.self, forKey: .cleanEmbeddedFonts) ?? defaults.cleanEmbeddedFonts
        cleanGlossary = try container.decodeIfPresent(Bool.self, forKey: .cleanGlossary) ?? defaults.cleanGlossary
        cleanFastSaveData = try container.decodeIfPresent(Bool.self, forKey: .cleanFastSaveData) ?? defaults.cleanFastSaveData

        cleanExternalLinks = try container.decodeIfPresent(Bool.self, forKey: .cleanExternalLinks) ?? defaults.cleanExternalLinks
        cleanUNCPaths = try container.decodeIfPresent(Bool.self, forKey: .cleanUNCPaths) ?? defaults.cleanUNCPaths
        cleanUserPaths = try container.decodeIfPresent(Bool.self, forKey: .cleanUserPaths) ?? defaults.cleanUserPaths
        cleanInternalURLs = try container.decodeIfPresent(Bool.self, forKey: .cleanInternalURLs) ?? defaults.cleanInternalURLs
        cleanOLESources = try container.decodeIfPresent(Bool.self, forKey: .cleanOLESources) ?? defaults.cleanOLESources
        cleanImageEXIF = try container.decodeIfPresent(Bool.self, forKey: .cleanImageEXIF) ?? defaults.cleanImageEXIF
        cleanStyleNames = try container.decodeIfPresent(Bool.self, forKey: .cleanStyleNames) ?? defaults.cleanStyleNames
        cleanChartLabels = try container.decodeIfPresent(Bool.self, forKey: .cleanChartLabels) ?? defaults.cleanChartLabels
        cleanFormDefaults = try container.decodeIfPresent(Bool.self, forKey: .cleanFormDefaults) ?? defaults.cleanFormDefaults
        cleanLanguageSettings = try container.decodeIfPresent(Bool.self, forKey: .cleanLanguageSettings) ?? defaults.cleanLanguageSettings
        cleanActiveX = try container.decodeIfPresent(Bool.self, forKey: .cleanActiveX) ?? defaults.cleanActiveX
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(cleanCompany, forKey: .cleanCompany)
        try container.encode(cleanManager, forKey: .cleanManager)
        try container.encode(cleanTotalEditingTime, forKey: .cleanTotalEditingTime)
        try container.encode(cleanApplication, forKey: .cleanApplication)
        try container.encode(cleanAppVersion, forKey: .cleanAppVersion)
        try container.encode(cleanTemplate, forKey: .cleanTemplate)
        try container.encode(cleanHyperlinkBase, forKey: .cleanHyperlinkBase)
        try container.encode(cleanStatistics, forKey: .cleanStatistics)
        try container.encode(cleanDocSecurity, forKey: .cleanDocSecurity)
        try container.encode(cleanScaleCrop, forKey: .cleanScaleCrop)
        try container.encode(cleanLinksUpToDate, forKey: .cleanLinksUpToDate)
        try container.encode(cleanSharedDoc, forKey: .cleanSharedDoc)
        try container.encode(cleanHyperlinksChanged, forKey: .cleanHyperlinksChanged)

        try container.encode(cleanAuthor, forKey: .cleanAuthor)
        try container.encode(cleanLastModifiedBy, forKey: .cleanLastModifiedBy)
        try container.encode(cleanTitle, forKey: .cleanTitle)
        try container.encode(cleanSubject, forKey: .cleanSubject)
        try container.encode(cleanKeywords, forKey: .cleanKeywords)
        try container.encode(cleanComments, forKey: .cleanComments)
        try container.encode(cleanCategory, forKey: .cleanCategory)
        try container.encode(cleanContentStatus, forKey: .cleanContentStatus)
        try container.encode(cleanCreatedDate, forKey: .cleanCreatedDate)
        try container.encode(cleanModifiedDate, forKey: .cleanModifiedDate)
        try container.encode(cleanLastPrinted, forKey: .cleanLastPrinted)
        try container.encode(cleanRevisionNumber, forKey: .cleanRevisionNumber)
        try container.encode(cleanIdentifier, forKey: .cleanIdentifier)
        try container.encode(cleanLanguage, forKey: .cleanLanguage)
        try container.encode(cleanVersion, forKey: .cleanVersion)

        try container.encode(cleanCustomProperties, forKey: .cleanCustomProperties)

        try container.encode(cleanReviewComments, forKey: .cleanReviewComments)
        try container.encode(cleanTrackChanges, forKey: .cleanTrackChanges)
        try container.encode(cleanRSIDs, forKey: .cleanRSIDs)
        try container.encode(cleanDocumentGUID, forKey: .cleanDocumentGUID)
        try container.encode(cleanSpellGrammarState, forKey: .cleanSpellGrammarState)
        try container.encode(cleanDocumentVariables, forKey: .cleanDocumentVariables)
        try container.encode(cleanMailMerge, forKey: .cleanMailMerge)
        try container.encode(cleanDataBindings, forKey: .cleanDataBindings)
        try container.encode(cleanDocumentVersions, forKey: .cleanDocumentVersions)
        try container.encode(cleanInkAnnotations, forKey: .cleanInkAnnotations)
        try container.encode(cleanHiddenText, forKey: .cleanHiddenText)
        try container.encode(cleanInvisibleObjects, forKey: .cleanInvisibleObjects)
        try container.encode(cleanHeadersFooters, forKey: .cleanHeadersFooters)
        try container.encode(cleanWatermarks, forKey: .cleanWatermarks)

        try container.encode(cleanThumbnail, forKey: .cleanThumbnail)
        try container.encode(cleanHyperlinkURLs, forKey: .cleanHyperlinkURLs)
        try container.encode(cleanAltText, forKey: .cleanAltText)
        try container.encode(cleanOLEObjects, forKey: .cleanOLEObjects)
        try container.encode(cleanVBAMacros, forKey: .cleanVBAMacros)
        try container.encode(cleanDigitalSignatures, forKey: .cleanDigitalSignatures)
        try container.encode(cleanPrinterSettings, forKey: .cleanPrinterSettings)
        try container.encode(cleanEmbeddedFonts, forKey: .cleanEmbeddedFonts)
        try container.encode(cleanGlossary, forKey: .cleanGlossary)
        try container.encode(cleanFastSaveData, forKey: .cleanFastSaveData)

        try container.encode(cleanExternalLinks, forKey: .cleanExternalLinks)
        try container.encode(cleanUNCPaths, forKey: .cleanUNCPaths)
        try container.encode(cleanUserPaths, forKey: .cleanUserPaths)
        try container.encode(cleanInternalURLs, forKey: .cleanInternalURLs)
        try container.encode(cleanOLESources, forKey: .cleanOLESources)
        try container.encode(cleanImageEXIF, forKey: .cleanImageEXIF)
        try container.encode(cleanStyleNames, forKey: .cleanStyleNames)
        try container.encode(cleanChartLabels, forKey: .cleanChartLabels)
        try container.encode(cleanFormDefaults, forKey: .cleanFormDefaults)
        try container.encode(cleanLanguageSettings, forKey: .cleanLanguageSettings)
        try container.encode(cleanActiveX, forKey: .cleanActiveX)
    }
    
    // MARK: - Persistence
    
    private static let userDefaultsKey = "MetadataCleaningSettings"
    
    static func load() -> MetadataCleaningSettings {
        guard let data = UserDefaults.standard.data(forKey: userDefaultsKey),
              let settings = try? JSONDecoder().decode(MetadataCleaningSettings.self, from: data) else {
            return .default
        }
        return settings
    }
    
    func save() {
        if let data = try? JSONEncoder().encode(self) {
            UserDefaults.standard.set(data, forKey: Self.userDefaultsKey)
        }
    }
    
    // MARK: - CLI Arguments
    
    /// Generates CLI arguments for passing to Python
    func toCLIArguments() -> [String] {
        var args: [String] = []
        
        // Explicitly signal 'None' preset for robust handling
        if self == MetadataCleaningSettings.none {
            args.append("--preset-none")
        }
        
        // Only pass fields that are OFF (to minimize arg list)
        if !cleanCompany { args.append("--no-clean-company") }
        if !cleanManager { args.append("--no-clean-manager") }
        if !cleanTotalEditingTime { args.append("--no-clean-editing-time") }
        if !cleanApplication { args.append("--no-clean-application") }
        if !cleanAppVersion { args.append("--no-clean-app-version") }
        if !cleanTemplate { args.append("--no-clean-template") }
        if !cleanHyperlinkBase { args.append("--no-clean-hyperlink-base") }
        if !cleanStatistics { args.append("--no-clean-statistics") }
        if !cleanDocSecurity { args.append("--no-clean-doc-security") }
        if !cleanAuthor { args.append("--no-clean-author") }
        if !cleanLastModifiedBy { args.append("--no-clean-last-modified-by") }
        if !cleanTitle { args.append("--no-clean-title") }
        if !cleanSubject { args.append("--no-clean-subject") }
        if !cleanKeywords { args.append("--no-clean-keywords") }
        if !cleanComments { args.append("--no-clean-comments") }
        if !cleanCategory { args.append("--no-clean-category") }
        if !cleanContentStatus { args.append("--no-clean-content-status") }
        if !cleanCreatedDate { args.append("--no-clean-created-date") }
        if !cleanModifiedDate { args.append("--no-clean-modified-date") }
        if !cleanLastPrinted { args.append("--no-clean-last-printed") }
        if !cleanRevisionNumber { args.append("--no-clean-revision") }
        if !cleanIdentifier { args.append("--no-clean-identifier") }
        if !cleanLanguage { args.append("--no-clean-language") }
        if !cleanVersion { args.append("--no-clean-version") }
        if !cleanCustomProperties { args.append("--no-clean-custom-props") }
        if !cleanReviewComments { args.append("--no-clean-review-comments") }
        if !cleanTrackChanges { args.append("--no-clean-track-changes") }
        if !cleanRSIDs { args.append("--no-clean-rsids") }
        if !cleanDocumentGUID { args.append("--no-clean-guid") }
        if !cleanMailMerge { args.append("--no-clean-mail-merge") }
        if !cleanDataBindings { args.append("--no-clean-data-bindings") }
        if !cleanDocumentVersions { args.append("--no-clean-doc-versions") }
        if !cleanInkAnnotations { args.append("--no-clean-ink-annotations") }
        if !cleanHiddenText { args.append("--no-clean-hidden-text") }
        if !cleanInvisibleObjects { args.append("--no-clean-invisible-objects") }
        if !cleanHeadersFooters { args.append("--no-clean-headers-footers") }
        if !cleanWatermarks { args.append("--no-clean-watermarks") }
        if !cleanThumbnail { args.append("--no-clean-thumbnail") }
        if !cleanHyperlinkURLs { args.append("--no-clean-hyperlinks") }
        if !cleanAltText { args.append("--no-clean-alt-text") }
        if !cleanOLEObjects { args.append("--no-clean-ole") }
        if !cleanVBAMacros { args.append("--no-clean-macros") }
        if !cleanDigitalSignatures { args.append("--no-clean-signatures") }
        if !cleanPrinterSettings { args.append("--no-clean-printer") }
        if !cleanEmbeddedFonts { args.append("--no-clean-fonts") }
        if !cleanGlossary { args.append("--no-clean-glossary") }
        if !cleanFastSaveData { args.append("--no-clean-fast-save") }
        
        // Advanced hardening
        if !cleanExternalLinks { args.append("--no-clean-ext-links") }
        if !cleanUNCPaths { args.append("--no-clean-unc-paths") }
        if !cleanUserPaths { args.append("--no-clean-user-paths") }
        if !cleanInternalURLs { args.append("--no-clean-internal-urls") }
        if !cleanOLESources { args.append("--no-clean-ole-sources") }
        if !cleanImageEXIF { args.append("--no-clean-exif") }
        if !cleanStyleNames { args.append("--no-clean-style-names") }
        if !cleanChartLabels { args.append("--no-clean-chart-labels") }
        if !cleanFormDefaults { args.append("--no-clean-form-defaults") }
        if !cleanLanguageSettings { args.append("--no-clean-language-settings") }
        if !cleanActiveX { args.append("--no-clean-activex") }
        
        // Hidden settings (App Props / structure)
        if !cleanScaleCrop { args.append("--no-clean-scale-crop") }
        if !cleanLinksUpToDate { args.append("--no-clean-links-up-to-date") }
        if !cleanSharedDoc { args.append("--no-clean-shared-doc") }
        if !cleanHyperlinksChanged { args.append("--no-clean-hyperlinks-changed") }
        if !cleanSpellGrammarState { args.append("--no-clean-spell-grammar") }
        if !cleanDocumentVariables { args.append("--no-clean-doc-vars") }
        
        return args
    }
}
