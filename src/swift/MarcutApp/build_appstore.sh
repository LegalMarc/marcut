#!/bin/bash

# MarcutApp App Store Distribution Build Script
# Uses CLI-based signing and archiving for App Store submission

set -euo pipefail

# Configuration
APP_NAME="MarcutApp"
BUNDLE_ID="com.marclaw.marcutapp"
DEVELOPMENT_TEAM=""  # SET YOUR TEAM ID
CODE_SIGN_IDENTITY="Apple Distribution"
PROVISIONING_PROFILE_SPECIFIER=""  # SET YOUR PROFILE NAME

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================"
echo -e " MarcutApp App Store Distribution Build"
echo -e "======================================${NC}"

# Check required parameters
if [[ -z "$DEVELOPMENT_TEAM" ]]; then
    echo -e "${YELLOW}WARNING: DEVELOPMENT_TEAM not set${NC}"
    echo -e "Please set your Apple Developer Team ID:"
    echo -e "export DEVELOPMENT_TEAM=\"YOUR_TEAM_ID\""
    echo ""
fi

if [[ -z "$PROVISIONING_PROFILE_SPECIFIER" ]]; then
    echo -e "${YELLOW}WARNING: PROVISIONING_PROFILE_SPECIFIER not set${NC}"
    echo -e "Please set your provisioning profile name:"
    echo -e "export PROVISIONING_PROFILE_SPECIFIER=\"YOUR_PROFILE_NAME\""
    echo ""
fi

echo -e "${BLUE}Configuration:${NC}"
echo -e "  App Name: ${APP_NAME}"
echo -e "  Bundle ID: ${BUNDLE_ID}"
echo -e "  Team ID: ${DEVELOPMENT_TEAM:-"NOT SET"}"
echo -e "  Code Sign: ${CODE_SIGN_IDENTITY}"
echo -e "  Profile: ${PROVISIONING_PROFILE_SPECIFIER:-"NOT SET"}"
echo ""

# Check for required tools
echo -e "${BLUE}Checking prerequisites...${NC}"
if ! command -v xcodebuild &> /dev/null; then
    echo -e "${RED}ERROR: xcodebuild not found. Install Xcode Command Line Tools.${NC}"
    exit 1
fi

if ! command -v xcrun &> /dev/null; then
    echo -e "${RED}ERROR: xcrun not found. Install Xcode Command Line Tools.${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Xcode tools found${NC}"

# Clean previous builds
echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf ./.build
rm -rf ./*.xcodeproj
rm -rf ./DerivedData
rm -rf ./*.xcarchive

# Build the app
echo -e "${BLUE}Building Swift Package...${NC}"
swift build -c release --arch arm64

if [[ $? -ne 0 ]]; then
    echo -e "${RED}ERROR: Swift build failed${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Swift build completed${NC}"

# Create Xcode project structure
echo -e "${BLUE}Creating Xcode project for signing...${NC}"

# Create a temporary Xcode project wrapper
PROJECT_NAME="${APP_NAME}Wrapper"
PROJECT_DIR="./${PROJECT_NAME}"

rm -rf "${PROJECT_DIR}"
mkdir -p "${PROJECT_DIR}"

# Generate basic project.pbxproj
cat > "${PROJECT_DIR}/project.pbxproj" << 'EOF'
// !$*UTF8*$!
{
	archiveVersion = 1;
	classes = {
	};
	objectVersion = 56;
	objects = {

/* Begin PBXBuildFile section */
		A1234567890ABCDEF001 /* MarcutAppApp.app */ = {isa = PBXBuildFile; fileRef = A1234567890ABCDEF000 /* MarcutAppApp.app */; };
/* End PBXBuildFile section */

/* Begin PBXFileReference section */
		A1234567890ABCDEF000 /* MarcutAppApp.app */ = {isa = PBXFileReference; explicitFileType = wrapper.application; includeInIndex = 0; path = MarcutAppApp.app; sourceTree = BUILT_PRODUCTS_DIR; };
/* End PBXFileReference section */

/* Begin PBXNativeTarget section */
		A1234567890ABCDEF002 /* MarcutAppApp */ = {
			isa = PBXNativeTarget;
			buildConfigurationList = A1234567890ABCDEF003 /* Build configuration list for PBXNativeTarget "MarcutAppApp" */;
			buildPhases = (
			);
			buildRules = (
			);
			dependencies = (
			);
			name = MarcutAppApp;
			productName = MarcutAppApp;
			productReference = A1234567890ABCDEF000 /* MarcutAppApp.app */;
			productType = "com.apple.product-type.application";
		};
/* End PBXNativeTarget section */

/* Begin PBXProject section */
		A1234567890ABCDEF001 /* Project object */ = {
			isa = PBXProject;
			attributes = {
				BuildIndependentTargetsInParallel = 1;
				LastSwiftUpdateCheck = 1500;
				LastUpgradeCheck = 1500;
				TargetAttributes = {
					A1234567890ABCDEF002 = {
						CreatedOnToolsVersion = 15.0;
					};
				};
			};
			buildConfigurationList = A1234567890ABCDEF004 /* Build configuration list for PBXProject "MarcutAppWrapper" */;
			compatibilityVersion = "Xcode 14.0";
			developmentRegion = en;
			hasScannedForEncodings = 0;
			knownRegions = (
				en,
				Base,
			);
			mainGroup = A1234567890ABCDEF005;
			productRefGroup = A1234567890ABCDEF006 /* Products */;
			projectDirPath = "";
			projectRoot = "";
			targets = (
				A1234567890ABCDEF002 /* MarcutAppApp */,
			);
		};
/* End PBXProject section */

/* Begin XCBuildConfiguration section */
		A1234567890ABCDEF007 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				CODE_SIGN_ENTITLEMENTS = MarcutApp.entitlements;
				CODE_SIGN_IDENTITY = "";
				CURRENT_PROJECT_VERSION = 1;
				DEVELOPMENT_TEAM = "";
				ENABLE_USER_SCRIPT_SANDBOXING = 0;
				GENERATE_INFOPLIST_FILE = YES;
				INFOPLIST_FILE = MarcutAppApp/Info.plist;
				INFOPLIST_KEY_CFBundleDisplayName = MarcutApp;
				INFOPLIST_KEY_LSApplicationCategoryType = "public.app-category.productivity";
				INFOPLIST_KEY_NSHumanReadableCopyright = "Copyright © 2025 Marc Law Software. All rights reserved.";
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/../Frameworks",
				);
				MARKETING_VERSION = 1.0;
				PRODUCT_BUNDLE_IDENTIFIER = com.marclaw.marcutapp;
				PRODUCT_NAME = "$(TARGET_NAME)";
				SWIFT_EMIT_LOC_STRINGS = YES;
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = "1,2";
			};
			name = Debug;
		};
		A1234567890ABCDEF008 /* Release */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				CODE_SIGN_ENTITLEMENTS = MarcutApp.entitlements;
				CODE_SIGN_IDENTITY = "Apple Distribution";
				CURRENT_PROJECT_VERSION = 1;
				DEVELOPMENT_TEAM = "$(DEVELOPMENT_TEAM)";
				ENABLE_USER_SCRIPT_SANDBOXING = 0;
				GENERATE_INFOPLIST_FILE = YES;
				INFOPLIST_FILE = MarcutAppApp/Info.plist;
				INFOPLIST_KEY_CFBundleDisplayName = MarcutApp;
				INFOPLIST_KEY_LSApplicationCategoryType = "public.app-category.productivity";
				INFOPLIST_KEY_NSHumanReadableCopyright = "Copyright © 2025 Marc Law Software. All rights reserved.";
				LD_RUNPATH_SEARCH_PATHS = (
					"$(inherited)",
					"@executable_path/../Frameworks",
				);
				MARKETING_VERSION = 1.0;
				PRODUCT_BUNDLE_IDENTIFIER = com.marclaw.marcutapp;
				PRODUCT_NAME = "$(TARGET_NAME)";
				PROVISIONING_PROFILE_SPECIFIER = "$(PROVISIONING_PROFILE_SPECIFIER)";
				SWIFT_EMIT_LOC_STRINGS = YES;
				SWIFT_VERSION = 5.0;
				TARGETED_DEVICE_FAMILY = "1,2";
			};
			name = Release;
		};
		A1234567890ABCDEF009 /* Debug */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ALWAYS_SEARCH_USER_PATHS = NO;
				CLANG_ANALYZER_NONNULL = YES;
				CLANG_ANALYZER_NUMBER_OBJECT_CONVERSION = YES_AGGRESSIVE;
				CLANG_CXX_LANGUAGE_STANDARD = "gnu++20";
				CLANG_ENABLE_MODULES = YES;
				CLANG_ENABLE_OBJC_ARC = YES;
				CLANG_ENABLE_OBJC_WEAK = YES;
				CLANG_WARN_BLOCK_CAPTURE_AUTORELEASING = YES;
				CLANG_WARN_BOOL_CONVERSION = YES;
				CLANG_WARN_COMMA = YES;
				CLANG_WARN_CONSTANT_CONVERSION = YES;
				CLANG_WARN_DEPRECATED_OBJC_IMPLEMENTATIONS = YES;
				CLANG_WARN_DIRECT_OBJC_ISA_USAGE = YES_ERROR;
				CLANG_WARN_DOCUMENTATION_COMMENTS = YES;
				CLANG_WARN_EMPTY_BODY = YES;
				CLANG_WARN_ENUM_CONVERSION = YES;
				CLANG_WARN_INFINITE_RECURSION = YES;
				CLANG_WARN_INT_CONVERSION = YES;
				CLANG_WARN_NON_LITERAL_NULL_CONVERSION = YES;
				CLANG_WARN_OBJC_IMPLICIT_RETAIN_SELF = YES;
				CLANG_WARN_OBJC_LITERAL_CONVERSION = YES;
				CLANG_WARN_OBJC_ROOT_CLASS = YES_ERROR;
				CLANG_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER = YES;
				CLANG_WARN_RANGE_LOOP_ANALYSIS = YES;
				CLANG_WARN_STRICT_PROTOTYPES = YES;
				CLANG_WARN_SUSPICIOUS_MOVE = YES;
				CLANG_WARN_UNGUARDED_AVAILABILITY = YES_AGGRESSIVE;
				CLANG_WARN_UNREACHABLE_CODE = YES;
				CLANG_WARN__DUPLICATE_METHOD_MATCH = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = dwarf;
				ENABLE_STRICT_OBJC_MSGSEND = YES;
				ENABLE_TESTABILITY = YES;
				ENABLE_USER_SCRIPT_SANDBOXING = YES;
				GCC_C_LANGUAGE_STANDARD = gnu17;
				GCC_DYNAMIC_NO_PIC = NO;
				GCC_NO_COMMON_BLOCKS = YES;
				GCC_OPTIMIZATION_LEVEL = 0;
				GCC_PREPROCESSOR_DEFINITIONS = (
					"DEBUG=1",
					"$(inherited)",
				);
				GCC_WARN_64_TO_32_BIT_CONVERSION = YES;
				GCC_WARN_ABOUT_RETURN_TYPE = YES_ERROR;
				GCC_WARN_UNDECLARED_SELECTOR = YES;
				GCC_WARN_UNINITIALIZED_AUTOS = YES_AGGRESSIVE;
				GCC_WARN_UNUSED_FUNCTION = YES;
				GCC_WARN_UNUSED_VARIABLE = YES;
				LOCALIZATION_PREFERS_STRING_CATALOGS = YES;
				MTL_ENABLE_DEBUG_INFO = INCLUDE_SOURCE;
				MTL_FAST_MATH = YES;
				ONLY_ACTIVE_ARCH = YES;
				SDKROOT = auto;
			};
			name = Debug;
		};
		A1234567890ABCDEF010 /* Release */ = {
			isa = XCBuildConfiguration;
			buildSettings = {
				ALWAYS_SEARCH_USER_PATHS = NO;
				ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS = YES;
				CLANG_ANALYZER_NONNULL = YES;
				CLANG_ANALYZER_NUMBER_OBJECT_CONVERSION = YES_AGGRESSIVE;
				CLANG_CXX_LANGUAGE_STANDARD = "gnu++20";
				CLANG_ENABLE_MODULES = YES;
				CLANG_ENABLE_OBJC_ARC = YES;
				CLANG_ENABLE_OBJC_WEAK = YES;
				CLANG_WARN_BLOCK_CAPTURE_AUTORELEASING = YES;
				CLANG_WARN_BOOL_CONVERSION = YES;
				CLANG_WARN_COMMA = YES;
				CLANG_WARN_CONSTANT_CONVERSION = YES;
				CLANG_WARN_DEPRECATED_OBJC_IMPLEMENTATIONS = YES;
				CLANG_WARN_DIRECT_OBJC_ISA_USAGE = YES_ERROR;
				CLANG_WARN_DOCUMENTATION_COMMENTS = YES;
				CLANG_WARN_EMPTY_BODY = YES;
				CLANG_WARN_ENUM_CONVERSION = YES;
				CLANG_WARN_INFINITE_RECURSION = YES;
				CLANG_WARN_INT_CONVERSION = YES;
				CLANG_WARN_NON_LITERAL_NULL_CONVERSION = YES;
				CLANG_WARN_OBJC_IMPLICIT_RETAIN_SELF = YES;
				CLANG_WARN_OBJC_LITERAL_CONVERSION = YES;
				CLANG_WARN_OBJC_ROOT_CLASS = YES_ERROR;
				CLANG_WARN_QUOTED_INCLUDE_IN_FRAMEWORK_HEADER = YES;
				CLANG_WARN_RANGE_LOOP_ANALYSIS = YES;
				CLANG_WARN_STRICT_PROTOTYPES = YES;
				CLANG_WARN_SUSPICIOUS_MOVE = YES;
				CLANG_WARN_UNGUARDED_AVAILABILITY = YES_AGGRESSIVE;
				CLANG_WARN_UNREACHABLE_CODE = YES;
				CLANG_WARN__DUPLICATE_METHOD_MATCH = YES;
				COPY_PHASE_STRIP = NO;
				DEBUG_INFORMATION_FORMAT = "dwarf-with-dsym";
				ENABLE_NS_ASSERTIONS = NO;
				ENABLE_STRICT_OBJC_MSGSEND = YES;
				ENABLE_USER_SCRIPT_SANDBOXING = YES;
				GCC_C_LANGUAGE_STANDARD = gnu17;
				GCC_NO_COMMON_BLOCKS = YES;
				GCC_WARN_64_TO_32_BIT_CONVERSION = YES;
				GCC_WARN_ABOUT_RETURN_TYPE = YES_ERROR;
				GCC_WARN_UNDECLARED_SELECTOR = YES;
				GCC_WARN_UNINITIALIZED_AUTOS = YES_AGGRESSIVE;
				GCC_WARN_UNUSED_FUNCTION = YES;
				GCC_WARN_UNUSED_VARIABLE = YES;
				LOCALIZATION_PREFERS_STRING_CATALOGS = YES;
				MTL_ENABLE_DEBUG_INFO = NO;
				MTL_FAST_MATH = YES;
				SDKROOT = auto;
			};
			name = Release;
		};
/* End XCBuildConfiguration section */

/* Begin XCConfigurationList section */
		A1234567890ABCDEF003 /* Build configuration list for PBXNativeTarget "MarcutAppApp" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				A1234567890ABCDEF007 /* Debug */,
				A1234567890ABCDEF008 /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		};
		A1234567890ABCDEF004 /* Build configuration list for PBXProject "MarcutAppWrapper" */ = {
			isa = XCConfigurationList;
			buildConfigurations = (
				A1234567890ABCDEF009 /* Debug */,
				A1234567890ABCDEF010 /* Release */,
			);
			defaultConfigurationIsVisible = 0;
			defaultConfigurationName = Release;
		};
/* End XCConfigurationList section */
	};
	rootObject = A1234567890ABCDEF001 /* Project object */;
}
EOF

# Create Info.plist
mkdir -p "${PROJECT_DIR}/MarcutAppApp"
cat > "${PROJECT_DIR}/MarcutAppApp/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleExecutable</key>
	<string>MarcutApp</string>
	<key>CFBundleIdentifier</key>
	<string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
	<key>CFBundleInfoDictionaryVersion</key>
	<string>6.0</string>
	<key>CFBundleName</key>
	<string>$(PRODUCT_NAME)</string>
	<key>CFBundlePackageType</key>
	<string>APPL</string>
	<key>CFBundleShortVersionString</key>
	<string>$(MARKETING_VERSION)</string>
	<key>CFBundleVersion</key>
	<string>$(CURRENT_PROJECT_VERSION)</string>
	<key>LSMinimumSystemVersion</key>
	<string>14.0</string>
	<key>NSPrincipalClass</key>
	<string>NSApplication</string>
</dict>
</plist>
EOF

# Copy entitlements
cp MarcutApp.entitlements "${PROJECT_DIR}/"

echo -e "${GREEN}✅ Xcode project wrapper created${NC}"

# Copy built binary to app bundle
echo -e "${BLUE}Creating app bundle...${NC}"

# Get the built binary path
BUILT_BINARY=$(find ./.build -name "MarcutApp" -type f | grep release | head -1)
if [[ -z "$BUILT_BINARY" ]]; then
    echo -e "${RED}ERROR: Could not find built MarcutApp binary${NC}"
    exit 1
fi

echo -e "Found binary: $BUILT_BINARY"

# Create app bundle structure
APP_BUNDLE="${PROJECT_DIR}/MarcutAppApp.app"
mkdir -p "${APP_BUNDLE}/Contents/MacOS"
mkdir -p "${APP_BUNDLE}/Contents/Frameworks"
mkdir -p "${APP_BUNDLE}/Contents/Resources"

# Copy binary
cp "$BUILT_BINARY" "${APP_BUNDLE}/Contents/MacOS/MarcutApp"

# Copy frameworks and resources from your existing build
if [[ -d "./build_swift/MarcutApp.app/Contents/Frameworks" ]]; then
    cp -r "./build_swift/MarcutApp.app/Contents/Frameworks"/* "${APP_BUNDLE}/Contents/Frameworks/"
    echo -e "${GREEN}✅ Frameworks copied${NC}"
fi

if [[ -d "./build_swift/MarcutApp.app/Contents/Resources" ]]; then
    cp -r "./build_swift/MarcutApp.app/Contents/Resources"/* "${APP_BUNDLE}/Contents/Resources/"
    echo -e "${GREEN}✅ Resources copied${NC}"
fi

# Copy Python site from existing build
if [[ -d "./build_swift/MarcutApp.app/Contents/Resources/python_site" ]]; then
    cp -r "./build_swift/MarcutApp.app/Contents/Resources/python_site" "${APP_BUNDLE}/Contents/Resources/"
    echo -e "${GREEN}✅ Python site copied${NC}"
fi

# Copy Ollama if available
if [[ -d "./build_swift/MarcutApp.app/Contents/Resources/Ollama.app" ]]; then
    cp -R "./build_swift/MarcutApp.app/Contents/Resources/Ollama.app" "${APP_BUNDLE}/Contents/Resources/"
    echo -e "${GREEN}✅ Ollama copied to main app Resources${NC}"
fi

# Embed XPC service if built
if [[ -d "./build_swift/OllamaHelperService.xpc" ]]; then
    mkdir -p "${APP_BUNDLE}/Contents/XPCServices"
    cp -R "./build_swift/OllamaHelperService.xpc" "${APP_BUNDLE}/Contents/XPCServices/"
    echo -e "${GREEN}✅ XPC service embedded${NC}"

    # Ensure helper has Ollama.app in its Resources if available
    if [[ -d "./build_swift/MarcutApp.app/Contents/Resources/Ollama.app" ]]; then
        mkdir -p "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/Resources"
        cp -R "./build_swift/MarcutApp.app/Contents/Resources/Ollama.app" "${APP_BUNDLE}/Contents/XPCServices/OllamaHelperService.xpc/Contents/Resources/"
        echo -e "${GREEN}✅ Ollama copied into helper Resources${NC}"
    fi
fi

echo -e "${GREEN}✅ App bundle created${NC}"

# Archive the app
echo -e "${BLUE}Creating App Store archive...${NC}"

ARCHIVE_PATH="./${APP_NAME}.xcarchive"

xcodebuild archive \
    -project "${PROJECT_NAME}.xcodeproj" \
    -scheme MarcutAppApp \
    -configuration Release \
    -archivePath "${ARCHIVE_PATH}" \
    -destination "generic/platform=macOS" \
    -archiveBasePath "$(pwd)" \
    ONLY_ACTIVE_ARCH=NO \
    DEVELOPMENT_TEAM="${DEVELOPMENT_TEAM}" \
    CODE_SIGN_IDENTITY="${CODE_SIGN_IDENTITY}" \
    PROVISIONING_PROFILE_SPECIFIER="${PROVISIONING_PROFILE_SPECIFIER}" \
    CODE_SIGN_ENTITLEMENTS="${PROJECT_DIR}/MarcutApp.entitlements"

if [[ $? -eq 0 ]]; then
    echo -e "${GREEN}✅ Archive created successfully!${NC}"
    echo -e "Archive location: $(pwd)/${APP_NAME}.xcarchive"
    echo ""
    echo -e "${BLUE}Next steps:${NC}"
    echo -e "1. Open Xcode: ${YELLOW}open $(pwd)/${APP_NAME}.xcarchive${NC}"
    echo -e "2. Go to Window ▸ Organizer ▸ Archives"
    echo -e "3. Select your archive and click 'Distribute App'"
    echo -e "4. Choose 'App Store Connect' and follow the prompts"
    echo ""
    echo -e "${BLUE}Alternative - Upload from command line:${NC}"
    echo -e "xcrun altool --upload-app --type ios --file $(pwd)/${APP_NAME}.xcarchive --username \"YOUR_APPLE_ID\" --password \"@keychain:AC_PASSWORD\""
else
    echo -e "${RED}ERROR: Archive creation failed${NC}"
    exit 1
fi

echo -e "${GREEN}=== Build completed successfully! ===${NC}"
