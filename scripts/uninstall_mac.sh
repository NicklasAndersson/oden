#!/bin/bash

# ==============================================================================
# Oden - Avinstallationsskript för macOS
# ==============================================================================
# Hittar alla Oden- och signal-cli-komponenter, visar installerad version
# och storlek, och låter användaren välja vad som ska tas bort.
#
# Användning:
#   curl -fsSL https://raw.githubusercontent.com/NicklasAndersson/oden/main/scripts/uninstall_mac.sh | bash
#
# Eller:
#   ./uninstall_mac.sh

set -euo pipefail

# --- Colors ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_BOLD='\033[1m'
C_YELLOW='\033[0;33m'
C_DIM='\033[2m'

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

# Get human-readable size of a path
get_size() {
    if [[ -e "$1" ]]; then
        du -sh "$1" 2>/dev/null | awk '{print $1}'
    else
        echo "0B"
    fi
}

# --- Banner ---
echo -e "${C_RED}${C_BOLD}"
echo "==========================================="
echo "       Oden – Avinstallationsskript         "
echo "               (macOS)                      "
echo "==========================================="
echo -e "${C_RESET}"

# --- OS Check ---
if [[ "$(uname)" != "Darwin" ]]; then
    print_error "Detta skript är avsett för macOS. Du kör $(uname)."
    exit 1
fi

# --- Check if running via pipe (non-interactive) ---
if [[ ! -t 0 ]]; then
    print_error "Detta skript kräver interaktiv input."
    print_info "Ladda ner och kör det lokalt istället:"
    echo "  curl -fsSL https://raw.githubusercontent.com/NicklasAndersson/oden/main/scripts/uninstall_mac.sh -o uninstall_mac.sh"
    echo "  bash uninstall_mac.sh"
    exit 1
fi

# =============================================================================
# STEP 1: Detect all installations
# =============================================================================
print_header "Steg 1: Söker efter installerade komponenter"

# We'll track found components as numbered items
declare -a COMP_NAMES=()
declare -a COMP_PATHS=()
declare -a COMP_VERSIONS=()
declare -a COMP_SIZES=()
declare -a COMP_WARNINGS=()

# --- 1. Oden.app ---
if [[ -d "/Applications/Oden.app" ]]; then
    ODEN_VERSION="okänd"
    # Try to read version from Info.plist
    PLIST="/Applications/Oden.app/Contents/Info.plist"
    if [[ -f "$PLIST" ]]; then
        ODEN_VERSION=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$PLIST" 2>/dev/null || echo "okänd")
    fi
    COMP_NAMES+=("Oden.app (macOS-applikation)")
    COMP_PATHS+=("/Applications/Oden.app")
    COMP_VERSIONS+=("$ODEN_VERSION")
    COMP_SIZES+=("$(get_size "/Applications/Oden.app")")
    COMP_WARNINGS+=("")
fi

# --- 2. Oden config directory (~/.oden) ---
# First check the pointer file for custom location
ODEN_HOME="$HOME/.oden"
POINTER_FILE="$HOME/Library/Application Support/Oden/oden_home.txt"
if [[ -f "$POINTER_FILE" ]]; then
    CUSTOM_HOME=$(cat "$POINTER_FILE" 2>/dev/null | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//')
    if [[ -n "$CUSTOM_HOME" ]] && [[ -d "$CUSTOM_HOME" ]]; then
        ODEN_HOME="$CUSTOM_HOME"
    fi
fi

if [[ -d "$ODEN_HOME" ]]; then
    # Try to get version from config.db
    CONFIG_VERSION="—"
    if [[ -f "$ODEN_HOME/config.db" ]] && command -v sqlite3 &>/dev/null; then
        SCHEMA_VERSION=$(sqlite3 "$ODEN_HOME/config.db" "SELECT value FROM metadata WHERE key='schema_version' LIMIT 1" 2>/dev/null || echo "")
        if [[ -n "$SCHEMA_VERSION" ]]; then
            CONFIG_VERSION="schema v${SCHEMA_VERSION}"
        fi
    fi
    COMP_NAMES+=("Oden-konfiguration (config.db, loggar)")
    COMP_PATHS+=("$ODEN_HOME")
    COMP_VERSIONS+=("$CONFIG_VERSION")
    COMP_SIZES+=("$(get_size "$ODEN_HOME")")
    COMP_WARNINGS+=("Innehåller din konfiguration och databas!")
fi

# --- 3. Oden signal-data (inside ODEN_HOME) ---
SIGNAL_DATA_PATH="$ODEN_HOME/signal-data"
if [[ -d "$SIGNAL_DATA_PATH" ]]; then
    ACCOUNTS_COUNT=0
    if [[ -f "$SIGNAL_DATA_PATH/data/accounts.json" ]] && command -v python3 &>/dev/null; then
        ACCOUNTS_COUNT=$(python3 -c "
import json, sys
try:
    data = json.load(open('$SIGNAL_DATA_PATH/data/accounts.json'))
    accounts = data.get('accounts', [])
    print(len(accounts))
except: print(0)
" 2>/dev/null || echo "0")
    fi
    COMP_NAMES+=("Oden signal-data (Signal-konton i Oden)")
    COMP_PATHS+=("$SIGNAL_DATA_PATH")
    COMP_VERSIONS+=("${ACCOUNTS_COUNT} konto(n)")
    COMP_SIZES+=("$(get_size "$SIGNAL_DATA_PATH")")
    COMP_WARNINGS+=("Innehåller dina Signal-konton och nycklar! Kan INTE återskapas!")
fi

# --- 4. Application Support pointer ---
APP_SUPPORT_DIR="$HOME/Library/Application Support/Oden"
if [[ -d "$APP_SUPPORT_DIR" ]]; then
    COMP_NAMES+=("Application Support (pekarfil)")
    COMP_PATHS+=("$APP_SUPPORT_DIR")
    COMP_VERSIONS+=("—")
    COMP_SIZES+=("$(get_size "$APP_SUPPORT_DIR")")
    COMP_WARNINGS+=("")
fi

# --- 5. Standard signal-cli data ---
STANDARD_SIGNAL_DATA="$HOME/.local/share/signal-cli"
if [[ -d "$STANDARD_SIGNAL_DATA" ]]; then
    STD_ACCOUNTS=0
    if [[ -f "$STANDARD_SIGNAL_DATA/data/accounts.json" ]] && command -v python3 &>/dev/null; then
        STD_ACCOUNTS=$(python3 -c "
import json, sys
try:
    data = json.load(open('$STANDARD_SIGNAL_DATA/data/accounts.json'))
    accounts = data.get('accounts', [])
    print(len(accounts))
except: print(0)
" 2>/dev/null || echo "0")
    fi
    COMP_NAMES+=("signal-cli data (standardplats)")
    COMP_PATHS+=("$STANDARD_SIGNAL_DATA")
    COMP_VERSIONS+=("${STD_ACCOUNTS} konto(n)")
    COMP_SIZES+=("$(get_size "$STANDARD_SIGNAL_DATA")")
    COMP_WARNINGS+=("Innehåller Signal-konton och nycklar! Kan INTE återskapas!")
fi

# --- 6. signal-cli (Homebrew) ---
if command -v brew &>/dev/null && brew list signal-cli &>/dev/null 2>&1; then
    SIGNAL_CLI_VER=$(signal-cli --version 2>&1 | head -1 || echo "okänd")
    SIGNAL_CLI_PATH=$(brew --prefix signal-cli 2>/dev/null || echo "")
    COMP_NAMES+=("signal-cli (Homebrew)")
    COMP_PATHS+=("brew:signal-cli")
    COMP_VERSIONS+=("$SIGNAL_CLI_VER")
    COMP_SIZES+=("$(get_size "$SIGNAL_CLI_PATH")")
    COMP_WARNINGS+=("")
fi

# --- 7. signal-cli (standalone in common locations) ---
for SIGNAL_PATH in "$HOME/.local/bin/signal-cli" "/usr/local/bin/signal-cli"; do
    if [[ -x "$SIGNAL_PATH" ]] && ! (command -v brew &>/dev/null && brew list signal-cli &>/dev/null 2>&1); then
        SIGNAL_CLI_VER=$("$SIGNAL_PATH" --version 2>&1 | head -1 || echo "okänd")
        COMP_NAMES+=("signal-cli (fristående)")
        COMP_PATHS+=("$SIGNAL_PATH")
        COMP_VERSIONS+=("$SIGNAL_CLI_VER")
        COMP_SIZES+=("—")
        COMP_WARNINGS+=("")
        break
    fi
done

# --- 8. signal-cli in project directories ---
for DIR in ./signal-cli-*/bin/signal-cli; do
    if [[ -x "$DIR" ]] 2>/dev/null; then
        LOCAL_VER=$("$DIR" --version 2>&1 | head -1 || echo "okänd")
        PARENT_DIR=$(dirname "$(dirname "$DIR")")
        COMP_NAMES+=("signal-cli (lokal mapp)")
        COMP_PATHS+=("$PARENT_DIR")
        COMP_VERSIONS+=("$LOCAL_VER")
        COMP_SIZES+=("$(get_size "$PARENT_DIR")")
        COMP_WARNINGS+=("")
    fi
done

# --- 9. Java/OpenJDK (Homebrew) ---
if command -v brew &>/dev/null && brew list openjdk &>/dev/null 2>&1; then
    JAVA_VER=$(java -version 2>&1 | head -1 || echo "okänd")
    JAVA_PATH=$(brew --prefix openjdk 2>/dev/null || echo "")
    COMP_NAMES+=("OpenJDK (Homebrew)")
    COMP_PATHS+=("brew:openjdk")
    COMP_VERSIONS+=("$JAVA_VER")
    COMP_SIZES+=("$(get_size "$JAVA_PATH")")
    COMP_WARNINGS+=("Kan användas av andra program!")
fi

# --- 10. Docker: Oden containers and images ---
if command -v docker &>/dev/null; then
    # Check for running Oden containers
    ODEN_CONTAINERS=$(docker ps -a --filter "ancestor=ghcr.io/nicklasandersson/oden" --format "{{.ID}} {{.Image}} {{.Status}}" 2>/dev/null || true)
    if [[ -n "$ODEN_CONTAINERS" ]]; then
        CONTAINER_COUNT=$(echo "$ODEN_CONTAINERS" | wc -l | tr -d ' ')
        COMP_NAMES+=("Docker-containrar (Oden)")
        COMP_PATHS+=("docker:containers")
        COMP_VERSIONS+=("${CONTAINER_COUNT} container(s)")
        COMP_SIZES+=("—")
        COMP_WARNINGS+=("")
    fi

    # Check for Oden Docker images
    ODEN_IMAGES=$(docker images "ghcr.io/nicklasandersson/oden" --format "{{.Repository}}:{{.Tag}} ({{.Size}})" 2>/dev/null || true)
    if [[ -n "$ODEN_IMAGES" ]]; then
        IMAGE_COUNT=$(echo "$ODEN_IMAGES" | wc -l | tr -d ' ')
        COMP_NAMES+=("Docker-images (Oden)")
        COMP_PATHS+=("docker:images")
        COMP_VERSIONS+=("${IMAGE_COUNT} image(s)")
        COMP_SIZES+=("—")
        COMP_WARNINGS+=("")
    fi
fi

# =============================================================================
# STEP 2: Display found components
# =============================================================================
TOTAL=${#COMP_NAMES[@]}

if [[ "$TOTAL" -eq 0 ]]; then
    echo ""
    print_success "Inga Oden-komponenter hittades. Systemet är redan rent!"
    exit 0
fi

print_header "Steg 2: Hittade ${TOTAL} komponent(er)"
echo ""

for i in $(seq 0 $((TOTAL - 1))); do
    NUM=$((i + 1))
    echo -e "  ${C_BOLD}[${NUM}]${C_RESET} ${COMP_NAMES[$i]}"
    echo -e "      Plats:   ${C_DIM}${COMP_PATHS[$i]}${C_RESET}"
    echo -e "      Version: ${COMP_VERSIONS[$i]}"
    echo -e "      Storlek: ${COMP_SIZES[$i]}"
    if [[ -n "${COMP_WARNINGS[$i]}" ]]; then
        echo -e "      ${C_YELLOW}⚠ ${COMP_WARNINGS[$i]}${C_RESET}"
    fi
    echo ""
done

# =============================================================================
# STEP 3: Let user choose what to remove
# =============================================================================
print_header "Steg 3: Välj vad som ska tas bort"
echo ""
echo -e "  ${C_BOLD}A${C_RESET} = Ta bort ALLT (alla ${TOTAL} komponenter)"
echo -e "  ${C_BOLD}1-${TOTAL}${C_RESET} = Välj specifika (kommaseparerat, t.ex. 1,2,4)"
echo -e "  ${C_BOLD}Q${C_RESET} = Avbryt"
echo ""
read -rp "Ditt val: " CHOICE

if [[ "$CHOICE" =~ ^[Qq]$ ]] || [[ -z "$CHOICE" ]]; then
    echo ""
    print_info "Avbrutet. Inget har tagits bort."
    exit 0
fi

# Parse selection
declare -a SELECTED=()
if [[ "$CHOICE" =~ ^[Aa]$ ]]; then
    for i in $(seq 0 $((TOTAL - 1))); do
        SELECTED+=("$i")
    done
else
    IFS=',' read -ra PARTS <<< "$CHOICE"
    for PART in "${PARTS[@]}"; do
        PART=$(echo "$PART" | tr -d '[:space:]')
        if [[ "$PART" =~ ^[0-9]+$ ]] && [[ "$PART" -ge 1 ]] && [[ "$PART" -le "$TOTAL" ]]; then
            SELECTED+=("$((PART - 1))")
        else
            print_error "Ogiltigt val: '$PART' (måste vara 1-${TOTAL})"
            exit 1
        fi
    done
fi

if [[ ${#SELECTED[@]} -eq 0 ]]; then
    print_info "Inget valt. Avbryter."
    exit 0
fi

# =============================================================================
# STEP 4: Confirm and check for running processes
# =============================================================================

# Check if Oden is running
if pgrep -f "/Applications/Oden.app/Contents/MacOS/" &>/dev/null || pgrep -f "python.*oden" &>/dev/null; then
    print_warning "Oden verkar köra! Stäng appen först."
    read -rp "Vill du fortsätta ändå? (j/N): " CONTINUE
    if [[ ! "$CONTINUE" =~ ^[JjYy]$ ]]; then
        echo "Avbryter."
        exit 0
    fi
fi

# Check for data loss warnings
HAS_WARNING=false
for IDX in "${SELECTED[@]}"; do
    if [[ -n "${COMP_WARNINGS[$IDX]}" ]]; then
        HAS_WARNING=true
        break
    fi
done

echo ""
echo -e "${C_RED}${C_BOLD}Följande kommer att tas bort:${C_RESET}"
echo ""
for IDX in "${SELECTED[@]}"; do
    echo -e "  ${C_RED}✗${C_RESET} ${COMP_NAMES[$IDX]} ${C_DIM}(${COMP_SIZES[$IDX]})${C_RESET}"
    if [[ -n "${COMP_WARNINGS[$IDX]}" ]]; then
        echo -e "    ${C_YELLOW}⚠ ${COMP_WARNINGS[$IDX]}${C_RESET}"
    fi
done
echo ""

if $HAS_WARNING; then
    print_warning "VARNING: Vissa valda komponenter innehåller data som INTE kan återskapas!"
    echo ""
fi

read -rp "Är du säker? Skriv 'JA' för att bekräfta: " CONFIRM
if [[ "$CONFIRM" != "JA" ]]; then
    echo ""
    print_info "Avbrutet. Inget har tagits bort."
    exit 0
fi

# =============================================================================
# STEP 5: Remove selected components
# =============================================================================
print_header "Steg 5: Tar bort valda komponenter"

ERRORS=0

for IDX in "${SELECTED[@]}"; do
    NAME="${COMP_NAMES[$IDX]}"
    CPATH="${COMP_PATHS[$IDX]}"

    echo -n "  Tar bort ${NAME}... "

    case "$CPATH" in
        brew:signal-cli)
            if brew uninstall signal-cli 2>/dev/null; then
                print_success "Borttagen"
            else
                print_error "Misslyckades (prova: brew uninstall signal-cli)"
                ((ERRORS++)) || true
            fi
            ;;
        brew:openjdk)
            if brew uninstall openjdk 2>/dev/null; then
                print_success "Borttagen"
            else
                print_error "Misslyckades (prova: brew uninstall openjdk)"
                ((ERRORS++)) || true
            fi
            ;;
        docker:containers)
            CONTAINER_IDS=$(docker ps -a --filter "ancestor=ghcr.io/nicklasandersson/oden" --format "{{.ID}}" 2>/dev/null || true)
            if [[ -n "$CONTAINER_IDS" ]]; then
                echo "$CONTAINER_IDS" | xargs docker rm -f 2>/dev/null && print_success "Borttagna" || {
                    print_error "Misslyckades"
                    ((ERRORS++)) || true
                }
            else
                print_success "Inga containrar att ta bort"
            fi
            ;;
        docker:images)
            IMAGE_IDS=$(docker images "ghcr.io/nicklasandersson/oden" --format "{{.ID}}" 2>/dev/null || true)
            if [[ -n "$IMAGE_IDS" ]]; then
                echo "$IMAGE_IDS" | xargs docker rmi -f 2>/dev/null && print_success "Borttagna" || {
                    print_error "Misslyckades"
                    ((ERRORS++)) || true
                }
            else
                print_success "Inga images att ta bort"
            fi
            ;;
        /Applications/Oden.app)
            if rm -rf "/Applications/Oden.app" 2>/dev/null; then
                print_success "Borttagen"
            else
                print_error "Misslyckades (prova: sudo rm -rf '/Applications/Oden.app')"
                ((ERRORS++)) || true
            fi
            ;;
        *)
            # Generic path removal — verify it is a strict subpath of $HOME (not $HOME itself)
            # Normalize both paths to resolve symlinks and eliminate trailing slashes
            CPATH_REAL=$(cd "$(dirname "$CPATH")" 2>/dev/null && echo "$(pwd)/$(basename "$CPATH")" || echo "$CPATH")
            HOME_REAL=$(cd "$HOME" 2>/dev/null && pwd || echo "$HOME")
            if [[ "$CPATH_REAL" == "${HOME_REAL}/"* ]]; then
                if rm -rf "$CPATH" 2>/dev/null; then
                    print_success "Borttagen"
                else
                    print_error "Misslyckades (prova: rm -rf '${CPATH}')"
                    ((ERRORS++)) || true
                fi
            else
                print_error "Skippade — sökvägen ser inte säker ut att radera: ${CPATH}"
                ((ERRORS++)) || true
            fi
            ;;
    esac
done

# =============================================================================
# Done
# =============================================================================
echo ""
if [[ "$ERRORS" -eq 0 ]]; then
    echo -e "${C_GREEN}${C_BOLD}==========================================="
    echo "       Avinstallation klar! ✓"
    echo "==========================================${C_RESET}"
else
    echo -e "${C_YELLOW}${C_BOLD}==========================================="
    echo "   Avinstallation klar med ${ERRORS} fel"
    echo "==========================================${C_RESET}"
    print_info "Kontrollera felen ovan och åtgärda manuellt vid behov."
fi
echo ""
