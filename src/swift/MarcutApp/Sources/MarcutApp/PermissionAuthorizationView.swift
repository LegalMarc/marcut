import SwiftUI

struct PermissionAuthorizationView: View {
    @ObservedObject var permissionManager: PermissionManager
    @State private var showExplanation = false
    @State private var isAuthorizing = false
    @State private var authorizationStep = ""
    @State private var authorizationError: String? = nil

    var body: some View {
        VStack(spacing: 30) {
            // Header
            VStack(spacing: 12) {
                Image(systemName: "lock.shield.fill")
                    .font(.system(size: 60))
                    .foregroundColor(.blue)

                Text("Welcome to MarcutApp")
                    .font(.largeTitle)
                    .fontWeight(.bold)

                Text("One-time setup required")
                    .font(.title2)
                    .foregroundColor(.secondary)
            }

            // Permission Details
            VStack(spacing: 16) {
                Text("MarcutApp needs these permissions to work properly:")
                    .font(.headline)
                    .frame(maxWidth: .infinity, alignment: .leading)

                VStack(spacing: 12) {
                    PermissionRow(
                        icon: "folder.fill",
                        iconColor: .orange,
                        title: "File System Access",
                        description: "Read Word documents and create redacted files in your chosen folders",
                        isRequired: true
                    )

                    PermissionRow(
                        icon: "network.fill",
                        iconColor: .green,
                        title: "Local AI Processing",
                        description: "Run AI models locally on your Mac for private, offline processing",
                        isRequired: true
                    )

                    PermissionRow(
                        icon: "doc.text.fill",
                        iconColor: .blue,
                        title: "Document Folder Access",
                        description: "Access your Documents folder to redact Word files",
                        isRequired: true
                    )
                }
                .padding()
                .background(Color(NSColor.controlBackgroundColor))
                .cornerRadius(12)
            }

            // Processing State
            if isAuthorizing {
                VStack(spacing: 12) {
                    ProgressView()
                        .scaleEffect(1.2)

                    Text(authorizationStep)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                }
                .padding()
            }

            // Error Display
            if let error = authorizationError {
                VStack(spacing: 8) {
                    Label("Authorization Failed", systemImage: "exclamationmark.triangle.fill")
                        .font(.headline)
                        .foregroundColor(.red)

                    Text(error)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)

                    Button("Try Again") {
                        authorizePermissions()
                    }
                    .buttonStyle(.borderedProminent)
                }
                .padding()
                .background(Color.red.opacity(0.1))
                .cornerRadius(12)
            }

            // Action Buttons
            if !isAuthorizing && authorizationError == nil {
                VStack(spacing: 16) {
                    Button(action: {
                        authorizePermissions()
                    }) {
                        HStack {
                            Text("Grant Permissions & Continue")
                            Image(systemName: "arrow.right")
                        }
                        .frame(maxWidth: .infinity)
                        .font(.headline)
                    }
                    .buttonStyle(.borderedProminent)
                    .controlSize(.large)
                    .disabled(isAuthorizing)

                    HStack(spacing: 20) {
                        Button("Learn More") {
                            showExplanation.toggle()
                        }
                        .foregroundColor(.blue)

                        Button("Quit") {
                            NSApplication.shared.terminate(nil)
                        }
                        .foregroundColor(.secondary)
                    }
                }
            }

            // Privacy & Security Info
            VStack(spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.shield.fill")
                        .foregroundColor(.green)
                        .font(.caption)

                    Text("All processing happens locally on your Mac")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }

                HStack(spacing: 6) {
                    Image(systemName: "lock.fill")
                        .foregroundColor(.blue)
                        .font(.caption)

                    Text("No data ever leaves your computer")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }

                HStack(spacing: 6) {
                    Image(systemName: "clock.fill")
                        .foregroundColor(.orange)
                        .font(.caption)

                    Text("These permissions are requested only once")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
        }
        .padding(40)
        .frame(width: 520, height: 600)
        .background(Color(NSColor.windowBackgroundColor))
        .sheet(isPresented: $showExplanation) {
            PermissionExplanationView()
        }
        .onAppear {
            authorizationError = nil
        }
    }

    private func authorizePermissions() {
        authorizationError = nil
        authorizationStep = "Requesting permissions..."
        isAuthorizing = true

        Task {
            do {
                try await permissionManager.requestNotificationPermission()
                authorizationStep = "Permissions granted"
            } catch {
                authorizationError = error.localizedDescription
            }
            isAuthorizing = false
        }
    }
}

struct PermissionRow: View {
    let icon: String
    let iconColor: Color
    let title: String
    let description: String
    let isRequired: Bool

    init(icon: String, iconColor: Color, title: String, description: String, isRequired: Bool = true) {
        self.icon = icon
        self.iconColor = iconColor
        self.title = title
        self.description = description
        self.isRequired = isRequired
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundColor(iconColor)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(title)
                        .font(.headline)
                        .fontWeight(.medium)

                    if isRequired {
                        Text("Required")
                            .font(.caption)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.red.opacity(0.1))
                            .foregroundColor(.red)
                            .cornerRadius(4)
                    }
                }

                Text(description)
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer()
        }
        .padding(.vertical, 4)
    }
}

struct PermissionExplanationView: View {
    @Environment(\.presentationMode) var presentationMode

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Text("Why MarcutApp Needs These Permissions")
                .font(.largeTitle)
                .fontWeight(.bold)
                .multilineTextAlignment(.leading)

            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    ExplanationSection(
                        title: "File System Access",
                        icon: "folder.fill",
                        color: .orange,
                        explanation: "MarcutApp needs to read your Word documents (.docx files) and save the redacted versions. This permission allows the app to access the files you select and create new redacted files in your chosen output folder.",
                        details: [
                            "Read Microsoft Word documents that you select",
                            "Create new redacted documents with track changes",
                            "Generate audit reports in JSON format",
                            "Access files in your Downloads, Documents, and Desktop folders"
                        ]
                    )

                    ExplanationSection(
                        title: "Local AI Processing",
                        icon: "network.fill",
                        color: .green,
                        explanation: "MarcutApp runs AI models locally on your Mac to identify sensitive information. The app starts a local server (Ollama) that runs entirely on your device.",
                        details: [
                            "Run AI models like Llama 3.1 8B locally",
                            "No internet connection required for processing",
                            "All AI computation happens on your Mac",
                            "Complete privacy - no data sent to external servers"
                        ]
                    )

                    ExplanationSection(
                        title: "Document Folder Access",
                        icon: "doc.text.fill",
                        color: .blue,
                        explanation: "This permission allows MarcutApp to access your Documents folder so you can easily select Word files for redaction without having to navigate through file dialogs each time.",
                        details: [
                            "One-time access to your Documents folder",
                            "Access only to files you explicitly select",
                            "Maintains security through sandboxing",
                            "You can revoke this permission at any time in System Preferences"
                        ]
                    )
                }
            }
            .frame(maxHeight: 400)

            HStack {
                Button("Close") {
                    presentationMode.wrappedValue.dismiss()
                }
                .keyboardShortcut(.defaultAction)
                .controlSize(.large)

                Spacer()
            }
            .padding(.top)
        }
        .padding(30)
        .frame(width: 600, height: 650)
    }
}

struct ExplanationSection: View {
    let title: String
    let icon: String
    let color: Color
    let explanation: String
    let details: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 10) {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundColor(color)

                Text(title)
                    .font(.title2)
                    .fontWeight(.semibold)
            }

            Text(explanation)
                .font(.body)
                .foregroundColor(.primary)

            VStack(alignment: .leading, spacing: 6) {
                ForEach(details, id: \.self) { detail in
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(color)
                            .font(.caption)

                        Text(detail)
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                    }
                }
            }
        }
        .padding(16)
        .background(Color(NSColor.controlBackgroundColor))
        .cornerRadius(8)
    }
}
