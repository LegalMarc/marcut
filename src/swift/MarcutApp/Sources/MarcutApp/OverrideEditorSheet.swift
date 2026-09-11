import SwiftUI

struct OverrideEditorSheet: View {
    let title: String
    let description: String
    @Binding var text: String
    let onCancel: () -> Void
    let onSave: () -> Void
    let onRestoreDefaults: () -> Void
    var showsMatchPreview: Bool = false
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title)
                .font(.title2)
                .fontWeight(.semibold)
                .foregroundColor(CustomColors.primaryText(for: colorScheme))

            Text(description)
                .font(.body)
                .foregroundColor(CustomColors.secondaryText(for: colorScheme))

            ScrollableTextEditor(text: $text)
                .frame(minHeight: 300)
                .accessibilityIdentifier("settings.override.text")

            if showsMatchPreview {
                ExcludedWordMatchPreview(excludedWordsText: text)
            }

            HStack(spacing: 12) {
                Button("Cancel") {
                    onCancel()
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("settings.override.cancel")

                Button("Restore Defaults") {
                    onRestoreDefaults()
                }
                .buttonStyle(.bordered)
                .accessibilityIdentifier("settings.override.restoreDefaults")

                Spacer()

                Button("Save Changes") {
                    onSave()
                }
                .buttonStyle(.borderedProminent)
                .accessibilityIdentifier("settings.override.save")
            }

            Spacer()
        }
        .padding(24)
        .frame(minWidth: 500, minHeight: 625)
    }
}
