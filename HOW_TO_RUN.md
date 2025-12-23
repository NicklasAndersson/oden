# Oden S7 Watcher

Oden S7 Watcher is a utility that monitors a directory for new files and processes them based on your configuration.

## Getting Started

Follow these three steps to get the application running:

1. **Download the Correct Executable**
   - From the latest release, download the `s7_watcher-release.zip` file.
   - Unzip the file. You will find executables for macOS and Windows. Use the one that matches your operating system.

2. **Edit `config.ini`**
   - In the same directory as the executable, you will find a file named `config.ini` (included in the release package).
   - Edit the values in this file to match your setup. See the **Configuration** section below for details.

3. **Run the Application**
   - Open a terminal (or Command Prompt on Windows) and navigate to the directory.
   - Follow the instructions in the **Running the Application** section below.

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