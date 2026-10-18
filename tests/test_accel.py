"""
test_accel.py
=============

Parity and behaviour tests for the acceleration layer (opticipher.accel).

THE POINT OF THIS FILE
----------------------
The v1 encrypted-PNG format is a compatibility promise: files must be
interchangeable with the original OptiCipher CLI, and every backend must
produce the exact same bytes as the upstream reference implementation. These
tests are the enforcement mechanism — if a backend ever drifts by a single
byte, CI fails before anyone's data can be affected.

Covered here:
  * CPU diffusion == reference diffusion, byte-for-byte, across shapes.
  * Thread/band-count invariance (1 thread == N threads, any band split).
  * Banded counter-seek edge cases around 64-byte block boundaries.
  * CPU permutation == reference permutation (forward and inverse).
  * Full core round-trip through the backend still bit-exact; wrong
    passphrase still rejected.
  * Backend selection: cpu/auto/gpu preferences, including graceful GPU
    fallback.
"""

import numpy as np
import pytest

from opticipher import decrypt_image, encrypt_image
from opticipher import diffusion as ref_diffusion
from opticipher import scramble as ref_scramble
from opticipher.accel import configure, get_backend, get_config, list_backends, shutdown
from opticipher.accel.cpu import CpuBackend, _chacha_xor_banded, _derive_nonce
from opticipher.core import DecryptionError


# Restore the default configuration after tests that change it, so test order
# never leaks settings into other files.
@pytest.fixture(autouse=True)
def _reset_config():
    yield
    configure(device="auto", threads=None, ram_budget_mb=None)


def _cpu(threads: int = 4) -> CpuBackend:
    return CpuBackend(threads=threads, ram_budget_bytes=256 * 1024 * 1024)


# ---------------------------------------------------------------------------
# Diffusion parity.
# ---------------------------------------------------------------------------
DIFFUSION_SHAPES = [
    (1, 1, 3),        # degenerate
    (1, 63, 3),       # 189 bytes: shorter than a few blocks, odd width
    (1, 64, 3),       # exactly 192 bytes = 3 blocks
    (8, 8, 3),
    (33, 47, 3),      # odd dims, row = 141 bytes (not block-aligned)
    (64, 64, 4),      # RGBA
    (100, 1, 3),      # single column
    (257, 199, 3),    # larger, row = 597 bytes
]


@pytest.mark.parametrize("shape", DIFFUSION_SHAPES)
def test_cpu_diffuse_matches_reference(shape):
    """The CPU backend must XOR with the exact reference keystream."""
    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, shape, dtype=np.uint8)
    key = rng.bytes(32)
    salt = rng.bytes(16)

    expected = ref_diffusion.diffuse(img, key, salt)
    for threads in (1, 2, 4, 8):
        got = _cpu(threads).diffuse(img, key, salt)
        assert np.array_equal(got, expected), f"drift at threads={threads}, shape={shape}"


@pytest.mark.parametrize("workers", [1, 2, 3, 5, 8, 16])
def test_banded_seek_edge_cases(workers):
    """
    Directly exercise the banded ChaCha20 at lengths around 64-byte block
    boundaries and odd worker counts: every configuration must equal the
    single-context reference stream.
    """
    rng = np.random.default_rng(11)
    key = rng.bytes(32)
    salt = rng.bytes(16)
    nonce = _derive_nonce(salt)

    for length in (0, 1, 63, 64, 65, 127, 128, 129, 4095, 4096, 4097, 65537):
        data = rng.bytes(length)
        # Reference: one continuous context over the whole buffer.
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        enc = Cipher(algorithms.ChaCha20(key, nonce), mode=None).encryptor()
        expected = enc.update(data) + enc.finalize()

        got = _chacha_xor_banded(memoryview(data), key, nonce, workers)
        assert got == expected, f"length={length}, workers={workers}"


def test_thread_count_invariance_on_large_image():
    """Bigger surface: many band splits must all agree, byte-for-byte."""
    rng = np.random.default_rng(13)
    img = rng.integers(0, 256, (311, 271, 3), dtype=np.uint8)
    key = rng.bytes(32)
    salt = rng.bytes(16)

    expected = ref_diffusion.diffuse(img, key, salt)
    for threads in (1, 2, 3, 4, 6, 7, 9, 16):
        got = _cpu(threads).diffuse(img, key, salt)
        assert np.array_equal(got, expected)


# ---------------------------------------------------------------------------
# Permutation parity.
# ---------------------------------------------------------------------------
PERM_SHAPES = [
    (1, 1, 3),
    (8, 8, 3),
    (33, 47, 3),
    (64, 64, 4),
    (100, 1, 3),
    (1, 500, 3),
]


@pytest.mark.parametrize("shape", PERM_SHAPES)
def test_cpu_scramble_matches_reference(shape):
    """int32 index storage must not change the permutation output."""
    rng = np.random.default_rng(17)
    img = rng.integers(0, 256, shape, dtype=np.uint8)
    seed = int(rng.integers(0, 2**62))

    backend = _cpu()
    assert np.array_equal(
        backend.scramble(img, seed), ref_scramble.scramble_pixels(img, seed)
    )
    assert np.array_equal(
        backend.unscramble(img, seed), ref_scramble.unscramble_pixels(img, seed)
    )


def test_cpu_scramble_unscramble_roundtrip():
    """Forward then inverse must restore the original exactly."""
    rng = np.random.default_rng(19)
    img = rng.integers(0, 256, (50, 80, 3), dtype=np.uint8)
    backend = _cpu()
    assert np.array_equal(
        backend.unscramble(backend.scramble(img, 42), 42), img
    )


# ---------------------------------------------------------------------------
# End-to-end through core.py (the real call path).
# ---------------------------------------------------------------------------
def test_core_roundtrip_through_backend():
    """encrypt_image -> decrypt_image via the backend stays bit-exact."""
    rng = np.random.default_rng(23)
    img = rng.integers(0, 256, (40, 40, 3), dtype=np.uint8)

    enc = encrypt_image(img.copy(), "backend passphrase")
    dec = decrypt_image(enc, "backend passphrase")
    assert np.array_equal(dec, img)


def test_core_wrong_passphrase_still_rejected():
    """Routing through the backend must not weaken the HMAC gate."""
    rng = np.random.default_rng(29)
    img = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)

    enc = encrypt_image(img.copy(), "right")
    with pytest.raises(DecryptionError):
        decrypt_image(enc, "wrong")


# ---------------------------------------------------------------------------
# Backend selection & configuration.
# ---------------------------------------------------------------------------
def test_cpu_preference_selects_cpu_backend():
    configure(device="cpu", threads=3)
    backend = get_backend()
    assert isinstance(backend, CpuBackend)
    assert backend.threads == 3


def test_auto_resolves_to_some_backend():
    """'auto' must always resolve — GPU here, or CPU fallback on this box."""
    configure(device="auto")
    backend = get_backend()
    assert backend.name in ("cpu", "gpu")


def test_gpu_preference_falls_back_gracefully():
    """
    Requesting gpu must never crash: either a GPU backend appears, or we get a
    CPU backend with a recorded fallback reason for the UI to display.
    """
    configure(device="gpu")
    backend = get_backend()
    if backend.name == "cpu":
        assert getattr(backend, "fallback_reason", None)


def test_config_snapshot_reflects_settings():
    configure(device="cpu", threads=5, ram_budget_mb=128)
    cfg = get_config()
    assert cfg["device"] == "cpu"
    assert cfg["resolved_threads"] == 5
    assert cfg["resolved_ram_mb"] == 128


def test_list_backends_reports_cpu_and_gpu_rows():
    rows = list_backends()
    names = {row["name"] for row in rows}
    assert "cpu" in names
    assert "gpu" in names


def test_shutdown_releases_cache_and_reresolves():
    """
    Regression pin for the process-exit heap-corruption fix.

    shutdown() must (a) drop the cached backend so a later get_backend()
    re-resolves a fresh instance, and (b) be safe to call when nothing was
    ever resolved. Leaving stale WebGPU buffers/device to be freed during
    interpreter finalization raced Qt's teardown and corrupted the heap
    ("corrupted double-linked list" crashes at exit).
    """
    configure(device="cpu")
    first = get_backend()
    assert get_backend() is first  # cached
    shutdown()
    second = get_backend()
    assert second is not first
    shutdown()  # idempotent
    shutdown()
