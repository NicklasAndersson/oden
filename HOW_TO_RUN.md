# Oden S7 Watcher

Oden S7 Watcher is a utility that monitors a directory for new files and processes them based on your configuration.

## Installation and Setup

Follow these steps to get the application running.

### 1. Run the Installation Script (macOS)

If you are on macOS, the easiest way to get started is to use the interactive installation script.

1.  Open a terminal.
2.  Navigate to the directory where you unzipped the release file.
3.  Run the script:
    ```bash
    ./install_mac.sh
    ```
This script will check for dependencies (like Java) and guide you through connecting your Signal account.

### 2. Manual Setup (Windows)

Unfortunately, an automated installation script for Windows is not yet available. We apologize for the inconvenience. Windows users will need to set up `signal-cli` manually. Please refer to the official `signal-cli` documentation for instructions on how to either [register a new number](https://github.com/AsamK/signal-cli/wiki/Register-a-new-signal-account) or [link an existing device](https://github.com/AsamK/signal-cli/wiki/Link-a-second-device).

### 3. Edit `config.ini`

After setting up Signal, you need to configure Oden. In the same directory as the executable, you will find a file named `config.ini`. Edit the values in this file to match your setup. See the **Configuration** section below for details.

### 4. Run the Application

Once your setup and configuration are complete, you can run the application. See the **Running the Application** section below for instructions.

## Configuration (`config.ini`)

The application requires a `config.ini` file to be present in the same directory. This file contains the necessary settings for the application to function correctly.

### Template

Your `config.ini` should look like this:

```ini
[Vault]
path = ./vault

[Regex]
# Lista med regex som används för att automatiskt länka [[]] i markdown-filer
# Registreringsnummer (t.ex. ABC12D)
registration_number = [A-Z,a-z]{3}[0-9]{2}[A-Z,a-z,0-9]{1}

[Timezone]
# Tidszon för tidsstämplar (t.ex. Europe/Stockholm för Sverige)
timezone = Europe/Stockholm
```

### Settings Explained

- `[Vault]`
  - **path**: The full path to the root directory of your Obsidian vault.

- `[Regex]`
  - List of regex patterns used to automatically create `[[...]]` links in markdown files.
  - **registration_number**: Pattern for Swedish car registration numbers (e.g., ABC12D).
  - You can add more patterns by adding new lines with `pattern_name = regex_pattern`.

- `[Timezone]`
  - **timezone**: The timezone for timestamps. Use standard timezone names like `Europe/Stockholm` for Sweden, `Europe/London` for UK, etc.

## Running the Application

Once your executable is in place and `config.ini` is configured, you can run the application.

### On macOS or Linux

1. **Make the file executable:**

   ```bash
   chmod +x ./s7_watcher
   ```

2. **Run the watcher:**

   ```bash
   ./s7_watcher
   ```

### On Windows

Run the executable directly from the Command Prompt or PowerShell.

```powershell
.\s7_watcher.exe
```