"""
test_gpu_accel.py
=================

Golden-vector and parity tests for the WebGPU backend (opticipher.accel.gpu).

These tests are the CI enforcement of the format promise for the GPU path:
the WGSL ChaCha20 kernel must reproduce the reference keystream byte-for-byte,
and the metric kernels must return exactly the reference values. A single
diverging byte fails the build.

The whole module is skipped when no usable WebGPU adapter exists (typical for
headless CI runners): GPU acceleration is an enhancement with a CPU fallback,
never a requirement for the suite to be green.
"""

import numpy as np
import pytest

from opticipher import decrypt_image, encrypt_image
from opticipher import diffusion as ref_diffusion
from opticipher import scramble as ref_scramble
from opticipher import metrics as ref_metrics
from opticipher.accel import configure
from opticipher.accel.cpu import _derive_nonce
from opticipher.accel.gpu import GpuBackend
from opticipher.core import DecryptionError

# ---------------------------------------------------------------------------
# One shared backend for the whole module (device creation is cached inside).
# ---------------------------------------------------------------------------
_gb = GpuBackend()

pytestmark = pytest.mark.skipif(
    not _gb.usable, reason="no usable WebGPU adapter on this machine"
)


@pytest.fixture(autouse=True)
def _reset_config():
    yield
    configure(device="auto", threads=None, ram_budget_mb=None)


def _reference_chacha(data: bytes, key: bytes, salt: bytes) -> bytes:
    """Single continuous context — the ground truth for every comparison."""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    enc = Cipher(algorithms.ChaCha20(key, _derive_nonce(salt)), mode=None).encryptor()
    return enc.update(data) + enc.finalize()


# ---------------------------------------------------------------------------
# Golden keystream vectors: CPU (OpenSSL) vs GPU (WGSL), byte-for-byte.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "length",
    [1, 63, 64, 65, 127, 128, 129, 191, 192, 193, 1000, 4096, 65536, 65537, 100_003],
)
def test_gpu_chacha_matches_cpu_reference(length):
    rng = np.random.default_rng(101)
    key = rng.bytes(32)
    salt = rng.bytes(16)
    data = rng.bytes(length)

    expected = _reference_chacha(data, key, salt)
    got = _gb.diffuse_bytes(memoryview(data), key, salt)
    assert got == expected, f"GPU keystream drift at length={length}"


@pytest.mark.parametrize("shape", [(256, 256, 3), (333, 171, 3), (64, 64, 4), (1, 4096, 3)])
def test_gpu_diffuse_image_parity(shape):
    """Full-image path (CPU tail + GPU blocks) stays byte-exact."""
    rng = np.random.default_rng(103)
    img = rng.integers(0, 256, shape, dtype=np.uint8)
    key = rng.bytes(32)
    salt = rng.bytes(16)

    expected = ref_diffusion.diffuse(img, key, salt)
    got = _gb.diffuse(img, key, salt)
    assert np.array_equal(got, expected)


def test_gpu_scramble_matches_reference():
    """Permutation is CPU-delegated; must equal the reference exactly."""
    rng = np.random.default_rng(107)
    img = rng.integers(0, 256, (97, 83, 3), dtype=np.uint8)
    seed = int(rng.integers(0, 2**62))
    assert np.array_equal(_gb.scramble(img, seed), ref_scramble.scramble_pixels(img, seed))
    assert np.array_equal(
        _gb.unscramble(img, seed), ref_scramble.unscramble_pixels(img, seed)
    )


# ---------------------------------------------------------------------------
# Metric kernels: exact equality with the reference implementation.
# ---------------------------------------------------------------------------
def test_gpu_histograms_exact():
    rng = np.random.default_rng(109)
    img = rng.integers(0, 256, (517, 389, 3), dtype=np.uint8)
    got = _gb.histograms(img)
    for c in range(3):
        assert np.array_equal(got[c], ref_metrics.histogram(img[:, :, c]))


def test_gpu_npcr_uaci_exact():
    rng = np.random.default_rng(113)
    a = rng.integers(0, 256, (331, 279, 3), dtype=np.uint8)
    b = a.copy()
    b[10:14, 20:25] ^= 1  # sparse single-region change
    assert _gb.npcr(a, b) == ref_metrics.npcr(a, b)
    assert _gb.uaci(a, b) == ref_metrics.uaci(a, b)


def test_gpu_npcr_uaci_exact_on_large_random():
    """Exercise the partial-reduction path with many workgroups."""
    rng = np.random.default_rng(127)
    a = rng.integers(0, 256, (1400, 1200, 3), dtype=np.uint8)
    b = rng.integers(0, 256, (1400, 1200, 3), dtype=np.uint8)  # fully unrelated
    assert _gb.npcr(a, b) == ref_metrics.npcr(a, b)
    assert _gb.uaci(a, b) == ref_metrics.uaci(a, b)


def test_gpu_npcr_identical_images_zero():
    rng = np.random.default_rng(131)
    a = rng.integers(0, 256, (200, 200, 3), dtype=np.uint8)
    assert _gb.npcr(a, a) == 0.0
    assert _gb.uaci(a, a) == 0.0


# ---------------------------------------------------------------------------
# End-to-end through core with the GPU selected, plus cross-backend flows.
# ---------------------------------------------------------------------------
def test_gpu_backend_end_to_end_roundtrip():
    configure(device="gpu")
    rng = np.random.default_rng(137)
    img = rng.integers(0, 256, (120, 90, 3), dtype=np.uint8)

    enc = encrypt_image(img.copy(), "gpu passphrase")
    dec = decrypt_image(enc, "gpu passphrase")
    assert np.array_equal(dec, img)


def test_cpu_encrypted_decrypts_on_gpu_backend():
    """The interchange promise: file from the CPU path opens on the GPU path."""
    configure(device="cpu")
    rng = np.random.default_rng(139)
    img = rng.integers(0, 256, (100, 80, 4), dtype=np.uint8)
    enc = encrypt_image(img.copy(), "cross backend")

    configure(device="gpu")
    dec = decrypt_image(enc, "cross backend")
    assert np.array_equal(dec, img)


def test_gpu_wrong_passphrase_still_rejected():
    configure(device="gpu")
    rng = np.random.default_rng(149)
    img = rng.integers(0, 256, (60, 60, 3), dtype=np.uint8)
    enc = encrypt_image(img.copy(), "right")
    with pytest.raises(DecryptionError):
        decrypt_image(enc, "wrong")


# ---------------------------------------------------------------------------
# Device discovery / introspection.
# ---------------------------------------------------------------------------
def test_gpu_info_reports_adapter_fields():
    info = _gb.info()
    assert info["available"] is True
    assert info["name"] == "gpu"
    # vendor/backend_type come from the adapter; present on all platforms.
    assert "backend_type" in info
    assert "adapter" in info


# ---------------------------------------------------------------------------
# Deterministic teardown (process-exit corruption regression guard).
# ---------------------------------------------------------------------------
def test_gpu_close_releases_buffers_before_device():
    """
    GpuBackend.close() must drop cached buffers, then pipelines, then the
    device — the strict order accel.shutdown() relies on. Freeing cached
    WebGPU buffers during interpreter finalization (GC order undefined)
    raced Qt's own teardown and corrupted the heap: sporadic
    "corrupted double-linked list" aborts at process exit.
    """
    gpu = GpuBackend()
    assert gpu.usable
    rng = np.random.default_rng(77)
    img = rng.integers(0, 256, (256, 256, 3), dtype=np.uint8)
    gpu.diffuse(img, b"\x11" * 32, b"\x22" * 16)
    assert gpu._buf_cache  # the call populated the buffer cache
    gpu.close()
    assert gpu._buf_cache == {}
    assert gpu._chacha_pipeline is None
    assert gpu._hist_pipeline is None
    assert gpu._npcr_uaci_pipeline is None
    assert gpu._device is None
