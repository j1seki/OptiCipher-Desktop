"""
test_metrics_and_sample.py
==========================

Tests for the research metrics module and an integration test that runs the full
pipeline on the bundled sample image (the "CLAUDE CODE" PNG).

The metric thresholds here are intentionally loose: they assert that encryption
moves each metric strongly in the expected direction, not that it hits a precise
literature value (which varies slightly with image content and sampling).
"""

from pathlib import Path

import numpy as np
import pytest

from opticipher import decrypt_image, encrypt_image, load_image
from opticipher import metrics

SAMPLE = Path(__file__).resolve().parent.parent / "samples" / "sample_claude_code.png"


@pytest.fixture(scope="module")
def sample_image():
    """Load the bundled sample once for all tests in this module."""
    if not SAMPLE.exists():
        pytest.skip(f"sample image not found at {SAMPLE}")
    return load_image(SAMPLE)


# ---------------------------------------------------------------------------
# Metric primitives
# ---------------------------------------------------------------------------
def test_entropy_of_uniform_is_near_eight():
    """A uniform random channel should have entropy close to 8 bits/byte."""
    rng = np.random.default_rng(0)
    channel = rng.integers(0, 256, (256, 256), dtype=np.uint8)
    assert metrics.shannon_entropy(channel) > 7.9


def test_entropy_of_constant_is_zero():
    """A constant channel carries no information -> entropy 0."""
    channel = np.full((50, 50), 7, dtype=np.uint8)
    assert metrics.shannon_entropy(channel) == 0.0


def test_correlation_of_gradient_is_high():
    """A smooth gradient has strong adjacent-pixel correlation (~1)."""
    grad = np.tile(np.arange(256, dtype=np.uint8), (256, 1))
    r = metrics.adjacent_correlation(grad)["horizontal"]
    assert r > 0.9


def test_npcr_uaci_identical_images_are_zero():
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    assert metrics.npcr(img, img) == 0.0
    assert metrics.uaci(img, img) == 0.0


# ---------------------------------------------------------------------------
# Full-pipeline integration on the real sample
# ---------------------------------------------------------------------------
def test_sample_roundtrip_exact(sample_image):
    enc = encrypt_image(sample_image.copy(), "demo-pass")
    dec = decrypt_image(enc, "demo-pass")
    assert np.array_equal(dec, sample_image)


def test_sample_entropy_increases(sample_image):
    """Encryption should drive per-channel entropy toward 8 bits/byte."""
    enc_main = encrypt_image(sample_image.copy(), "demo")[: sample_image.shape[0]]

    orig = metrics.entropy_report(sample_image)["mean"]
    enc = metrics.entropy_report(enc_main)["mean"]

    assert orig < 6.0  # the text image is low-entropy
    assert enc > 7.99  # ciphertext is near-uniform


def test_sample_correlation_drops(sample_image):
    """Adjacent-pixel correlation should collapse toward zero after encryption."""
    enc_main = encrypt_image(sample_image.copy(), "demo")[: sample_image.shape[0]]

    orig = metrics.adjacent_correlation(sample_image[:, :, 0])["horizontal"]
    enc = metrics.adjacent_correlation(enc_main[:, :, 0])["horizontal"]

    assert abs(orig) > 0.8   # original is highly correlated
    assert abs(enc) < 0.05   # ciphertext is essentially uncorrelated


def test_sample_npcr_uaci_in_expected_range(sample_image):
    """One-pixel plaintext change should avalanche through the ciphertext."""
    a = sample_image.copy()
    b = sample_image.copy()
    b[0, 0, 0] ^= 1

    ea = encrypt_image(a, "k")[: sample_image.shape[0]]
    eb = encrypt_image(b, "k")[: sample_image.shape[0]]

    npcr = metrics.npcr(ea, eb)
    uaci = metrics.uaci(ea, eb)

    # Loose bounds around the ideal 8-bit values (NPCR ~99.6, UACI ~33.4).
    assert 99.0 < npcr <= 100.0
    assert 30.0 < uaci < 36.0
