#!/bin/bash

# ==============================================================================
# Oden - Run Script for macOS
# ==============================================================================
# This script installs dependencies and launches Oden.
# All configuration is done through the web-based setup wizard.

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

# macOS binary (universal - works on both Intel and Apple Silicon)
if [ -f "./s7_watcher_mac" ]; then
    EXECUTABLE="./s7_watcher_mac"
else
    EXECUTABLE="./s7_watcher"
fi

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
echo "                 (macOS)                   "
echo "==========================================="
echo -e "${C_RESET}"

# --- OS Check ---
if [[ "$(uname)" != "Darwin" ]]; then
    print_warning "VARNING: Detta skript är avsett för macOS men du kör $(uname)."
    print_warning "Använd run_linux.sh för Linux eller run_windows.ps1 för Windows."
    echo ""
    read -p "Vill du fortsätta ändå? (y/N): " CONTINUE_ANYWAY
    if [[ ! "$CONTINUE_ANYWAY" =~ ^[Yy]$ ]]; then
        echo "Avbryter."
        exit 1
    fi
fi

# --- Find script directory ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# =============================================================================
# STEP 1: Check Dependencies
# =============================================================================
print_header "Steg 1: Kontrollerar beroenden"

# Check for Homebrew
HOMEBREW_INSTALLED=false
if command -v brew &> /dev/null; then
    HOMEBREW_INSTALLED=true
    print_success "Homebrew"
else
    print_warning "Homebrew hittades inte."
    read -p "Installera Homebrew? (J/n): " INSTALL_BREW
    if [[ -z "$INSTALL_BREW" || "$INSTALL_BREW" =~ ^[JjYy]$ ]]; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Configure brew for this session
        if [ -x "/opt/homebrew/bin/brew" ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -x "/usr/local/bin/brew" ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        
        if command -v brew &> /dev/null; then
            HOMEBREW_INSTALLED=true
            print_success "Homebrew installerat."
        fi
    fi
fi

# Check for Java 21+
check_java() {
    echo -n "Kontrollerar Java 21+... "
    if ! command -v java &> /dev/null; then
        print_error "Inte hittat."
        if $HOMEBREW_INSTALLED; then
            read -p "Installera openjdk med Homebrew? (J/n): " INSTALL_JAVA
            if [[ -z "$INSTALL_JAVA" || "$INSTALL_JAVA" =~ ^[JjYy]$ ]]; then
                brew install openjdk
                # Link it so java command works
                if [ -d "/opt/homebrew/opt/openjdk/bin" ]; then
                    export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"
                elif [ -d "/usr/local/opt/openjdk/bin" ]; then
                    export PATH="/usr/local/opt/openjdk/bin:$PATH"
                fi
                check_java
            else
                print_error "Java krävs. Avbryter."
                exit 1
            fi
        else
            print_error "Installera Java 21+ från https://adoptium.net/"
            exit 1
        fi
    else
        JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}')
        JAVA_MAJOR_VERSION=$(echo "$JAVA_VERSION" | cut -d. -f1)

        if [[ "$JAVA_MAJOR_VERSION" -lt 21 ]]; then
            print_warning "Hittade version $JAVA_VERSION, men behöver 21+."
            if $HOMEBREW_INSTALLED; then
                read -p "Installera nyare openjdk med Homebrew? (J/n): " INSTALL_JAVA
                if [[ -z "$INSTALL_JAVA" || "$INSTALL_JAVA" =~ ^[JjYy]$ ]]; then
                    brew install openjdk
                    if [ -d "/opt/homebrew/opt/openjdk/bin" ]; then
                        export PATH="/opt/homebrew/opt/openjdk/bin:$PATH"
                    elif [ -d "/usr/local/opt/openjdk/bin" ]; then
                        export PATH="/usr/local/opt/openjdk/bin:$PATH"
                    fi
                    check_java
                else
                    print_error "Java 21+ krävs för signal-cli. Avbryter."
                    exit 1
                fi
            else
                print_error "Installera Java 21+ från https://adoptium.net/"
                exit 1
            fi
        else
            print_success "Java $JAVA_VERSION"
        fi
    fi
}
check_java

# =============================================================================
# STEP 2: Setup signal-cli
# =============================================================================
print_header "Steg 2: Kontrollerar signal-cli"

SIGNAL_CLI_EXEC=""

# 1. Check if bundled with release
if [ -f "$SCRIPT_DIR/signal-cli/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="$SCRIPT_DIR/signal-cli/bin/signal-cli"
    print_success "Använder medföljande signal-cli"
# 2. Check in PATH
elif command -v signal-cli &> /dev/null; then
    SIGNAL_CLI_EXEC=$(command -v signal-cli)
    print_success "Hittade signal-cli i PATH: $SIGNAL_CLI_EXEC"
# 3. Check project directory (development)
elif [ -f "./signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="$(pwd)/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli"
    print_success "Hittade signal-cli: $SIGNAL_CLI_EXEC"
# 4. Check older version
elif [ -f "./signal-cli-0.13.22/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="$(pwd)/signal-cli-0.13.22/bin/signal-cli"
    print_success "Hittade signal-cli: $SIGNAL_CLI_EXEC"
# 5. Check standard locations
elif [ -f "/usr/local/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="/usr/local/bin/signal-cli"
    print_success "Hittade signal-cli: $SIGNAL_CLI_EXEC"
elif [ -f "$HOME/.local/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="$HOME/.local/bin/signal-cli"
    print_success "Hittade signal-cli: $SIGNAL_CLI_EXEC"
else
    print_warning "signal-cli hittades inte."
    echo ""
    read -p "Ladda ner signal-cli $SIGNAL_CLI_VERSION automatiskt? (J/n): " DOWNLOAD_CLI
    if [[ -z "$DOWNLOAD_CLI" || "$DOWNLOAD_CLI" =~ ^[JjYy]$ ]]; then
        echo "Laddar ner signal-cli..."
        DOWNLOAD_URL="https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz"
        
        curl -L -o signal-cli.tar.gz "$DOWNLOAD_URL"
        echo "Extraherar..."
        tar -xzf signal-cli.tar.gz
        rm signal-cli.tar.gz
        chmod +x "./signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli"
        
        SIGNAL_CLI_EXEC="$(pwd)/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli"
        print_success "signal-cli installerat: $SIGNAL_CLI_EXEC"
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

# Write signal-cli path for the app to find
echo "$SIGNAL_CLI_EXEC" > "$ODEN_CONFIG_DIR/.signal_cli_path"

# =============================================================================
# STEP 4: Launch Oden
# =============================================================================
print_header "Steg 4: Startar Oden"

# Export signal-cli path for the app
export SIGNAL_CLI_PATH="$SIGNAL_CLI_EXEC"

# Try to run the binary if it exists
if [ -f "$EXECUTABLE" ]; then
    chmod +x "$EXECUTABLE"
    
    # Remove macOS quarantine attribute (Gatekeeper blocks unsigned binaries)
    xattr -cr "$EXECUTABLE" 2>/dev/null
    
    if [ ! -f "$ODEN_CONFIG_DIR/config.ini" ]; then
        print_info "Första körningen - setup wizard kommer att öppnas i webbläsaren."
        echo ""
    fi
    
    echo "Startar Oden..."
    echo "Webb-GUI: http://127.0.0.1:8080"
    echo ""
    echo -e "${C_YELLOW}Tryck Ctrl+C för att avsluta${C_RESET}"
    echo ""
    
    "$EXECUTABLE"
    EXIT_CODE=$?
    
    # If binary execution failed (130 = Ctrl+C, which is expected), fall back to Python
    if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 130 ]; then
        print_warning "Binär körning misslyckades med kod $EXIT_CODE"
        print_warning "Försöker med Python-fallback..."
        
        # Python fallback
        PYTHON_CMD=""
        if command -v python3 &> /dev/null; then
            PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
            PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
            
            if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
                PYTHON_CMD="python3"
            else
                print_warning "Python $PYTHON_VERSION hittades, men Oden kräver Python 3.10+"
                if $HOMEBREW_INSTALLED; then
                    read -p "Installera Python 3.11 med Homebrew? (J/n): " INSTALL_PYTHON
                    if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[JjYy]$ ]]; then
                        brew install python@3.11
                        if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                            PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                        elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                            PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                        fi
                    fi
                else
                    print_error "Installera Python 3.10+ från https://www.python.org/"
                    exit 1
                fi
            fi
        else
            print_error "Python 3 krävs men hittades inte."
            if $HOMEBREW_INSTALLED; then
                read -p "Installera Python 3.11 med Homebrew? (J/n): " INSTALL_PYTHON
                if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[JjYy]$ ]]; then
                    brew install python@3.11
                    if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                    elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                    fi
                else
                    print_error "Python 3.10+ krävs. Avbryter."
                    exit 1
                fi
            else
                print_error "Installera Python 3.10+ från https://www.python.org/"
                exit 1
            fi
        fi
        
        if [ -z "$PYTHON_CMD" ]; then
            print_error "Kunde inte hitta eller installera Python 3.10+. Avbryter."
            exit 1
        fi
        
        # Check if oden package exists
        if [ ! -d "./oden" ]; then
            print_error "Oden-källkod hittades inte."
            print_error "Detta kan vara en binär-only release. Rapportera detta problem."
            exit 1
        fi
        
        # Create virtual environment if needed (PEP 668 - externally managed environments)
        VENV_DIR="./.venv"
        if [ ! -d "$VENV_DIR" ]; then
            print_warning "Skapar Python virtuell miljö..."
            $PYTHON_CMD -m venv "$VENV_DIR" || {
                print_error "Kunde inte skapa virtuell miljö."
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
        echo -e "\n${C_GREEN}${C_BOLD}=== Oden startar (Python-läge) ===${C_RESET}\n"
        echo -e "${C_YELLOW}Tryck Ctrl+C för att avsluta${C_RESET}"
        echo ""
        exec $PYTHON_CMD -m oden
    fi
    exit $EXIT_CODE
else
    # No binary found, try Python directly
    print_warning "Körbar fil hittades inte: $EXECUTABLE"
    print_warning "Försöker köra från Python-källkod..."
    
    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
        PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
        
        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
            PYTHON_CMD="python3"
        else
            print_warning "Python $PYTHON_VERSION hittades, men Oden kräver Python 3.10+"
            if $HOMEBREW_INSTALLED; then
                read -p "Installera Python 3.11 med Homebrew? (J/n): " INSTALL_PYTHON
                if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[JjYy]$ ]]; then
                    brew install python@3.11
                    if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                    elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                    fi
                fi
            else
                print_error "Installera Python 3.10+ från https://www.python.org/"
                exit 1
            fi
        fi
    else
        print_error "Python 3 krävs men hittades inte."
        if $HOMEBREW_INSTALLED; then
            read -p "Installera Python 3.11 med Homebrew? (J/n): " INSTALL_PYTHON
            if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[JjYy]$ ]]; then
                brew install python@3.11
                if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                    PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                    PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                fi
            else
                print_error "Python 3.10+ krävs. Avbryter."
                exit 1
            fi
        else
            print_error "Installera Python 3.10+ från https://www.python.org/"
            exit 1
        fi
    fi
    
    if [ -z "$PYTHON_CMD" ]; then
        print_error "Kunde inte hitta eller installera Python 3.10+. Avbryter."
        exit 1
    fi
    
    # Check if oden package exists
    if [ ! -d "./oden" ]; then
        print_error "Oden-källkod hittades inte."
        print_error "Se till att du har hela Oden-paketet."
        exit 1
    fi
    
    # Create virtual environment if needed (PEP 668 - externally managed environments)
    VENV_DIR="./.venv"
    if [ ! -d "$VENV_DIR" ]; then
        print_warning "Skapar Python virtuell miljö..."
        $PYTHON_CMD -m venv "$VENV_DIR" || {
            print_error "Kunde inte skapa virtuell miljö."
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
    
    if [ ! -f "$ODEN_CONFIG_DIR/config.ini" ]; then
        print_info "Första körningen - setup wizard kommer att öppnas i webbläsaren."
        echo ""
    fi
    
    # Run using Python
    echo -e "\n${C_GREEN}${C_BOLD}=== Oden startar (Python-läge) ===${C_RESET}\n"
    echo "Webb-GUI: http://127.0.0.1:8080"
    echo ""
    echo -e "${C_YELLOW}Tryck Ctrl+C för att avsluta${C_RESET}"
    echo ""
    exec $PYTHON_CMD -m oden
fi
