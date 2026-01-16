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
# Try OS-specific binary first, fall back to generic name
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

if command -v signal-cli &> /dev/null; then
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

EXISTING_ACCOUNT_OUTPUT=$($SIGNAL_CLI_EXEC listAccounts 2>/dev/null)
SIGNAL_NUMBER=""

if [ $? -eq 0 ] && [ -n "$EXISTING_ACCOUNT_OUTPUT" ]; then
    SIGNAL_NUMBER=$(echo "$EXISTING_ACCOUNT_OUTPUT" | grep 'Number' | awk '{print $2}')
    print_success "Found existing account: $SIGNAL_NUMBER"
    read -p "Use this account? (Y/n): " KEEP_ACCOUNT
    if [[ ! -z "$KEEP_ACCOUNT" && ! "$KEEP_ACCOUNT" =~ ^[Yy]$ ]]; then
        SIGNAL_NUMBER=""
    fi
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
            
            LINK_OUTPUT=$($SIGNAL_CLI_EXEC link -n "$DEVICE_NAME" 2>&1)
            LINK_URI=$(echo "$LINK_OUTPUT" | grep 'tsdevice:')
            
            if [ -z "$LINK_URI" ]; then
                print_error "Failed to generate link."
                echo "$LINK_OUTPUT"
                exit 1
            fi
            
            if $QRENCODE_INSTALLED; then
                qrencode -t UTF8 "$LINK_URI"
            else
                echo -e "Link: ${C_BOLD}$LINK_URI${C_RESET}"
            fi
            
            echo "Waiting for link to complete..."
            sleep 3
            EXISTING_ACCOUNT_OUTPUT=$($SIGNAL_CLI_EXEC listAccounts 2>/dev/null)
            SIGNAL_NUMBER=$(echo "$EXISTING_ACCOUNT_OUTPUT" | grep 'Number' | awk '{print $2}')
            
            if [ -z "$SIGNAL_NUMBER" ]; then
                read -p "Enter your Signal phone number (e.g., +46701234567): " SIGNAL_NUMBER
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

NEEDS_CONFIG=false
if [ ! -f "$CONFIG_FILE" ]; then
    NEEDS_CONFIG=true
elif grep -q "YOUR_SIGNAL_NUMBER" "$CONFIG_FILE"; then
    NEEDS_CONFIG=true
fi

if $NEEDS_CONFIG; then
    echo "Setting up configuration..."
    
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
    
    # Create config.ini
    cat > "$CONFIG_FILE" << EOF
[Vault]
path = $VAULT_PATH

[Signal]
number = $SIGNAL_NUMBER
signal_cli_path = $SIGNAL_CLI_PATH
log_file = signal-cli.log
display_name = oden
#unmanaged_signal_cli = false
#host = 127.0.0.1
#port = 7583

[Regex]
registration_number = [A-Z,a-z]{3}[0-9]{2}[A-Z,a-z,0-9]{1}
phone_number = (\\+46|0)[1-9][0-9]{7,8}
personal_number = [0-9]{6}[-]?[0-9]{4}

[Settings]
append_window_minutes = 30
#ignored_groups = 

[Timezone]
timezone = $TIMEZONE
EOF
    
    print_success "Configuration saved to $CONFIG_FILE"
else
    print_success "Configuration already exists."
    if [ -n "$SIGNAL_NUMBER" ]; then
        sed -i '' "s/number = .*/number = $SIGNAL_NUMBER/" "$CONFIG_FILE"
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
        
        # Check if Python is available
        if ! command -v python3 &> /dev/null; then
            print_error "Python 3 is required but not found."
            print_error "Please install Python 3.10+ from https://www.python.org/"
            exit 1
        fi
        
        # Check if oden package exists
        if [ ! -d "./oden" ]; then
            print_error "Oden source code not found."
            print_error "This may be a binary-only release. Please report this issue."
            exit 1
        fi
        
        # Run using Python
        echo -e "\n${C_GREEN}${C_BOLD}=== Oden is starting (Python mode) ===${C_RESET}\n"
        echo "Press Ctrl+C to stop."
        echo ""
        exec python3 -m oden
    fi
    exit $EXIT_CODE
else
    # No binary found, try Python directly
    print_warning "Executable not found: $EXECUTABLE"
    print_warning "Trying to run from Python source..."
    
    # Check if Python is available
    if ! command -v python3 &> /dev/null; then
        print_error "Python 3 is required but not found."
        print_error "Please install Python 3.10+ from https://www.python.org/"
        exit 1
    fi
    
    # Check if oden package exists
    if [ ! -d "./oden" ]; then
        print_error "Oden source code not found."
        print_error "Please make sure you have the complete Oden package."
        exit 1
    fi
    
    # Install dependencies if needed
    if ! python3 -c "import oden" 2>/dev/null; then
        print_warning "Installing Python dependencies..."
        python3 -m pip install --quiet -e . || {
            print_error "Failed to install dependencies."
            exit 1
        }
    fi
    
    # Run using Python
    echo -e "\n${C_GREEN}${C_BOLD}=== Oden is starting (Python mode) ===${C_RESET}\n"
    echo "Press Ctrl+C to stop."
    echo ""
    exec python3 -m oden
fi
