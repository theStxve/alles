"""Write version_info.txt (Windows file properties of ALLES.exe) for PyInstaller."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from alles import __version__  # noqa: E402

TEMPLATE = """# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040704B0', [
      StringStruct('CompanyName', 'theStxve'),
      StringStruct('FileDescription', 'ALLES - Dateisuche'),
      StringStruct('FileVersion', '{v}'),
      StringStruct('InternalName', 'ALLES'),
      StringStruct('LegalCopyright', 'MIT License, (c) theStxve'),
      StringStruct('OriginalFilename', 'ALLES.exe'),
      StringStruct('ProductName', 'ALLES'),
      StringStruct('ProductVersion', '{v}')])]),
    VarFileInfo([VarStruct('Translation', [0x0407, 1200])])
  ]
)
"""


def main():
    parts = [int(p) for p in __version__.split(".")[:3]] + [0]
    while len(parts) < 4:
        parts.insert(-1, 0)
    path = os.path.join(ROOT, "version_info.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(t=tuple(parts[:4]), v=__version__))
    print("wrote", path)


if __name__ == "__main__":
    main()
