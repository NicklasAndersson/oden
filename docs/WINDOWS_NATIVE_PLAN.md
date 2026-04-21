# Native Windows Build — Plan

> **Status:** Partially implemented (PR 1 complete).
>
> **Goal:** Ship Oden as a true native Windows application — no Docker, no WSL —
> with a proper installer, Start Menu shortcuts, autostart on login, and a system
> tray icon. The user should be able to download a single `Oden-Setup-x.y.z.exe`,
> run it, and be done.

## Implementation status (2026-04-21)

Implemented:

- `build-windows` job in `.github/workflows/release.yml` (with `continue-on-error: true`)
- JRE + signal-cli Windows download/cache/extract in CI
- PyInstaller Windows `--onedir` GUI build path in `s7_watcher.spec`
- Windows tray hidden imports (`pystray._win32`, `PIL.ImageWin`)
- Inno Setup script `scripts/oden.iss`
- Windows installer artifact upload and conditional inclusion in release assets
- Windows installer text in versioned release notes
- `.ico` generation in `scripts/generate_icon.py`

Not yet implemented:

- Windows version resource (`VSVersionInfo`) in `s7_watcher.spec`
- Runtime polish in `oden/signal_manager.py` (`CREATE_NO_WINDOW` and final Windows invocation path)
- Confirmed `.exe` suffix handling for bundled Java path in `oden/bundle_utils.py`
- Dedicated end-user native Windows setup doc and README final wording
- Signing (`signtool`) and release hardening

---

## 1. Why a native build?

Today Windows users must install Docker Desktop, which in turn requires WSL 2,
virtualization in BIOS, ~4 GB of RAM headroom, and a Microsoft account to
reasonably keep updated. That is a significant barrier for the target audience
(Hemvärnet personnel, often non-technical, sometimes on locked-down laptops
where WSL/Hyper-V is disabled by group policy).

A native build gives us:

- **One-click install** via a familiar `Setup.exe` wizard.
- **No virtualization required** — runs on any Windows 10/11 x64 machine.
- **Real native UX:** Start Menu entry, system-tray icon (already supported via
  `pystray`), autostart on login, "Add/Remove Programs" entry, file associations
  if we ever want them.
- **Smaller disk footprint** than Docker Desktop + image (~250 MB vs. several GB).
- **Easier to support in restricted environments** (no admin rights for Hyper-V,
  no corporate proxy issues with `docker pull`).

---

## 2. What "done" looks like

A user on a fresh Windows 11 machine can:

1. Download `Oden-Setup-<version>-x64.exe` from the GitHub Releases page.
2. Double-click it. Inno Setup wizard appears (Swedish + English).
3. Choose install location (default `%LocalAppData%\Programs\Oden`),
   tick "Start Oden on login", tick "Create desktop shortcut".
4. Click **Install** → done in ~10 seconds (no admin rights required for a
   per-user install).
5. Oden launches automatically, tray icon appears, default browser opens at
   `http://127.0.0.1:8080/setup`.
6. The setup wizard runs exactly like on macOS: choose Oden home dir, link
   Signal account via QR code, choose vault folder.
7. From now on, Oden starts silently on login and lives in the tray.

Uninstall via "Apps & features" cleanly removes the program but **preserves
user data** (`%AppData%\Oden\` and the vault) unless the user opts in to wipe.

---

## 3. Components that need to be bundled

Oden has three runtime dependencies that don't exist on a stock Windows box:

| Component   | Why                                              | How to bundle                                      |
|-------------|--------------------------------------------------|----------------------------------------------------|
| Python 3.12 | Application runtime                              | Frozen into the EXE by PyInstaller                 |
| JRE 25      | `signal-cli` is Java; needs a JRE                | Bundled Temurin JRE 25 (Windows x64 zip)           |
| signal-cli  | Talks to the Signal protocol                     | Bundled `signal-cli-<ver>` distribution            |

The PyInstaller spec (`s7_watcher.spec`) already has hooks for `jre-x64` and
`signal-cli` directories — the same pattern used for macOS — so most of the
plumbing already exists. The Windows branch in the spec just needs to be
fleshed out (icon, version info, no-console option, etc.).

---

## 4. Architecture of the Windows package

```text
Oden-Setup-x.y.z-x64.exe        (Inno Setup installer, ~150 MB)
└── installs to %LocalAppData%\Programs\Oden\
    ├── Oden.exe                (PyInstaller --onedir launcher, GUI mode)
    ├── _internal\              (PyInstaller runtime: python DLL, libs, datas)
    │   ├── jre-x64\bin\java.exe
    │   ├── signal-cli\bin\signal-cli.bat
    │   ├── templates\          (Jinja2 web templates)
    │   ├── images\
    │   └── ...
    ├── unins000.exe            (Inno Setup uninstaller)
    └── LICENSE.txt, README.txt
```

User data lives **outside** the install dir, in standard Windows locations:

| Data                  | Location                                              |
|-----------------------|-------------------------------------------------------|
| Pointer file          | `%APPDATA%\Oden\oden_home.txt` (already implemented)  |
| Default Oden home     | `%UserProfile%\.oden\` (already implemented)          |
| Vault                 | User chooses in setup wizard, e.g. `Documents\Vault`  |
| Logs                  | Inside the Oden home dir (already implemented)        |

`oden/bundle_utils.py` already uses `%APPDATA%\Oden` on Windows for the
pointer file directory (that expands under `...\AppData\Roaming\Oden`) and
`Path.home() / ".oden"` for the default home, so those parts are already
Windows-aware. One related code tweak is still likely needed when bundling a
JRE on Windows: `get_bundled_java_path()` should resolve `bin/java.exe`
instead of `bin/java`.

---

## 5. Build pipeline

Current state: this section is now mostly implemented for CI and packaging. The
remaining gaps are version-resource metadata in the Windows executable and
optional signing.

### 5.1 PyInstaller configuration

Status: mostly implemented.

Completed in `s7_watcher.spec`:

- Windows branch produces a `--onedir --windowed` style build (`console=False`)
  for installer packaging.
- Embed Windows version info (`VSVersionInfo`) so "Properties → Details" in
  Explorer shows version, copyright, and product name.
- Application icon path is wired for `images/oden.ico`.
- `pystray._win32` and `PIL.ImageWin` are included in Windows hidden imports.
- `--onedir` is used (not `--onefile`), so Windows Defender doesn't have to
  unpack a 150 MB executable on every launch (which is slow and trips AV
  heuristics). `--onedir` also makes incremental updates feasible.

Still pending:

- Embed Windows version info (`VSVersionInfo`) so "Properties → Details" in
  Explorer shows version, copyright, and product name.

### 5.2 Bundling the JRE and signal-cli

In a new `build-windows` job in `.github/workflows/release.yml`, mirror the
macOS job:

1. Download Temurin JRE 25 Windows x64 zip from the Adoptium API.
2. Download `signal-cli-<ver>.zip` from `AsamK/signal-cli` releases (the
   Windows zip ships a `bin\signal-cli.bat` that already wraps Java —
   we'll prefer to call our bundled `java.exe` directly to avoid a separate
   `JAVA_HOME` lookup, see §7).
3. Extract both into the build directory next to the PyInstaller spec, exactly
   as macOS already does it.
4. Cache both downloads with `actions/cache@v5`, keyed on version, to keep the
   workflow fast.

### 5.3 Building the installer with Inno Setup

[Inno Setup](https://jrsoftware.org/isinfo.php) is the de-facto open-source
choice for Windows installers, has a clean script syntax, supports per-user
installs without admin (which is what we want), and is pre-installed on the
GitHub `windows-latest` runner.

Status: implemented (`scripts/oden.iss` exists and is used by CI).

Current script:

```iss
[Setup]
AppName=Oden
AppVersion={#MyAppVersion}
AppPublisher=Oden
DefaultDirName={localappdata}\Programs\Oden
DefaultGroupName=Oden
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputBaseFilename=Oden-Setup-{#MyAppVersion}-x64
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\images\oden.ico
UninstallDisplayIcon={app}\Oden.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "swedish"; MessagesFile: "compiler:Languages\Swedish.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"
Name: "startup";     Description: "Start Oden when I log in"; Flags: checkedonce

[Files]
Source: "..\dist\Oden\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Oden";          Filename: "{app}\Oden.exe"
Name: "{group}\Uninstall Oden"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Oden";    Filename: "{app}\Oden.exe"; Tasks: desktopicon
Name: "{userstartup}\Oden";    Filename: "{app}\Oden.exe"; Tasks: startup

[Run]
Filename: "{app}\Oden.exe"; Description: "Launch Oden"; Flags: nowait postinstall skipifsilent
```

The `{userstartup}` shortcut handles autostart cleanly — no registry hacks,
no scheduled tasks, easy to opt out of from Task Manager → Startup.

### 5.4 Signing (optional but strongly recommended)

Without a code-signing certificate, SmartScreen will show
"Windows protected your PC" the first time a user runs the installer, and
Windows Defender may flag the unsigned PyInstaller binary as suspicious.

Options, cheapest to most professional:

1. **Do nothing.** Document the SmartScreen "More info → Run anyway" workaround
   in `WINDOWS_SETUP.md`. Acceptable for a small open-source project, painful
   for non-technical users.
2. **Self-signed certificate.** Adds nothing for end users (still untrusted).
   Not worth it.
3. **Azure Trusted Signing** (~$10/month, EV-equivalent reputation, no
   hardware token). Requires a verified Microsoft Partner publisher identity.
   Recommended once the project has stable users.
4. **Sectigo / DigiCert OV/EV certificate** ($150–$400/yr, USB token for EV).
   Traditional path; works without monthly fees.

The build pipeline should be structured so signing can be added later by
wrapping the produced `Oden.exe` and `Oden-Setup-*.exe` in a `signtool` step
gated on a secret being present.

---

## 6. CI/CD integration

Status: implemented for initial rollout.

`build-windows` now exists in `.github/workflows/release.yml`, parallel to
`build-macos` and `build-docker`:

- Runner: `windows-latest`.
- Steps mirror macOS:
  1. Checkout, compute version (tag or `snapshot-<sha>`), patch
     `oden/__init__.py`.
  2. Set up Python 3.12 (`actions/setup-python@v5`).
  3. `pip install -e ".[tray]"` plus `pyinstaller`.
  4. Cache + download Temurin JRE x64 and signal-cli; extract next to the spec.
  5. Generate `oden.ico` (extend `scripts/generate_icon.py`).
  6. Run `pyinstaller --clean --noconfirm s7_watcher.spec`.
  7. Run Inno Setup compiler: `iscc /DMyAppVersion=<v> scripts/oden.iss`.
     (`iscc` is on the runner's PATH on `windows-latest`.)
  8. Optional: `signtool sign` if signing secrets are present.
  9. `actions/upload-artifact@v7` of `Oden-Setup-*.exe`.
- The `release` job now conditionally downloads Windows artifacts and includes
  them when the Windows build succeeds.
- Versioned release notes include a Windows native installer section.

The Windows job should **not block** macOS or Docker on failure — mark it
with `continue-on-error: true` for the first few releases until we trust the
pipeline.

---

## 7. Code changes inside Oden

Most of the codebase is already platform-aware. The list of actual changes is
small:

- **`oden/signal_manager.py`**: confirm it locates `signal-cli.bat` on
  Windows (extension difference from the Linux/macOS `signal-cli` script). The
  cleanest approach is to invoke our bundled `java.exe -jar signal-cli.jar`
  directly, the same way the wrapper script does, so we are independent of
  shell quoting differences. Verify subprocess flags include
  `subprocess.CREATE_NO_WINDOW` (or `creationflags=0x08000000`) so the
  `java.exe` child does not pop a console window.
- **`oden/bundle_utils.py`**: already returns `jre-x64/bin/java.exe`-style
  paths via `bin/java`. Confirm it appends `.exe` on Windows; if not, add a
  one-line tweak.
- **`oden/tray.py`**: `pystray` already supports Windows via `pystray._win32`.
  Add it to PyInstaller `hiddenimports`. Verify the icon file format
  (`pystray` on Windows wants a PIL `Image`, which we already pass).
- **`s7_watcher.spec`**: flesh out the Linux/Windows branch (icon,
  `version` resource, `console=False` for the GUI build, hidden imports for
  the Windows tray).
- **`scripts/generate_icon.py`**: also emit `images/oden.ico` (multi-size:
  16, 32, 48, 64, 128, 256).

No changes are expected in `web_server.py`, `processing.py`, `config.py`, or
the web handlers — they are already pure-Python and platform-neutral.

---

## 8. Documentation

- Add `docs/WINDOWS_NATIVE_SETUP.md` (Swedish, mirroring the existing
  `WINDOWS_SETUP.md` but for the installer flow). Cover:
  - Download → install → setup wizard → done.
  - Where the data lives (`%AppData%\Oden`, the chosen vault).
  - How to update (run new installer; data is preserved).
  - How to uninstall (Apps & features) and what is/isn't deleted.
  - Troubleshooting: SmartScreen warning, Defender false positives, port 8080
    in use, log location.
- Update the top-level `README.md` to list three install paths: macOS DMG,
  Windows installer, Docker.
- Update `release.yml`'s release notes block to mention the Windows installer.
- Keep `WINDOWS_SETUP.md` (Docker) for users who specifically want the
  container path; cross-link both docs.

---

## 9. Testing

- **Local manual test:** build on a Windows VM (or `windows-latest` runner with
  Remote Desktop), install on a clean Windows 10 22H2 and Windows 11 23H2 VM,
  walk through the setup wizard, link a Signal test number, send a few
  messages, verify reports land in the chosen vault.
- **CI smoke test:** in the `build-windows` job, after PyInstaller finishes,
  run `dist\Oden\Oden.exe --version` (we'd need a tiny `--version` flag) to
  catch missing-DLL errors at build time rather than at user-install time.
- **Unit tests:** the existing pytest suite already runs on Linux in CI; no
  Windows-specific test additions required for the first release. Optionally
  add a `windows-latest` matrix entry to `python-test.yml` to keep the codebase
  honest about path/encoding differences.

---

## 10. Rollout plan

1. **PR 1 — Build infrastructure** (completed):
   - Update `s7_watcher.spec` Windows branch.
   - Generate `oden.ico`.
   - Add `scripts/oden.iss`.
   - Add the `build-windows` GitHub Actions job, **with `continue-on-error`**,
     producing snapshot installers as artifacts.
2. **PR 2 — Code polish** (in progress):
   - Subprocess `CREATE_NO_WINDOW` flags in `signal_manager.py`.
   - `.exe` suffix handling in `bundle_utils.py` if missing.
   - Add `pystray._win32` and friends to hidden imports.
3. **PR 3 — Documentation** (in progress):
   - `docs/WINDOWS_NATIVE_SETUP.md`, README updates.
4. **PR 4 — Promote to release** (pending):
   - Drop `continue-on-error`, include the installer in both snapshot and
     versioned releases, mention it in CHANGELOG.
5. **PR 5 (later, optional) — Code signing** (pending):
   - Add `signtool` step gated on `secrets.WINDOWS_CERT_*`.

---

## 11. Open questions / decisions to make

- **Per-user vs. per-machine install?** Per-user (`{localappdata}`) means no
  UAC prompt and no admin rights — best for our audience. Per-machine
  (`{commonpfiles}`) is more "professional" but blocked on locked-down
  laptops. **Proposal: per-user by default, allow user to switch in the
  installer wizard via `PrivilegesRequiredOverridesAllowed=dialog`.**
- **Auto-update?** Out of scope for v1. Long-term, consider
  [WinSparkle](https://github.com/vslavik/winsparkle) — it integrates cleanly
  with our existing GitHub Releases feed.
- **32-bit support?** No. signal-cli requires Java 21+ which is x64-only on
  Windows in practice; 32-bit Windows is also at <0.5% market share.
- **ARM64 Windows support?** Skip for v1. There is no Temurin Windows ARM64
  JRE for Java 25 yet (as of writing); ARM64 Windows users can fall back to
  the existing Docker path or run the x64 build under Microsoft's emulation.
- **Where does the vault default to?** Suggest `%UserProfile%\Documents\Oden
  Vault` in the setup wizard's vault-path step — this matches Obsidian's
  default and is easy for users to find.

---

## 12. Effort estimate (rough)

This section intentionally left empty — no estimate requested.
