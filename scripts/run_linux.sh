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
EXECUTABLE=""
if [ -f "$SCRIPT_DIR/oden_linux" ]; then
    EXECUTABLE="$SCRIPT_DIR/oden_linux"
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

# Function for Python fallback
run_python_fallback() {
    print_warning "Försöker med Python-fallback..."
    
    PYTHON_CMD=""
    # Try python3 first, then python
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
        PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
        
        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
            PYTHON_CMD="python3"
        fi
    fi
    
    if [ -z "$PYTHON_CMD" ] && command -v python &> /dev/null; then
        PYTHON_VERSION=$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
        PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
        
        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
            PYTHON_CMD="python"
        fi
    fi
    
    if [ -z "$PYTHON_CMD" ]; then
        print_error "Python 3.10+ krävs men hittades inte."
        print_info "Installera med: sudo apt install python3.11 python3.11-venv"
        exit 1
    fi
    
    print_success "Python $PYTHON_VERSION"
    
    # Check if oden package exists
    if [ ! -d "$SCRIPT_DIR/oden" ]; then
        print_error "Oden-källkod hittades inte."
        print_error "Detta kan vara en binär-only release. Rapportera detta problem."
        exit 1
    fi
    
    cd "$SCRIPT_DIR" || exit 1
    
    # Create virtual environment if needed
    VENV_DIR="$SCRIPT_DIR/.venv"
    if [ ! -d "$VENV_DIR" ]; then
        print_warning "Skapar Python virtuell miljö..."
        $PYTHON_CMD -m venv "$VENV_DIR" || {
            print_error "Kunde inte skapa virtuell miljö."
            print_info "Installera venv med: sudo apt install python3.11-venv"
            exit 1
        }
    fi
    
    # Use the venv Python
    PYTHON_CMD="$VENV_DIR/bin/python3"
    
    # Install dependencies
    print_warning "Installerar Python-beroenden..."
    $PYTHON_CMD -m pip install -e . || {
        print_error "Kunde inte installera beroenden."
        exit 1
    }
    
    # Run using Python
    echo ""
    echo -e "${C_GREEN}${C_BOLD}=== Oden startar (Python-läge) ===${C_RESET}"
    echo "Webb-GUI: http://127.0.0.1:8080"
    echo ""
    echo -e "${C_YELLOW}Tryck Ctrl+C för att avsluta${C_RESET}"
    echo ""
    exec $PYTHON_CMD -m oden
}

# Try to run the binary if it exists
if [ -n "$EXECUTABLE" ] && [ -f "$EXECUTABLE" ]; then
    chmod +x "$EXECUTABLE"
    
    "$EXECUTABLE"
    EXIT_CODE=$?
    
    # If binary failed (130 = Ctrl+C, which is expected), fall back to Python
    if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 130 ]; then
        print_warning "Binär körning misslyckades med kod $EXIT_CODE"
        run_python_fallback
    fi
    exit $EXIT_CODE
else
    # No binary found, try Python directly
    print_warning "Körbar fil hittades inte: oden_linux"
    run_python_fallback
fi
