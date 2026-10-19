# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for OptiCipher Desktop — one-folder build.

One-folder (not one-file) because wgpu-native and Qt ship multiple dynamic
libraries that must sit at known relative paths; one-file extraction at
startup fights both antivirus tools and cold-start times.

Run from the repo root:
    pyinstaller packaging/opticipher-desktop.spec --noconfirm

The wgpu package is collected wholesale (submodules + data + dynamic libs) so
the bundled wgpu-native backend works without any user-side install.
"""

import os
import sys

from PyInstaller.utils.hooks import (
    collect_dynamic_libs,
    collect_data_files,
    collect_submodules,
)

block_cipher = None

# Paths inside a spec resolve relative to the spec file's directory, so anchor
# everything to SPECPATH and point pathex at the repo root (the spec lives in
# packaging/, the packages live at the root).
SPEC_DIR = os.path.abspath(SPECPATH)
ROOT = os.path.dirname(SPEC_DIR)

hiddenimports = (
    collect_submodules("wgpu")
    + collect_submodules("opticipher")
    + collect_submodules("app")
)
# app/sftp.py imports paramiko LAZILY (so the app starts and --smoke passes
# even without it), which PyInstaller's static analysis cannot see. Collect it
# — plus its key-cryptography backends — when present, so packaged releases
# ship working sftp:// outputs. Absent in a bare dev install: skip quietly.
import importlib.util as _ilu  # noqa: E402

for _pkg in ("paramiko", "bcrypt", "nacl"):
    if _ilu.find_spec(_pkg) is not None:
        hiddenimports += collect_submodules(_pkg)
datas = collect_data_files("wgpu")
binaries = collect_dynamic_libs("wgpu")

ICON = (
    os.path.join(SPEC_DIR, "icon.ico")
    if sys.platform == "win32"
    else os.path.join(SPEC_DIR, "icon.icns")
)

a = Analysis(
    [os.path.join(SPEC_DIR, "entry.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["wgpu.utils.imgui"],  # optional imgui demo helper, not shipped
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OptiCipherDesktop",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="OptiCipherDesktop",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="OptiCipher Desktop.app",
        icon=ICON,
        bundle_identifier="org.biocolab.opticipher.desktop",
        info_plist={
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": "1.0.0",
        },
    )
