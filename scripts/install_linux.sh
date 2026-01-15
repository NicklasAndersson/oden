#!/bin/bash

# ==============================================================================
# Oden Installation Script for Linux (Ubuntu/Debian)
# ==============================================================================

# --- Colors for output ---
C_RESET='\033[0m'
C_RED='\033[0;31m'
C_GREEN='\033[0;32m'
C_BLUE='\033[0;34m'
C_BOLD='\033[1m'
C_YELLOW='\033[0;33m'

# --- Helper Functions ---
function print_header() {
    echo -e "\n${C_BLUE}${C_BOLD}---  ---${C_RESET}"
}

# --- Banner ---
echo -e "${C_BLUE}${C_BOLD}"
echo "-------------------------------------------"
echo "--- Oden Signal Integration Installer ---"
echo "---          (Linux/Ubuntu)            ---"
echo "-------------------------------------------"
echo -e "${C_RESET}"
echo "This script will guide you through setting up signal-cli to work with Oden."
echo "It will check for dependencies, help you install them, and then configure your Signal account."
echo -e "${C_YELLOW}Note: This script may require sudo privileges for installing packages.${C_RESET}"

# --- Dependency Check ---
print_header "Step 1: Checking Dependencies"

# 1. Check for Java
function check_java() {
    echo -n "Checking for Java 17+... "
    if ! command -v java &> /dev/null; then
        echo -e "${C_RED}Not found.${C_RESET}"
        read -p "Java is required. Install openjdk-17-jdk with apt? (Y/n): " INSTALL_JAVA
        if [[ -z "$INSTALL_JAVA" || "$INSTALL_JAVA" =~ ^[Yy]$ ]]; then
            echo "Installing openjdk-17-jdk (requires sudo)..."
            sudo apt update && sudo apt install -y openjdk-17-jdk
            if [ $? -eq 0 ]; then
                echo -e "${C_GREEN}Java installed successfully.${C_RESET}"
                check_java # Re-run the check
            else
                echo -e "${C_RED}Installation failed. Please check apt output.${C_RESET}"
                exit 1
            fi
        else
            echo -e "${C_RED}Java is required to continue. Exiting.${C_RESET}"
            exit 1
        fi
    else
        JAVA_VERSION=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}')
        JAVA_MAJOR_VERSION=$(echo "$JAVA_VERSION" | cut -d. -f1)

        if [[ "$JAVA_MAJOR_VERSION" -lt 17 ]]; then
            echo -e "${C_RED}Found version $JAVA_VERSION, but need 17+.${C_RESET}"
            echo "Error: Your Java version is too old. signal-cli requires Java 17 or higher."
            echo "Please update or install a newer version, e.g., via 'sudo apt install openjdk-17-jdk'"
            exit 1
        else
            echo -e "${C_GREEN}OK (found version $JAVA_VERSION).${C_RESET}"
        fi
    fi
}
check_java # Initial call to the java check function

# 2. Check for qrencode (for linking)
echo -n "Checking for qrencode... "
if ! command -v qrencode &> /dev/null; then
    echo -e "${C_YELLOW}Not found.${C_RESET}"
    read -p "'qrencode' is recommended for easy device linking. Install with apt? (Y/n): " INSTALL_QRENCODE
    if [[ -z "$INSTALL_QRENCODE" || "$INSTALL_QRENCODE" =~ ^[Yy]$ ]]; then
        echo "Installing qrencode (requires sudo)..."
        sudo apt install -y qrencode
    fi
fi
# Re-check for qrencode after optional installation
if command -v qrencode &> /dev/null; then
    echo -e "${C_GREEN}qrencode is available.${C_RESET}"
    QRENCODE_INSTALLED=true
else
    echo -e "${C_YELLOW}qrencode not installed. Will show link as text.${C_RESET}"
    QRENCODE_INSTALLED=false
fi

# --- Setup: Find signal-cli ---
print_header "Locating signal-cli"

if command -v signal-cli &> /dev/null; then
    SIGNAL_CLI_EXEC=$(command -v signal-cli)
    echo -e "${C_GREEN}Found signal-cli in your PATH at: $SIGNAL_CLI_EXEC${C_RESET}"
elif [ -f "./signal-cli-0.13.22/bin/signal-cli" ]; then
    SIGNAL_CLI_EXEC="./signal-cli-0.13.22/bin/signal-cli"
    echo -e "${C_GREEN}Found bundled signal-cli at: $SIGNAL_CLI_EXEC${C_RESET}"
else
    echo -e "${C_YELLOW}Could not automatically find signal-cli.${C_RESET}"
    read -p "Do you have another installation of signal-cli you would like to use? (y/N): " USE_CUSTOM_PATH
    if [[ "$USE_CUSTOM_PATH" =~ ^[Yy]$ ]]; then
        read -p "Please enter the full path to your signal-cli executable: " CUSTOM_PATH
        if [ -f "$CUSTOM_PATH" ]; then
            SIGNAL_CLI_EXEC="$CUSTOM_PATH"
            echo -e "${C_GREEN}Using signal-cli at: $SIGNAL_CLI_EXEC${C_RESET}"
        else
            echo -e "${C_RED}Error: File not found at '$CUSTOM_PATH'. Exiting.${C_RESET}"
            exit 1
        fi
    else
        echo -e "${C_RED}Error: signal-cli executable not found. Exiting.${C_RESET}"
        exit 1
    fi
fi


# --- Check for existing setup ---
print_header "Step 2: Checking for Existing Signal Setup"
echo "Checking if an account is already configured..."

EXISTING_ACCOUNT_OUTPUT=$($SIGNAL_CLI_EXEC listAccounts 2>/dev/null)

if [ $? -eq 0 ] && [ -n "$EXISTING_ACCOUNT_OUTPUT" ]; then
    ACCOUNT_ID=$(echo "$EXISTING_ACCOUNT_OUTPUT" | grep 'Number' | awk '{print $2}')
    echo -e "${C_GREEN}Found existing configured account: ${C_BOLD}$ACCOUNT_ID${C_RESET}"
    read -p "Do you want to keep using this account? (Y/n): " KEEP_ACCOUNT
    if [[ -z "$KEEP_ACCOUNT" || "$KEEP_ACCOUNT" =~ ^[Yy]$ ]]; then
        echo -e "\n${C_GREEN}Great! Your existing Signal setup is ready to use.${C_RESET}"
        echo "Setup is complete. Please see docs/HOW_TO_RUN.md for instructions on how to run the application."
        exit 0
    else
        echo "Proceeding with re-configuration..."
    fi
else
    echo "No existing account found. Proceeding with first-time setup."
fi

# --- Main Menu ---
print_header "Step 3: Choose Setup Method"
echo "How do you want to set up Signal?"
echo "  1) ${C_GREEN}Link to an existing Signal account${C_RESET} (Recommended)"
echo "     Links this app as a new device to your primary Signal account on your phone."
echo "  2) ${C_RED}Register a completely new number${C_RESET}"
echo "     This requires a separate phone number that is NOT already used for Signal."
echo

read -p "Enter your choice (1 or 2): " choice

case $choice in
    1)
        print_header "Linking Existing Account"
        DEVICE_NAME="Oden-Watcher-$(hostname | cut -d. -f1)"
        echo "I will now generate a QR code to link a new device named '${DEVICE_NAME}'."
        echo -e "On your phone, open Signal and go to: ${C_BOLD}Settings > Linked Devices > '+'${C_RESET}"
        echo
        read -p "Press [Enter] to generate the QR code..."

        LINK_URI_OUTPUT=$($SIGNAL_CLI_EXEC link -n "$DEVICE_NAME" 2>&1)

        if [ $? -ne 0 ]; then
            echo -e "\n${C_RED}Error: signal-cli failed to generate a link.${C_RESET}"
            echo "--- signal-cli output ---"
            echo "$LINK_URI_OUTPUT"
            echo "--------------------------"
            exit 1
        fi
        
        LINK_URI=$(echo "$LINK_URI_OUTPUT" | grep 'tsdevice:')

        if $QRENCODE_INSTALLED; then
            echo "Scan this QR code with your phone:"
            qrencode -t UTF8 "$LINK_URI"
        else
            echo "Please copy the following link and paste it into the 'Add Device' screen on your phone:"
            echo -e "\n${C_BOLD}$LINK_URI${C_RESET}\n"
        fi
        
        echo -e "\n${C_GREEN}Success! Once linked, Oden is ready to be configured and run.${C_RESET}"
        ;;
    2)
        print_header "Registering New Number"
        echo "This process requires a phone number that can receive an SMS or a voice call."
        echo -e "${C_BOLD}WARNING:${C_RESET} Do NOT use your primary Signal number that is already active on your phone."
        echo "This will cause your phone app to be disconnected."
        echo
        
        read -p "Enter the new phone number (with country code, e.g., +14155552671): " PHONE_NUMBER
        if [ -z "$PHONE_NUMBER" ]; then
            echo -e "${C_RED}Error: Phone number cannot be empty.${C_RESET}"
            exit 1
        fi

        read -p "Receive verification code via (1) SMS or (2) Voice call? [1]: " VERIFY_METHOD
        VERIFY_FLAG=""
        if [[ "$VERIFY_METHOD" == "2" ]]; then
            VERIFY_FLAG="--voice"
            echo "Will request verification via voice call."
        else
            echo "Will request verification via SMS."
        fi
        
        echo "Attempting to register $PHONE_NUMBER..."
        REGISTER_OUTPUT=$($SIGNAL_CLI_EXEC -u "$PHONE_NUMBER" register $VERIFY_FLAG 2>&1)

        if [ $? -ne 0 ]; then
            CAPTCHA_URL=$(echo "$REGISTER_OUTPUT" | grep 'captcha:')
            if [[ -n "$CAPTCHA_URL" ]]; then
                echo -e "\n${C_RED}Registration requires a CAPTCHA to be solved.${C_RESET}"
                echo "1. Open this URL in your browser: ${C_BOLD}${CAPTCHA_URL}${C_RESET}"
                echo "2. Solve the puzzle."
                echo "3. You will get a token that starts with 'signal-captcha://'"
                read -p "4. Paste the entire 'signal-captcha://...' token here: " CAPTCHA_TOKEN
                
                if [ -z "$CAPTCHA_TOKEN" ]; then
                   echo -e "${C_RED}Error: CAPTCHA token cannot be empty.${C_RESET}"
                   exit 1
                fi

                echo "Re-attempting registration with CAPTCHA token..."
                REGISTER_OUTPUT=$($SIGNAL_CLI_EXEC -u "$PHONE_NUMBER" register $VERIFY_FLAG --captcha "$CAPTCHA_TOKEN" 2>&1)
                
                if [ $? -ne 0 ]; then
                    echo -e "\n${C_RED}Error: Registration failed again, even with CAPTCHA.${C_RESET}"
                    echo "--- signal-cli output ---"
                    echo "$REGISTER_OUTPUT"
                    echo "--------------------------"
                    exit 1
                fi
            else
                echo -e "\n${C_RED}Error: Registration failed.${C_RESET}"
                echo "--- signal-cli output ---"
                echo "$REGISTER_OUTPUT"
                echo "--------------------------"
                exit 1
            fi
        fi

        echo "Registration initiated. You should receive a verification code."
        read -p "Enter the verification code: " VERIFY_CODE

        if [ -z "$VERIFY_CODE" ]; then
            echo -e "${C_RED}Error: Verification code cannot be empty.${C_RESET}"
            exit 1
        fi
        
        echo "Verifying..."
        VERIFY_OUTPUT=$($SIGNAL_CLI_EXEC -u "$PHONE_NUMBER" verify "$VERIFY_CODE" 2>&1)
        
        if [ $? -ne 0 ]; then
            echo -e "\n${C_RED}Error: Verification failed.${C_RESET}"
            echo "Please double-check the code and try again."
            echo "--- signal-cli output ---"
            echo "$VERIFY_OUTPUT"
            echo "--------------------------"
            exit 1
        fi

        echo -e "\n${C_GREEN}Success! Number $PHONE_NUMBER is now registered and ready for use.${C_RESET}"
        ;;
    *)
        echo -e "\n${C_RED}Invalid choice. Please run the script again and select 1 or 2.${C_RESET}"
        exit 1
        ;;
esac

echo
echo "Setup is complete. Please see docs/HOW_TO_RUN.md for instructions on how to run the application."
echo
