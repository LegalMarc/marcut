import SwiftUI

struct AboutView: View {
    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "Unknown"
    }
    private var buildNumber: String {
        Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? ""
    }

    var body: some View {
        VStack(spacing: 20) {
            // App Icon with gradient background
            ZStack {
                Circle()
                    .fill(LinearGradient(
                        colors: [Color.blue.opacity(0.1), Color.teal.opacity(0.1)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ))
                    .frame(width: 90, height: 90)

                if let appIcon = NSApp.applicationIconImage {
                    Image(nsImage: appIcon)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 64, height: 64)
                } else {
                    Image(systemName: "doc.text.magnifyingglass")
                        .font(.system(size: 48))
                        .foregroundStyle(
                            LinearGradient(
                                colors: [.blue, .teal],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                }
            }

            // App Name and Version
            VStack(spacing: 6) {
                Text("MarcutApp")
                    .font(.system(size: 28, weight: .bold, design: .rounded))

                Text(versionLabel)
                    .font(.system(size: 14))
                    .foregroundColor(.secondary)
            }

            // Copyright
            Text("© 2025 Marc Mandel")
                .font(.system(size: 13))
                .foregroundColor(.secondary)

            Divider()
                .padding(.horizontal, 50)

            // Description
            VStack(spacing: 16) {
                Text("AI-Powered Document Redaction")
                    .font(.system(size: 15, weight: .medium))
                    .multilineTextAlignment(.center)

                VStack(spacing: 8) {
                    AboutFeatureRow(icon: "lock.shield.fill", text: "100% Local Processing", color: .green)
                    AboutFeatureRow(icon: "brain", text: "Powered by Llama AI", color: .orange)
                    AboutFeatureRow(icon: "doc.text", text: "Preserves Document Layout", color: .blue)
                }
            }

            Spacer()

            // Links
            HStack(spacing: 8) {
                AboutLinkButton(icon: "globe", title: "Website", url: URL(string: "https://github.com/legalmarc/marcut")!)
                AboutLinkButton(icon: "person.bubble.fill", title: "Support", url: URL(string: "https://www.linkedin.com/in/marcmandel/")!)
                AboutActionButton(icon: "book.fill", title: "Help") {
                    Task { @MainActor in
                        LifecycleUtils.openHelpWindow(anchor: "marcutapp-help")
                    }
                }
                AboutActionButton(icon: "doc.text.magnifyingglass", title: "OSS Licensing") {
                    Task { @MainActor in
                        LifecycleUtils.openHelpWindow(anchor: "open-source-licenses")
                    }
                }
            }

            // Close button
            Button("OK") {
                NSApp.keyWindow?.close()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.regular)
            .keyboardShortcut(.defaultAction)
            .accessibilityIdentifier("about.ok")
        }
        .padding(32)
        .frame(width: 420, height: 520)
        .background(Color(NSColor.windowBackgroundColor))
    }

    private var versionLabel: String {
        let cleanBuild = buildNumber.trimmingCharacters(in: .whitespacesAndNewlines)
        if cleanBuild.isEmpty || cleanBuild == appVersion {
            return "Version \(appVersion)"
        }
        return "Version \(appVersion) (Build \(cleanBuild))"
    }
}

struct AboutFeatureRow: View {
    let icon: String
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 14))
                .foregroundColor(color)
                .frame(width: 20)
            Text(text)
                .font(.system(size: 13))
            Spacer()
        }
        .frame(maxWidth: 250)
    }
}

struct AboutLinkButton: View {
    let icon: String
    let title: String
    let url: URL

    var body: some View {
        Link(destination: url) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                Text(title)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .font(.system(size: 11, weight: .medium))
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(Color.secondary.opacity(0.1))
            .cornerRadius(8)
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
    }
}

struct AboutActionButton: View {
    let icon: String
    let title: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                Text(title)
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
            }
            .font(.system(size: 11, weight: .medium))
            .padding(.horizontal, 8)
            .padding(.vertical, 6)
            .background(Color.secondary.opacity(0.1))
            .cornerRadius(8)
            .frame(maxWidth: .infinity)
        }
        .buttonStyle(.plain)
    }
}
