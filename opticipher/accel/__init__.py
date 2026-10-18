"""
accel
=====

Hardware-acceleration layer for OptiCipher (Desktop fork).

This package sits UNDER the public API: `encrypt_image` / `decrypt_image` keep
their exact signatures and the v1 file format stays bit-exact, but the heavy
pixel stages (ChaCha20 diffusion, the pixel permutation, and later the research
metrics) are routed through a pluggable compute backend.

Why a backend layer?
--------------------
The upstream reference implementation does everything in one NumPy/OpenSSL
path. That is clean and portable, but it leaves hardware on the table:

  * CPUs with several cores can XOR a large image with a ChaCha20 keystream
    several times faster than one core can (the operation is a pure stream of
    independent 64-byte blocks).
  * GPUs (via WebGPU: Metal on macOS, Vulkan on Linux, DX12/Vulkan on Windows)
    can push far more throughput on the same keystream XOR and on the
    statistical metrics.

THE HARD CONSTRAINT: BIT-EXACTNESS
----------------------------------
Every backend MUST produce the exact same bytes as the upstream reference
implementation for the same inputs. The v1 encrypted-PNG format is a promise to
users: a file encrypted by the original CLI must decrypt here (and vice
versa), and the same passphrase must always recover the same pixels. The test
suite (`tests/test_accel.py`) enforces byte-parity between backends, so any
divergence fails CI rather than corrupting someone's data.

Public surface
--------------
    get_backend()            -> the active backend instance
    configure(...)           -> set device preference / threads / RAM budget
    get_config()             -> snapshot of current settings (for the GUI)
    list_backends()          -> which backends this build can use
"""

from __future__ import annotations

from .backend import (
    AccelerationBackend,
    configure,
    get_backend,
    get_config,
    list_backends,
    shutdown,
)

__all__ = [
    "AccelerationBackend",
    "configure",
    "get_backend",
    "get_config",
    "list_backends",
    "shutdown",
]
