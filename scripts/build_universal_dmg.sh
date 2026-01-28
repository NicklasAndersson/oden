#!/bin/bash
# =============================================================================
# Oden Universal macOS DMG Builder
# =============================================================================
# This script builds a universal macOS app bundle with:
# - Bundled JRE 25 for both arm64 and x64
# - Bundled signal-cli 0.13.23
# - Creates a DMG installer with Applications link
#
# Requirements:
# - macOS with Xcode command line tools
# - Python 3.10+ with pyinstaller
# - create-dmg (brew install create-dmg)
#
# Usage:
#   ./scripts/build_universal_dmg.sh [--skip-download] [--sign IDENTITY]
# =============================================================================

set -e

# Configuration
SIGNAL_CLI_VERSION="0.13.23"
JRE_VERSION="25"
JRE_VENDOR="eclipse"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Parse arguments
SKIP_DOWNLOAD=false
CODESIGN_IDENTITY=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-download)
            SKIP_DOWNLOAD=true
            shift
            ;;
        --sign)
            CODESIGN_IDENTITY="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}=== Oden Universal macOS DMG Builder ===${NC}"
echo ""

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# Get version from git tag or use dev
if git describe --tags --exact-match 2>/dev/null; then
    VERSION=$(git describe --tags --exact-match | sed 's/^v//')
else
    VERSION="0.0.0-dev"
fi
echo -e "Version: ${YELLOW}$VERSION${NC}"

# Create build directories
BUILD_DIR="$PROJECT_ROOT/build-dmg"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"

# =============================================================================
# Download JRE for both architectures
# =============================================================================
download_jre() {
    local arch=$1
    local jre_arch=$2
    local dest_dir="$BUILD_DIR/jre-$arch"

    if [ -d "$dest_dir" ]; then
        echo -e "${YELLOW}JRE $arch already exists, skipping download${NC}"
        return
    fi

    echo -e "${GREEN}Downloading Temurin JRE $JRE_VERSION for $arch...${NC}"

    # Use Adoptium API to get download URL
    local api_url="https://api.adoptium.net/v3/assets/latest/$JRE_VERSION/hotspot?architecture=$jre_arch&image_type=jre&os=mac&vendor=$JRE_VENDOR"
    local download_url=$(curl -s "$api_url" | python3 -c "import sys, json; print(json.load(sys.stdin)[0]['binary']['package']['link'])")

    if [ -z "$download_url" ]; then
        echo -e "${RED}Failed to get JRE download URL for $arch${NC}"
        exit 1
    fi

    echo "Downloading from: $download_url"
    curl -L -o "$BUILD_DIR/jre-$arch.tar.gz" "$download_url"

    mkdir -p "$dest_dir"
    tar -xzf "$BUILD_DIR/jre-$arch.tar.gz" -C "$dest_dir" --strip-components=1
    rm "$BUILD_DIR/jre-$arch.tar.gz"

    # Remove unnecessary files to reduce size
    rm -rf "$dest_dir/man" "$dest_dir/legal"

    echo -e "${GREEN}JRE $arch downloaded: $(du -sh "$dest_dir" | cut -f1)${NC}"
}

# =============================================================================
# Download signal-cli
# =============================================================================
download_signal_cli() {
    local dest_dir="$BUILD_DIR/signal-cli"

    if [ -d "$dest_dir" ]; then
        echo -e "${YELLOW}signal-cli already exists, skipping download${NC}"
        return
    fi

    echo -e "${GREEN}Downloading signal-cli $SIGNAL_CLI_VERSION...${NC}"

    local download_url="https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz"
    curl -L -o "$BUILD_DIR/signal-cli.tar.gz" "$download_url"

    mkdir -p "$dest_dir"
    tar -xzf "$BUILD_DIR/signal-cli.tar.gz" -C "$BUILD_DIR"
    mv "$BUILD_DIR/signal-cli-$SIGNAL_CLI_VERSION"/* "$dest_dir/"
    rmdir "$BUILD_DIR/signal-cli-$SIGNAL_CLI_VERSION"
    rm "$BUILD_DIR/signal-cli.tar.gz"

    # Make signal-cli executable
    chmod +x "$dest_dir/bin/signal-cli"

    echo -e "${GREEN}signal-cli downloaded: $(du -sh "$dest_dir" | cut -f1)${NC}"
}

# =============================================================================
# Download dependencies
# =============================================================================
if [ "$SKIP_DOWNLOAD" = false ]; then
    echo ""
    echo -e "${GREEN}=== Downloading dependencies ===${NC}"

    download_jre "arm64" "aarch64"
    download_jre "x64" "x64"
    download_signal_cli
else
    echo -e "${YELLOW}Skipping downloads (--skip-download)${NC}"
fi

# =============================================================================
# Copy dependencies to project root for PyInstaller
# =============================================================================
echo ""
echo -e "${GREEN}=== Preparing build files ===${NC}"

# Copy JRE directories
cp -r "$BUILD_DIR/jre-arm64" "$PROJECT_ROOT/jre-arm64"
cp -r "$BUILD_DIR/jre-x64" "$PROJECT_ROOT/jre-x64"
cp -r "$BUILD_DIR/signal-cli" "$PROJECT_ROOT/signal-cli"

# Create static directory for setup wizard
mkdir -p "$PROJECT_ROOT/oden/static"

# =============================================================================
# Build with PyInstaller
# =============================================================================
echo ""
echo -e "${GREEN}=== Building app with PyInstaller ===${NC}"

# Install/update pyinstaller
pip install --quiet pyinstaller

# Set version environment variable
export ODEN_VERSION="$VERSION"

# Set code signing if provided
if [ -n "$CODESIGN_IDENTITY" ]; then
    export CODESIGN_IDENTITY="$CODESIGN_IDENTITY"
    echo -e "Code signing with: ${YELLOW}$CODESIGN_IDENTITY${NC}"
fi

# Run PyInstaller
pyinstaller --clean --noconfirm s7_watcher.spec

# Clean up copied dependencies
rm -rf "$PROJECT_ROOT/jre-arm64" "$PROJECT_ROOT/jre-x64" "$PROJECT_ROOT/signal-cli"

# =============================================================================
# Create DMG
# =============================================================================
echo ""
echo -e "${GREEN}=== Creating DMG ===${NC}"

# Check if create-dmg is installed
if ! command -v create-dmg &> /dev/null; then
    echo -e "${YELLOW}Installing create-dmg...${NC}"
    brew install create-dmg
fi

DMG_NAME="Oden-$VERSION-macOS-universal.dmg"
DMG_PATH="$PROJECT_ROOT/dist/$DMG_NAME"

# Remove old DMG if exists
rm -f "$DMG_PATH"

# Create DMG with nice layout
create-dmg \
    --volname "Oden $VERSION" \
    --volicon "$PROJECT_ROOT/images/oden.icns" \
    --background "$PROJECT_ROOT/images/dmg_background.png" \
    --window-pos 200 120 \
    --window-size 600 400 \
    --icon-size 100 \
    --icon "Oden.app" 150 190 \
    --hide-extension "Oden.app" \
    --app-drop-link 450 190 \
    "$DMG_PATH" \
    "$PROJECT_ROOT/dist/Oden.app" \
    2>/dev/null || true  # create-dmg returns non-zero even on success sometimes

# Fallback if create-dmg fails or background is missing
if [ ! -f "$DMG_PATH" ]; then
    echo -e "${YELLOW}Falling back to simple DMG creation...${NC}"
    hdiutil create -volname "Oden $VERSION" \
        -srcfolder "$PROJECT_ROOT/dist/Oden.app" \
        -ov -format UDZO \
        "$DMG_PATH"
fi

if [ -f "$DMG_PATH" ]; then
    echo ""
    echo -e "${GREEN}=== Build complete! ===${NC}"
    echo ""
    echo "DMG created: $DMG_PATH"
    echo "Size: $(du -h "$DMG_PATH" | cut -f1)"
    echo ""

    # List contents
    echo "Contents:"
    ls -la "$PROJECT_ROOT/dist/"
else
    echo -e "${RED}Failed to create DMG${NC}"
    exit 1
fi
