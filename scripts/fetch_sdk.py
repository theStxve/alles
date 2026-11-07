"""Download the official Everything SDK from voidtools and extract Everything64.dll.

Usage:  python scripts/fetch_sdk.py [--force]
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import urllib.request
import zipfile

SDK_URL = "https://www.voidtools.com/Everything-SDK.zip"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WANTED = {"dll/Everything64.dll": "Everything64.dll"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="overwrite an existing DLL")
    args = ap.parse_args()

    targets = {src: os.path.join(ROOT, dst) for src, dst in WANTED.items()}
    if not args.force and all(os.path.exists(t) for t in targets.values()):
        print("Everything64.dll already present (use --force to re-download).")
        return 0

    print(f"Downloading {SDK_URL} ...")
    req = urllib.request.Request(SDK_URL, headers={"User-Agent": "ALLES-build-script"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()

    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = {n.replace("\\", "/").lower(): n for n in zf.namelist()}
        for src, dst in targets.items():
            member = names.get(src.lower())
            if member is None:
                print(f"ERROR: {src} not found in SDK archive", file=sys.stderr)
                return 1
            with zf.open(member) as fsrc, open(dst, "wb") as fdst:
                fdst.write(fsrc.read())
            print(f"wrote {dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
