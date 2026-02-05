# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.13.0] - 2026-02-05

### Added

- **Jinja2 report templates**: Rapporter formateras nu med anpassningsbara Jinja2-mallar
  - `templates/report.md.j2` för nya rapporter
  - `templates/append.md.j2` för append-läge (++ och svar)
  - Stöd för villkorliga block (`{% if %}`) för valfritt innehåll (position, citat, bilagor)
  - Ny modul `template_loader.py` för att ladda och rendera mallar
  - Dokumentation i `docs/REPORT_TEMPLATE.md` med alla placeholders

## [0.12.4] - 2026-01-28

### Fixed

- **Komplett live reload**: Utökade live reload till att även inkludera `formatting.py` och `link_formatter.py` så att "Spara och applicera"-knappen fungerar för alla inställningar

## [0.12.3] - 2026-01-28

### Fixed

- **Live reload av config**: Ändrade modulimporter så att config-ändringar via GUI (Ignorera/Whitelist-knappar) appliceras direkt utan omstart
- **macOS JRE-sökväg**: Fixade så att bundled Java alltid hittas på macOS (använder jre-x64 via Rosetta på Apple Silicon)
- **CONFIG_FILE-sökväg**: Korrigerade sökvägen till config.ini i web handlers (från relativ till ~/.oden/config.ini)

## [0.12.0] - 2026-01-28

### Added

- **Whitelist-knapp i GUI**: Ny knapp bredvid "Ignorera" för att enkelt lägga till/ta bort grupper från whitelist direkt i grupplistan
- **Filnamnsformat i inställningar**: Dropdown i GUI för att välja filnamnsformat (Classic/TNR/TNR-namn)

### Fixed

- **Bevarar kommentarer i config.ini**: När man klickar på Ignorera/Whitelist-knapparna bevaras nu alla kommentarer i konfigurationsfilen (tidigare försvann de)
- **Windows-build**: Lagt till `tzdata` som dependency och robust fallback för tidszonshantering under PyInstaller-build

## [0.11.1] - 2026-01-28

### Changed

- **Code refactoring**: Stora filer uppdelade i mindre, mer hanterbara moduler
  - `web_server.py` reducerad från 2556 → 187 rader (93% minskning)
  - Ny modul `web_templates.py` för HTML-mallar
  - Nytt paket `web_handlers/` med `config_handlers.py`, `group_handlers.py`, `setup_handlers.py`
  - Ny modul `bundle_utils.py` för gemensamma PyInstaller bundle-funktioner
  - Eliminerad kodduplikation av `get_bundle_path()` mellan config.py och signal_manager.py

## [0.11.0] - 2026-01-28

### Added

- **Whitelist Groups**: Ny konfiguration för att endast tillåta specifika grupper
  - Om whitelist är satt ignoreras alla andra grupper (har prioritet över ignore-listan)
  - Konfigurerbar via `config.ini` (`whitelist_groups`) eller webbgränssnittet
  - Grön toggle-knapp i grupplistan för att lägga till/ta bort grupper från whitelist

- **Flexibla filnamnsformat**: Stöd för olika filnamnsformat via `filename_format` i config
  - `classic` (default): `DDHHMM-telefon-namn.md` (t.ex. `261427-46762320406-Nicklas.md`)
  - `tnr`: `TNR.md` (t.ex. `261427.md`, `261427-1.md` vid duplikat)
  - `tnr-name`: `TNR-namn.md` (t.ex. `261427-Nicklas.md`)
  - Automatisk duplikathantering med `-1`, `-2` suffix
  - Fileid i frontmatter för konsekvent identifiering oavsett format

## [0.10.0] - 2026-01-28

### Added

- **Shutdown button**: Stäng av Oden direkt från webbgränssnittet

## [0.9.3] - 2026-01-28

### Fixed

- **Lint fixes**: Code formatting cleanup

## [0.9.2] - 2026-01-28

### Changed

- **New App Icon**: Updated to official Oden logo (raven with compass)
- **macOS Build**: Now builds x86_64 via Rosetta on Apple Silicon runners
  - Works natively on Intel Macs
  - Works via Rosetta 2 on Apple Silicon Macs

## [0.9.1] - 2026-01-28

### Fixed

- **Intel Mac Support**: App now builds as universal binary (arm64 + x86_64)
  - Previously only worked on Apple Silicon Macs
  - Intel Mac users saw "app is not supported on this mac" error

### Changed

- **Windows/Linux Release Packages**: Now include complete bundles with:
  - Pre-bundled signal-cli (no manual download needed)
  - Simplified run scripts that launch setup wizard
  - `responses/` directory for help commands
  
- **Simplified Run Scripts**: Rewrote `run_linux.sh` and `run_windows.ps1`
  - Scripts now only handle dependency checks (Java) and signal-cli setup
  - All configuration moved to web-based setup wizard
  - No more interactive prompts for Signal linking in terminal
  
- **Signal-cli Path Detection**: App now reads signal-cli path from:
  1. Environment variable `SIGNAL_CLI_PATH`
  2. File `~/.oden/.signal_cli_path` (written by run scripts)
  3. Config file `signal_cli_path` setting

## [0.9.0] - 2026-01-28

### ✨ Highlights

This is a major release focused on **simplified installation** and a **completely redesigned configuration experience**. New users can now get started in minutes with the setup wizard, and experienced users get a powerful web-based config editor with live reload.

### Added

- **🧙 First-run Setup Wizard**: New web-based setup wizard guides you through initial configuration
  - Automatically detects existing Signal accounts from signal-cli
  - QR code linking for new devices (generated server-side, no external dependencies)
  - Choose your vault path with sensible defaults (`~/oden-vault`)
  - Opens automatically in your browser on first launch

- **⚙️ Redesigned Config Editor**: Complete overhaul of the settings interface
  - **Grundläggande tab**: Signal number, display name, vault path, timezone, append window, startup message
  - **Avancerat tab**: signal-cli host/port, custom path, external signal-cli mode, web server settings, log level
  - **Rå config tab**: Traditional textarea for power users who prefer editing INI directly
  - Form-based editing with proper input types (dropdowns, checkboxes, number fields)

- **🔄 Live Configuration Reload**: Changes take effect immediately without restart
  - Click "Spara och applicera" to save and reload config in one step
  - No more "restart required" warnings for most settings
  - Config is read fresh from disk on each API request

- **📁 New Config Location**: Configuration now lives in `~/.oden/`
  - `~/.oden/config.ini` - Main configuration file
  - `~/.oden/signal-data/` - Signal-cli data directory (for bundled builds)
  - Automatic migration from project-local config.ini

- **🔍 Faster Account Detection**: Existing Signal accounts are detected instantly
  - Reads directly from `accounts.json` instead of running `signal-cli listAccounts`
  - No more 30+ second timeouts waiting for JVM startup
  - Checks both standard (`~/.local/share/signal-cli/`) and bundled paths

### Changed

- **Config API**: `/api/config` now reads live from disk instead of cached values
- **Signal number display**: Fixed issue where phone number showed as `+46XXXXXXXXX` after setup
- **Dynamic config imports**: Functions that need config values now read them dynamically to support live reload

### Technical

- New `reload_config()` function updates all module-level config variables
- New `/api/config-save` endpoint for form-based config saving
- `save_config()` now supports all configuration options including advanced settings
- Server-side QR code generation using `qrcode` library (SVG output)

## [0.8.7] - 2026-01-25

### Added
- **Obsidian template**: Release includes pre-configured Obsidian settings with Map View plugin. Run scripts offer to copy these to your vault on first run.

## [0.8.6] - 2026-01-25

### Changed
- **Web GUI**: Config panel now displays all available configuration parameters.
- **Recommended software**: Added Obsidian Map View plugin to README.

## [0.8.5] - 2026-01-25

### Changed
- **Complete config.ini template**: Release now includes a fully documented `config.ini.template` with all available options and descriptions. Run scripts use this template instead of generating config from scratch.
- **Recommended software**: Added section to README with links to Signal Desktop, Obsidian, and Syncthing.

## [0.8.4] - 2026-01-25

### Changed
- **Append messages**: When appending to existing files (via reply or `++`), now includes TNR timestamp and sender info for the appended message. This preserves attribution when different users reply to the same thread.

## [0.8.3] - 2026-01-22

### Added
- **`plus_plus_enabled` config option**: New setting to enable/disable the `++` append feature (disabled by default). Reply-to-append still works regardless of this setting.

## [0.8.2] - 2026-01-21

### Fixed
- **Multiple accounts**: Run scripts now handle multiple signal-cli accounts, letting user choose which to use
- **Account switching**: Config.ini is now correctly updated when switching to a different account
- **sed error**: Fixed "unescaped newline" error by trimming whitespace from phone numbers

## [0.8.1] - 2026-01-21

### Fixed
- **QR code linking**: Fixed blocking issue where QR code wasn't displayed until Ctrl+C was pressed. Now runs signal-cli link in background and polls for URI.

### Changed
- Updated README with Signal account recommendations (use dedicated number, not personal)

## [0.8.0] - 2026-01-21

### Added
- **OS detection in run scripts**: Warns if running macOS script on Linux or vice versa
- **Signal state warning**: Alerts user if existing signal-cli data is found in `~/.local/share/signal-cli/`

### Fixed
- **Link device URI**: Updated to use new `sgnl://linkdevice` format instead of deprecated `tsdevice:`

## [0.7.1] - 2026-01-21

### Changed
- Improved chat help responses

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
