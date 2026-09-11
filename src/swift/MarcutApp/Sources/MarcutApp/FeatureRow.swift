import SwiftUI

struct FeatureRow: View {
    let icon: String
    let title: String
    let description: String
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        HStack(spacing: 16) {
            Image(systemName: icon)
                .font(.system(size: 24))
                .foregroundColor(CustomColors.accentColor(for: colorScheme))
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(CustomColors.primaryText(for: colorScheme))

                Text(description)
                    .font(.system(size: 14))
                    .foregroundColor(CustomColors.secondaryText(for: colorScheme))
            }

            Spacer()
        }
    }
}
