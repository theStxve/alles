# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller ALLES.spec   (Everything64.dll must be in the project root,
#        see scripts/fetch_sdk.py)
import os

datas = [("assets/alles.ico", "assets")]
binaries = []
if os.path.exists("Everything64.dll"):
    binaries.append(("Everything64.dll", "."))
else:
    print("WARNUNG: Everything64.dll fehlt - python scripts/fetch_sdk.py ausführen")

a = Analysis(
    ["run_alles.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["PIL", "numpy", "pytest", "unittest", "pydoc", "test"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ALLES",
    icon="assets/alles.ico",
    version="version_info.txt" if os.path.exists("version_info.txt") else None,
    debug=False,
    strip=False,
    upx=False,  # UPX triggers antivirus false positives
    console=False,
    disable_windowed_traceback=False,
)
