# Metadata Forensics Primer

## The Digital Paper Trail: A Forensic Guide to .docx Metadata

The evolution of document processing from binary structures to the Office Open XML (OOXML) standard has fundamentally transformed the landscape of digital forensics and legal discovery. For the junior forensic analyst or the litigation specialist using Marcut, it is essential to recognize that a modern `.docx` file is not a singular, monolithic entity. Instead, it represents a highly structured, modular ecosystem of data, governed by the Open Packaging Conventions (OPC) and the ECMA-376 standard. To the naked eye, a document is a collection of words and images; to the forensic investigator, it is a complex ZIP archive — a container that encapsulates a network of XML files, relationship maps, and binary assets that collectively document the document's entire lifecycle.

While the visible narrative provides the "what" of a case, the metadata — the data about data — provides the "who, when, where, and how." This forensic guide serves as a comprehensive introduction to navigating the layers of information hidden within the OOXML standard. By mastering the extraction and interpretation of these digital fingerprints, analysts can establish immutable timelines, attribute authorship to specific workstations, and uncover the environmental context where a document was born, edited, or intentionally manipulated.

## The Anatomy and Architecture of the OOXML Container

The transition from the legacy `.doc` binary format to the XML-based `.docx` format was driven by the need for interoperability, transparency, and data recovery. The OOXML architecture relies on the Open Packaging Conventions, which utilize the ZIP compression format to bundle disparate components into a single file package. This modularity allows applications like Marcut to target specific "parts" of a document without the need to parse the entire file, but it also creates numerous hiding places for "ghost" data and steganographic content.

### The Package Root and Master Index

Every `.docx` package contains a root directory that serves as the foundation for its internal file system. The most critical component at this level is the `[Content_Types].xml` file. This file acts as the master index, defining the MIME types for every other part within the package. From a forensic standpoint, this index is a primary validation tool. Any file present in the ZIP container that is not declared in `[Content_Types].xml` is an immediate red flag, often indicating the presence of hidden malware, steganographic payloads, or manual tampering that bypassed the Word application.

### The Relationship Model and `.rels` Files

Relationships are the "connective tissue" of an OOXML document. They are stored in `_rels` folders as XML files that define how one part of the package relates to another, or to external resources. The primary relationship file, located at `/_rels/.rels`, identifies the main document part, while the `word/_rels/document.xml.rels` file maps the internal assets of the document, such as images, headers, and hyperlinks.

| Relationship Component | XML Attribute | Forensic Significance |
| --- | --- | --- |
| Relationship ID | `Id` | A unique identifier (e.g., `rId1`) used to link text to assets. |
| Target | `Target` | The path to the internal or external resource. |
| Target Mode | `TargetMode` | Defines if the resource is "Internal" or "External." |
| Type | `Type` | The schema definition (e.g., image, hyperlink, or template). |

Analyzing the `Target` attribute is a high-value forensic activity. For instance, a relationship target pointing to a local file path like `C:\Users\JohnDoe\Documents\Confidential\evidence.jpg` provides a direct link to the creator's local directory structure, even if the image itself has been deleted or moved. Furthermore, external targets pointing to remote URLs can indicate "Remote Template Injection" attacks, where a document is configured to fetch a malicious template from an attacker-controlled server upon opening.

## Core and Extended Property Metadata

Metadata in the OOXML standard is categorized primarily into core properties, which follow the Dublin Core Metadata Initiative (DCMI), and extended or custom properties, which provide application-specific statistics and user-defined governance labels.

### Core Properties (`docProps/core.xml`)

The `core.xml` file is the "digital ID card" of the document. It contains the standard timestamps and authorship fields that are most frequently introduced as evidence in legal proceedings.

| Property | XML Element | Forensic Interpretation |
| --- | --- | --- |
| Creator | `dc:creator` | The user profile that initially created the document. |
| Last Modified By | `cp:lastModifiedBy` | The user profile that performed the last save operation. |
| Created Date | `dcterms:created` | Initial creation timestamp in UTC format. |
| Modified Date | `dcterms:modified` | Last modification timestamp in UTC format. |
| Revision | `cp:revision` | An integer representing the total number of save events. |

A common forensic insight involves comparing the **Creator** and **Last Modified By** fields. In procurement fraud cases, investigators have identified collusion when multiple bid documents, supposedly from competing firms, all shared the same **Creator** metadata, indicating they originated from a single source within the organization. Similarly, a high revision count coupled with a very short duration between the creation and modification dates suggests a document that was heavily edited elsewhere and then "pasted" into a new file to hide its true history.

### Extended Properties (`docProps/app.xml`)

The `app.xml` file houses statistical metadata generated by the Microsoft Word application. While core properties provide a timeline, extended properties provide an audit of the document's production process.

One of the most valuable fields in `app.xml` is the `TotalTime` element, which tracks the cumulative number of minutes the document has been active for editing. A "0" or unusually low value in a lengthy or complex document is a classic indicator of metadata scrubbing or content transplantation. Additionally, the `Template` field records the name of the base template used. Forensic analysis of this field can reveal the use of proprietary organizational templates or specific versions of `Normal.dotm`, which can then be cross-referenced with the subject's computer to confirm the document's origin.

### Custom Properties and Sensitivity Labels (`custom.xml`)

The `custom.xml` file allows for user-defined metadata. In high-stakes legal and corporate environments, this file is often used to store Microsoft Information Protection (MIP) sensitivity labels. These labels are critical for forensic investigators tracking the mishandling of sensitive data.

| MIP Attribute | Value Format | Forensic Value |
| --- | --- | --- |
| `MSIP_Label_GUID_Enabled` | Boolean | Confirms if a sensitivity policy was active. |
| `MSIP_Label_GUID_SetDate` | ISO 8601 Timestamp | Precise time when the classification was applied. |
| `MSIP_Label_GUID_Method` | "Standard" or "Privileged" | Distinguishes between automatic and manual labeling. |
| `MSIP_Label_GUID_SiteId` | GUID | Identifies the specific Microsoft Entra tenant (Organization ID). |

The presence of the **Privileged** method indicates a user manually selected the label, which can be used to prove intent in data exfiltration cases. If a user downgrades a label from "Highly Confidential" to "Public" before emailing a file, the `custom.xml` (or `docMetadata`) audit trail will reflect this change, providing evidence of policy evasion.

## Revision Session Identifiers (RSIDs): The Forensic Heartbeat

Perhaps the most powerful and technically nuanced artifact in the `.docx` format is the Revision Session Identifier (RSID). RSIDs are four-digit hexadecimal numbers (e.g., `00BE2C6C`) assigned by Microsoft Word to track individual editing sessions. An editing session is defined as the period between two save actions.

### The Mechanism of RSID Propagation

When a document is edited and saved, Word generates a new RSID and uses it to tag every insertion, deletion, and formatting change made during that session. These IDs are stored in a summary table called the `rsidtbl` within `word/settings.xml`. The `rsidRoot` represents the initial ID assigned when the document was first created.

The retention of RSIDs is what enables "document genealogy." If two documents have entirely different text but share an identical `rsidRoot` and a majority of the same IDs in their `rsidtbl`, they are undeniably related by a common ancestor. This technique is used extensively to detect academic plagiarism and contract cheating. Research has shown that RSIDs are highly unique; a study detected only a 2% false positive rate where unrelated documents shared identifiers, making them a robust tool for establishing the source of intellectual property.

### Tracing Authorship through Template Signatures

RSIDs also serve as machine signatures. When Microsoft Word is first installed on a computer, it generates "legacy RSIDs" in the `normal.dotm` template. Every new document created on that machine will inherit these specific RSIDs as part of its baseline metadata. This allows forensic analysts to link a document back to a specific installation of Word, providing a "fingerprint" of the workstation used even if the author's name has been changed in the core properties.

## Structural Metadata and the Digital Environment

Structural metadata reveals the "blueprint" of the document and its relationship to the external digital world. This information is primarily housed in `settings.xml` and the various `.rels` files.

### Attached Templates and Network Paths

The `word/settings.xml` file often contains the `attachedTemplate` element, which stores the full local or network path of the template used to generate the document. This path is a frequent source of "leaked" information, often containing the local Windows username (e.g., `C:\Users\JohnDoe\AppData\Roaming\Microsoft\Templates\Normal.dotm`) or internal server names. In cases of anonymous harassment or leaked corporate memos, this path can provide the critical link to a specific employee’s account.

### Printer Settings and Hardware Attribution

Another often-overlooked artifact in `settings.xml` is the reference to printer settings. Word documents may contain binary parts (e.g., `printerSettings1.bin`) that store the configuration of the last printer used. This can include the printer's network name, model, and even the paper tray configurations. For an investigator, this data can be used to correlate a digital file with physical hardware found at a suspect's location, establishing that the document was not only created on a certain computer but also printed on a certain device.

## The "Hidden Cargo": Media, OLE Objects, and Thumbnails

The `.docx` container is frequently used to transport other files, and the way these assets are handled by the OOXML standard creates significant forensic opportunities.

### Embedded Image EXIF Data

When a user inserts a photo into a Word document, the application stores a copy of that image in the `word/media/` folder. Word does not automatically strip the metadata from these files. Consequently, a JPEG embedded in a document may still contain its original Exchangeable Image File Format (EXIF) data, including:

- GPS coordinates: the exact location where the photo was taken.
- Device information: the serial number and model of the camera or smartphone used.
- Original timestamps: which may differ significantly from the document's creation date, revealing the actual timeline of evidence gathering.

### The Forensic Significance of Thumbnails

The `docProps/thumbnail.jpeg` file provides a low-resolution preview of the document's first page. A critical forensic anomaly occurs when a document is modified but the thumbnail is not updated. If the thumbnail displays content that is no longer present in the `document.xml` file, it provides proof that the document was altered after its initial creation. Furthermore, Windows creates a "thumbcache" on the local disk that persists even after a document is deleted. Analysts can use these cached thumbnails to reconstruct user activity and identify files that have been "wiped" from the system.

### OLE Objects and Recursive Analysis

Microsoft Word allows for the embedding of "Object Linking and Embedding" (OLE) items, such as Excel spreadsheets or other Word documents. These are stored as binary files (e.g., `embeddings/oleObject1.bin`) within the archive. These objects contain their own independent metadata streams and revision histories. A thorough forensic examination must be recursive, treating every embedded object as a separate "sub-document" with its own provenance.

## Understanding "Ghost" Data and Content Persistence

Forensic analysis often involves finding what was meant to be hidden. The OOXML format is surprisingly "noisy," retaining data that users believe they have deleted.

### Track Changes and Comments

Even if the "Track Changes" feature is hidden in the Word user interface, the underlying XML in `document.xml` and `comments.xml` retains the full history of deletions and insertions. Every change is tagged with the author's name and a timestamp. These "ghost" versions of the text can be extracted to reveal discarded arguments, retracted statements, or the involvement of unauthorized collaborators.

### External Relationships and Link Paths

The `.rels` files can expose links to files on the creator’s hard drive or private network drives that are no longer accessible. For example, if a document was created by merging data from a spreadsheet, the relationship file may still contain the path `D:\Confidential\Project_X\Financials.xlsx`. Even if the spreadsheet was not included in the final package, its former location and name provide insight into the creator's file organization and the scope of the project.

## The Temporal Dimension: Correlating Internal and File System Metadata

One of the most complex tasks for a forensic analyst is the synchronization of time. A `.docx` file has two distinct sets of timestamps that must be cross-referenced to ensure authenticity.

### File System Metadata (NTFS MACB Times)

The operating system records "MACB" times (Modified, Accessed, Changed, Birth) for every file on a disk. These are derived from the system clock and are stored in the Master File Table (MFT).

| Timestamp | Description | Forensic Context |
| --- | --- | --- |
| Modified | Content of the file changed. | Updates only when the ZIP container is resaved. |
| Accessed | File was read or executed. | Can be updated by antivirus scans or backups. |
| Changed | MFT metadata was altered. | Includes permission changes or renaming. |
| Birth | File creation on the volume. | In copy operations, "Birth" is the time of the copy. |

### Internal XML Metadata (Application Times)

The `core.xml` file contains timestamps generated by the Word application itself. A critical forensic insight is that if a document is copied from a USB drive to a Desktop, the NTFS "Birth" time will reflect the moment of the copy, but the internal `dcterms:created` time will still reflect the original creation date. If the internal "Modified" date is older than the NTFS "Created" date, the file was almost certainly copied from another source.

### Detecting "Time-Stomping"

"Time-stomping" is an anti-forensic technique where a user intentionally modifies system timestamps to align them with a false narrative. Analysts detect this by looking for inconsistencies between the `$STANDARD_INFORMATION` and `$FILE_NAME` attributes in the NTFS MFT. While many tools can "stomp" the former, the latter is only updated by the kernel and can reveal the original, true timestamps. Furthermore, dynamic time analysis involves comparing file timestamps to independent, external sources of time, such as internal document text that references a news event that occurred after the supposed creation date.

## Legal Admissibility and the Forensic Workflow

In modern jurisprudence, metadata is no longer considered "secondary" evidence. It is a cornerstone of evidence management and courtroom strategy.

### Metadata as Evidence (FRE 901 and 902)

Under the Federal Rules of Evidence (FRE), metadata plays a critical role in authentication.

- **FRE 901**: Metadata serves as circumstantial evidence of authenticity by documenting the history and origin of a file.
- **FRE 902(13) & (14)**: These rules allow for the self-authentication of electronic records if they are accompanied by a certification from a qualified person and have a verified digital hash.
- **Non-hearsay**: Because metadata is machine-generated rather than created by a human witness, it often qualifies as a non-hearsay form of evidence, simplifying its admissibility.

### The Danger of Improper Redaction

A frequent "metadata trap" in legal settings involves the failure to properly sanitize documents before production. Simply highlighting text in black or deleting a paragraph in Word does not remove the underlying XML metadata or the revision history. In one high-profile case, a law firm shared a "sanitized" PDF, but the metadata revealed that the document was originally authored by a different law firm, exposing a hidden collaboration that sabotaged their strategy. To avoid this, legal professionals must use forensic-grade tools to "flatten" or sanitize files, ensuring that only the intended information is shared.

## Advanced Forensics: Steganography and Data Hiding

The modularity of the OOXML format makes it an ideal environment for steganography — the practice of concealing information within a seemingly innocuous file.

### Technical Steganographic Methods

Malicious actors can exploit the OOXML structure in several ways:

- **Attribute overloading**: Adding hidden data into existing XML attributes that the Word application ignores but that can be read by a custom decoder.
- **Part injection**: Adding entirely new XML parts or media files into the ZIP archive that are not referenced in any relationship file. These files will not appear when the document is opened in Word but are easily recovered by forensic tools.
- **RSID substitution**: Manually altering RSID values to encode secret text or watermarks into the document's revision table.

Detecting these hidden elements requires a "black box" approach, where an analyst compares the actual files present in the ZIP container against the official schema and relationship maps. Any discrepancy — such as a file named `secret.txt` in the `word/` folder that has no relationship ID — is an immediate indicator of steganographic use.

## Practical Recommendations for Marcut Users

When beginning a forensic extraction with Marcut, analysts should follow a standardized workflow to ensure the integrity and comprehensiveness of their findings.

1. **Verification of Integrity**
   - Always begin by calculating the cryptographic hash (MD5, SHA-1, or SHA-256) of the original file.
   - Perform analysis on a forensic copy to prevent accidental modification of system metadata.
   - If the Marcut analysis reveals a revision count that does not match the file's modification history, investigate whether the document was edited in a non-Word application or metadata was scrubbed.

2. **Cross-Referencing Timelines**
   - Never rely on a single timestamp. Build a multi-layered timeline that includes:
     - Internal XML creation and modification dates.
     - File system MACB times.
     - Revision session (RSID) timestamps (if available through version comparison).
     - Timestamps from embedded assets (EXIF data and OLE objects).
   - Inconsistencies between these sources are where the most valuable forensic "truth" is often hidden.

3. **Structural and Relationship Analysis**
   - Scrutinize the `.rels` files for external targets. A document that "calls home" to a remote server for a template or a style sheet is a major security and forensic concern.
   - Check for orphaned media files or XML parts that are present in the ZIP container but are not declared in the relationship maps; these are prime candidates for steganographic data or malware.

4. **Qualitative Narrative over Quantitative Lists**
   - When presenting findings to a court or a client, weave the technical metadata into a human narrative.
   - A list of RSIDs is meaningless to a jury; an explanation that "these identical session IDs prove that Document A was the source for the plagiarized sections of Document B" is compelling evidence.
   - Use Marcut to extract data, but use forensic intuition to explain its implications for the case at hand.

## Final Synthesis: Metadata as the Digital Witness

The journey through the `.docx` container reveals a simple truth: in the digital age, every action leaves a trace. Metadata is the digital equivalent of body language — subtle, often subconscious, and frequently more revealing than the written word. For junior forensic analysts and lawyers, the mastery of OOXML forensics is no longer an optional skill; it is a fundamental requirement for the modern practice of law and investigation.

As you use Marcut to explore the digital paper trail, remember that metadata never forgets. It is a secret diary kept by the file itself, documenting its origins, its collaborators, and its modifications. Whether you are verifying the authenticity of a contract, uncovering an insider threat, or tracing the genealogy of a leaked document, the metadata is your most reliable witness. By understanding the technical architecture of the OOXML standard and the forensic significance of its many parts, you can uncover the truth that lies beneath the surface of every document.

## References and Standards

### Technical Standards and Specifications

- ECMA-376 / ISO/IEC 29500: Office Open XML File Formats — official technical specifications for the structure of `.docx`, `.xlsx`, and `.pptx` containers.
- Microsoft Purview Information Protection: LabelInfo Stream Schema — technical documentation for the storage and XML schema of sensitivity labels (MIP) within OOXML files.
- Microsoft Word Internal Settings and XML Schema — developer references for `settings.xml`, `app.xml`, and the relationship model (`_rels`).

### Academic Research on Document Genealogy and RSIDs

- Spennemann, D. H. R. & Spennemann, R. J. (2023) "Establishing Genealogies of Born Digital Content: The Suitability of Revision Identifier (RSID) Numbers in MS Word for Forensic Enquiry." Publications, MDPI.
- Spennemann, D. H. R. & Singh, C. L. (2024) "The Generation of Revision Identifier (rsid) Numbers in MS Word: Implications for Document Analysis." International Journal of Digital Curation.
- Garfinkel, S. L. (2009/2012) "Digital Forensics XML and the DFXML Toolset" and research on XML metadata vulnerabilities.

### Forensic Methods and Temporal Analysis

- GIAC / SANS Institute (2023) "Filesystem Timestamps: What Makes Them Tick" — analysis of NTFS MACB behavior and time-stomping detection.
- Utica College / Economic Crime Investigation Institute (2002) "Dynamic Time and Date Stamp Analysis" — methodology for correlating internal application dates with system metadata.
- Pentest Partners (2023) "Thumbnail Forensics: DFIR Techniques for Analysing Windows Thumbcache."
- Cyber Engage (2024) "Understanding NTFS Timestamps for Timeline Analysis."

### Legal Standards and Professional Case Studies

- US Legal Support / Axon: "Admissibility Standards for Digital Evidence: Federal Rules of Evidence (FRE) 901, 902, and 803."
- Summit Consulting Ltd / Forensic Institute (2025) "Metadata Matters: What Your Files Reveal Without Saying a Word" — case studies on procurement fraud and legal document collaboration leaks.
- Maras, M. (2011) "Computer Forensics: Cybercriminals, Laws, and Evidence" — documentation of the BTK killer investigation and the role of metadata in serial murder cases.
- LegalFuel / Florida Bar: "Seven Things Every Litigator Must Know About Metadata" — system vs. application metadata distinctions.
