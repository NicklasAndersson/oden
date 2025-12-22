# Oden S7 Watcher

Oden S7 Watcher is a utility that monitors a directory for new files and processes them based on your configuration.

## Getting Started

Follow these three steps to get the application running:

1.  **Download the Correct Executable**
    - From the latest release, download the `s7_watcher-release.zip` file.
    - Unzip the file. You will find executables for macOS, and Windows. Use the one that matches your operating system.

2.  **Create `config.ini`**
    - In the same directory where you placed the executable, create a new file named `config.ini`.
    - Copy the content from the **Configuration** section below into this file and modify the values to match your setup.

3.  **Run the Application**
    - Open a terminal (or Command Prompt on Windows) and navigate to the directory.
    - Follow the instructions in the **Running the Application** section below.

## Configuration (`config.ini`)

The application requires a `config.ini` file to be present in the same directory. This file contains the necessary settings for the application to function correctly.

### Template

Copy and paste the following template into your `config.ini` file:

```ini
[Vault]
Path = /path/to/your/vault/
Inbox = /path/to/your/inbox/

[Signal]
Number = +1234567890
```

### Settings Explained

-   `[Vault]`
    -   **Path**: The full path to the root directory of your Obsidian vault.
    -   **Inbox**: The specific sub-directory within your vault that the watcher should monitor for new files.
-   `[Signal]`
    -   **Number**: The international phone number to be used for sending notifications via Signal.

## Running the Application

Once your executable is in place and `config.ini` is configured, you can run the application.

### On macOS or Linux

1.  **Make the file executable:** Before running it for the first time, you must give it execute permissions.
    ```bash
    chmod +x ./s7_watcher
    ```

2.  **Run the watcher:**
    ```bash
    ./s7_watcher
    ```

### On Windows

Run the executable directly from the Command Prompt or PowerShell.

```powershell
.\s7_watcher.exe
```