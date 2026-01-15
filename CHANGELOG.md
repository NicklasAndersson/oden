# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
