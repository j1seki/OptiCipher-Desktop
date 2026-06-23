"""
test_roundtrip.py
=================

End-to-end correctness tests: encrypting then decrypting must reproduce the
original image bit-for-bit, and the scheme must reject wrong passphrases and
tampering.

These are the most important tests in the project: lossless round-tripping is
the core promise of OptiCipher.
"""

import numpy as np
import pytest

from opticipher import decrypt_image, encrypt_image
from opticipher.core import DecryptionError


# A spread of shapes, including odd sizes, a single-row image, and RGBA, to make
# sure the reserved-strip sizing and the permutation work for any geometry.
SHAPES = [
    (1, 500, 3),    # single tall-width row
    (8, 8, 3),      # tiny square
    (20, 20, 3),
    (33, 47, 3),    # non-square, prime-ish dims
    (64, 64, 4),    # RGBA
    (100, 1, 3),    # single column
]


@pytest.mark.parametrize("shape", SHAPES)
def test_roundtrip_is_bit_exact(shape):
    """Decrypting an encrypted image must return the exact original bytes."""
    rng = np.random.default_rng(12345)
    img = rng.integers(0, 256, shape, dtype=np.uint8)

    encrypted = encrypt_image(img.copy(), "correct horse battery staple")
    decrypted = decrypt_image(encrypted, "correct horse battery staple")

    assert decrypted.shape == img.shape
    assert np.array_equal(decrypted, img)


def test_roundtrip_with_unicode_passphrase():
    """Non-ASCII (e.g. Arabic) passphrases must work consistently."""
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (40, 40, 3), dtype=np.uint8)
    secret = "كلمة سر قوية ١٢٣"

    encrypted = encrypt_image(img.copy(), secret)
    decrypted = decrypt_image(encrypted, secret)

    assert np.array_equal(decrypted, img)


def test_wrong_passphrase_is_rejected():
    """A wrong passphrase must fail the HMAC check, not silently return junk."""
    rng = np.random.default_rng(2)
    img = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)

    encrypted = encrypt_image(img.copy(), "right-passphrase")
    with pytest.raises(DecryptionError):
        decrypt_image(encrypted, "wrong-passphrase")


def test_tampering_is_detected():
    """Flipping a ciphertext pixel must trigger an integrity failure."""
    rng = np.random.default_rng(3)
    img = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)

    encrypted = encrypt_image(img.copy(), "secret")
    # Tamper with a main-image pixel (not in the strip).
    encrypted[0, 0, 0] ^= 0xFF

    with pytest.raises(DecryptionError):
        decrypt_image(encrypted, "secret")


def test_two_encryptions_differ():
    """
    Encrypting the same image twice must yield different ciphertexts, because a
    fresh random salt is drawn each time. This is essential to avoid leaking
    that two files share a plaintext.
    """
    rng = np.random.default_rng(4)
    img = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)

    e1 = encrypt_image(img.copy(), "secret")
    e2 = encrypt_image(img.copy(), "secret")

    # Compare only the main region (strips also differ via salt/hmac).
    assert not np.array_equal(e1[: img.shape[0]], e2[: img.shape[0]])


def test_non_opticipher_image_raises_valueerror():
    """Feeding a plain image to the decryptor should fail with a clear error."""
    rng = np.random.default_rng(5)
    img = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)

    with pytest.raises(ValueError):
        decrypt_image(img, "secret")
