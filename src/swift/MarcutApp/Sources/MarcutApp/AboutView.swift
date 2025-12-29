import SwiftUI

struct AboutView: View {
    private var appVersion: String {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "Unknown"
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

                Text("Version \(appVersion)")
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
            HStack(spacing: 16) {
                Link(destination: URL(string: "https://github.com/marclaw/marcut")!) {
                    HStack(spacing: 6) {
                        Image(systemName: "globe")
                        Text("Website")
                    }
                    .font(.system(size: 13, weight: .medium))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.secondary.opacity(0.1))
                    .cornerRadius(8)
                }
                .buttonStyle(.plain)

                Link(destination: URL(string: "https://www.linkedin.com/in/marcmandel/")!) {
                    HStack(spacing: 6) {
                        Image(systemName: "person.bubble.fill")
                        Text("Support")
                    }
                    .font(.system(size: 13, weight: .medium))
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.secondary.opacity(0.1))
                    .cornerRadius(8)
                }
                .buttonStyle(.plain)
            }

            // Close button
            Button("OK") {
                NSApp.keyWindow?.close()
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.regular)
            .keyboardShortcut(.defaultAction)
        }
        .padding(32)
        .frame(width: 420, height: 520)
        .background(Color(NSColor.windowBackgroundColor))
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
