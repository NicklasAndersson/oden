#!/bin/bash

# ==============================================================================
# Oden - Run Script for Linux (Ubuntu/Debian)
# ==============================================================================
# This script installs dependencies and launches Oden.
# All configuration is done through the web-based setup wizard.

set -e

# --- Colors for output ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_BOLD='\033[1m'
C_YELLOW='\033[0;33m'

# --- Configuration ---
SIGNAL_CLI_VERSION="0.13.23"
ODEN_CONFIG_DIR="$HOME/.oden"

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
echo -e "${C_BLUE}${C_BOLD}"
echo "==========================================="
echo "              Oden S7 Watcher              "
echo "              (Linux/Ubuntu)               "
echo "==========================================="
echo -e "${C_RESET}"

# --- OS Check ---
if [[ "$(uname)" != "Linux" ]]; then
    print_warning "Detta skript är avsett för Linux men du kör $(uname)."
    if [[ "$(uname)" == "Darwin" ]]; then
        echo "Använd Oden.app (DMG) för macOS istället."
    fi
    exit 1
fi

# --- Find script directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Check if we're in the release package
if [ -f "$SCRIPT_DIR/oden_linux" ]; then
    EXECUTABLE="$SCRIPT_DIR/oden_linux"
else
    print_error "Kunde inte hitta oden_linux binär."
    print_info "Se till att du kör detta skript från release-paketet."
    exit 1
fi

# =============================================================================
# STEP 1: Check Dependencies
# =============================================================================
print_header "Steg 1: Kontrollerar beroenden"

# Check for Java 21+
check_java() {
    echo -n "Kontrollerar Java 21+... "
    if ! command -v java &> /dev/null; then
        print_error "Inte installerat."
        echo ""
        read -p "Java krävs. Installera openjdk-21-jdk med apt? (J/n): " INSTALL_JAVA
        if [[ -z "$INSTALL_JAVA" || "$INSTALL_JAVA" =~ ^[JjYy]$ ]]; then
            echo "Installerar openjdk-21-jdk (kräver sudo)..."
            sudo apt update && sudo apt install -y openjdk-21-jdk
            if [ $? -eq 0 ]; then
                print_success "Java installerat."
            else
                print_error "Installation misslyckades."
                exit 1
            fi
        else
            print_error "Java krävs för att fortsätta."
            exit 1
        fi
    fi
    
    JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}')
    JAVA_MAJOR_VERSION=$(echo "$JAVA_VERSION" | cut -d. -f1)

    if [[ "$JAVA_MAJOR_VERSION" -lt 21 ]]; then
        print_error "Hittade version $JAVA_VERSION, men behöver 21+."
        echo "Installera med: sudo apt install openjdk-21-jdk"
        exit 1
    else
        print_success "Java $JAVA_VERSION"
    fi
}
check_java

# =============================================================================
# STEP 2: Setup signal-cli
# =============================================================================
print_header "Steg 2: Kontrollerar signal-cli"

# Check multiple locations for signal-cli
SIGNAL_CLI_EXEC=""

# 1. Check if bundled with release
if [ -f "$SCRIPT_DIR/signal-cli/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="$SCRIPT_DIR/signal-cli/bin/signal-cli"
    print_success "Använder medföljande signal-cli"
# 2. Check in PATH
elif command -v signal-cli &> /dev/null; then
    SIGNAL_CLI_EXEC=$(command -v signal-cli)
    print_success "Hittade signal-cli i PATH: $SIGNAL_CLI_EXEC"
# 3. Check standard locations
elif [ -f "$HOME/.local/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="$HOME/.local/bin/signal-cli"
    print_success "Hittade signal-cli: $SIGNAL_CLI_EXEC"
elif [ -f "/usr/local/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="/usr/local/bin/signal-cli"
    print_success "Hittade signal-cli: $SIGNAL_CLI_EXEC"
else
    print_warning "signal-cli hittades inte."
    echo ""
    read -p "Ladda ner signal-cli $SIGNAL_CLI_VERSION automatiskt? (J/n): " DOWNLOAD_CLI
    if [[ -z "$DOWNLOAD_CLI" || "$DOWNLOAD_CLI" =~ ^[JjYy]$ ]]; then
        echo "Laddar ner signal-cli..."
        DOWNLOAD_URL="https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz"
        
        mkdir -p "$HOME/.local/bin"
        cd "$HOME/.local"
        
        if command -v curl &> /dev/null; then
            curl -L -o signal-cli.tar.gz "$DOWNLOAD_URL"
        elif command -v wget &> /dev/null; then
            wget -O signal-cli.tar.gz "$DOWNLOAD_URL"
        else
            print_error "Varken curl eller wget hittades."
            exit 1
        fi
        
        tar -xzf signal-cli.tar.gz
        rm signal-cli.tar.gz
        
        # Create symlink
        ln -sf "$HOME/.local/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli" "$HOME/.local/bin/signal-cli"
        chmod +x "$HOME/.local/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli"
        
        SIGNAL_CLI_EXEC="$HOME/.local/bin/signal-cli"
        print_success "signal-cli installerat: $SIGNAL_CLI_EXEC"
        
        cd "$SCRIPT_DIR"
    else
        print_error "signal-cli krävs för att fortsätta."
        exit 1
    fi
fi

# Verify signal-cli works
echo -n "Verifierar signal-cli... "
if $SIGNAL_CLI_EXEC --version &> /dev/null; then
    CLI_VERSION=$($SIGNAL_CLI_EXEC --version 2>&1 | head -1)
    print_success "$CLI_VERSION"
else
    print_error "signal-cli kunde inte köras."
    exit 1
fi

# =============================================================================
# STEP 3: Create config directory
# =============================================================================
print_header "Steg 3: Förbereder konfiguration"

mkdir -p "$ODEN_CONFIG_DIR"
print_success "Konfigurationskatalog: $ODEN_CONFIG_DIR"

# Write signal-cli path to a temp location for the app to find
echo "$SIGNAL_CLI_EXEC" > "$ODEN_CONFIG_DIR/.signal_cli_path"

# =============================================================================
# STEP 4: Launch Oden
# =============================================================================
print_header "Steg 4: Startar Oden"

chmod +x "$EXECUTABLE"

if [ ! -f "$ODEN_CONFIG_DIR/config.ini" ]; then
    print_info "Första körningen - setup wizard kommer att öppnas i webbläsaren."
    echo ""
fi

echo "Startar Oden..."
echo "Webb-GUI: http://127.0.0.1:8080"
echo ""
echo -e "${C_YELLOW}Tryck Ctrl+C för att avsluta${C_RESET}"
echo ""

# Export signal-cli path for the app
export SIGNAL_CLI_PATH="$SIGNAL_CLI_EXEC"

exec "$EXECUTABLE"
