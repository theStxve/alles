"""
Windows shell thumbnails and file-type icons as PNG bytes (Tk 8.6 reads PNG
natively), implemented with ctypes - no Pillow needed.

COM calls must run on a thread that called ``com_init()``.
"""
from __future__ import annotations

import ctypes
import struct
import threading
import zlib
from ctypes import wintypes

SIIGBF_RESIZETOFIT = 0x0
SIIGBF_BIGGERSIZEOK = 0x1
SIIGBF_ICONONLY = 0x4
SIIGBF_THUMBNAILONLY = 0x8

SHGFI_ICON = 0x100
SHGFI_SMALLICON = 0x1
SHGFI_LARGEICON = 0x0
SHGFI_TYPENAME = 0x400
SHGFI_USEFILEATTRIBUTES = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_ATTRIBUTE_DIRECTORY = 0x10
DI_NORMAL = 0x3


# ----------------------------------------------------------------------------- PNG
def png_rgba(width: int, height: int, rgba: bytes) -> bytes:
    """Encode raw RGBA pixels as PNG (pure Python + zlib)."""
    stride = width * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 3)) + chunk(b"IEND", b""))


def bgra_to_rgba(bgra: bytes) -> bytes:
    px = bytearray(bgra)
    px[0::4], px[2::4] = bgra[2::4], bgra[0::4]
    alpha = px[3::4]
    if not any(alpha):  # no alpha channel: opaque where something was drawn
        px[3::4] = bytes(255 if (r or g or b) else 0
                         for r, g, b in zip(px[0::4], px[1::4], px[2::4], strict=True))
    return bytes(px)


# ----------------------------------------------------------------------------- Win32
class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG),
                ("bmHeight", wintypes.LONG), ("bmWidthBytes", wintypes.LONG),
                ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD)]


class SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int),
                ("dwAttributes", wintypes.DWORD), ("szDisplayName", wintypes.WCHAR * 260),
                ("szTypeName", wintypes.WCHAR * 80)]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


IID_IShellItemImageFactory = GUID(0xBCC18B79, 0xBA16, 0x442F,
                                  (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59,
                                                       0xC3, 0x0C, 0x46, 0x3B))

_gdi = ctypes.WinDLL("gdi32")
_u32 = ctypes.WinDLL("user32")
_shell = ctypes.WinDLL("shell32")
_ole = ctypes.WinDLL("ole32")

_gdi.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                           ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
_gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi.CreateCompatibleDC.restype = wintypes.HDC
_gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                  ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE,
                                  wintypes.DWORD]
_gdi.CreateDIBSection.restype = wintypes.HBITMAP
_gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi.SelectObject.restype = wintypes.HGDIOBJ
_gdi.DeleteDC.argtypes = [wintypes.HDC]
_u32.GetDC.argtypes = [wintypes.HWND]
_u32.GetDC.restype = wintypes.HDC
_u32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_u32.DrawIconEx.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.HICON,
                            ctypes.c_int, ctypes.c_int, wintypes.UINT, wintypes.HBRUSH,
                            wintypes.UINT]
_u32.DestroyIcon.argtypes = [wintypes.HICON]
_u32.GetSystemMetrics.argtypes = [ctypes.c_int]
_shell.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD,
                                  ctypes.POINTER(SHFILEINFOW), wintypes.UINT, wintypes.UINT]
_shell.SHGetFileInfoW.restype = ctypes.c_size_t
_shell.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                               ctypes.POINTER(GUID),
                                               ctypes.POINTER(ctypes.c_void_p)]
_shell.SHCreateItemFromParsingName.restype = ctypes.c_long
_ole.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
_ole.CoInitializeEx.restype = ctypes.c_long

_GetImage = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int,
                               ctypes.POINTER(wintypes.HBITMAP))
_Release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

_com_state = threading.local()


def com_init() -> None:
    if not getattr(_com_state, "done", False):
        _ole.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        _com_state.done = True


def _bmi(width: int, height: int) -> BITMAPINFOHEADER:
    bmi = BITMAPINFOHEADER()
    bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.biWidth = width
    bmi.biHeight = -height  # top-down rows
    bmi.biPlanes = 1
    bmi.biBitCount = 32
    return bmi


def hbitmap_to_png(hbm) -> bytes | None:
    bm = BITMAP()
    if not _gdi.GetObjectW(hbm, ctypes.sizeof(BITMAP), ctypes.byref(bm)):
        return None
    w, h = bm.bmWidth, abs(bm.bmHeight)
    if w <= 0 or h <= 0:
        return None
    buf = ctypes.create_string_buffer(w * h * 4)
    hdc = _u32.GetDC(None)
    try:
        lines = _gdi.GetDIBits(hdc, hbm, 0, h, buf, ctypes.byref(_bmi(w, h)), 0)
    finally:
        _u32.ReleaseDC(None, hdc)
    if lines != h:
        return None
    return png_rgba(w, h, bgra_to_rgba(buf.raw))


def thumbnail_png(path: str, size: int = 256, icon_only: bool = False) -> bytes | None:
    """Explorer thumbnail (or the file's icon) as PNG bytes. Call com_init() first."""
    com_init()
    obj = ctypes.c_void_p()
    hr = _shell.SHCreateItemFromParsingName(path, None, ctypes.byref(IID_IShellItemImageFactory),
                                            ctypes.byref(obj))
    if hr < 0 or not obj.value:
        return None
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
    try:
        hbm = wintypes.HBITMAP()
        flags = SIIGBF_ICONONLY if icon_only else SIIGBF_RESIZETOFIT
        hr = _GetImage(vtbl[3])(obj, SIZE(size, size), flags, ctypes.byref(hbm))
        if hr < 0 or not hbm:
            return None
        try:
            return hbitmap_to_png(hbm)
        finally:
            _gdi.DeleteObject(hbm)
    finally:
        _Release(vtbl[2])(obj)


def small_icon_size() -> int:
    return max(16, _u32.GetSystemMetrics(49))  # SM_CXSMICON (DPI-aware)


def type_info(ext: str, is_dir: bool = False, size: int | None = None
              ) -> tuple[bytes | None, str]:
    """(icon PNG, friendly type name) for an extension like 'pdf' - no file needed."""
    size = size or small_icon_size()
    name = "ordner" if is_dir else ("datei." + ext if ext else "datei")
    attrs = FILE_ATTRIBUTE_DIRECTORY if is_dir else FILE_ATTRIBUTE_NORMAL
    info = SHFILEINFOW()
    flags = SHGFI_ICON | SHGFI_TYPENAME | SHGFI_USEFILEATTRIBUTES
    flags |= SHGFI_SMALLICON if size <= 24 else SHGFI_LARGEICON
    if not _shell.SHGetFileInfoW(name, attrs, ctypes.byref(info), ctypes.sizeof(info), flags):
        return None, ""
    png = None
    if info.hIcon:
        try:
            png = _icon_to_png(info.hIcon, size)
        finally:
            _u32.DestroyIcon(info.hIcon)
    return png, info.szTypeName


def _icon_to_png(hicon, size: int) -> bytes | None:
    hdc = _gdi.CreateCompatibleDC(None)
    bits = ctypes.c_void_p()
    dib = _gdi.CreateDIBSection(hdc, ctypes.byref(_bmi(size, size)), 0, ctypes.byref(bits),
                                None, 0)
    if not dib:
        _gdi.DeleteDC(hdc)
        return None
    old = _gdi.SelectObject(hdc, dib)
    try:
        _u32.DrawIconEx(hdc, 0, 0, hicon, size, size, 0, None, DI_NORMAL)
        raw = ctypes.string_at(bits, size * size * 4)
    finally:
        _gdi.SelectObject(hdc, old)
        _gdi.DeleteObject(dib)
        _gdi.DeleteDC(hdc)
    return png_rgba(size, size, bgra_to_rgba(raw))
