import SwiftUI

struct ModelSelectionRow: View {
    let modelId: String
    let displayName: String
    let description: String
    let size: String?
    let badge: String?
    let processingTime: String?
    let accentColor: Color?
    let isSelected: Bool
    let onSelect: () -> Void
    let isInstalled: Bool
    let accessibilityId: String?
    let onDownload: (() -> Void)?
    @Environment(\.colorScheme) private var colorScheme

    /// Convenience initializers for different use cases
    init(
        modelId: String,
        displayName: String,
        description: String,
        processingTime: String,
        accentColor: Color,
        isSelected: Bool,
        isInstalled: Bool,
        accessibilityId: String? = nil,
        onDownload: (() -> Void)? = nil,
        onSelect: @escaping () -> Void
    ) {
        self.modelId = modelId
        self.displayName = displayName
        self.description = description
        self.size = nil
        self.badge = nil
        self.processingTime = processingTime
        self.accentColor = accentColor
        self.isSelected = isSelected
        self.onSelect = onSelect
        self.isInstalled = isInstalled
        self.accessibilityId = accessibilityId
        self.onDownload = onDownload
    }

    init(
        modelId: String,
        displayName: String,
        description: String,
        size: String,
        badge: String,
        isSelected: Bool,
        isInstalled: Bool,
        accessibilityId: String? = nil,
        onDownload: (() -> Void)? = nil,
        onSelect: @escaping () -> Void
    ) {
        self.modelId = modelId
        self.displayName = displayName
        self.description = description
        self.size = size
        self.badge = badge
        self.processingTime = nil
        self.accentColor = nil
        self.isSelected = isSelected
        self.onSelect = onSelect
        self.isInstalled = isInstalled
        self.accessibilityId = accessibilityId
        self.onDownload = onDownload
    }

    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 16) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 20))
                    .foregroundColor(isSelected ? (accentColor ?? CustomColors.accentColor(for: colorScheme)) :
                        CustomColors.secondaryText(for: colorScheme))

                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text(displayName)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(CustomColors.primaryText(for: colorScheme))

                        if let badge {
                            Text(badge)
                                .font(.system(size: 11, weight: .medium))
                                .padding(.horizontal, 8)
                                .padding(.vertical, 2)
                                .background(
                                    RoundedRectangle(cornerRadius: 10)
                                        .fill((accentColor ?? CustomColors.accentColor(for: colorScheme)).opacity(0.2))
                                )
                                .foregroundColor(accentColor ?? CustomColors.accentColor(for: colorScheme))
                        }

                        Spacer()
                    }

                    Text(description)
                        .font(.system(size: 14))
                        .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        .multilineTextAlignment(.leading)

                    HStack {
                        if let size {
                            Text(size)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }

                        if let processingTime {
                            Text("• \(processingTime)")
                                .font(.system(size: 12))
                                .foregroundColor(CustomColors.secondaryText(for: colorScheme))
                        }

                        Spacer()

                        let statusColor = isInstalled ? Color.green : Color.orange
                        Text(isInstalled ? "Installed" : "Download required")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(statusColor)
                            .padding(.horizontal, 10)
                            .padding(.vertical, 4)
                            .background(
                                Capsule()
                                    .fill(statusColor.opacity(0.15))
                            )
                            .contentShape(Capsule())
                            .onTapGesture {
                                if !isInstalled {
                                    onDownload?()
                                }
                            }
                    }
                }
            }
            .padding(16)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(isSelected ? (accentColor ?? CustomColors.accentColor(for: colorScheme))
                        .opacity(0.12) : CustomColors.contentBackground(for: colorScheme))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(
                        isSelected ? (accentColor ?? CustomColors.accentColor(for: colorScheme)) : Color.clear,
                        lineWidth: 2
                    )
            )
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(accessibilityId ?? "model.\(modelId)")
    }
}
