# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller ALLES.spec   (Everything64.dll must be in the project root,
#        see scripts/fetch_sdk.py)
import os

datas = [("assets/alles.ico", "assets")]
binaries = []
for dll in ("Everything64.dll",      # Everything 1.4 (SDK2)
            "Everything3_x64.dll"):  # Everything 1.5 (SDK3, MIT licensed)
    if os.path.exists(dll):
        binaries.append((dll, "."))
    else:
        print(f"WARNUNG: {dll} fehlt - python scripts/fetch_sdk.py ausführen")

a = Analysis(
    ["run_alles.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    excludes=["PIL", "numpy", "pytest", "unittest", "pydoc", "test", "pygame", "psutil",
              "matplotlib", "pandas", "scipy", "IPython"],
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
