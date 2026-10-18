"""
app.device
==========

System introspection for the settings dialog and the device-info bar:
CPU core count, total RAM, and the compute backends the accel layer can use
(the GPU row carries the adapter name and API — Metal / Vulkan / DX12 — so
users can see exactly what hardware will run their jobs).
"""

from __future__ import annotations

import os
import platform
from typing import Dict, List

from opticipher import accel


def cpu_count() -> int:
    return os.cpu_count() or 1


def total_ram_mb() -> int:
    """Total system RAM in MiB, best-effort across the three OSes."""
    try:
        if hasattr(os, "sysconf"):  # Linux / macOS
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages * page_size / (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        pass
    try:  # Windows
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_uint64),
                ("ullAvailPhys", ctypes.c_uint64),
                ("ullTotalPageFile", ctypes.c_uint64),
                ("ullAvailPageFile", ctypes.c_uint64),
                ("ullTotalVirtual", ctypes.c_uint64),
                ("ullAvailVirtual", ctypes.c_uint64),
                ("ullAvailExtendedVirtual", ctypes.c_uint64),
            ]

        ms = _MemoryStatus()
        ms.dwLength = ctypes.sizeof(_MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return int(ms.ullTotalPhys / (1024 * 1024))
    except Exception:
        return 0


def compute_backends() -> List[Dict[str, object]]:
    """Rows for the device dropdown: GPU (if any) then CPU."""
    return accel.list_backends()


def platform_summary() -> str:
    return f"{platform.system()} {platform.release()} ({platform.machine()})"
