"""Download the official Everything SDKs and extract the 64-bit DLLs.

* SDK 2 (Everything 1.4): Everything64.dll    - https://www.voidtools.com/Everything-SDK.zip
* SDK 3 (Everything 1.5): Everything3_x64.dll - github.com/voidtools/everything_sdk3 (MIT)

Usage:  python scripts/fetch_sdk.py [--force]
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK3_VERSION = "3.0.1.12"
SDKS = [
    ("https://www.voidtools.com/Everything-SDK.zip",
     {"dll/Everything64.dll": "Everything64.dll"}),
    (f"https://github.com/voidtools/everything_sdk3/releases/download/{SDK3_VERSION}/"
     f"Everything-SDK-{SDK3_VERSION}.zip",
     {"dll/Everything3_x64.dll": "Everything3_x64.dll"}),
]


def download(url: str) -> bytes:
    """urllib first; curl.exe as fallback (proxies/TLS scanners that break Python's
    certificate check)."""
    req = urllib.request.Request(url, headers={"User-Agent": "ALLES-build-script"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except OSError as exc:  # URLError is an OSError
        curl = shutil.which("curl.exe") or shutil.which("curl")
        if not curl:
            raise
        print(f"  urllib failed ({exc.__class__.__name__}), retrying with curl")
        return subprocess.run([curl, "-fsSL", "-A", "ALLES-build-script", url],
                              capture_output=True, check=True).stdout


def fetch(url: str, wanted: dict[str, str], force: bool) -> bool:
    targets = {src: os.path.join(ROOT, dst) for src, dst in wanted.items()}
    if not force and all(os.path.exists(t) for t in targets.values()):
        print(f"present: {', '.join(wanted.values())}")
        return True
    print(f"Downloading {url} ...")
    data = download(url)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = {n.replace("\\", "/").lower(): n for n in zf.namelist()}
        for src, dst in targets.items():
            member = names.get(src.lower())
            if member is None:
                print(f"ERROR: {src} not found in {url}", file=sys.stderr)
                return False
            with zf.open(member) as fsrc, open(dst, "wb") as fdst:
                fdst.write(fsrc.read())
            print(f"wrote {dst}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="overwrite existing DLLs")
    args = ap.parse_args()
    ok = all(fetch(url, wanted, args.force) for url, wanted in SDKS)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
