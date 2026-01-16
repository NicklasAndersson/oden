# ==============================================================================
# Oden - Run Script for Windows
# ==============================================================================
# This script handles everything: installation, configuration, and running Oden.

# --- Colors ---
$C_RED = "Red"
$C_GREEN = "Green"
$C_BLUE = "Blue"
$C_YELLOW = "Yellow"

# --- Configuration ---
$SIGNAL_CLI_VERSION = "0.13.22"
$SIGNAL_CLI_DIR = ".\signal-cli-$SIGNAL_CLI_VERSION"
$CONFIG_FILE = ".\config.ini"
# Try OS-specific binary first, fall back to generic name
if (Test-Path ".\s7_watcher_windows.exe") {
    $EXECUTABLE = ".\s7_watcher_windows.exe"
} else {
    $EXECUTABLE = ".\s7_watcher.exe"
}

# --- Helper Functions ---
function Print-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "--- $Title ---" -ForegroundColor $C_BLUE
}

function Print-Success {
    param([string]$Message)
    Write-Host $Message -ForegroundColor $C_GREEN
}

function Print-Error {
    param([string]$Message)
    Write-Host $Message -ForegroundColor $C_RED
}

function Print-Warning {
    param([string]$Message)
    Write-Host $Message -ForegroundColor $C_YELLOW
}

# --- Banner ---
Write-Host "===========================================" -ForegroundColor $C_BLUE
Write-Host "              Oden S7 Watcher              " -ForegroundColor $C_BLUE
Write-Host "                (Windows)                  " -ForegroundColor $C_BLUE
Write-Host "===========================================" -ForegroundColor $C_BLUE
Write-Host ""

# =============================================================================
# STEP 1: Check Dependencies
# =============================================================================
Print-Header "Step 1: Checking Dependencies"

# Check for Java 21+
Write-Host "Checking for Java 21+... " -NoNewline
$javaPath = Get-Command java -ErrorAction SilentlyContinue
if (-not $javaPath) {
    Print-Error "Not found."
    Write-Host "Please install Java 21+ from: https://adoptium.net/temurin/releases/"
    Write-Host "After installation, restart this script."
    Read-Host "Press Enter to exit"
    exit 1
}

$javaVersionOutput = & "java" -version 2>&1
$javaVersionString = $javaVersionOutput | Select-String -Pattern "version"
$javaVersion = $javaVersionString -replace '.*version "(.*)\".*', '$1'
$javaMajorVersion = ($javaVersion.Split('.'))[0]

if ([int]$javaMajorVersion -lt 21) {
    Print-Error "Found version $javaVersion, but need 21+."
    Write-Host "Please install Java 21+ from: https://adoptium.net/"
    Read-Host "Press Enter to exit"
    exit 1
} else {
    Print-Success "OK (version $javaVersion)"
}

# =============================================================================
# STEP 2: Setup signal-cli
# =============================================================================
Print-Header "Step 2: Setting up signal-cli"

$signalCliPath = Get-Command signal-cli -ErrorAction SilentlyContinue
if ($signalCliPath) {
    $SIGNAL_CLI_EXEC = $signalCliPath.Source
    Print-Success "Found signal-cli in PATH: $SIGNAL_CLI_EXEC"
} elseif (Test-Path "$SIGNAL_CLI_DIR\bin\signal-cli.bat") {
    $SIGNAL_CLI_EXEC = "$SIGNAL_CLI_DIR\bin\signal-cli.bat"
    Print-Success "Found bundled signal-cli: $SIGNAL_CLI_EXEC"
} else {
    Print-Warning "signal-cli not found."
    $hasInstall = Read-Host "Do you have an existing signal-cli installation? (y/N)"
    
    if ($hasInstall -eq 'y') {
        $customPath = Read-Host "Enter full path to signal-cli.bat"
        if (Test-Path $customPath) {
            $SIGNAL_CLI_EXEC = $customPath
            Print-Success "Using: $SIGNAL_CLI_EXEC"
        } else {
            Print-Error "File not found. Exiting."
            exit 1
        }
    } else {
        Write-Host "Downloading signal-cli $SIGNAL_CLI_VERSION..."
        $downloadUrl = "https://github.com/AsamK/signal-cli/releases/download/v$SIGNAL_CLI_VERSION/signal-cli-$SIGNAL_CLI_VERSION.tar.gz"
        $tarFile = "signal-cli.tar.gz"
        
        try {
            Invoke-WebRequest -Uri $downloadUrl -OutFile $tarFile -UseBasicParsing
        } catch {
            Print-Error "Failed to download signal-cli."
            exit 1
        }
        
        Write-Host "Extracting..."
        tar -xzf $tarFile
        Remove-Item $tarFile
        $SIGNAL_CLI_EXEC = "$SIGNAL_CLI_DIR\bin\signal-cli.bat"
        Print-Success "signal-cli installed: $SIGNAL_CLI_EXEC"
    }
}

# =============================================================================
# STEP 3: Configure Signal Account
# =============================================================================
Print-Header "Step 3: Signal Account Configuration"

$existingAccountOutput = & $SIGNAL_CLI_EXEC listAccounts 2>$null
$SIGNAL_NUMBER = ""

if ($LASTEXITCODE -eq 0 -and $existingAccountOutput) {
    $SIGNAL_NUMBER = $existingAccountOutput | Select-String -Pattern "Number" | ForEach-Object { ($_ -split ' ')[1] }
    Print-Success "Found existing account: $SIGNAL_NUMBER"
    $keepAccount = Read-Host "Use this account? (Y/n)"
    if ($keepAccount -ne '' -and $keepAccount -ne 'y' -and $keepAccount -ne 'Y') {
        $SIGNAL_NUMBER = ""
    }
}

if ([string]::IsNullOrEmpty($SIGNAL_NUMBER)) {
    Write-Host "How do you want to set up Signal?"
    Write-Host "  1) Link to existing Signal account (Recommended)" -ForegroundColor $C_GREEN
    Write-Host "  2) Register a new number" -ForegroundColor $C_YELLOW
    $setupChoice = Read-Host "Choice (1 or 2)"

    switch ($setupChoice) {
        "1" {
            Print-Header "Linking Account"
            $deviceName = "Oden-$env:COMPUTERNAME"
            Write-Host "On your phone: Signal > Settings > Linked Devices > +"
            Read-Host "Press Enter to generate link..."
            
            $linkOutput = & $SIGNAL_CLI_EXEC link -n "$deviceName" 2>&1
            $linkUri = $linkOutput | Select-String 'tsdevice:'
            
            if (-not $linkUri) {
                Print-Error "Failed to generate link."
                Write-Host $linkOutput
                exit 1
            }
            
            Write-Host ""
            Write-Host "Copy this link and use it on your phone:" -ForegroundColor $C_GREEN
            Write-Host $linkUri
            Write-Host ""
            
            Write-Host "Waiting for link to complete..."
            Start-Sleep -Seconds 3
            $existingAccountOutput = & $SIGNAL_CLI_EXEC listAccounts 2>$null
            $SIGNAL_NUMBER = $existingAccountOutput | Select-String -Pattern "Number" | ForEach-Object { ($_ -split ' ')[1] }
            
            if ([string]::IsNullOrEmpty($SIGNAL_NUMBER)) {
                $SIGNAL_NUMBER = Read-Host "Enter your Signal phone number (e.g., +46701234567)"
            }
            Print-Success "Account linked!"
        }
        "2" {
            Print-Header "Registering New Number"
            Print-Warning "WARNING: Do NOT use your primary Signal number!"
            $SIGNAL_NUMBER = Read-Host "Enter phone number (e.g., +46701234567)"
            
            if ([string]::IsNullOrEmpty($SIGNAL_NUMBER)) {
                Print-Error "Phone number required."
                exit 1
            }
            
            $verifyMethod = Read-Host "Verification via (1) SMS or (2) Voice? [1]"
            $verifyFlag = ""
            if ($verifyMethod -eq "2") { $verifyFlag = "--voice" }
            
            $registerOutput = & $SIGNAL_CLI_EXEC -u "$SIGNAL_NUMBER" register $verifyFlag 2>&1
            
            if ($LASTEXITCODE -ne 0) {
                $captchaRequired = $registerOutput | Select-String -Pattern 'captcha' -CaseSensitive:$false
                if ($captchaRequired) {
                    Print-Warning "CAPTCHA required."
                    Write-Host "1. Open: https://signalcaptchas.org/registration/generate.html"
                    Write-Host "2. Solve the captcha"
                    Write-Host "3. Right-click 'Open Signal' and copy link"
                    $captchaToken = Read-Host "Paste signalcaptcha:// link"
                    
                    $registerOutput = & $SIGNAL_CLI_EXEC -u "$SIGNAL_NUMBER" register $verifyFlag --captcha "$captchaToken" 2>&1
                    if ($LASTEXITCODE -ne 0) {
                        Print-Error "Registration failed."
                        Write-Host $registerOutput
                        exit 1
                    }
                } else {
                    Print-Error "Registration failed."
                    Write-Host $registerOutput
                    exit 1
                }
            }
            
            $verifyCode = Read-Host "Enter verification code"
            & $SIGNAL_CLI_EXEC -u "$SIGNAL_NUMBER" verify "$verifyCode"
            
            if ($LASTEXITCODE -ne 0) {
                Print-Error "Verification failed."
                exit 1
            }
            Print-Success "Number registered!"
        }
        default {
            Print-Error "Invalid choice."
            exit 1
        }
    }
}

# =============================================================================
# STEP 4: Configure Oden (config.ini)
# =============================================================================
Print-Header "Step 4: Configuring Oden"

$needsConfig = $false
if (-not (Test-Path $CONFIG_FILE)) {
    $needsConfig = $true
} elseif (Select-String -Path $CONFIG_FILE -Pattern "YOUR_SIGNAL_NUMBER" -Quiet) {
    $needsConfig = $true
}

if ($needsConfig) {
    Write-Host "Setting up configuration..."
    
    # Get vault path
    Write-Host ""
    Write-Host "Where is your Obsidian vault?"
    $vaultPath = Read-Host "Vault path (default: .\vault)"
    if ([string]::IsNullOrEmpty($vaultPath)) { $vaultPath = ".\vault" }
    
    # Get timezone
    $currentTz = (Get-TimeZone).Id
    $timezone = Read-Host "Timezone (default: $currentTz)"
    if ([string]::IsNullOrEmpty($timezone)) { $timezone = $currentTz }
    
    # Convert signal-cli path to absolute
    $signalCliFullPath = (Resolve-Path $SIGNAL_CLI_EXEC -ErrorAction SilentlyContinue).Path
    if (-not $signalCliFullPath) { $signalCliFullPath = $SIGNAL_CLI_EXEC }
    
    # Create config.ini
    $configContent = @"
[Vault]
path = $vaultPath

[Signal]
number = $SIGNAL_NUMBER
signal_cli_path = $signalCliFullPath
log_file = signal-cli.log

[Regex]
registration_number = [A-Z,a-z]{3}[0-9]{2}[A-Z,a-z,0-9]{1}
phone_number = (\+46|0)[1-9][0-9]{7,8}
personal_number = [0-9]{6}[-]?[0-9]{4}

[Settings]
append_window_minutes = 30

[Timezone]
timezone = $timezone
"@
    
    $configContent | Out-File -FilePath $CONFIG_FILE -Encoding UTF8
    Print-Success "Configuration saved to $CONFIG_FILE"
} else {
    Print-Success "Configuration already exists."
    if (-not [string]::IsNullOrEmpty($SIGNAL_NUMBER)) {
        (Get-Content $CONFIG_FILE) -replace 'number = .*', "number = $SIGNAL_NUMBER" | Set-Content $CONFIG_FILE
    }
}

# =============================================================================
# STEP 5: Run Application
# =============================================================================
Print-Header "Step 5: Starting Oden"

# Try to run the binary if it exists
if (Test-Path $EXECUTABLE) {
    Write-Host ""
    Write-Host "=== Oden is starting ===" -ForegroundColor $C_GREEN
    Write-Host ""
    Write-Host "Press Ctrl+C to stop."
    Write-Host ""
    
    # Try to execute the binary
    try {
        & $EXECUTABLE
        $exitCode = $LASTEXITCODE
    }
    catch {
        $exitCode = 1
    }
    
    # If binary execution failed (and not user interrupt), fall back to Python
    # -1073741510 is the Windows exit code for Ctrl+C interrupt (0xC000013A)
    if ($exitCode -ne 0 -and $exitCode -ne -1073741510) {
        Print-Warning "Binary execution failed with exit code $exitCode"
        Print-Warning "Trying Python fallback..."
        
        # Check if Python is available
        $pythonCmd = $null
        if (Get-Command python -ErrorAction SilentlyContinue) {
            $pythonCmd = "python"
        }
        elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
            $pythonCmd = "python3"
        }
        
        if (-not $pythonCmd) {
            Print-Error "Python 3 is required but not found."
            Print-Error "Please install Python 3.10+ from https://www.python.org/"
            Read-Host "Press Enter to exit"
            exit 1
        }
        
        # Check if oden package exists
        if (-not (Test-Path ".\oden")) {
            Print-Error "Oden source code not found."
            Print-Error "This may be a binary-only release. Please report this issue."
            Read-Host "Press Enter to exit"
            exit 1
        }
        
        # Run using Python
        Write-Host ""
        Write-Host "=== Oden is starting (Python mode) ===" -ForegroundColor $C_GREEN
        Write-Host ""
        Write-Host "Press Ctrl+C to stop."
        Write-Host ""
        & $pythonCmd -m oden
    }
    exit $exitCode
}
else {
    # No binary found, try Python directly
    Print-Warning "Executable not found: $EXECUTABLE"
    Print-Warning "Trying to run from Python source..."
    
    # Check if Python is available
    $pythonCmd = $null
    if (Get-Command python -ErrorAction SilentlyContinue) {
        $pythonCmd = "python"
    }
    elseif (Get-Command python3 -ErrorAction SilentlyContinue) {
        $pythonCmd = "python3"
    }
    
    if (-not $pythonCmd) {
        Print-Error "Python 3 is required but not found."
        Print-Error "Please install Python 3.10+ from https://www.python.org/"
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    # Check if oden package exists
    if (-not (Test-Path ".\oden")) {
        Print-Error "Oden source code not found."
        Print-Error "Please make sure you have the complete Oden package."
        Read-Host "Press Enter to exit"
        exit 1
    }
    
    # Install dependencies if needed
    $importTest = & $pythonCmd -c "import oden" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Print-Warning "Installing Python dependencies..."
        & $pythonCmd -m pip install --quiet -e .
        if ($LASTEXITCODE -ne 0) {
            Print-Error "Failed to install dependencies."
            Read-Host "Press Enter to exit"
            exit 1
        }
    }
    
    # Run using Python
    Write-Host ""
    Write-Host "=== Oden is starting (Python mode) ===" -ForegroundColor $C_GREEN
    Write-Host ""
    Write-Host "Press Ctrl+C to stop."
    Write-Host ""
    & $pythonCmd -m oden
}
