# Oden - Copilot Instructions

## Project Overview
Oden is a Signal-to-Obsidian bridge that receives Signal messages via `signal-cli` and saves them as Markdown files. It's a Python asyncio application connecting to signal-cli's JSON-RPC TCP socket.

## Architecture
```
signal-cli daemon (TCP:7583) → s7_watcher.py → processing.py → Markdown files in vault/
```

- **s7_watcher.py**: Entry point. Manages signal-cli subprocess, TCP connection, startup tasks (profile update, group logging, startup message), web GUI
- **processing.py**: Core logic. Parses messages, handles commands (`#help`), append mode (`++`), file I/O
- **config.py**: Loads `config.ini`, exports constants like `VAULT_PATH`, `SIGNAL_NUMBER`, `TIMEZONE`, `WEB_ENABLED`, `WEB_PORT`
- **formatting.py**: Filename sanitization, path generation, display formatting
- **signal_manager.py**: Starts/stops the signal-cli subprocess
- **web_server.py**: aiohttp web server for read-only GUI (config & logs)
- **log_buffer.py**: In-memory log buffer for web GUI display

## Key Patterns

### Async JSON-RPC Communication
All signal-cli communication uses JSON-RPC over TCP. Pattern for sending:
```python
json_request = {"jsonrpc": "2.0", "method": "methodName", "params": {...}, "id": request_id}
writer.write((json.dumps(json_request) + "\n").encode("utf-8"))
await writer.drain()
```

### Config Constants
Import from `oden.config` - they're loaded at module level:
```python
from oden.config import VAULT_PATH, SIGNAL_NUMBER, TIMEZONE, IGNORED_GROUPS
```

### Message Flow
1. Messages arrive via `receive` method notifications
2. `process_message()` extracts envelope, checks ignore rules
3. Commands (`#help`) → load response from `responses/` directory
4. Append mode: `++` prefix or reply within 30 min → append to existing file
5. New messages → create timestamped markdown file in `vault/{group_name}/`

## Development

### Environment Setup
macOS uses externally-managed Python (PEP 668), so use a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

The `.venv/` directory is gitignored.

### Commands
```bash
source .venv/bin/activate # Activate virtual environment (required)
pip install -e .          # Install in dev mode
pytest                    # Run tests
pytest --cov=oden         # With coverage
ruff check . && ruff format .  # Lint and format
python -m oden            # Run application
```

**IMPORTANT:** Always run `ruff check . && ruff format .` before committing to fix lint errors.

### Web GUI
A read-only web interface runs automatically at `http://127.0.0.1:8080` (localhost only, no auth).
- Shows current config and live logs (polls every 3 seconds)
- Configure in `config.ini` under `[Web]` section: `enabled` and `port`
- API endpoints: `GET /api/config`, `GET /api/logs`

### Versioning
- `__version__` in `oden/__init__.py` is set to `0.0.0-dev`
- CI injects actual version from git tag during release build
- Don't manually update version - it's managed by the release workflow

### Release Process
1. Update `CHANGELOG.md` with new version section
2. Commit changes to a feature branch
3. Create a pull request to `main`
4. Wait for required status checks to pass (2 checks required)
5. Merge the pull request
6. Create annotated tag on main: `git tag -a v0.5.0 -m "description"`
7. Push tag: `git push origin v0.5.0`
8. GitHub Actions builds binaries and creates release

**IMPORTANT:** Once a tag has been pushed and a build has started, that tag is immutable. Never delete and recreate a tag - always create a new patch version (e.g., v0.9.1 → v0.9.2).

**Note:** Direct pushes to `main` are blocked by branch protection rules. All changes must go through pull requests with passing status checks.

## Testing Guidelines
- Tests are in `tests/` using pytest
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
