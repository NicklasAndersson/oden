#!/bin/bash

# ==============================================================================
# Oden - Installationsskript för SNAPSHOT (macOS)
# ==============================================================================
# Laddar ner senaste snapshot-DMG (pre-release) från GitHub, installerar
# Oden.app i Applications och tar bort karantänattributet.
#
# Snapshots byggs automatiskt vid varje push till main och är avsedda
# för testning — inte för produktion.
#
# Användning:
#   curl -fsSL https://raw.githubusercontent.com/NicklasAndersson/oden/main/scripts/install_snapshot_mac.sh | bash
#
# Eller:
#   ./install_snapshot_mac.sh

set -euo pipefail

# --- Colors for output ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_BOLD='\033[1m'
C_YELLOW='\033[0;33m'

# --- Configuration ---
REPO="NicklasAndersson/oden"
API_URL="https://api.github.com/repos/${REPO}/releases"
APP_NAME="Oden.app"
INSTALL_DIR="/Applications"

# --- Helper Functions ---
print_header() {
    echo -e "\n${C_BLUE}${C_BOLD}--- $1 ---${C_RESET}"
}

print_success() {
    echo -e "${C_GREEN}✓ $1${C_RESET}"
}

print_error() {
    echo -e "${C_RED}✗ $1${C_RESET}"
}

print_warning() {
    echo -e "${C_YELLOW}⚠ $1${C_RESET}"
}

print_info() {
    echo -e "${C_BLUE}ℹ $1${C_RESET}"
}

# --- Banner ---
echo -e "${C_YELLOW}${C_BOLD}"
echo "==========================================="
echo "     Oden – Snapshot-installation           "
echo "          (macOS, testversion)               "
echo "==========================================="
echo -e "${C_RESET}"
print_warning "Snapshots är testversioner och kan vara instabila."
echo ""

# --- OS Check ---
if [[ "$(uname)" != "Darwin" ]]; then
    print_error "Detta skript är avsett för macOS. Du kör $(uname)."
    exit 1
fi

# =============================================================================
# STEP 1: Find latest snapshot release
# =============================================================================
print_header "Steg 1: Hämtar information om senaste snapshot"

if ! command -v curl &>/dev/null; then
    print_error "curl hittades inte. Installera curl och försök igen."
    exit 1
fi

# Fetch recent releases (first page is enough — old snapshots are deleted)
RELEASES_JSON=$(curl -fsSL "${API_URL}?per_page=20") || {
    print_error "Kunde inte hämta release-information från GitHub."
    print_info "Kontrollera din internetanslutning och försök igen."
    exit 1
}

# Find the first pre-release with a snapshot tag
# Snapshot tags look like: snapshot-abc1234
SNAPSHOT_JSON=$(echo "$RELEASES_JSON" \
    | grep -o '{[^{}]*"tag_name" *: *"snapshot-[^"]*"[^{}]*"prerelease" *: *true[^{}]*}' \
    | head -1 || true)

# Also try the reverse field order (prerelease before tag_name)
if [[ -z "$SNAPSHOT_JSON" ]]; then
    SNAPSHOT_JSON=$(echo "$RELEASES_JSON" \
        | grep -o '{[^{}]*"prerelease" *: *true[^{}]*"tag_name" *: *"snapshot-[^"]*"[^{}]*}' \
        | head -1 || true)
fi

if [[ -z "$SNAPSHOT_JSON" ]]; then
    print_error "Kunde inte hitta någon snapshot-release."
    print_info "Besök https://github.com/${REPO}/releases för att kontrollera."
    exit 1
fi

# Extract tag name
SNAPSHOT_TAG=$(echo "$SNAPSHOT_JSON" | grep -o '"tag_name" *: *"snapshot-[^"]*"' | sed 's/.*"tag_name" *: *"//;s/"$//')

if [[ -z "$SNAPSHOT_TAG" ]]; then
    print_error "Kunde inte tolka snapshot-taggen."
    exit 1
fi

print_success "Hittade snapshot: ${SNAPSHOT_TAG}"

# Now fetch the full release details for this specific tag to get assets
RELEASE_JSON=$(curl -fsSL "${API_URL}/tags/${SNAPSHOT_TAG}") || {
    print_error "Kunde inte hämta detaljer för ${SNAPSHOT_TAG}."
    exit 1
}

# Extract DMG download URL (pattern: Oden-*-macOS.dmg)
DMG_URL=$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*macOS\.dmg"' | head -1 | sed 's/.*"browser_download_url": *"//;s/"$//')

if [[ -z "$DMG_URL" ]]; then
    print_error "Kunde inte hitta en DMG i snapshot-releasen."
    print_info "Besök https://github.com/${REPO}/releases/tag/${SNAPSHOT_TAG}"
    exit 1
fi

DMG_FILENAME=$(basename "$DMG_URL")
print_info "Fil: ${DMG_FILENAME}"

# =============================================================================
# STEP 2: Download DMG
# =============================================================================
print_header "Steg 2: Laddar ner ${DMG_FILENAME}"

TMPDIR_DL=$(mktemp -d)
DMG_PATH="${TMPDIR_DL}/${DMG_FILENAME}"

cleanup() {
    if [[ -d "$TMPDIR_DL" ]]; then
        if [[ -n "${MOUNT_POINT:-}" ]] && [[ -d "$MOUNT_POINT" ]]; then
            hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
        fi
        rm -rf "$TMPDIR_DL"
    fi
}
trap cleanup EXIT

curl -fSL --progress-bar -o "$DMG_PATH" "$DMG_URL" || {
    print_error "Kunde inte ladda ner ${DMG_FILENAME}."
    exit 1
}

print_success "Nedladdning klar"

# =============================================================================
# STEP 3: Mount and install
# =============================================================================
print_header "Steg 3: Installerar ${APP_NAME}"

# Check if Oden is already running
if pgrep -f "/Applications/Oden.app/Contents/MacOS/" &>/dev/null; then
    print_warning "Oden verkar köra. Stäng appen innan du fortsätter."
    if [[ -t 0 ]]; then
        read -rp "Vill du fortsätta ändå? (j/N): " CONTINUE
        if [[ ! "$CONTINUE" =~ ^[JjYy]$ ]]; then
            echo "Avbryter."
            exit 0
        fi
    else
        print_info "Kör via pipe — hoppar över frågan och fortsätter."
    fi
fi

# Mount DMG
MOUNT_OUTPUT=$(hdiutil attach "$DMG_PATH" -nobrowse 2>&1) || {
    print_error "Kunde inte montera DMG-filen."
    echo "$MOUNT_OUTPUT"
    exit 1
}

MOUNT_POINT=$(echo "$MOUNT_OUTPUT" | grep -o '/Volumes/.*' | head -1 || true)

if [[ -z "$MOUNT_POINT" ]] || [[ ! -d "$MOUNT_POINT" ]]; then
    print_error "Kunde inte hitta monteringspunkten."
    echo "$MOUNT_OUTPUT"
    exit 1
fi

print_success "DMG monterad: ${MOUNT_POINT}"

# Check that app exists in DMG
if [[ ! -d "${MOUNT_POINT}/${APP_NAME}" ]]; then
    print_error "${APP_NAME} hittades inte i DMG-filen."
    hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
    exit 1
fi

# Remove old installation if present
if [[ -d "${INSTALL_DIR}/${APP_NAME}" ]]; then
    print_warning "En befintlig installation hittades. Den kommer att ersättas."
    if [[ "$INSTALL_DIR" != "/Applications" ]] || [[ "$APP_NAME" != "Oden.app" ]]; then
        print_error "Oväntade värden för INSTALL_DIR/APP_NAME. Avbryter."
        exit 1
    fi
    rm -rf "${INSTALL_DIR:?}/${APP_NAME:?}" || {
        print_error "Kunde inte ta bort befintlig installation."
        print_info "Prova: sudo rm -rf '${INSTALL_DIR}/${APP_NAME}'"
        hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
        exit 1
    }
fi

# Copy app to Applications
cp -R "${MOUNT_POINT}/${APP_NAME}" "${INSTALL_DIR}/" || {
    print_error "Kunde inte kopiera ${APP_NAME} till ${INSTALL_DIR}."
    print_info "Du kan behöva köra skriptet med sudo."
    hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
    exit 1
}

print_success "${APP_NAME} installerad i ${INSTALL_DIR}"

# Unmount DMG
hdiutil detach "$MOUNT_POINT" -quiet 2>/dev/null || true
MOUNT_POINT=""

# =============================================================================
# STEP 4: Remove quarantine (bypass Gatekeeper)
# =============================================================================
print_header "Steg 4: Tar bort karantänattribut (Gatekeeper)"

xattr -cr "${INSTALL_DIR}/${APP_NAME}" 2>/dev/null || {
    print_warning "Kunde inte ta bort karantänattribut automatiskt."
    print_info "Kör manuellt: xattr -cr '${INSTALL_DIR}/${APP_NAME}'"
}

print_success "Karantänattribut borttaget — macOS kommer att lita på appen"

# =============================================================================
# Done
# =============================================================================
echo ""
echo -e "${C_YELLOW}${C_BOLD}==========================================="
echo "    Snapshot-installation klar! ✓"
echo "       (${SNAPSHOT_TAG})"
echo "==========================================${C_RESET}"
echo ""
print_warning "Detta är en testversion — inte en stabil release."
print_info "Starta Oden från Applications eller med:"
echo -e "  ${C_BOLD}open ${INSTALL_DIR}/${APP_NAME}${C_RESET}"
echo ""
print_info "Webbgränssnitt: http://127.0.0.1:8080"
print_info "Första körningen öppnar en setup-wizard."
echo ""
