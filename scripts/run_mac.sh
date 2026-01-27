#!/bin/bash

# ==============================================================================
# Oden - Run Script for macOS
# ==============================================================================
# This script handles everything: installation, configuration, and running Oden.

# --- Colors for output ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_BOLD='\033[1m'
C_YELLOW='\033[0;33m'

# --- Configuration ---
SIGNAL_CLI_VERSION="0.13.22"
SIGNAL_CLI_DIR="./signal-cli-${SIGNAL_CLI_VERSION}"
CONFIG_FILE="./config.ini"

# macOS binary (universal - works on both Intel and Apple Silicon)
if [ -f "./s7_watcher_mac" ]; then
    EXECUTABLE="./s7_watcher_mac"
else
    EXECUTABLE="./s7_watcher"
fi

# --- Helper Functions ---
function print_header() {
    echo -e "\n${C_BLUE}${C_BOLD}--- $1 ---${C_RESET}"
}

function print_success() {
    echo -e "${C_GREEN}$1${C_RESET}"
}

function print_error() {
    echo -e "${C_RED}$1${C_RESET}"
}

function print_warning() {
    echo -e "${C_YELLOW}$1${C_RESET}"
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

# =============================================================================
# STEP 1: Check Dependencies
# =============================================================================
print_header "Step 1: Checking Dependencies"

# Check for Homebrew
HOMEBREW_INSTALLED=false
if command -v brew &> /dev/null; then
    HOMEBREW_INSTALLED=true
    print_success "Homebrew: OK"
else
    print_warning "Homebrew not found."
    read -p "Install Homebrew? (Y/n): " INSTALL_BREW
    if [[ -z "$INSTALL_BREW" || "$INSTALL_BREW" =~ ^[Yy]$ ]]; then
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        
        # Configure brew for this session
        if [ -x "/opt/homebrew/bin/brew" ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        elif [ -x "/usr/local/bin/brew" ]; then
            eval "$(/usr/local/bin/brew shellenv)"
        fi
        
        if command -v brew &> /dev/null; then
            HOMEBREW_INSTALLED=true
            print_success "Homebrew installed."
        fi
    fi
fi

# Check for Java 21+
function check_java() {
    echo -n "Checking for Java 21+... "
    if ! command -v java &> /dev/null; then
        print_error "Not found."
        if $HOMEBREW_INSTALLED; then
            read -p "Install openjdk@21 with Homebrew? (Y/n): " INSTALL_JAVA
            if [[ -z "$INSTALL_JAVA" || "$INSTALL_JAVA" =~ ^[Yy]$ ]]; then
                brew install openjdk@21
                if [ -d "/opt/homebrew/opt/openjdk@21/bin" ]; then
                    export PATH="/opt/homebrew/opt/openjdk@21/bin:$PATH"
                elif [ -d "/usr/local/opt/openjdk@21/bin" ]; then
                    export PATH="/usr/local/opt/openjdk@21/bin:$PATH"
                fi
                check_java
            else
                print_error "Java is required. Exiting."
                exit 1
            fi
        else
            echo "Please install Java 21+ from https://adoptium.net/"
            exit 1
        fi
    else
        JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}')
        JAVA_MAJOR_VERSION=$(echo "$JAVA_VERSION" | cut -d. -f1)

        if [[ "$JAVA_MAJOR_VERSION" -lt 21 ]]; then
            print_error "Found version $JAVA_VERSION, but need 21+."
            exit 1
        else
            print_success "OK (version $JAVA_VERSION)"
        fi
    fi
}
check_java

# Check for qrencode
echo -n "Checking for qrencode... "
if ! command -v qrencode &> /dev/null; then
    print_warning "Not found."
    if $HOMEBREW_INSTALLED; then
        read -p "Install qrencode? (Y/n): " INSTALL_QRENCODE
        if [[ -z "$INSTALL_QRENCODE" || "$INSTALL_QRENCODE" =~ ^[Yy]$ ]]; then
            brew install qrencode
        fi
    fi
fi
if command -v qrencode &> /dev/null; then
    QRENCODE_INSTALLED=true
    print_success "OK"
else
    QRENCODE_INSTALLED=false
    print_warning "Not installed. QR codes will be shown as text."
fi

# =============================================================================
# STEP 2: Setup signal-cli
# =============================================================================
print_header "Step 2: Setting up signal-cli"

# First, check if config.ini already has a valid signal_cli_path
EXISTING_CLI_PATH=""
if [ -f "$CONFIG_FILE" ]; then
    EXISTING_CLI_PATH=$(grep -E "^signal_cli_path\s*=" "$CONFIG_FILE" 2>/dev/null | sed 's/signal_cli_path\s*=\s*//' | xargs)
fi

if [ -n "$EXISTING_CLI_PATH" ] && [ -f "$EXISTING_CLI_PATH" ]; then
    SIGNAL_CLI_EXEC="$EXISTING_CLI_PATH"
    print_success "Found signal-cli from config: $SIGNAL_CLI_EXEC"
elif command -v signal-cli &> /dev/null; then
    SIGNAL_CLI_EXEC=$(command -v signal-cli)
    print_success "Found signal-cli in PATH: $SIGNAL_CLI_EXEC"
elif [ -f "${SIGNAL_CLI_DIR}/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="${SIGNAL_CLI_DIR}/bin/signal-cli"
    print_success "Found bundled signal-cli: $SIGNAL_CLI_EXEC"
else
    print_warning "signal-cli not found."
    read -p "Do you have an existing signal-cli installation? (y/N): " HAS_INSTALL
    
    if [[ "$HAS_INSTALL" =~ ^[Yy]$ ]]; then
        read -p "Enter full path to signal-cli: " CUSTOM_PATH
        if [ -f "$CUSTOM_PATH" ]; then
            SIGNAL_CLI_EXEC="$CUSTOM_PATH"
            print_success "Using: $SIGNAL_CLI_EXEC"
        else
            print_error "File not found. Exiting."
            exit 1
        fi
    else
        echo "Downloading signal-cli ${SIGNAL_CLI_VERSION}..."
        DOWNLOAD_URL="https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz"
        curl -L -o signal-cli.tar.gz "$DOWNLOAD_URL"
        
        echo "Extracting..."
        tar -xzf signal-cli.tar.gz
        rm signal-cli.tar.gz
        chmod +x "${SIGNAL_CLI_DIR}/bin/signal-cli"
        SIGNAL_CLI_EXEC="${SIGNAL_CLI_DIR}/bin/signal-cli"
        print_success "signal-cli installed: $SIGNAL_CLI_EXEC"
    fi
fi

# =============================================================================
# STEP 3: Configure Signal Account
# =============================================================================
print_header "Step 3: Signal Account Configuration"

# Check for existing signal-cli state
SIGNAL_STATE_DIR="$HOME/.local/share/signal-cli"
if [ -d "$SIGNAL_STATE_DIR" ]; then
    print_warning "OBS: Befintlig signal-cli data hittades i: $SIGNAL_STATE_DIR"
    print_warning "Detta innehåller sparade konton och krypteringsnycklar från tidigare installationer."
    echo -e "Om du vill börja helt från scratch, ta bort katalogen med: ${C_BOLD}rm -rf $SIGNAL_STATE_DIR${C_RESET}"
    echo ""
fi

EXISTING_ACCOUNT_OUTPUT=$($SIGNAL_CLI_EXEC listAccounts 2>/dev/null)
SIGNAL_NUMBER=""
ACCOUNT_CHANGED=false

if [ $? -eq 0 ] && [ -n "$EXISTING_ACCOUNT_OUTPUT" ]; then
    # Get all account numbers
    ACCOUNT_NUMBERS=$(echo "$EXISTING_ACCOUNT_OUTPUT" | grep 'Number' | awk '{print $2}')
    ACCOUNT_COUNT=$(echo "$ACCOUNT_NUMBERS" | wc -l | tr -d ' ')
    
    if [ "$ACCOUNT_COUNT" -gt 1 ]; then
        echo "Found $ACCOUNT_COUNT existing accounts:"
        i=1
        while IFS= read -r num; do
            echo "  $i) $num"
            i=$((i+1))
        done <<< "$ACCOUNT_NUMBERS"
        echo "  $i) Link/register a new account"
        read -p "Choose account (1-$i): " ACCOUNT_CHOICE
        
        if [ "$ACCOUNT_CHOICE" -eq "$i" ] 2>/dev/null; then
            SIGNAL_NUMBER=""
        elif [ "$ACCOUNT_CHOICE" -ge 1 ] && [ "$ACCOUNT_CHOICE" -lt "$i" ] 2>/dev/null; then
            SIGNAL_NUMBER=$(echo "$ACCOUNT_NUMBERS" | sed -n "${ACCOUNT_CHOICE}p")
            ACCOUNT_CHANGED=true
        else
            SIGNAL_NUMBER=$(echo "$ACCOUNT_NUMBERS" | head -1)
        fi
    else
        SIGNAL_NUMBER=$(echo "$ACCOUNT_NUMBERS" | head -1)
        print_success "Found existing account: $SIGNAL_NUMBER"
        read -p "Use this account? (Y/n): " KEEP_ACCOUNT
        if [[ ! -z "$KEEP_ACCOUNT" && ! "$KEEP_ACCOUNT" =~ ^[Yy]$ ]]; then
            SIGNAL_NUMBER=""
        fi
    fi
    # Trim any whitespace/newlines
    SIGNAL_NUMBER=$(echo "$SIGNAL_NUMBER" | tr -d '\n\r ' )
fi

if [ -z "$SIGNAL_NUMBER" ]; then
    echo "How do you want to set up Signal?"
    echo -e "  1) ${C_GREEN}Link to existing Signal account${C_RESET} (Recommended)"
    echo -e "  2) ${C_YELLOW}Register a new number${C_RESET}"
    read -p "Choice (1 or 2): " SETUP_CHOICE

    case $SETUP_CHOICE in
        1)
            print_header "Linking Account"
            DEVICE_NAME="Oden-$(hostname | cut -d. -f1)"
            echo -e "On your phone: ${C_BOLD}Signal > Settings > Linked Devices > +${C_RESET}"
            read -p "Press Enter to generate QR code..."
            
            # Create a temp file for the link output
            LINK_FIFO=$(mktemp)
            rm "$LINK_FIFO"  # Remove so we can use it as a named pipe marker
            
            # Run signal-cli link in background, capturing output
            $SIGNAL_CLI_EXEC link -n "$DEVICE_NAME" > "${LINK_FIFO}.out" 2>&1 &
            LINK_PID=$!
            
            # Wait for the URI to appear (max 30 seconds)
            echo "Generating link..."
            LINK_URI=""
            for i in {1..30}; do
                sleep 1
                if [ -f "${LINK_FIFO}.out" ]; then
                    LINK_URI=$(grep -o 'sgnl://linkdevice[^[:space:]]*' "${LINK_FIFO}.out" 2>/dev/null | head -1)
                    if [ -n "$LINK_URI" ]; then
                        break
                    fi
                fi
            done
            
            if [ -z "$LINK_URI" ]; then
                print_error "Failed to generate link within 30 seconds."
                kill $LINK_PID 2>/dev/null
                cat "${LINK_FIFO}.out" 2>/dev/null
                rm -f "${LINK_FIFO}.out"
                exit 1
            fi
            
            if $QRENCODE_INSTALLED; then
                qrencode -t UTF8 "$LINK_URI"
            else
                echo -e "Link: ${C_BOLD}$LINK_URI${C_RESET}"
            fi
            
            echo ""
            echo "Scan the QR code with your phone, then wait for linking to complete..."
            echo "(This may take a minute)"
            
            # Wait for the link process to complete
            wait $LINK_PID
            LINK_EXIT=$?
            rm -f "${LINK_FIFO}.out"
            
            if [ $LINK_EXIT -ne 0 ]; then
                print_warning "Link process exited with code $LINK_EXIT"
            fi
            
            # Get the account number (use the newest/last one after linking)
            sleep 2
            EXISTING_ACCOUNT_OUTPUT=$($SIGNAL_CLI_EXEC listAccounts 2>/dev/null)
            NEW_NUMBER=$(echo "$EXISTING_ACCOUNT_OUTPUT" | grep 'Number' | tail -1 | awk '{print $2}' | tr -d '\n\r ')
            
            if [ -n "$NEW_NUMBER" ]; then
                SIGNAL_NUMBER="$NEW_NUMBER"
                ACCOUNT_CHANGED=true
            elif [ -z "$SIGNAL_NUMBER" ]; then
                read -p "Enter your Signal phone number (e.g., +46701234567): " SIGNAL_NUMBER
                SIGNAL_NUMBER=$(echo "$SIGNAL_NUMBER" | tr -d '\n\r ')
                ACCOUNT_CHANGED=true
            fi
            print_success "Account linked!"
            ;;
        2)
            print_header "Registering New Number"
            echo -e "${C_YELLOW}WARNING: Do NOT use your primary Signal number!${C_RESET}"
            read -p "Enter phone number (e.g., +46701234567): " SIGNAL_NUMBER
            
            if [ -z "$SIGNAL_NUMBER" ]; then
                print_error "Phone number required."
                exit 1
            fi
            
            read -p "Verification via (1) SMS or (2) Voice? [1]: " VERIFY_METHOD
            VERIFY_FLAG=""
            [[ "$VERIFY_METHOD" == "2" ]] && VERIFY_FLAG="--voice"
            
            REGISTER_OUTPUT=$($SIGNAL_CLI_EXEC -u "$SIGNAL_NUMBER" register $VERIFY_FLAG 2>&1)
            
            if [ $? -ne 0 ]; then
                if echo "$REGISTER_OUTPUT" | grep -qi 'captcha'; then
                    print_warning "CAPTCHA required."
                    echo -e "1. Open: ${C_BOLD}https://signalcaptchas.org/registration/generate.html${C_RESET}"
                    echo "2. Solve the captcha"
                    echo "3. Right-click 'Open Signal' and copy link"
                    read -p "Paste signalcaptcha:// link: " CAPTCHA_TOKEN
                    
                    REGISTER_OUTPUT=$($SIGNAL_CLI_EXEC -u "$SIGNAL_NUMBER" register $VERIFY_FLAG --captcha "$CAPTCHA_TOKEN" 2>&1)
                    if [ $? -ne 0 ]; then
                        print_error "Registration failed."
                        echo "$REGISTER_OUTPUT"
                        exit 1
                    fi
                else
                    print_error "Registration failed."
                    echo "$REGISTER_OUTPUT"
                    exit 1
                fi
            fi
            
            read -p "Enter verification code: " VERIFY_CODE
            $SIGNAL_CLI_EXEC -u "$SIGNAL_NUMBER" verify "$VERIFY_CODE"
            
            if [ $? -ne 0 ]; then
                print_error "Verification failed."
                exit 1
            fi
            print_success "Number registered!"
            ;;
        *)
            print_error "Invalid choice."
            exit 1
            ;;
    esac
fi

# =============================================================================
# STEP 4: Configure Oden (config.ini)
# =============================================================================
print_header "Step 4: Configuring Oden"

# Template config is shipped with the release
TEMPLATE_CONFIG="./config.ini.template"

NEEDS_CONFIG=false
if [ ! -f "$CONFIG_FILE" ]; then
    NEEDS_CONFIG=true
elif grep -q "+46XXXXXXXXX" "$CONFIG_FILE"; then
    NEEDS_CONFIG=true
fi

if $NEEDS_CONFIG; then
    echo "Setting up configuration..."
    
    # Copy template if it exists, otherwise we'll update in place
    if [ -f "$TEMPLATE_CONFIG" ] && [ ! -f "$CONFIG_FILE" ]; then
        cp "$TEMPLATE_CONFIG" "$CONFIG_FILE"
    elif [ ! -f "$CONFIG_FILE" ]; then
        print_error "config.ini.template not found. Please re-download the release."
        exit 1
    fi
    
    # Get vault path
    if [ -z "$VAULT_PATH" ]; then
        echo -e "\nWhere is your Obsidian vault?"
        read -p "Vault path (default: ./vault): " VAULT_PATH
        VAULT_PATH=${VAULT_PATH:-./vault}
    fi
    
    # Get timezone
    read -p "Timezone (default: Europe/Stockholm): " TIMEZONE
    TIMEZONE=${TIMEZONE:-Europe/Stockholm}
    
    # Convert signal-cli path to absolute if relative
    if [[ "$SIGNAL_CLI_EXEC" == ./* ]]; then
        SIGNAL_CLI_PATH="$(pwd)/${SIGNAL_CLI_EXEC#./}"
    else
        SIGNAL_CLI_PATH="$SIGNAL_CLI_EXEC"
    fi
    
    # Update config values using sed
    sed -i '' "s|^path = .*|path = $VAULT_PATH|" "$CONFIG_FILE"
    sed -i '' "s|^number = .*|number = $SIGNAL_NUMBER|" "$CONFIG_FILE"
    sed -i '' "s|^timezone = .*|timezone = $TIMEZONE|" "$CONFIG_FILE"
    
    # Uncomment and set signal_cli_path
    if grep -qE "^#signal_cli_path" "$CONFIG_FILE"; then
        sed -i '' "s|^#signal_cli_path = .*|signal_cli_path = $SIGNAL_CLI_PATH|" "$CONFIG_FILE"
    elif grep -qE "^signal_cli_path" "$CONFIG_FILE"; then
        sed -i '' "s|^signal_cli_path = .*|signal_cli_path = $SIGNAL_CLI_PATH|" "$CONFIG_FILE"
    fi
    
    # Uncomment and set log_file
    if grep -qE "^#log_file" "$CONFIG_FILE"; then
        sed -i '' "s|^#log_file = .*|log_file = signal-cli.log|" "$CONFIG_FILE"
    fi
    
    # Uncomment and set display_name
    if grep -qE "^#display_name" "$CONFIG_FILE"; then
        sed -i '' "s|^#display_name = .*|display_name = oden|" "$CONFIG_FILE"
    fi
    
    print_success "Configuration saved to $CONFIG_FILE"
else
    print_success "Configuration already exists."
    # Update number if account changed or number is set
    if [ -n "$SIGNAL_NUMBER" ] && ($ACCOUNT_CHANGED || ! grep -q "number = $SIGNAL_NUMBER" "$CONFIG_FILE"); then
        sed -i '' "s|^number = .*|number = $SIGNAL_NUMBER|" "$CONFIG_FILE"
        print_success "Updated Signal number: $SIGNAL_NUMBER"
    fi
    # Update signal_cli_path if user specified a custom path
    if [ -n "$SIGNAL_CLI_EXEC" ]; then
        # Convert to absolute path if relative
        if [[ "$SIGNAL_CLI_EXEC" == ./* ]]; then
            SIGNAL_CLI_PATH="$(pwd)/${SIGNAL_CLI_EXEC#./}"
        else
            SIGNAL_CLI_PATH="$SIGNAL_CLI_EXEC"
        fi
        # Check if signal_cli_path exists (commented or not)
        if grep -qE "^#?\s*signal_cli_path\s*=" "$CONFIG_FILE"; then
            # Replace existing line (uncomment if needed)
            sed -i '' "s|^#*\s*signal_cli_path\s*=.*|signal_cli_path = $SIGNAL_CLI_PATH|" "$CONFIG_FILE"
        else
            # Add after log_file line in [Signal] section
            sed -i '' "/^log_file\s*=/a\\
signal_cli_path = $SIGNAL_CLI_PATH
" "$CONFIG_FILE"
        fi
        print_success "Updated signal_cli_path: $SIGNAL_CLI_PATH"
    fi
fi

# =============================================================================
# STEP 4.5: Obsidian Template (optional)
# =============================================================================
OBSIDIAN_TEMPLATE="./obsidian-template/.obsidian"

# Get vault path from config if not already set
if [ -z "$VAULT_PATH" ] && [ -f "$CONFIG_FILE" ]; then
    VAULT_PATH=$(grep "^path = " "$CONFIG_FILE" | sed 's/^path = //')
fi

# Create vault directory if it doesn't exist
if [ -n "$VAULT_PATH" ] && [ ! -d "$VAULT_PATH" ]; then
    mkdir -p "$VAULT_PATH"
    print_success "Skapade valv-mappen: $VAULT_PATH"
fi

# Only ask if vault path is set and doesn't already have .obsidian
if [ -n "$VAULT_PATH" ] && [ ! -d "$VAULT_PATH/.obsidian" ] && [ -d "$OBSIDIAN_TEMPLATE" ]; then
    print_header "Obsidian Settings"
    echo "Vi har en Obsidian-mall med förinstallerade plugins (bl.a. Map View för kartor)."
    echo ""
    read -p "Vill du kopiera Obsidian-inställningar till ditt valv? [J/n]: " INSTALL_OBSIDIAN
    INSTALL_OBSIDIAN=${INSTALL_OBSIDIAN:-J}
    
    if [[ "$INSTALL_OBSIDIAN" =~ ^[JjYy]$ ]]; then
        cp -r "$OBSIDIAN_TEMPLATE" "$VAULT_PATH/"
        print_success "Obsidian-inställningar kopierade till $VAULT_PATH/.obsidian"
        echo "Tips: Starta Obsidian och aktivera community plugins under Inställningar > Community plugins"
    else
        echo "Hoppade över Obsidian-inställningar."
    fi
fi

# =============================================================================
# STEP 5: Run Application
# =============================================================================
print_header "Step 5: Starting Oden"

# Try to run the binary if it exists
if [ -f "$EXECUTABLE" ]; then
    chmod +x "$EXECUTABLE"
    
    # Remove macOS quarantine attribute (Gatekeeper blocks unsigned binaries)
    xattr -cr "$EXECUTABLE" 2>/dev/null
    
    echo -e "\n${C_GREEN}${C_BOLD}=== Oden is starting ===${C_RESET}\n"
    echo "Press Ctrl+C to stop."
    echo ""
    
    # Try to execute the binary directly, but if it fails immediately (e.g., cannot execute binary file),
    # the error will be visible and we can fall back to Python
    "$EXECUTABLE"
    EXIT_CODE=$?
    
    # If binary execution failed (130 = Ctrl+C, which is expected for user interrupt), fall back to Python
    # This handles the "cannot execute binary file" error case
    if [ $EXIT_CODE -ne 0 ] && [ $EXIT_CODE -ne 130 ]; then
        print_warning "Binary execution failed with exit code $EXIT_CODE"
        print_warning "Trying Python fallback..."
        
        # Check if Python is available and version is 3.10+
        PYTHON_CMD=""
        if command -v python3 &> /dev/null; then
            PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
            PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
            PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
            
            if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
                PYTHON_CMD="python3"
            else
                print_warning "Python $PYTHON_VERSION found, but Oden requires Python 3.10+"
                if $HOMEBREW_INSTALLED; then
                    read -p "Install Python 3.11 with Homebrew? (Y/n): " INSTALL_PYTHON
                    if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[Yy]$ ]]; then
                        brew install python@3.11
                        if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                            PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                        elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                            PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                        fi
                    fi
                else
                    print_error "Please install Python 3.10+ from https://www.python.org/"
                    exit 1
                fi
            fi
        else
            print_error "Python 3 is required but not found."
            if $HOMEBREW_INSTALLED; then
                read -p "Install Python 3.11 with Homebrew? (Y/n): " INSTALL_PYTHON
                if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[Yy]$ ]]; then
                    brew install python@3.11
                    if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                    elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                    fi
                else
                    print_error "Python 3.10+ is required. Exiting."
                    exit 1
                fi
            else
                print_error "Please install Python 3.10+ from https://www.python.org/"
                exit 1
            fi
        fi
        
        if [ -z "$PYTHON_CMD" ]; then
            print_error "Could not find or install Python 3.10+. Exiting."
            exit 1
        fi
        
        # Check if oden package exists
        if [ ! -d "./oden" ]; then
            print_error "Oden source code not found."
            print_error "This may be a binary-only release. Please report this issue."
            exit 1
        fi
        
        # Create virtual environment if needed (PEP 668 - externally managed environments)
        VENV_DIR="./.venv"
        if [ ! -d "$VENV_DIR" ]; then
            print_warning "Creating Python virtual environment..."
            $PYTHON_CMD -m venv "$VENV_DIR" || {
                print_error "Failed to create virtual environment."
                exit 1
            }
        fi
        
        # Use the venv Python
        PYTHON_CMD="$VENV_DIR/bin/python3"
        
        # Install dependencies (always run to ensure aiohttp etc are installed)
        print_warning "Installing Python dependencies..."
        $PYTHON_CMD -m pip install -e . || {
            print_error "Failed to install dependencies."
            exit 1
        }
        
        # Verify aiohttp is installed
        if ! $PYTHON_CMD -c "import aiohttp" 2>/dev/null; then
            print_error "Failed to install aiohttp. Please run manually:"
            print_error "  $PYTHON_CMD -m pip install aiohttp"
            exit 1
        fi
        
        # Run using Python
        echo -e "\n${C_GREEN}${C_BOLD}=== Oden is starting (Python mode) ===${C_RESET}\n"
        echo "Press Ctrl+C to stop."
        echo ""
        exec $PYTHON_CMD -m oden
    fi
    exit $EXIT_CODE
else
    # No binary found, try Python directly
    print_warning "Executable not found: $EXECUTABLE"
    print_warning "Trying to run from Python source..."
    
    # Check if Python is available and version is 3.10+
    PYTHON_CMD=""
    if command -v python3 &> /dev/null; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
        PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
        
        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 10 ]; then
            PYTHON_CMD="python3"
        else
            print_warning "Python $PYTHON_VERSION found, but Oden requires Python 3.10+"
            if $HOMEBREW_INSTALLED; then
                read -p "Install Python 3.11 with Homebrew? (Y/n): " INSTALL_PYTHON
                if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[Yy]$ ]]; then
                    brew install python@3.11
                    if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                    elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                        PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                    fi
                fi
            else
                print_error "Please install Python 3.10+ from https://www.python.org/"
                exit 1
            fi
        fi
    else
        print_error "Python 3 is required but not found."
        if $HOMEBREW_INSTALLED; then
            read -p "Install Python 3.11 with Homebrew? (Y/n): " INSTALL_PYTHON
            if [[ -z "$INSTALL_PYTHON" || "$INSTALL_PYTHON" =~ ^[Yy]$ ]]; then
                brew install python@3.11
                if [ -x "/opt/homebrew/opt/python@3.11/bin/python3.11" ]; then
                    PYTHON_CMD="/opt/homebrew/opt/python@3.11/bin/python3.11"
                elif [ -x "/usr/local/opt/python@3.11/bin/python3.11" ]; then
                    PYTHON_CMD="/usr/local/opt/python@3.11/bin/python3.11"
                fi
            else
                print_error "Python 3.10+ is required. Exiting."
                exit 1
            fi
        else
            print_error "Please install Python 3.10+ from https://www.python.org/"
            exit 1
        fi
    fi
    
    if [ -z "$PYTHON_CMD" ]; then
        print_error "Could not find or install Python 3.10+. Exiting."
        exit 1
    fi
    
    # Check if oden package exists
    if [ ! -d "./oden" ]; then
        print_error "Oden source code not found."
        print_error "Please make sure you have the complete Oden package."
        exit 1
    fi
    
    # Create virtual environment if needed (PEP 668 - externally managed environments)
    VENV_DIR="./.venv"
    if [ ! -d "$VENV_DIR" ]; then
        print_warning "Creating Python virtual environment..."
        $PYTHON_CMD -m venv "$VENV_DIR" || {
            print_error "Failed to create virtual environment."
            exit 1
        }
    fi
    
    # Use the venv Python
    PYTHON_CMD="$VENV_DIR/bin/python3"
    
    # Install dependencies (always run to ensure aiohttp etc are installed)
    print_warning "Installing Python dependencies..."
    $PYTHON_CMD -m pip install -e . || {
        print_error "Failed to install dependencies."
        exit 1
    }
    
    # Verify aiohttp is installed
    if ! $PYTHON_CMD -c "import aiohttp" 2>/dev/null; then
        print_error "Failed to install aiohttp. Please run manually:"
        print_error "  $PYTHON_CMD -m pip install aiohttp"
        exit 1
    fi
    
    # Run using Python
    echo -e "\n${C_GREEN}${C_BOLD}=== Oden is starting (Python mode) ===${C_RESET}\n"
    echo "Press Ctrl+C to stop."
    echo ""
    exec $PYTHON_CMD -m oden
fi
