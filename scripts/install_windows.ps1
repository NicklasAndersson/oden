# ==============================================================================
# Oden Installation Script for Windows
# ==============================================================================
# --- Colors for output ---
$C_RESET = $Host.UI.RawUI.ForegroundColor
$C_RED = "Red"
$C_GREEN = "Green"
$C_BLUE = "Blue"
$C_BOLD = "" # PowerShell doesn't have a simple equivalent for bold in the same way.
$C_YELLOW = "Yellow"

# --- Helper Functions ---
function Print-Header {
    param(
        [string]$Title
    )
    Write-Host ""
    Write-Host "--- $Title ---" -ForegroundColor $C_BLUE
}

# --- Banner ---
Write-Host "-------------------------------------------" -ForegroundColor $C_BLUE
Write-Host "--- Oden Signal Integration Installer ---" -ForegroundColor $C_BLUE
Write-Host "-------------------------------------------" -ForegroundColor $C_BLUE
Write-Host ""
Write-Host "This script will guide you through setting up signal-cli to work with Oden."
Write-Host "It will check for dependencies, help you install them, and then configure your Signal account."

# --- Dependency Check ---
Print-Header "Step 1: Checking Dependencies"

# 1. Check for Java
function Check-Java {
    Write-Host "Checking for Java 17+... " -NoNewline
    $javaPath = Get-Command java -ErrorAction SilentlyContinue
    if (-not $javaPath) {
        Write-Host "Not found." -ForegroundColor $C_RED
        Write-Host "Java is required. Please download and install Java 17+ (Temurin) from:"
        Write-Host "https://adoptium.net/temurin/releases/"
        Write-Host "After installation, please re-run this script."
        exit 1
    }

    $javaVersionOutput = & "java" -version 2>&1
    $javaVersionString = $javaVersionOutput | Select-String -Pattern "version"
    $javaVersion = $javaVersionString -replace '.*version "(.*)".*', '$1'
    $javaMajorVersion = ($javaVersion.Split('.'))[0]

    if ([int]$javaMajorVersion -lt 17) {
        Write-Host "Found version $javaVersion, but need 17+." -ForegroundColor $C_RED
        Write-Host "Error: Your Java version is too old. signal-cli requires Java 17 or higher."
        Write-Host "Please update or install a newer version from https://adoptium.net/"
        exit 1
    } else {
        Write-Host "OK (found version $javaVersion)." -ForegroundColor $C_GREEN
    }
}
Check-Java # Initial call to the java check function

# --- Setup: Find signal-cli ---
Print-Header "Locating signal-cli"

$signalCliPath = Get-Command signal-cli -ErrorAction SilentlyContinue
if ($signalCliPath) {
    $SIGNAL_CLI_EXEC = $signalCliPath.Source
    Write-Host "Found signal-cli in your PATH at: $SIGNAL_CLI_EXEC" -ForegroundColor $C_GREEN
} elseif (Test-Path ".\signal-cli-0.13.22\bin\signal-cli.bat") {
    $SIGNAL_CLI_EXEC = ".\signal-cli-0.13.22\bin\signal-cli.bat"
    Write-Host "Found bundled signal-cli at: $SIGNAL_CLI_EXEC" -ForegroundColor $C_GREEN
} else {
    Write-Host "Could not automatically find signal-cli." -ForegroundColor $C_YELLOW
    $useCustomPath = Read-Host "Do you have another installation of signal-cli you would like to use? (y/N)"
    if ($useCustomPath -eq 'y') {
        $customPath = Read-Host "Please enter the full path to your signal-cli executable (signal-cli.bat or signal-cli.exe)"
        if (Test-Path $customPath) {
            $SIGNAL_CLI_EXEC = $customPath
            Write-Host "Using signal-cli at: $SIGNAL_CLI_EXEC" -ForegroundColor $C_GREEN
        } else {
            Write-Host "Error: File not found at '$customPath'. Exiting." -ForegroundColor $C_RED
            exit 1
        }
    } else {
        Write-Host "Error: signal-cli executable not found. Exiting." -ForegroundColor $C_RED
        exit 1
    }
}

# --- Check for existing setup ---
Print-Header "Step 2: Checking for Existing Signal Setup"
Write-Host "Checking if an account is already configured..."

$existingAccountOutput = & $SIGNAL_CLI_EXEC listAccounts 2>$null
if ($LASTEXITCODE -eq 0 -and $existingAccountOutput) {
    $accountId = $existingAccountOutput | Select-String -Pattern "Number" | ForEach-Object { ($_ -split ' ')[1] }
    Write-Host "Found existing configured account: $accountId" -ForegroundColor $C_GREEN
    $keepAccount = Read-Host "Do you want to keep using this account? (Y/n)"
    if ($keepAccount -eq '' -or $keepAccount -eq 'y') {
        Write-Host ""
        Write-Host "Great! Your existing Signal setup is ready to use." -ForegroundColor $C_GREEN
        Write-Host "Setup is complete. Please see docs/HOW_TO_RUN.md for instructions on how to run the application."
        exit 0
    } else {
        Write-Host "Proceeding with re-configuration..."
    }
} else {
    Write-Host "No existing account found. Proceeding with first-time setup."
}

# --- Main Menu ---
Print-Header "Step 3: Choose Setup Method"
Write-Host "How do you want to set up Signal?"
Write-Host "  1) Link to an existing Signal account (Recommended)" -ForegroundColor $C_GREEN
Write-Host "     Links this app as a new device to your primary Signal account on your phone."
Write-Host "  2) Register a completely new number" -ForegroundColor $C_RED
Write-Host "     This requires a separate phone number that is NOT already used for Signal."
Write-Host ""

$choice = Read-Host "Enter your choice (1 or 2)"

switch ($choice) {
    "1" {
        Print-Header "Linking Existing Account"
        $deviceName = "Oden-Watcher-" + $env:COMPUTERNAME
        Write-Host "I will now generate a link to add a new device named '$deviceName'."
        Write-Host "On your phone, open Signal and go to: Settings > Linked Devices > '+'"
        Read-Host "Press [Enter] to generate the link..."

        $linkUriOutput = & $SIGNAL_CLI_EXEC link -n "$deviceName" 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "Error: signal-cli failed to generate a link." -ForegroundColor $C_RED
            Write-Host "--- signal-cli output ---"
            Write-Host $linkUriOutput
            Write-Host "--------------------------"
            exit 1
        }
        
        $linkUri = $linkUriOutput | Select-String 'tsdevice:'
        
        Write-Host "Please copy the following link and paste it into the 'Add Device' screen on your phone:"
        Write-Host ""
        Write-Host $linkUri -ForegroundColor $C_GREEN
        Write-Host ""
        
        Write-Host "Success! Once linked, Oden is ready to be configured and run." -ForegroundColor $C_GREEN
    }
    "2" {
        Print-Header "Registering New Number"
        Write-Host "This process requires a phone number that can receive an SMS or a voice call."
        Write-Host "WARNING: Do NOT use your primary Signal number that is already active on your phone." -ForegroundColor $C_YELLOW
        Write-Host "This will cause your phone app to be disconnected."
        Write-Host ""
        
        $phoneNumber = Read-Host "Enter the new phone number (with country code, e.g., +14155552671)"
        if ([string]::IsNullOrEmpty($phoneNumber)) {
            Write-Host "Error: Phone number cannot be empty." -ForegroundColor $C_RED
            exit 1
        }

        $verifyMethod = Read-Host "Receive verification code via (1) SMS or (2) Voice call? [1]"
        $verifyFlag = ""
        if ($verifyMethod -eq "2") {
            $verifyFlag = "--voice"
            Write-Host "Will request verification via voice call."
        } else {
            Write-Host "Will request verification via SMS."
        }
        
        Write-Host "Attempting to register $phoneNumber..."
        $registerOutput = & $SIGNAL_CLI_EXEC -u "$phoneNumber" register $verifyFlag 2>&1

        if ($LASTEXITCODE -ne 0) {
            $captchaUrl = $registerOutput | Select-String 'captcha:'
            if ($captchaUrl) {
                Write-Host ""
                Write-Host "Registration requires a CAPTCHA to be solved." -ForegroundColor $C_RED
                Write-Host "1. Open this URL in your browser: $($captchaUrl -replace 'captcha:','')"
                Write-Host "2. Solve the puzzle."
                Write-Host "3. You will get a token that starts with 'signal-captcha://'"
                $captchaToken = Read-Host "4. Paste the entire 'signal-captcha://...' token here"
                
                if ([string]::IsNullOrEmpty($captchaToken)) {
                   Write-Host "Error: CAPTCHA token cannot be empty." -ForegroundColor $C_RED
                   exit 1
                }

                Write-Host "Re-attempting registration with CAPTCHA token..."
                $registerOutput = & $SIGNAL_CLI_EXEC -u "$phoneNumber" register $verifyFlag --captcha "$captchaToken" 2>&1
                
                if ($LASTEXITCODE -ne 0) {
                    Write-Host ""
                    Write-Host "Error: Registration failed again, even with CAPTCHA." -ForegroundColor $C_RED
                    Write-Host "--- signal-cli output ---"
                    Write-Host $registerOutput
                    Write-Host "--------------------------"
                    exit 1
                }
            } else {
                Write-Host ""
                Write-Host "Error: Registration failed." -ForegroundColor $C_RED
                Write-Host "--- signal-cli output ---"
                Write-Host $registerOutput
                Write-Host "--------------------------"
                exit 1
            }
        }

        Write-Host "Registration initiated. You should receive a verification code."
        $verifyCode = Read-Host "Enter the verification code"

        if ([string]::IsNullOrEmpty($verifyCode)) {
            Write-Host "Error: Verification code cannot be empty." -ForegroundColor $C_RED
            exit 1
        }
        
        Write-Host "Verifying..."
        $verifyOutput = & $SIGNAL_CLI_EXEC -u "$phoneNumber" verify "$verifyCode" 2>&1
        
        if ($LASTEXITCODE -ne 0) {
            Write-Host ""
            Write-Host "Error: Verification failed." -ForegroundColor $C_RED
            Write-Host "Please double-check the code and try again."
            Write-Host "--- signal-cli output ---"
            Write-Host $verifyOutput
            Write-Host "--------------------------"
            exit 1
        }

        Write-Host ""
        Write-Host "Success! Number $phoneNumber is now registered and ready for use." -ForegroundColor $C_GREEN
    }
    default {
        Write-Host ""
        Write-Host "Invalid choice. Please run the script again and select 1 or 2." -ForegroundColor $C_RED
        exit 1
    }
}

Write-Host ""
Write-Host "Setup is complete. Please see docs/HOW_TO_RUN.md for instructions on how to run the application."
Write-Host ""
