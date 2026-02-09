# Oden - Copilot Instructions

## Project Overview
Oden is a Signal-to-Obsidian bridge that receives Signal messages via `signal-cli` and saves them as Markdown files. It's a Python asyncio application connecting to signal-cli's JSON-RPC TCP socket.

## Architecture
```
┌─────────────┐     ┌──────────────┐     ┌──────────────┐
│ System Tray │────►│ s7_watcher   │◄───►│ signal-cli   │
│ (pystray)   │     │ (entry point)│     │ TCP:7583     │
└─────────────┘     └──────┬───────┘     └──────────────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
     ┌────────▼──┐  ┌──────▼─────┐ ┌────▼────────┐
     │processing │  │ web_server │ │ config.py   │
     │(messages) │  │ (GUI/API)  │ │ config_db   │
     └────────┬──┘  └──────┬─────┘ │ (SQLite)    │
              │            │       └─────────────┘
     ┌────────▼──┐  ┌──────▼─────────────────────┐
     │template_  │  │ web_handlers/              │
     │loader     │  │  setup / config / groups   │
     │(Jinja2)   │  │  templates                 │
     └───────────┘  └───────────────────────────-┘
```

- **s7_watcher.py**: Entry point. Manages signal-cli subprocess, TCP connection, startup tasks, web GUI, tray icon
- **processing.py**: Core logic. Parses messages, handles commands (`#help`), append mode (`++`), file I/O
- **config.py**: Loads config from `config_db`, exports constants like `VAULT_PATH`, `SIGNAL_NUMBER`, `TIMEZONE`. Legacy INI import/export supported
- **config_db.py**: SQLite config database (`config.db`). Key-value store with type-aware serialization, INI migration, integrity checking
- **app_state.py**: Singleton application state — holds references to writer, signal-cli process, web runner, tray icon
- **tray.py**: System tray icon via pystray. Start/stop toggle, open web GUI, quit. Blocks main thread on macOS (NSApplication)
- **formatting.py**: Filename sanitization, path generation, display formatting
- **signal_manager.py**: Starts/stops the signal-cli subprocess
- **web_server.py**: aiohttp web server with setup mode and dashboard mode, token-based auth for sensitive endpoints
- **web_handlers/**: Route handlers — `setup_handlers.py` (wizard, Signal linking/QR), `config_handlers.py` (CRUD, export), `group_handlers.py` (ignore/whitelist, join, invitations), `template_handlers.py` (Jinja2 editor, preview)
- **web_templates.py**: Inline HTML/CSS templates for dashboard and setup wizard
- **template_loader.py**: Jinja2 template engine for report formatting. Templates loaded from config_db or files, with LRU cache and validation
- **attachment_handler.py**: Downloads and saves Signal attachments to vault subdirectories
- **link_formatter.py**: Regex-based linking and location extraction (Google Maps, Apple Maps, OSM → geo coordinates)
- **path_utils.py**: Path validation, sanitization, directory operations. When `ODEN_HOME` env var is set (Docker), the home-directory constraint is relaxed
- **log_utils.py**: Logging setup with file rotation, log level persistence
- **log_buffer.py**: In-memory log buffer for web GUI display
- **bundle_utils.py**: PyInstaller bundle path detection, `ODEN_HOME` env var support (highest priority), pointer file resolution

## Key Patterns

### Async JSON-RPC Communication
All signal-cli communication uses JSON-RPC over TCP. Pattern for sending:
```python
json_request = {"jsonrpc": "2.0", "method": "methodName", "params": {...}, "id": request_id}
writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
await writer.drain()
```

### Config Constants
Config is stored in SQLite via `config_db`. Module-level constants are loaded from the database at startup:
```python
from oden.config import VAULT_PATH, SIGNAL_NUMBER, TIMEZONE, IGNORED_GROUPS
```
For direct database access (read/write individual settings):
```python
from oden.config_db import get_config_value, set_config_value
```

### Message Flow
1. Messages arrive via `receive` method notifications
2. `process_message()` extracts envelope, checks ignore rules
3. Commands (`#help`) → load response from `responses/` directory
4. Append mode: `++` prefix or reply within 30 min → append to existing file
5. New messages → create timestamped markdown file in `vault/{group_name}/`

## Development

### IMPORTANT: Never modify the local environment
Never run scripts, migrations, or commands that modify the user's local environment (databases like `~/.oden/config.db`, config files outside the repo, etc.) unless explicitly asked. Code changes should be tested via snapshot builds from the CI pipeline, not by running directly against the local setup.

### Environment Setup
macOS uses externally-managed Python (PEP 668), so use a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[tray]"
```

The `.venv/` directory is gitignored.

### Commands
```bash
source .venv/bin/activate       # Activate virtual environment (required)
pip install -e ".[tray]"        # Install in dev mode (with system tray support)
pytest                          # Run tests
pytest --cov=oden               # With coverage
ruff check . && ruff format .   # Lint and format
python -m oden                  # Run application
```

**IMPORTANT:** Always run `ruff check . && ruff format .` before committing to fix lint errors.

### Web GUI
A web interface runs automatically at `http://127.0.0.1:8080` (localhost only, or `0.0.0.0:8080` in Docker via `WEB_HOST` env var).

**Setup mode** (first run): Wizard for choosing Oden home dir, linking Signal account (QR code), setting vault path.

**Dashboard mode** (normal operation):
- Config viewer/editor (3 tabs: Grundläggande, Avancerat, Rå config)
- Live logs (polls every 3 seconds)
- Groups list with ignore/whitelist toggle
- Join group via Signal invite link, accept/decline pending invitations
- Template editor with split-screen preview
- Shutdown button
- INI export/import

**Security:** Token-based auth for sensitive endpoints (generated per session). Localhost only.

**Tray icon:** On macOS, a system tray icon (pystray) provides start/stop, open GUI, and quit buttons. `pystray` and `Pillow` are optional extras (`pip install .[tray]`). Falls back to terminal-only mode if unavailable (always the case in Docker).

### Docker
Oden is distributed as a multi-arch Docker image (`linux/amd64`, `linux/arm64`) alongside the macOS DMG.

Key environment variables for Docker:
- `ODEN_HOME=/data` — where config.db and signal-data live (volume mount)
- `WEB_HOST=0.0.0.0` — bind web GUI to all interfaces

```bash
docker compose up -d  # Uses docker-compose.yml in repo root
```

### Versioning
- `__version__` in `oden/__init__.py` is set to `0.0.0-dev`
- CI injects actual version from git tag or commit SHA during build
- Don't manually update version - it's managed by the release workflow

### Snapshot Releases
Every push to `main` triggers a macOS DMG build and a multi-arch Docker image push to `ghcr.io`, and creates a **snapshot pre-release** on GitHub:
- Version is set to `snapshot-<short-sha>` (e.g., `snapshot-abc1234`)
- Docker image tagged `snapshot-<short-sha>` is pushed to GitHub Container Registry
- The snapshot release is tagged `snapshot-<short-sha>` and marked as pre-release
- Each new snapshot deletes all previous snapshot releases first
- Snapshot releases are **not** shown as the "latest release" on GitHub

### Versioned Releases
For stable releases, use git tags:
1. Update `CHANGELOG.md` with new version section
2. Commit changes to a feature branch
3. Create a pull request to `main`
4. Wait for required status checks to pass (2 checks required)
5. Merge the pull request
6. Create annotated tag on main: `git tag -a v0.5.0 -m "description"`
7. Push tag: `git push origin v0.5.0`
8. GitHub Actions builds macOS DMG, pushes Docker image to ghcr.io, and creates a versioned release

**IMPORTANT:** Once a tag has been pushed and a build has started, that tag is immutable. Never delete and recreate a tag - always create a new patch version (e.g., v0.9.1 → v0.9.2).

**Note:** Direct pushes to `main` are blocked by branch protection rules. All changes must go through pull requests with passing status checks.

## Testing Guidelines
- Tests are in `tests/` using pytest
- The full test suite (~130 tests) runs in about **10 seconds** — always wait for it to finish
- Mock config values when testing: patch `oden.config.VAULT_PATH` etc.
- Don't get stuck fixing difficult tests - note the issue and move on
- **Terminal output**: Always read terminal output using `get_terminal_output` tool before continuing. Run commands directly without piping or redirection tricks like `2>&1`, `| tail`, `| head`, `echo $?` etc. Just run `python -m pytest -v` straight up.
- **Hanging tests**: If tests appear to hang, use `terminal_last_command` to check what's running

## File Naming Convention
Markdown files: `DDHHMM-{phone}-{name}.md` (e.g., `161430-46701234567-Nicklas.md`)

## Swedish Context
- UI messages and config comments are in Swedish
- Default timezone: `Europe/Stockholm`
- The app is designed for Swedish Home Guard (Hemvärnet) intelligence reports
