"""
diffusion.py
============

Colour-value diffusion (the RGB stream cipher) for OptiCipher.

ROLE IN THE PIPELINE
--------------------
Scrambling (scramble.py) moves pixels around but does NOT change any colour
value, so a histogram of the scrambled image is identical to the original. An
attacker could still learn a lot from that histogram (e.g. "this image is mostly
black with some orange", which already leaks the look of our sample). This stage
fixes that by XOR-ing every colour byte with a pseudo-random keystream, so the
output histogram becomes flat/uniform and individual colour values are masked.

  scramble  -> hides WHERE colours are (spatial confusion)
  diffusion -> hides WHAT the colours are (value confusion)

Together they approximate the classic "confusion + diffusion" design principle.

WHY ChaCha20?
-------------
ChaCha20 is a modern, fast, well-vetted stream cipher (used in TLS). We use it
purely as a keystream generator: encrypt = decrypt = XOR with the keystream.
Because XOR is its own inverse, the same function both encrypts and decrypts,
which keeps the code small and obviously-correct.

We get ChaCha20 from the `cryptography` package's hazmat layer. The nonce is
fixed-derived per image (see below) and the key comes from the KDF, so we never
reuse a (key, nonce) pair across two different passphrases/salts.

    SECURITY NOTE ON THE NONCE
    --------------------------
    A stream cipher MUST NOT reuse the same (key, nonce) pair for two different
    plaintexts, or XOR-ing the two ciphertexts cancels the keystream. In
    OptiCipher every image gets a fresh random `salt`, the salt feeds PBKDF2,
    and PBKDF2 produces a fresh `stream_key`. Because the key itself is unique
    per image, a constant nonce is safe *here*. We still derive the nonce from
    the salt for defence in depth and to make the construction explicit.

    RESEARCH NOTE
    -------------
    `metrics.py` reports the histogram and Shannon entropy of each channel so a
    researcher can verify empirically that diffusion flattens the distribution
    (entropy should approach 8.0 bits/byte for a well-diffused image).
"""

from __future__ import annotations

import hashlib

import numpy as np
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


# ChaCha20 in the `cryptography` library is exposed via the generic Cipher API
# using a 256-bit key and a 16-byte nonce (the first 4 bytes act as an initial
# block counter; the remaining 12 are the nonce proper).
_NONCE_LENGTH: int = 16


def _derive_nonce(salt: bytes) -> bytes:
    """
    Deterministically derive a 16-byte ChaCha20 nonce from the image salt.

    We hash the salt with SHA256 and take the first 16 bytes. Since the salt is
    unique per image and the stream key is also unique per image, this nonce
    only needs to be unique-ish; deriving it from the salt guarantees the
    decryptor computes the identical nonce without storing it separately.
    """
    return hashlib.sha256(salt).digest()[:_NONCE_LENGTH]


def _keystream_xor(data: bytes, key: bytes, salt: bytes) -> bytes:
    """
    XOR `data` with the ChaCha20 keystream generated from (key, nonce(salt)).

    Because XOR is symmetric, this single helper performs both encryption and
    decryption. Encryptor and decryptor pass identical (key, salt), so they
    generate identical keystreams and the operation round-trips perfectly.
    """
    nonce = _derive_nonce(salt)
    cipher = Cipher(algorithms.ChaCha20(key, nonce), mode=None)
    encryptor = cipher.encryptor()
    return encryptor.update(data) + encryptor.finalize()


def diffuse(pixels: np.ndarray, stream_key: bytes, salt: bytes) -> np.ndarray:
    """
    Apply the colour-value stream cipher to every pixel byte.

    Parameters
    ----------
    pixels:
        uint8 array of shape (H, W, C). Every byte is encrypted, including all
        channels. (For RGBA images this also masks the alpha channel; that is
        fine and round-trips correctly.)
    stream_key:
        32-byte key from the KDF.
    salt:
        Per-image salt, used to derive the nonce.

    Returns
    -------
    np.ndarray
        Encrypted pixels, same shape and dtype.
    """
    original_shape = pixels.shape
    flat_bytes = pixels.tobytes()  # row-major, C-contiguous byte stream
    encrypted = _keystream_xor(flat_bytes, stream_key, salt)
    # Rebuild the array from the encrypted byte stream.
    return np.frombuffer(encrypted, dtype=np.uint8).reshape(original_shape)


def undiffuse(pixels: np.ndarray, stream_key: bytes, salt: bytes) -> np.ndarray:
    """
    Reverse the colour-value stream cipher.

    Identical to :func:`diffuse` because XOR with the same keystream is its own
    inverse. Provided as a separate name purely for readability at call sites.
    """
    return diffuse(pixels, stream_key, salt)
