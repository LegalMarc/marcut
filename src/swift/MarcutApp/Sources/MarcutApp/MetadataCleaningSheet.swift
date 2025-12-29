import SwiftUI

/// Sheet view for configuring metadata cleaning options
struct MetadataCleaningSheet: View {
    @Binding var settings: MetadataCleaningSettings
    @State private var selectedPreset: MetadataCleaningPreset
    @State private var customSettings: MetadataCleaningSettings // Memory for custom preset
    @State private var collapsedStates: [String: [MetadataCleaningPreset: Bool]] = [:] // Per-preset collapse states
    @Environment(\.dismiss) private var dismiss
    @Environment(\.colorScheme) private var colorScheme
    
    private let groupNames = ["appProperties", "coreProperties", "customProperties", "documentStructure", "embeddedContent", "advancedHardening"]
    
    init(settings: Binding<MetadataCleaningSettings>) {
        self._settings = settings
        let currentPreset = settings.wrappedValue.detectPreset()
        self._selectedPreset = State(initialValue: currentPreset)
        self._customSettings = State(initialValue: settings.wrappedValue)
        
        // Initialize default collapsed states (all expanded)
        var defaultStates: [String: [MetadataCleaningPreset: Bool]] = [:]
        for name in ["appProperties", "coreProperties", "customProperties", "documentStructure", "embeddedContent", "advancedHardening"] {
            defaultStates[name] = [:]
            for preset in MetadataCleaningPreset.allCases {
                defaultStates[name]?[preset] = false // false = expanded
            }
        }
        self._collapsedStates = State(initialValue: defaultStates)
    }
    
    var body: some View {
        VStack(spacing: 0) {
            // Header
            VStack(spacing: 8) {
                Text("Metadata Cleaning Options")
                    .font(.title2)
                    .fontWeight(.semibold)
                
                Text("Select which metadata fields to remove during redaction")
                    .font(.body)
                    .foregroundColor(.secondary)
            }
            .padding(.top, 24)
            .padding(.bottom, 16)
            
            // Preset Picker with label
            HStack {
                Text("Preset:")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(.secondary)
                
                Picker("", selection: $selectedPreset) {
                    ForEach(MetadataCleaningPreset.allCases) { preset in
                        Text(preset.displayName).tag(preset)
                    }
                }
                .pickerStyle(.segmented)
                .labelsHidden()
                .onChange(of: selectedPreset) { newPreset in
                    applyPreset(newPreset)
                }
                
                Spacer()
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 16)
            
            // Scrollable checkbox groups
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    // Group 1: App Properties
                    MetadataGroupView(
                        title: "App Properties",
                        subtitle: "docProps/app.xml",
                        groupKey: "appProperties",
                        collapsedStates: $collapsedStates,
                        currentPreset: selectedPreset,
                        items: [
                            MetadataItem(label: "Company", description: "Organization name (often auto-filled from system)", binding: makeCustomBinding($settings.cleanCompany)),
                            MetadataItem(label: "Manager", description: "Manager's name field", binding: makeCustomBinding($settings.cleanManager)),
                            MetadataItem(label: "Total Editing Time", description: "Cumulative minutes spent editing", binding: makeCustomBinding($settings.cleanTotalEditingTime)),
                            MetadataItem(label: "Application", description: "Application name (e.g., \"Microsoft Office Word\")", binding: makeCustomBinding($settings.cleanApplication)),
                            MetadataItem(label: "App Version", description: "Specific Office version number", binding: makeCustomBinding($settings.cleanAppVersion)),
                            MetadataItem(label: "Template", description: "Template name used (e.g., \"Normal.dotm\")", binding: makeCustomBinding($settings.cleanTemplate)),
                            MetadataItem(label: "Hyperlink Base", description: "Base URL for resolving relative links", binding: makeCustomBinding($settings.cleanHyperlinkBase)),
                            MetadataItem(label: "Document Statistics", description: "Character, word, line, paragraph, and page counts", binding: makeCustomBinding($settings.cleanStatistics)),
                            MetadataItem(label: "Document Security", description: "Security settings value", binding: makeCustomBinding($settings.cleanDocSecurity)),
                            MetadataItem(label: "Thumbnail Settings", description: "Scale/crop display settings", binding: makeCustomBinding($settings.cleanScaleCrop)),
                            MetadataItem(label: "Shared Document Flag", description: "Whether document was shared", binding: makeCustomBinding($settings.cleanSharedDoc)),
                            MetadataItem(label: "Links Up-to-Date Flag", description: "Status of external link updates", binding: makeCustomBinding($settings.cleanLinksUpToDate)),
                            MetadataItem(label: "Hyperlinks Changed Flag", description: "Status of hyperlink modifications", binding: makeCustomBinding($settings.cleanHyperlinksChanged)),
                        ],
                        onSelectAll: { switchToCustomAndApply { selectAllInGroup(appProperties: true) } },
                        onClearAll: { switchToCustomAndApply { clearAllInGroup(appProperties: true) } },
                        onInvert: { switchToCustomAndApply { invertGroup(appProperties: true) } }
                    )
                    
                    Divider()
                    
                    // Group 2: Core Properties
                    MetadataGroupView(
                        title: "Core Properties",
                        subtitle: "docProps/core.xml",
                        groupKey: "coreProperties",
                        collapsedStates: $collapsedStates,
                        currentPreset: selectedPreset,
                        items: [
                            MetadataItem(label: "Author", description: "Document creator's name", binding: makeCustomBinding($settings.cleanAuthor)),
                            MetadataItem(label: "Last Modified By", description: "Last person who edited", binding: makeCustomBinding($settings.cleanLastModifiedBy)),
                            MetadataItem(label: "Title", description: "Document title", binding: makeCustomBinding($settings.cleanTitle)),
                            MetadataItem(label: "Subject", description: "Document subject", binding: makeCustomBinding($settings.cleanSubject)),
                            MetadataItem(label: "Keywords", description: "Search keywords/tags", binding: makeCustomBinding($settings.cleanKeywords)),
                            MetadataItem(label: "Comments", description: "Document description field", binding: makeCustomBinding($settings.cleanComments)),
                            MetadataItem(label: "Category", description: "Document category", binding: makeCustomBinding($settings.cleanCategory)),
                            MetadataItem(label: "Content Status", description: "Status (Draft, Final, etc.)", binding: makeCustomBinding($settings.cleanContentStatus)),
                            MetadataItem(label: "Created Date", description: "Creation timestamp", binding: makeCustomBinding($settings.cleanCreatedDate)),
                            MetadataItem(label: "Modified Date", description: "Last modification timestamp", binding: makeCustomBinding($settings.cleanModifiedDate)),
                            MetadataItem(label: "Last Printed", description: "Last print timestamp", binding: makeCustomBinding($settings.cleanLastPrinted)),
                            MetadataItem(label: "Revision Number", description: "Document revision count", binding: makeCustomBinding($settings.cleanRevisionNumber)),
                            MetadataItem(label: "Identifier", description: "Unique document identifier", binding: makeCustomBinding($settings.cleanIdentifier)),
                            MetadataItem(label: "Language", description: "Document language code", binding: makeCustomBinding($settings.cleanLanguage)),
                            MetadataItem(label: "Version", description: "Document version string", binding: makeCustomBinding($settings.cleanVersion)),
                        ],
                        onSelectAll: { switchToCustomAndApply { selectAllInGroup(coreProperties: true) } },
                        onClearAll: { switchToCustomAndApply { clearAllInGroup(coreProperties: true) } },
                        onInvert: { switchToCustomAndApply { invertGroup(coreProperties: true) } }
                    )
                    
                    Divider()
                    
                    // Group 3: Custom Properties
                    MetadataGroupView(
                        title: "Custom Properties",
                        subtitle: "docProps/custom.xml",
                        groupKey: "customProperties",
                        collapsedStates: $collapsedStates,
                        currentPreset: selectedPreset,
                        items: [
                            MetadataItem(label: "Custom Properties & Custom XML", description: "User-defined properties and custom XML parts", binding: makeCustomBinding($settings.cleanCustomProperties)),
                        ],
                        onSelectAll: { switchToCustomAndApply { settings.cleanCustomProperties = true } },
                        onClearAll: { switchToCustomAndApply { settings.cleanCustomProperties = false } },
                        onInvert: { switchToCustomAndApply { settings.cleanCustomProperties.toggle() } }
                    )
                    
                    Divider()
                    
                    // Group 4: Document Structure
                    MetadataGroupView(
                        title: "Document Structure",
                        subtitle: "Internal document data",
                        groupKey: "documentStructure",
                        collapsedStates: $collapsedStates,
                        currentPreset: selectedPreset,
                        items: [
                            MetadataItem(label: "Review Comments", description: "Comment annotations in document", binding: makeCustomBinding($settings.cleanReviewComments)),
                            MetadataItem(label: "Track Changes", description: "Insertions, deletions, formatting changes", binding: makeCustomBinding($settings.cleanTrackChanges)),
                            MetadataItem(label: "RSIDs", description: "Revision Save IDs (fingerprinting data)", binding: makeCustomBinding($settings.cleanRSIDs)),
                            MetadataItem(label: "Document GUID", description: "Unique document identifier in settings", binding: makeCustomBinding($settings.cleanDocumentGUID)),
                            MetadataItem(label: "Spell/Grammar State", description: "Proofing state markers", binding: makeCustomBinding($settings.cleanSpellGrammarState)),
                            MetadataItem(label: "Document Variables", description: "Programmatic variables", binding: makeCustomBinding($settings.cleanDocumentVariables)),
                            MetadataItem(label: "Mail Merge Data", description: "Data source bindings and merge fields", binding: makeCustomBinding($settings.cleanMailMerge)),
                            MetadataItem(label: "Data Bindings", description: "Content control XML bindings", binding: makeCustomBinding($settings.cleanDataBindings)),
                            MetadataItem(label: "Document Versions", description: "Legacy version history parts", binding: makeCustomBinding($settings.cleanDocumentVersions)),
                            MetadataItem(label: "Ink Annotations", description: "Pen/ink markup data", binding: makeCustomBinding($settings.cleanInkAnnotations)),
                            MetadataItem(label: "Hidden Text", description: "Runs marked as hidden text", binding: makeCustomBinding($settings.cleanHiddenText)),
                            MetadataItem(label: "Invisible Objects", description: "Shapes marked as hidden", binding: makeCustomBinding($settings.cleanInvisibleObjects)),
                            MetadataItem(label: "Headers & Footers", description: "Remove all header/footer parts", binding: makeCustomBinding($settings.cleanHeadersFooters)),
                            MetadataItem(label: "Watermarks", description: "Remove watermark shapes in headers", binding: makeCustomBinding($settings.cleanWatermarks)),
                        ],
                        onSelectAll: { switchToCustomAndApply { selectAllInGroup(documentStructure: true) } },
                        onClearAll: { switchToCustomAndApply { clearAllInGroup(documentStructure: true) } },
                        onInvert: { switchToCustomAndApply { invertGroup(documentStructure: true) } }
                    )
                    
                    Divider()
                    
                    // Group 5: Embedded Content
                    MetadataGroupView(
                        title: "Embedded Content",
                        subtitle: "Files and objects within document",
                        groupKey: "embeddedContent",
                        collapsedStates: $collapsedStates,
                        currentPreset: selectedPreset,
                        items: [
                            MetadataItem(label: "Thumbnail Image", description: "Document preview image", binding: makeCustomBinding($settings.cleanThumbnail)),
                            MetadataItem(label: "Hyperlink URLs", description: "External links (converted to plain text)", binding: makeCustomBinding($settings.cleanHyperlinkURLs)),
                            MetadataItem(label: "Alt Text on Images", description: "Descriptive text on embedded images", binding: makeCustomBinding($settings.cleanAltText)),
                            MetadataItem(label: "OLE Objects", description: "Embedded Excel, PDFs, etc.", binding: makeCustomBinding($settings.cleanOLEObjects)),
                            MetadataItem(label: "VBA Macros", description: "Embedded code (security risk)", binding: makeCustomBinding($settings.cleanVBAMacros)),
                            MetadataItem(label: "Digital Signatures", description: "Document signing data", binding: makeCustomBinding($settings.cleanDigitalSignatures)),
                            MetadataItem(label: "Printer Settings", description: "Print configuration data", binding: makeCustomBinding($settings.cleanPrinterSettings)),
                            MetadataItem(label: "Embedded Fonts", description: "Embedded font information", binding: makeCustomBinding($settings.cleanEmbeddedFonts)),
                            MetadataItem(label: "Glossary/AutoText", description: "Auto-complete entries", binding: makeCustomBinding($settings.cleanGlossary)),
                            MetadataItem(label: "Fast Save Data", description: "Incremental save fragments", binding: makeCustomBinding($settings.cleanFastSaveData)),
                        ],
                        onSelectAll: { switchToCustomAndApply { selectAllInGroup(embeddedContent: true) } },
                        onClearAll: { switchToCustomAndApply { clearAllInGroup(embeddedContent: true) } },
                        onInvert: { switchToCustomAndApply { invertGroup(embeddedContent: true) } }
                    )
                    
                    Divider()
                    
                    // Group 6: Advanced Hardening
                    MetadataGroupView(
                        title: "Advanced Hardening",
                        subtitle: "Path leakage, EXIF, and deep cleaning",
                        groupKey: "advancedHardening",
                        collapsedStates: $collapsedStates,
                        currentPreset: selectedPreset,
                        items: [
                            MetadataItem(label: "External Link Paths", description: "File paths in external links", binding: makeCustomBinding($settings.cleanExternalLinks)),
                            MetadataItem(label: "Network (UNC) Paths", description: "\\\\server\\share style paths", binding: makeCustomBinding($settings.cleanUNCPaths)),
                            MetadataItem(label: "User Profile Paths", description: "/Users/name or C:\\Users\\name paths", binding: makeCustomBinding($settings.cleanUserPaths)),
                            MetadataItem(label: "Internal URLs", description: "Internal site URLs (intranet, etc.)", binding: makeCustomBinding($settings.cleanInternalURLs)),
                            MetadataItem(label: "OLE Source Paths", description: "Source paths embedded in OLE objects", binding: makeCustomBinding($settings.cleanOLESources)),
                            MetadataItem(label: "Image EXIF Data", description: "GPS, camera info, author in JPEG/PNG", binding: makeCustomBinding($settings.cleanImageEXIF)),
                            MetadataItem(label: "Custom Style Names", description: "Rename identifying style names", binding: makeCustomBinding($settings.cleanStyleNames)),
                            MetadataItem(label: "Chart Labels", description: "Clean identifying chart text", binding: makeCustomBinding($settings.cleanChartLabels)),
                            MetadataItem(label: "Form Field Defaults", description: "Clear pre-filled form values", binding: makeCustomBinding($settings.cleanFormDefaults)),
                            MetadataItem(label: "Language Settings", description: "Locale and language fingerprints", binding: makeCustomBinding($settings.cleanLanguageSettings)),
                            MetadataItem(label: "ActiveX Controls", description: "Remove embedded ActiveX", binding: makeCustomBinding($settings.cleanActiveX)),
                        ],
                        onSelectAll: { switchToCustomAndApply { selectAllInGroup(advancedHardening: true) } },
                        onClearAll: { switchToCustomAndApply { clearAllInGroup(advancedHardening: true) } },
                        onInvert: { switchToCustomAndApply { invertGroup(advancedHardening: true) } }
                    )
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 24)
            }
            
            Divider()
            
            // Footer buttons
            HStack(spacing: 12) {
                Button("Cancel") {
                    dismiss()
                }
                .buttonStyle(.bordered)
                .controlSize(.large)
                
                Spacer()
                
                Button("Save Preferences") {
                    settings.save()
                    dismiss()
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.large)
            }
            .padding(24)
        }
        .frame(width: 650, height: 800)
        .background(Color(NSColor.windowBackgroundColor))
        .onChange(of: settings) { newSettings in
            // Save custom settings when in custom mode
            if selectedPreset == .custom {
                customSettings = newSettings
                return
            }
            // Update preset detection when settings change
            selectedPreset = newSettings.detectPreset()
        }
    }
    
    private func applyPreset(_ preset: MetadataCleaningPreset) {
        switch preset {
        case .maximum:
            settings = .maximumPrivacy
        case .balanced:
            settings = .balanced
        case .none:
            settings = .none
        case .custom:
            // Restore remembered custom settings
            settings = customSettings
        }
    }
    
    /// Apply action and switch to Custom preset
    private func switchToCustomAndApply(_ action: () -> Void) {
        if selectedPreset != .custom {
            customSettings = settings
            selectedPreset = .custom
        }
        action()
    }
    
    /// Creates a binding that switches to Custom when modified
    private func makeCustomBinding(_ binding: Binding<Bool>) -> Binding<Bool> {
        Binding<Bool>(
            get: { binding.wrappedValue },
            set: { newValue in
                if selectedPreset != .custom {
                    customSettings = settings
                    selectedPreset = .custom
                }
                binding.wrappedValue = newValue
            }
        )
    }
    
    private func selectAllInGroup(appProperties: Bool = false, coreProperties: Bool = false, documentStructure: Bool = false, embeddedContent: Bool = false, advancedHardening: Bool = false) {
        if appProperties {
            settings.cleanCompany = true
            settings.cleanManager = true
            settings.cleanTotalEditingTime = true
            settings.cleanApplication = true
            settings.cleanAppVersion = true
            settings.cleanTemplate = true
            settings.cleanStatistics = true
            settings.cleanDocSecurity = true
            settings.cleanScaleCrop = true
            settings.cleanLinksUpToDate = true
            settings.cleanSharedDoc = true
            settings.cleanHyperlinksChanged = true
        }
        if coreProperties {
            settings.cleanAuthor = true
            settings.cleanLastModifiedBy = true
            settings.cleanTitle = true
            settings.cleanSubject = true
            settings.cleanKeywords = true
            settings.cleanComments = true
            settings.cleanCategory = true
            settings.cleanContentStatus = true
            settings.cleanCreatedDate = true
            settings.cleanModifiedDate = true
            settings.cleanLastPrinted = true
            settings.cleanRevisionNumber = true
            settings.cleanIdentifier = true
            settings.cleanLanguage = true
            settings.cleanVersion = true
        }
        if documentStructure {
            settings.cleanReviewComments = true
            settings.cleanTrackChanges = true
            settings.cleanRSIDs = true
            settings.cleanDocumentGUID = true
            settings.cleanSpellGrammarState = true
            settings.cleanDocumentVariables = true
        }
        if embeddedContent {
            settings.cleanThumbnail = true
            settings.cleanHyperlinkURLs = true
            settings.cleanAltText = true
            settings.cleanOLEObjects = true
            settings.cleanVBAMacros = true
            settings.cleanDigitalSignatures = true
            settings.cleanPrinterSettings = true
            settings.cleanEmbeddedFonts = true
            settings.cleanGlossary = true
            settings.cleanFastSaveData = true
        }
        if advancedHardening {
            settings.cleanExternalLinks = true
            settings.cleanUNCPaths = true
            settings.cleanUserPaths = true
            settings.cleanInternalURLs = true
            settings.cleanOLESources = true
            settings.cleanImageEXIF = true
            settings.cleanStyleNames = true
            settings.cleanChartLabels = true
            settings.cleanFormDefaults = true
            settings.cleanLanguageSettings = true
            settings.cleanActiveX = true
        }
    }
    
    private func clearAllInGroup(appProperties: Bool = false, coreProperties: Bool = false, documentStructure: Bool = false, embeddedContent: Bool = false, advancedHardening: Bool = false) {
        if appProperties {
            settings.cleanCompany = false
            settings.cleanManager = false
            settings.cleanTotalEditingTime = false
            settings.cleanApplication = false
            settings.cleanAppVersion = false
            settings.cleanTemplate = false
            settings.cleanStatistics = false
            settings.cleanDocSecurity = false
            settings.cleanScaleCrop = false
            settings.cleanLinksUpToDate = false
            settings.cleanSharedDoc = false
            settings.cleanHyperlinksChanged = false
        }
        if coreProperties {
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
        }
        if documentStructure {
            settings.cleanReviewComments = false
            settings.cleanTrackChanges = false
            settings.cleanRSIDs = false
            settings.cleanDocumentGUID = false
            settings.cleanSpellGrammarState = false
            settings.cleanDocumentVariables = false
        }
        if embeddedContent {
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
        }
        if advancedHardening {
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
        }
    }
    
    private func invertGroup(appProperties: Bool = false, coreProperties: Bool = false, documentStructure: Bool = false, embeddedContent: Bool = false, advancedHardening: Bool = false) {
        if appProperties {
            settings.cleanCompany.toggle()
            settings.cleanManager.toggle()
            settings.cleanTotalEditingTime.toggle()
            settings.cleanApplication.toggle()
            settings.cleanAppVersion.toggle()
            settings.cleanTemplate.toggle()
            settings.cleanStatistics.toggle()
            settings.cleanDocSecurity.toggle()
            settings.cleanScaleCrop.toggle()
            settings.cleanLinksUpToDate.toggle()
            settings.cleanSharedDoc.toggle()
            settings.cleanHyperlinksChanged.toggle()
        }
        if coreProperties {
            settings.cleanAuthor.toggle()
            settings.cleanLastModifiedBy.toggle()
            settings.cleanTitle.toggle()
            settings.cleanSubject.toggle()
            settings.cleanKeywords.toggle()
            settings.cleanComments.toggle()
            settings.cleanCategory.toggle()
            settings.cleanContentStatus.toggle()
            settings.cleanCreatedDate.toggle()
            settings.cleanModifiedDate.toggle()
            settings.cleanLastPrinted.toggle()
            settings.cleanRevisionNumber.toggle()
            settings.cleanIdentifier.toggle()
            settings.cleanLanguage.toggle()
            settings.cleanVersion.toggle()
        }
        if documentStructure {
            settings.cleanReviewComments.toggle()
            settings.cleanTrackChanges.toggle()
            settings.cleanRSIDs.toggle()
            settings.cleanDocumentGUID.toggle()
            settings.cleanSpellGrammarState.toggle()
            settings.cleanDocumentVariables.toggle()
        }
        if embeddedContent {
            settings.cleanThumbnail.toggle()
            settings.cleanHyperlinkURLs.toggle()
            settings.cleanAltText.toggle()
            settings.cleanOLEObjects.toggle()
            settings.cleanVBAMacros.toggle()
            settings.cleanDigitalSignatures.toggle()
            settings.cleanPrinterSettings.toggle()
            settings.cleanEmbeddedFonts.toggle()
            settings.cleanGlossary.toggle()
            settings.cleanFastSaveData.toggle()
        }
        if advancedHardening {
            settings.cleanExternalLinks.toggle()
            settings.cleanUNCPaths.toggle()
            settings.cleanUserPaths.toggle()
            settings.cleanInternalURLs.toggle()
            settings.cleanOLESources.toggle()
            settings.cleanImageEXIF.toggle()
            settings.cleanStyleNames.toggle()
            settings.cleanChartLabels.toggle()
            settings.cleanFormDefaults.toggle()
            settings.cleanLanguageSettings.toggle()
            settings.cleanActiveX.toggle()
        }
    }
}

// MARK: - Supporting Views

struct MetadataItem {
    let label: String
    let description: String
    var binding: Binding<Bool>
}

struct MetadataGroupView: View {
    let title: String
    let subtitle: String
    let groupKey: String
    @Binding var collapsedStates: [String: [MetadataCleaningPreset: Bool]]
    let currentPreset: MetadataCleaningPreset
    let items: [MetadataItem]
    let onSelectAll: () -> Void
    let onClearAll: () -> Void
    let onInvert: () -> Void
    
    private var isExpanded: Bool {
        !(collapsedStates[groupKey]?[currentPreset] ?? false)
    }
    
    private func setExpanded(_ expanded: Bool) {
        if collapsedStates[groupKey] == nil {
            collapsedStates[groupKey] = [:]
        }
        collapsedStates[groupKey]?[currentPreset] = !expanded
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header with expand/collapse
            HStack {
                Button {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        setExpanded(!isExpanded)
                    }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: isExpanded ? "chevron.down" : "chevron.right")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(.secondary)
                            .frame(width: 16)
                        
                        Text(title)
                            .font(.system(size: 14, weight: .semibold))
                        
                        Text("(\(subtitle))")
                            .font(.system(size: 12))
                            .foregroundColor(.secondary)
                    }
                }
                .buttonStyle(.plain)
                
                Spacer()
                
                // Only show All/None/Invert buttons in Custom mode
                if isExpanded && currentPreset == .custom {
                    Button("All") {
                        onSelectAll()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
                    
                    Button("None") {
                        onClearAll()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
                    
                    Button("Invert") {
                        onInvert()
                    }
                    .buttonStyle(.bordered)
                    .controlSize(.mini)
                }
            }
            
            if isExpanded {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(items.indices, id: \.self) { index in
                        let item = items[index]
                        Toggle(isOn: item.binding) {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(item.label)
                                    .font(.system(size: 13))
                                Text(item.description)
                                    .font(.system(size: 11))
                                    .foregroundColor(.secondary)
                            }
                        }
                        .toggleStyle(.checkbox)
                    }
                }
                .padding(.leading, 22)
            }
        }
    }
}

#Preview {
    MetadataCleaningSheet(settings: .constant(.default))
}
