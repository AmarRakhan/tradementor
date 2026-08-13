"""Windows DPAPI storage for the local Hyperliquid API-wallet credential."""
from __future__ import annotations

import base64
import ctypes
import json
from ctypes import wintypes
from pathlib import Path

STORE = Path(__file__).with_name(".api_wallet.dpapi")


class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32
_crypt32.CryptProtectData.argtypes = [ctypes.POINTER(DATA_BLOB), wintypes.LPCWSTR, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(DATA_BLOB)]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _blob(data: bytes):
    buffer = ctypes.create_string_buffer(data)
    return DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))), buffer


def _protect(data: bytes) -> bytes:
    source, keepalive = _blob(data)
    target = DATA_BLOB()
    if not _crypt32.CryptProtectData(ctypes.byref(source), "TradeMentor API wallet", None, None, None, 0, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        _kernel32.LocalFree(target.pbData)


def _unprotect(data: bytes) -> bytes:
    source, keepalive = _blob(data)
    target = DATA_BLOB()
    if not _crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 0, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        _kernel32.LocalFree(target.pbData)


def save(master_address: str, api_private_key: str) -> None:
    payload = json.dumps({"master": master_address.strip().lower(), "key": api_private_key.strip()}).encode()
    STORE.write_text(base64.b64encode(_protect(payload)).decode(), encoding="ascii")


def load() -> tuple[str, str] | None:
    if not STORE.exists():
        return None
    payload = json.loads(_unprotect(base64.b64decode(STORE.read_text(encoding="ascii"))).decode())
    return str(payload["master"]), str(payload["key"])
