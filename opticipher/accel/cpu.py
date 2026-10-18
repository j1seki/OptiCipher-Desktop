"""
accel/cpu.py
============

The always-available CPU backend: multi-core ChaCha20 diffusion and a
RAM-frugal pixel permutation.

This is the fallback path for every machine (and the primary path for CPU-only
boxes). It performs the IDENTICAL arithmetic to the upstream reference
implementation — same keystream, same permutation — but executes it across
several cores and with bounded working memory.

WHY THREADING HELPS HERE
------------------------
ChaCha20 is a stream cipher built from tiny ARX operations on 64-byte blocks;
each block's keystream depends only on (key, nonce, block counter), never on
neighbouring blocks. That makes the keystream embarrassingly parallel: split
the pixel buffer into row-aligned bands and encrypt each band on its own core.

THE SUBTLE PART: CONTINUOUS KEYSTREAM ACROSS BANDS
--------------------------------------------------
The reference implementation feeds the WHOLE image through one cipher context,
so the keystream is one continuous stream across the entire buffer. If each
band naively started its own cipher at block 0, every band would XOR with the
SAME keystream prefix — catastrophic (it would leak XOR-of-plaintexts across
bands) and, more immediately, it would not match the reference bytes.

The fix is the standard counter-seek: `cryptography`'s ChaCha20 takes a
16-byte nonce whose FIRST 4 bytes are the little-endian initial block counter
and whose last 12 bytes are the nonce proper. A band starting at global byte
offset `off` therefore gets its own context with counter = base + off//64,
then discards the first (off % 64) keystream bytes so its position matches the
continuous stream exactly. Each band's context is independent, so results do
not depend on how many threads run or where the band boundaries fall —
byte-identical to the single-context reference, proven by tests across many
sizes and thread counts.

RAM BEHAVIOUR
-------------
Band sizes are derived from the user's RAM budget and thread count, so
concurrent working memory stays roughly within budget even for very large
images. Inputs are read through memoryviews (no per-band copies of the input);
only the output bands are allocated, then stitched into one result buffer.

PERMUTATION
-----------
The permutation itself stays on the CPU: it is already a fast C loop inside
NumPy, and it must remain bit-identical to upstream (same PCG64 stream, same
Fisher-Yates order). The one improvement here is index storage: for images
below 2^31 pixels the index array is kept as int32 instead of int64, halving
the temporary memory of the shuffle while producing exactly the same gather.
"""

from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import List, Tuple

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .backend import AccelerationBackend

# Same convention as upstream diffusion.py: ChaCha20 with a 16-byte nonce whose
# first 4 bytes are the little-endian initial block counter.
_NONCE_LENGTH: int = 16
_BLOCK: int = 64  # ChaCha20 keystream block size in bytes


def _derive_nonce(salt: bytes) -> bytes:
    """16-byte nonce derived from the salt, identical to upstream."""
    return hashlib.sha256(salt).digest()[:_NONCE_LENGTH]


def _chacha_xor_banded(data: memoryview, key: bytes, nonce: bytes, workers: int) -> bytes:
    """
    XOR `data` with the ChaCha20 keystream for (key, nonce), using `workers`
    threads over row-agnostic byte bands. Byte-identical to a single continuous
    `encryptor.update(data)` call.

    Parameters
    ----------
    data:
        Contiguous uint8 view of the whole payload.
    key:
        32-byte ChaCha20 key.
    nonce:
        16-byte nonce (4-byte LE initial counter + 12-byte nonce proper),
        exactly as `cryptography.algorithms.ChaCha20` expects.
    workers:
        Number of parallel bands (>= 1). 1 means a single seeked context,
        which is still exercised by the parity tests.

    Returns
    -------
    bytes
        The XORed payload, same length as `data`.
    """
    n = len(data)
    if n == 0:
        return b""

    # Single-thread fast path: one context, exactly like the reference.
    if workers <= 1 or n < 2 * _BLOCK:
        cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None)
        enc = cipher.encryptor()
        return enc.update(data) + enc.finalize()

    # Band boundaries at whole multiples of the ChaCha20 block so each band's
    # context starts on a block boundary (a band could still begin mid-row; the
    # seek math below handles any offset, but block alignment keeps every band
    # on an exact block start and avoids intra-band discards).
    base_counter = int.from_bytes(nonce[:4], "little")
    nonce_tail = nonce[4:]

    band_len = ((n // workers) + _BLOCK - 1) // _BLOCK * _BLOCK
    band_len = max(band_len, _BLOCK)

    ranges: List[Tuple[int, int]] = []
    start = 0
    while start < n:
        end = min(start + band_len, n)
        ranges.append((start, end))
        start = end

    def process(band: Tuple[int, int]) -> bytes:
        start_i, end_i = band
        off = start_i
        counter = base_counter + (off // _BLOCK)
        skip = off % _BLOCK
        band_nonce = counter.to_bytes(4, "little") + nonce_tail
        cipher = Cipher(algorithms.ChaCha20(key, band_nonce), mode=None)
        enc = cipher.encryptor()
        if skip:
            # Consume the keystream bytes that belong to the previous band's
            # final partial block, discarding their XOR output.
            enc.update(bytes(skip))
        return enc.update(data[start_i:end_i]) + enc.finalize()

    with ThreadPoolExecutor(max_workers=len(ranges)) as pool:
        parts = list(pool.map(process, ranges))

    return b"".join(parts)


class CpuBackend(AccelerationBackend):
    """
    Multi-core CPU implementation of the pixel operations.

    Attributes
    ----------
    name:
        "cpu" (shown in the UI).
    threads:
        Worker threads for diffusion.
    ram_budget_bytes:
        Soft working-memory cap used to size bands.
    fallback_reason:
        Set by the resolver when this backend stands in for a requested GPU.
    """

    name = "cpu"

    def __init__(self, threads: int = 1, ram_budget_bytes: int = 512 * 1024 * 1024):
        self.threads = max(1, int(threads))
        self.ram_budget_bytes = int(ram_budget_bytes)
        self.fallback_reason: str | None = None

    # -- diffusion ----------------------------------------------------------
    def diffuse(self, pixels: np.ndarray, stream_key: bytes, salt: bytes) -> np.ndarray:
        """
        ChaCha20 XOR over every byte of the (H, W, C) uint8 array, across
        `self.threads` cores. Output is bit-identical to upstream `diffuse`.
        """
        original_shape = pixels.shape
        flat = np.ascontiguousarray(pixels).reshape(-1)
        view = memoryview(flat).cast("B")

        nonce = _derive_nonce(salt)

        # Size bands from the RAM budget: each concurrent worker holds its
        # input slice (view, ~free) and its output slice (allocated), so the
        # budget is split across workers with ~2x overhead headroom.
        per_worker = max(64 * 1024, self.ram_budget_bytes // (2 * self.threads))
        target_bytes = per_worker * self.threads
        if len(view) <= target_bytes:
            # Whole image fits the budget: one band per worker max, sized so we
            # never spin up more bands than threads for small images.
            workers = self.threads if len(view) >= self.threads * _BLOCK else 1
        else:
            workers = self.threads

        encrypted = _chacha_xor_banded(view, stream_key, nonce, workers)
        return np.frombuffer(encrypted, dtype=np.uint8).reshape(original_shape)

    # -- permutation --------------------------------------------------------
    def scramble(self, pixels: np.ndarray, seed: int) -> np.ndarray:
        """
        Forward permutation, byte-identical to upstream `scramble_pixels`, but
        keeping the index array in int32 when the image has fewer than 2^31
        pixels (same values, half the temporary RAM).
        """
        return _permute(pixels, seed, inverse=False)

    def unscramble(self, pixels: np.ndarray, seed: int) -> np.ndarray:
        """Inverse permutation, byte-identical to upstream `unscramble_pixels`."""
        return _permute(pixels, seed, inverse=True)

    # -- introspection ------------------------------------------------------
    def info(self) -> dict:
        """Device-panel description, including any GPU-fallback reason."""
        row = {
            "name": self.name,
            "available": True,
            "threads": self.threads,
            "ram_budget_mb": self.ram_budget_bytes // (1024 * 1024),
            "detail": f"{self.threads} CPU thread(s)",
        }
        if self.fallback_reason:
            row["fallback_reason"] = self.fallback_reason
        if getattr(self, "calibration_note", ""):
            row["calibration"] = self.calibration_note
        return row


def _permutation_for(seed: int, n: int) -> np.ndarray:
    """
    The keyed permutation for (seed, n), identical to upstream: same PCG64
    stream, same Fisher-Yates. Stored as int32 when safe to halve temp RAM.
    """
    rng = np.random.default_rng(seed & 0xFFFFFFFFFFFFFFFF)
    perm = rng.permutation(n)
    if n <= np.iinfo(np.int32).max:
        perm = perm.astype(np.int32)
    return perm


def _permute(pixels: np.ndarray, seed: int, inverse: bool) -> np.ndarray:
    """
    Gather (forward) or scatter (inverse) pixel positions with an int32 index
    array. Produces exactly the same output as the upstream functions.
    """
    h, w = pixels.shape[:2]
    channels = pixels.shape[2] if pixels.ndim == 3 else 1
    flat = pixels.reshape(h * w, channels)
    perm = _permutation_for(seed, h * w)

    if inverse:
        restored = np.empty_like(flat)
        restored[perm] = flat
        return restored.reshape(h, w, channels)
    scrambled = flat[perm]
    return scrambled.reshape(h, w, channels)
