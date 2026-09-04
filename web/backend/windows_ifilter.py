from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


class WindowsIFilterError(RuntimeError):
    pass


HRESULT = ctypes.c_long
ULONG = wintypes.ULONG
FILTER_E_END_OF_CHUNKS = 0x80041700
FILTER_E_NO_MORE_TEXT = 0x80041701
RPC_E_CHANGED_MODE = 0x80010106
CHUNK_TEXT = 0x1


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class PROPSPEC_UNION(ctypes.Union):
    _fields_ = [("propid", wintypes.ULONG), ("lpwstr", wintypes.LPWSTR)]


class PROPSPEC(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("ulKind", wintypes.ULONG), ("value", PROPSPEC_UNION)]


class FULLPROPSPEC(ctypes.Structure):
    _fields_ = [("guidPropSet", GUID), ("psProperty", PROPSPEC)]


class STAT_CHUNK(ctypes.Structure):
    _fields_ = [
        ("idChunk", wintypes.ULONG),
        ("breakType", ctypes.c_int),
        ("flags", ctypes.c_int),
        ("locale", wintypes.LCID),
        ("attribute", FULLPROPSPEC),
        ("idChunkSource", wintypes.ULONG),
        ("cwcStartSource", wintypes.ULONG),
        ("cwcLenSource", wintypes.ULONG),
    ]


def _unsigned_hresult(value: int) -> int:
    return ctypes.c_ulong(value).value


def extract_legacy_word_text(path: Path) -> str:
    """Extract Word 97-2003 text through the registered Windows Office IFilter."""

    if os.name != "nt":
        raise WindowsIFilterError("旧版 DOC 本地解析仅支持 Windows。")
    source = path.resolve()
    if not source.is_file():
        raise WindowsIFilterError("旧版 DOC 文件不存在。")

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = HRESULT
    initialized = ole32.CoInitializeEx(None, 2)
    initialized_here = initialized >= 0
    if initialized < 0 and _unsigned_hresult(initialized) != RPC_E_CHANGED_MODE:
        raise WindowsIFilterError(f"Windows COM 初始化失败：0x{_unsigned_hresult(initialized):08x}")

    instance = ctypes.c_void_p()
    release = None
    try:
        query = ctypes.WinDLL("query.dll")
        load_filter = query.LoadIFilter
        load_filter.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        load_filter.restype = HRESULT
        result = load_filter(str(source), None, ctypes.byref(instance))
        if result < 0 or not instance.value:
            raise WindowsIFilterError(
                f"Windows 未安装可读取该 DOC 的 Office IFilter：0x{_unsigned_hresult(result):08x}"
            )

        vtable = ctypes.cast(instance, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        release = ctypes.WINFUNCTYPE(ULONG, ctypes.c_void_p)(vtable[2])
        init = ctypes.WINFUNCTYPE(
            HRESULT, ctypes.c_void_p, ULONG, ULONG, ctypes.c_void_p, ctypes.POINTER(ULONG),
        )(vtable[3])
        get_chunk = ctypes.WINFUNCTYPE(
            HRESULT, ctypes.c_void_p, ctypes.POINTER(STAT_CHUNK),
        )(vtable[4])
        get_text = ctypes.WINFUNCTYPE(
            HRESULT, ctypes.c_void_p, ctypes.POINTER(ULONG), wintypes.LPWSTR,
        )(vtable[5])

        output_flags = ULONG()
        result = init(instance, 0, 0, None, ctypes.byref(output_flags))
        if result < 0:
            raise WindowsIFilterError(f"DOC 文本过滤器初始化失败：0x{_unsigned_hresult(result):08x}")

        parts: list[str] = []
        while True:
            chunk = STAT_CHUNK()
            result = get_chunk(instance, ctypes.byref(chunk))
            if _unsigned_hresult(result) == FILTER_E_END_OF_CHUNKS:
                break
            if result < 0:
                raise WindowsIFilterError(f"DOC 文本块读取失败：0x{_unsigned_hresult(result):08x}")
            if not chunk.flags & CHUNK_TEXT:
                continue
            while True:
                capacity = ULONG(4095)
                buffer = ctypes.create_unicode_buffer(4096)
                result = get_text(instance, ctypes.byref(capacity), buffer)
                if capacity.value:
                    parts.append(buffer[:capacity.value])
                if _unsigned_hresult(result) == FILTER_E_NO_MORE_TEXT or result != 0:
                    break
        return "\n".join(parts).strip()
    except OSError as error:
        raise WindowsIFilterError(f"旧版 DOC 本地解析失败：{error}") from error
    finally:
        if release is not None and instance.value:
            release(instance)
        if initialized_here:
            ole32.CoUninitialize()
