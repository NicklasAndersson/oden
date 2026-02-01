# ==============================================================================
# Oden - Run Script for Windows
# ==============================================================================
# This script installs dependencies and launches Oden.
# All configuration is done through the web-based setup wizard.

# Set UTF-8 encoding for proper Swedish character display
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# --- Colors ---
$C_RED = "Red"
$C_GREEN = "Green"
$C_BLUE = "Blue"
$C_YELLOW = "Yellow"
$C_WHITE = "White"

# --- Configuration ---
$SIGNAL_CLI_VERSION = "0.13.23"
$ODEN_CONFIG_DIR = "$env:USERPROFILE\.oden"

# --- Helper Functions ---
function Print-Header {
    param([string]$Title)
    Write-Host ""
    Write-Host "--- $Title ---" -ForegroundColor $C_BLUE
}

function Print-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor $C_GREEN
}

function Print-Error {
    param([string]$Message)
    Write-Host "[X] $Message" -ForegroundColor $C_RED
}

function Print-Warning {
    param([string]$Message)
    Write-Host "[!] $Message" -ForegroundColor $C_YELLOW
}

function Print-Info {
    param([string]$Message)
    Write-Host "[i] $Message" -ForegroundColor $C_BLUE
}

# --- Banner ---
Write-Host "===========================================" -ForegroundColor $C_BLUE
Write-Host "              Oden S7 Watcher              " -ForegroundColor $C_BLUE
Write-Host "                (Windows)                  " -ForegroundColor $C_BLUE
Write-Host "===========================================" -ForegroundColor $C_BLUE
Write-Host ""

# --- Find script directory ---
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

# Check for executable
$EXECUTABLE = $null
if (Test-Path "$SCRIPT_DIR\oden_windows.exe") {
    $EXECUTABLE = "$SCRIPT_DIR\oden_windows.exe"
}

# =============================================================================
# STEP 1: Check Dependencies
# =============================================================================
Print-Header "Steg 1: Kontrollerar beroenden"

# Check for Java 21+
Write-Host "Kontrollerar Java 21+... " -NoNewline
$javaPath = Get-Command java -ErrorAction SilentlyContinue
if (-not $javaPath) {
    Print-Error "Inte installerat."
    Write-Host ""
    Write-Host "Java 21+ kravs. Ladda ner fran:" -ForegroundColor $C_YELLOW
    Write-Host "https://adoptium.net/temurin/releases/" -ForegroundColor $C_WHITE
    Write-Host ""
    Write-Host "Valj 'Windows x64' och 'JDK 21' eller nyare."
    Read-Host "Tryck Enter for att avsluta"
    exit 1
}

$javaVersionOutput = & "java" -version 2>&1
$javaVersionString = $javaVersionOutput | Select-String -Pattern "version"
if ($javaVersionString -match '"([^"]+)"') {
    $javaVersion = $matches[1]
    $javaMajorVersion = ($javaVersion.Split('.'))[0]
    
    if ([int]$javaMajorVersion -lt 21) {
        Print-Error "Hittade version $javaVersion, men behover 21+."
        Write-Host "Ladda ner fran: https://adoptium.net/temurin/releases/"
        Read-Host "Tryck Enter for att avsluta"
        exit 1
    } else {
        Print-Success "Java $javaVersion"
    }
} else {
    Print-Warning "Kunde inte avgora Java-version, fortsatter..."
}

# =============================================================================
# STEP 2: Setup signal-cli
# =============================================================================
Print-Header "Steg 2: Kontrollerar signal-cli"

$SIGNAL_CLI_EXEC = $null

# 1. Check if bundled with release
if (Test-Path "$SCRIPT_DIR\signal-cli\bin\signal-cli.bat") {
    $SIGNAL_CLI_EXEC = "$SCRIPT_DIR\signal-cli\bin\signal-cli.bat"
    Print-Success "Anvander medfoljande signal-cli"
}
# 2. Check in PATH
elseif (Get-Command signal-cli -ErrorAction SilentlyContinue) {
    $SIGNAL_CLI_EXEC = (Get-Command signal-cli).Source
    Print-Success "Hittade signal-cli i PATH: $SIGNAL_CLI_EXEC"
}
# 3. Check standard locations
elseif (Test-Path "$env:LOCALAPPDATA\signal-cli\bin\signal-cli.bat") {
    $SIGNAL_CLI_EXEC = "$env:LOCALAPPDATA\signal-cli\bin\signal-cli.bat"
    Print-Success "Hittade signal-cli: $SIGNAL_CLI_EXEC"
}
else {
    Print-Warning "signal-cli hittades inte."
    Write-Host ""
    $downloadChoice = Read-Host "Ladda ner signal-cli $SIGNAL_CLI_VERSION automatiskt? (J/n)"
    
    if ([string]::IsNullOrEmpty($downloadChoice) -or $downloadChoice -match '^[JjYy]$') {
        Write-Host "Laddar ner signal-cli..."
        $downloadUrl = "https://github.com/AsamK/signal-cli/releases/download/v$SIGNAL_CLI_VERSION/signal-cli-$SIGNAL_CLI_VERSION.tar.gz"
        $installDir = "$env:LOCALAPPDATA\signal-cli-$SIGNAL_CLI_VERSION"
        $tarFile = "$env:TEMP\signal-cli.tar.gz"
        
        try {
            # Download
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $downloadUrl -OutFile $tarFile -UseBasicParsing
            
            # Extract
            Write-Host "Extraherar..."
            if (-not (Test-Path $env:LOCALAPPDATA)) {
                New-Item -ItemType Directory -Path $env:LOCALAPPDATA | Out-Null
            }
            
            Push-Location $env:LOCALAPPDATA
            tar -xzf $tarFile
            Pop-Location
            
            Remove-Item $tarFile -ErrorAction SilentlyContinue
            
            $SIGNAL_CLI_EXEC = "$installDir\bin\signal-cli.bat"
            Print-Success "signal-cli installerat: $SIGNAL_CLI_EXEC"
        }
        catch {
            Print-Error "Nedladdning misslyckades: $_"
            Read-Host "Tryck Enter for att avsluta"
            exit 1
        }
    }
    else {
        Print-Error "signal-cli kravs for att fortsatta."
        Read-Host "Tryck Enter for att avsluta"
        exit 1
    }
}

# Verify signal-cli works
Write-Host "Verifierar signal-cli... " -NoNewline
try {
    $cliVersion = & $SIGNAL_CLI_EXEC --version 2>&1 | Select-Object -First 1
    Print-Success "$cliVersion"
}
catch {
    Print-Error "signal-cli kunde inte koras."
    exit 1
}

# =============================================================================
# STEP 3: Create config directory
# =============================================================================
Print-Header "Steg 3: Förbereder konfiguration"

if (-not (Test-Path $ODEN_CONFIG_DIR)) {
    New-Item -ItemType Directory -Path $ODEN_CONFIG_DIR | Out-Null
}
Print-Success "Konfigurationskatalog: $ODEN_CONFIG_DIR"

# Write signal-cli path for the app to find
$SIGNAL_CLI_EXEC | Out-File -FilePath "$ODEN_CONFIG_DIR\.signal_cli_path" -Encoding UTF8 -NoNewline

# =============================================================================
# Python Fallback Function
# =============================================================================
function Run-PythonFallback {
    Print-Warning "Försöker med Python-fallback..."
    
    $PYTHON_CMD = $null
    
    # Try python first, then python3, then py -3
    $pythonCandidates = @("python", "python3")
    foreach ($candidate in $pythonCandidates) {
        $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $versionOutput = & $candidate -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
                if ($versionOutput -match "^(\d+)\.(\d+)$") {
                    $major = [int]$matches[1]
                    $minor = [int]$matches[2]
                    if ($major -ge 3 -and $minor -ge 10) {
                        $PYTHON_CMD = $candidate
                        Print-Success "Python $versionOutput"
                        break
                    }
                }
            } catch { }
        }
    }
    
    # Try py launcher
    if (-not $PYTHON_CMD) {
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCmd) {
            try {
                $versionOutput = & py -3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
                if ($versionOutput -match "^(\d+)\.(\d+)$") {
                    $major = [int]$matches[1]
                    $minor = [int]$matches[2]
                    if ($major -ge 3 -and $minor -ge 10) {
                        $PYTHON_CMD = "py"
                        Print-Success "Python $versionOutput (via py launcher)"
                    }
                }
            } catch { }
        }
    }
    
    if (-not $PYTHON_CMD) {
        Print-Error "Python 3.10+ krävs men hittades inte."
        Print-Info "Ladda ner från: https://www.python.org/downloads/"
        Read-Host "Tryck Enter för att avsluta"
        exit 1
    }
    
    # Check if oden package exists
    if (-not (Test-Path "$SCRIPT_DIR\oden")) {
        Print-Error "Oden-källkod hittades inte."
        Print-Error "Detta kan vara en binär-only release. Rapportera detta problem."
        Read-Host "Tryck Enter för att avsluta"
        exit 1
    }
    
    Push-Location $SCRIPT_DIR
    
    # Create virtual environment if needed
    $VENV_DIR = "$SCRIPT_DIR\.venv"
    if (-not (Test-Path $VENV_DIR)) {
        Print-Warning "Skapar Python virtuell miljö..."
        if ($PYTHON_CMD -eq "py") {
            & py -3 -m venv $VENV_DIR
        } else {
            & $PYTHON_CMD -m venv $VENV_DIR
        }
        if ($LASTEXITCODE -ne 0) {
            Print-Error "Kunde inte skapa virtuell miljö."
            Pop-Location
            Read-Host "Tryck Enter för att avsluta"
            exit 1
        }
    }
    
    # Use the venv Python
    $VENV_PYTHON = "$VENV_DIR\Scripts\python.exe"
    
    # Install dependencies
    Print-Warning "Installerar Python-beroenden..."
    & $VENV_PYTHON -m pip install -e . 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Print-Error "Kunde inte installera beroenden."
        Pop-Location
        Read-Host "Tryck Enter för att avsluta"
        exit 1
    }
    
    # Run using Python
    Write-Host ""
    Write-Host "=== Oden startar (Python-läge) ===" -ForegroundColor $C_GREEN
    Write-Host "Webb-GUI: http://127.0.0.1:8080"
    Write-Host ""
    Write-Host "Tryck Ctrl+C för att avsluta" -ForegroundColor $C_YELLOW
    Write-Host ""
    
    & $VENV_PYTHON -m oden
    Pop-Location
}

# =============================================================================
# STEP 4: Launch Oden
# =============================================================================
Print-Header "Steg 4: Startar Oden"

# Set environment variable for signal-cli path
$env:SIGNAL_CLI_PATH = $SIGNAL_CLI_EXEC

if ($EXECUTABLE -and (Test-Path $EXECUTABLE)) {
    if (-not (Test-Path "$ODEN_CONFIG_DIR\config.ini")) {
        Print-Info "Första körningen - setup wizard kommer att öppnas i webbläsaren."
        Write-Host ""
    }
    
    Write-Host "Startar Oden..."
    Write-Host "Webb-GUI: http://127.0.0.1:8080"
    Write-Host ""
    Write-Host "Tryck Ctrl+C för att avsluta" -ForegroundColor $C_YELLOW
    Write-Host ""
    
    # Run the executable
    & $EXECUTABLE
    $EXIT_CODE = $LASTEXITCODE
    
    # If binary failed, fall back to Python
    if ($EXIT_CODE -ne 0) {
        Print-Warning "Binär körning misslyckades med kod $EXIT_CODE"
        Run-PythonFallback
    }
} else {
    # No binary found, try Python directly
    Print-Warning "Körbar fil hittades inte: oden_windows.exe"
    Run-PythonFallback
}
