# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-01-16

### Added
- **Groups panel in Web GUI**: View all groups the account is a member of
- **Ignore groups from GUI**: Toggle ignore status for groups directly from the web interface
- **Config editor in Web GUI**: Edit config.ini directly in the browser with syntax validation
- **Restart warning**: Shows warning banner when config changes require restart

### Changed
- Run scripts now update `signal_cli_path` in existing config.ini when user specifies a custom path

## [0.6.1] - 2026-01-16

### Fixed
- **Regex patterns**: Use RawConfigParser to avoid interpolation issues with regex patterns in config.ini
- **macOS Gatekeeper**: Automatically remove quarantine attribute from binary before execution
- **Run scripts**: Read `signal_cli_path` from existing config.ini before prompting for installation

### Changed
- **Default display_name**: Run scripts now set `display_name = oden` by default

## [0.6.0] - 2026-01-16

### Added
- **Web GUI**: Built-in web interface at `http://127.0.0.1:8080`
  - View current configuration
  - Live log viewer (polls every 3 seconds)
  - Join groups via invitation link
  - View and accept/decline pending group invitations
- **Web configuration options** in `config.ini`:
  - `enabled`: Enable/disable web GUI (default: true)
  - `port`: Port to listen on (default: 8080)
  - `access_log`: File for HTTP request logging (separates from main log)

### Changed
- Logging refactored to support both console and in-memory buffer for web GUI
- Connection errors now re-raise instead of calling sys.exit()

## [0.5.1] - 2026-01-16

### Added
- **Configurable startup message**: New `startup_message` setting with options:
  - `self` (default): Send startup message to yourself only
  - `all`: Send startup message to all non-ignored groups
  - `off`: Disable startup message entirely

## [0.5.0] - 2026-01-16

### Added
- **Startup notifications**: Sends a message to yourself when Oden starts, including version and timestamp
- **Group logging**: Logs all groups the account is member of at startup, indicating which are ignored
- **Complete default config**: Run scripts now generate config.ini with all options (commented where optional)
- **Dynamic versioning**: Version is now injected from git tag during CI build

## [0.4.1] - 2026-01-16

### Added / Fixed
- Add Python fallback for incompatible binaries and fix CI artifact overwrite
- Update README and HOW_TO_RUN for new run scripts
- Use echo -e for ANSI escape codes in captcha instructions

See full commit history for more details.

## [0.4.0] - 2026-01-15

### Changed
- **Unified run scripts**: Renamed `install_*` to `run_*` scripts that handle everything:
  - Dependency installation (Java 21+, qrencode)
  - signal-cli download and setup
  - Signal account linking/registration
  - Automatic config.ini generation based on user input
  - Application startup
- **Simplified documentation**: HOW_TO_RUN.md now just says "run the script"

### Removed
- Old install_mac.sh, install_linux.sh, install_windows.ps1 (replaced by run_* scripts)

## [0.3.2] - 2026-01-15

### Fixed
- **Captcha handling**: Fixed detection of captcha requirement during Signal registration
- Clearer instructions with correct URL for solving captcha

## [0.3.1] - 2026-01-15

### Fixed
- **Java 21 requirement**: signal-cli 0.13.x requires Java 21, not 17. Updated all installers.
- **Windows installer**: Added auto-download of signal-cli (same as macOS/Linux)

## [0.3.0] - 2026-01-15

### Added
- **Auto-download signal-cli**: Installation scripts now automatically download signal-cli if not found
  - Asks user if they have an existing installation
  - If no, downloads signal-cli 0.13.22 from GitHub automatically
  - Works on both macOS and Linux

### Fixed
- Linux installer now executable by default
- Simplified installation flow for new users

## [0.2.0] - 2026-01-15

### Added
- **Linux/Ubuntu support**: New `install_linux.sh` installation script for Debian-based distributions
  - Uses `apt` for dependency installation (openjdk-17-jdk, qrencode)
  - Same Signal linking workflow as macOS/Windows scripts
- **CI/CD**: Added `ubuntu-latest` to GitHub Actions release build matrix

### Changed
- **Documentation**: Updated HOW_TO_RUN.md with Linux installation instructions

## [0.1.0] - 2026-01-11

### Added
- **Windows support**: New `install_windows.ps1` installation script for PowerShell
- **Code quality tooling**: Ruff linting/formatting, pre-commit hooks, pytest with coverage
- **Type checking**: mypy configuration and `py.typed` marker (PEP 561)
- **Security**: Dependabot for automated dependency updates
- **License**: MIT LICENSE file

### Changed
- **Project structure**: Reorganized to follow Python packaging standards
  - Source code moved to `oden/` package
  - Tests moved to `tests/` directory
  - Installation scripts moved to `scripts/` directory
- **CI/CD**: Updated GitHub Actions to v4/v5, replaced deprecated `create-release` action
- **Documentation**: Updated README with development instructions, pytest/ruff commands

### Fixed
- Logger names in tests to match new package structure
- Various lint errors and code formatting inconsistencies

## [0.0.4] - 2025-12-XX

### Added
- Initial release with Signal-to-Obsidian message processing
- macOS installation script
- Message append functionality (reply and `++` commands)
- Attachment handling
- Regex-based link formatting
