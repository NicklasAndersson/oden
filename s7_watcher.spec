# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for Oden macOS app bundle
# Builds an app with bundled JRE and signal-cli

import glob
import importlib.util
import os
import sys

# Data files to include
datas = [
    ('templates', 'templates'),
    ('config.ini', '.'),
    ('images/logo_small.jpg', 'images'),
]

# Add bundled JRE and signal-cli if directories exist (set up by build script)
if os.path.exists('jre-arm64'):
    datas.append(('jre-arm64', 'jre-arm64'))
if os.path.exists('jre-x64'):
    datas.append(('jre-x64', 'jre-x64'))
if os.path.exists('signal-cli'):
    datas.append(('signal-cli', 'signal-cli'))

# Add static files for web UI
if os.path.exists('oden/static'):
    datas.append(('oden/static', 'static'))

# Add Jinja2 web templates
if os.path.exists('oden/templates/web'):
    datas.append(('oden/templates/web', 'oden/templates/web'))

hiddenimports = [
    'oden.config',
    'oden.processing',
    'oden.formatting',
    'oden.link_formatter',
    'oden.attachment_handler',
    'oden.signal_manager',
    'oden.signal_linker',
    'oden.signal_registrar',
    'oden.signal_listener',
    'oden.responses_db',
    'oden.groups_db',
    'oden.web_server',
    'oden.log_buffer',
    'oden.app_state',
    'oden.tray',
    'PIL',
    'mgrs',
]

if sys.platform == 'darwin':
    hiddenimports.append('pystray._darwin')
elif sys.platform == 'win32':
    hiddenimports.extend(['pystray._win32', 'PIL.ImageWin'])

# Optional TAK support (oden[tak]): bundle pytak + its deps only when the
# build environment has them installed. Without this block the app builds
# fine, it just won't have TAK integration.
# cryptography ships a PyInstaller hook already, so only pytak needs collecting.
_tak_datas = []
_tak_binaries = []
if importlib.util.find_spec('pytak'):
    from PyInstaller.utils.hooks import collect_all

    hiddenimports += [
        'oden.tak.bridge',
        'oden.tak.listener',
        'oden.tak.cot',
        'oden.tak.eight_s',
        'oden.web_handlers.tak_handlers',
    ]
    for _pkg in ('pytak', 'takproto'):
        if importlib.util.find_spec(_pkg):
            _pkg_datas, _pkg_binaries, _pkg_hidden = collect_all(_pkg)
            _tak_datas += _pkg_datas
            _tak_binaries += _pkg_binaries
            hiddenimports += _pkg_hidden

# mgrs loads its native extension via ctypes at runtime — PyInstaller
# can't detect this statically, so we collect it explicitly.
_mgrs_binaries = []
_mgrs_spec = importlib.util.find_spec('mgrs')
if _mgrs_spec and _mgrs_spec.origin:
    _site_pkgs = os.path.dirname(os.path.dirname(_mgrs_spec.origin))
    for _pattern in ('libmgrs*.so', 'libmgrs*.dylib', 'libmgrs*.pyd', 'libmgrs*.dll'):
        for _lib in glob.glob(os.path.join(_site_pkgs, _pattern)):
            _mgrs_binaries.append((_lib, '.'))

a = Analysis(
    ['oden/s7_watcher.py'],
    pathex=[],
    binaries=_mgrs_binaries + _tak_binaries,
    datas=datas + _tak_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# Determine icon path
icon_path = 'images/oden.icns' if os.path.exists('images/oden.icns') else None
windows_icon_path = 'images/oden.ico' if os.path.exists('images/oden.ico') else None

# macOS: Create .app bundle with --windowed --onedir
if sys.platform == 'darwin':
    # Builds for the architecture of the running Python (arm64 in CI — Apple Silicon only)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name='Oden',
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,  # UPX breaks code signing on macOS
        console=False,  # --windowed
        disable_windowed_traceback=False,
        argv_emulation=True,  # Better macOS integration
        target_arch=None,  # Build for the runner's native arch (arm64 on macos-latest)
        codesign_identity=os.environ.get('CODESIGN_IDENTITY'),
        entitlements_file=os.environ.get('ENTITLEMENTS_FILE'),
        icon=icon_path,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name='Oden',
    )

    app = BUNDLE(
        coll,
        name='Oden.app',
        icon=icon_path,
        bundle_identifier='se.oden.app',
        info_plist={
            'CFBundleName': 'Oden',
            'CFBundleDisplayName': 'Oden',
            'CFBundleVersion': os.environ.get('ODEN_VERSION', '0.0.0'),
            'CFBundleShortVersionString': os.environ.get('ODEN_VERSION', '0.0.0'),
            'LSMinimumSystemVersion': '10.15',
            'NSHighResolutionCapable': True,
            'LSApplicationCategoryType': 'public.app-category.utilities',
            'NSHumanReadableCopyright': 'Copyright © 2024-2026 Oden',
        },
    )
else:
    if sys.platform == 'win32':
        # Windows: GUI onedir executable for installer packaging
        exe = EXE(
            pyz,
            a.scripts,
            [],
            exclude_binaries=True,
            name='Oden',
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=False,
            console=False,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
            icon=windows_icon_path,
        )

        coll = COLLECT(
            exe,
            a.binaries,
            a.datas,
            strip=False,
            upx=False,
            upx_exclude=[],
            name='Oden',
        )
    else:
        # Linux: console single-file executable
        exe = EXE(
            pyz,
            a.scripts,
            a.binaries,
            a.datas,
            [],
            name='oden',
            debug=False,
            bootloader_ignore_signals=False,
            strip=False,
            upx=True,
            upx_exclude=[],
            runtime_tmpdir=None,
            console=True,
            disable_windowed_traceback=False,
            argv_emulation=False,
            target_arch=None,
            codesign_identity=None,
            entitlements_file=None,
        )
