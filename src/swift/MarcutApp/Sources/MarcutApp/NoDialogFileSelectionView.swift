import SwiftUI

/// File selection that doesn't trigger permission dialogs by using authorized directories
struct NoDialogFileSelectionView: View {
    @StateObject private var fileCoordinator = FileAccessCoordinator.shared
    @State private var availableFiles: [URL] = []
    @State private var selectedFiles: Set<URL> = []
    @State private var isLoading = false

    let onFilesSelected: ([URL]) -> Void

    init(onFilesSelected: @escaping ([URL]) -> Void) {
        self.onFilesSelected = onFilesSelected
    }

    var body: some View {
        VStack(spacing: 20) {
            // Header
            VStack(spacing: 8) {
                Text("Select Documents to Redact")
                    .font(.largeTitle)
                    .fontWeight(.bold)

                Text("Choose from your Documents, Downloads, and Desktop folders")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
            }

            // File List
            if isLoading {
                VStack(spacing: 16) {
                    ProgressView()
                        .scaleEffect(1.2)

                    Text("Scanning for Word documents...")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
                .frame(height: 200)
            } else if availableFiles.isEmpty {
                VStack(spacing: 16) {
                    Image(systemName: "doc.text.fill")
                        .font(.system(size: 48))
                        .foregroundColor(.gray)

                    Text("No Word Documents Found")
                        .font(.headline)
                        .foregroundColor(.secondary)

                    Text("Place .docx files in your Documents, Downloads, or Desktop folders")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)

                    Button("Refresh") {
                        loadFiles()
                    }
                    .buttonStyle(.borderedProminent)
                }
                .frame(height: 200)
            } else {
                ScrollView {
                    LazyVStack(spacing: 8) {
                        ForEach(availableFiles, id: \.self) { fileURL in
                            FileRowView(
                                fileURL: fileURL,
                                isSelected: selectedFiles.contains(fileURL)
                            ) {
                                toggleSelection(fileURL)
                            }
                        }
                    }
                    .padding()
                }
                .frame(maxHeight: 300)
                .border(Color.gray.opacity(0.3), width: 1)
            }

            // Selection Info
            if !selectedFiles.isEmpty {
                Text("\(selectedFiles.count) document\(selectedFiles.count == 1 ? "" : "s") selected")
                    .font(.subheadline)
                    .foregroundColor(.blue)
            }

            // Action Buttons
            HStack(spacing: 16) {
                Button("Refresh") {
                    loadFiles()
                }
                .buttonStyle(.bordered)

                Spacer()

                Button("Add Selected (\(selectedFiles.count))") {
                    onFilesSelected(Array(selectedFiles))
                }
                .buttonStyle(.borderedProminent)
                .disabled(selectedFiles.isEmpty)
            }
        }
        .padding(24)
        .frame(width: 600, height: 500)
        .onAppear {
            loadFiles()
        }
    }

    private func loadFiles() {
        isLoading = true
        availableFiles = []
        selectedFiles = []

        Task {
            await fileCoordinator.authorizeCommonDirectories()

            let foundFiles = await fileCoordinator.findDocxFiles()
            await MainActor.run {
                availableFiles = foundFiles
                    .sorted { url1, url2 in
                        // Sort by filename, then by directory
                        let name1 = url1.lastPathComponent.lowercased()
                        let name2 = url2.lastPathComponent.lowercased()
                        if name1 != name2 {
                            return name1 < name2
                        }
                        return url1.path < url2.path
                    }
                isLoading = false
            }
        }
    }

    private func toggleSelection(_ fileURL: URL) {
        if selectedFiles.contains(fileURL) {
            selectedFiles.remove(fileURL)
        } else {
            selectedFiles.insert(fileURL)
        }
    }
}

struct FileRowView: View {
    let fileURL: URL
    let isSelected: Bool
    let onToggle: () -> Void

    private var fileName: String {
        fileURL.lastPathComponent
    }

    private var directoryName: String {
        fileURL.deletingLastPathComponent().lastPathComponent
    }

    private var fileSize: String {
        do {
            let attributes = try FileManager.default.attributesOfItem(atPath: fileURL.path)
            if let size = attributes[.size] as? Int64 {
                return ByteCountFormatter.string(fromByteCount: size, countStyle: .file)
            }
        } catch {
            // Handle error silently
        }
        return "Unknown"
    }

    var body: some View {
        HStack(spacing: 12) {
            // Selection checkbox
            Button(action: onToggle) {
                Image(systemName: isSelected ? "checkmark.square.fill" : "square")
                    .font(.title2)
                    .foregroundColor(isSelected ? .blue : .gray)
            }
            .buttonStyle(PlainButtonStyle())

            // File icon
            Image(systemName: "doc.text.fill")
                .font(.title2)
                .foregroundColor(.blue)

            // File info
            VStack(alignment: .leading, spacing: 2) {
                Text(fileName)
                    .font(.headline)
                    .lineLimit(1)

                HStack {
                    Text(directoryName)
                        .font(.caption)
                        .foregroundColor(.secondary)

                    Text("•")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    Text(fileSize)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }

            Spacer()
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background(
            RoundedRectangle(cornerRadius: 8)
                .fill(isSelected ? Color.blue.opacity(0.1) : Color.clear)
        )
        .contentShape(Rectangle())
        .onTapGesture {
            onToggle()
        }
    }
}

// MARK: - Alternative Simple View for Integration

/// Simple file browser that can replace NSOpenPanel in existing code
extension ContentView {
    func showNoDialogFileSelection(completion: @escaping ([URL]) -> Void) {
        let window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 600, height: 500),
            styleMask: [.titled, .closable],
            backing: .buffered,
            defer: false
        )

        window.title = "Select Documents"
        window.contentView = NSHostingView(rootView: NoDialogFileSelectionView(onFilesSelected: { urls in
            completion(urls)
            window.close()
        }))

        window.center()
        window.makeKeyAndOrderFront(nil)
    }
}