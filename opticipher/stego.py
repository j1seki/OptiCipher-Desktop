"""
stego.py
========

Reserved-strip storage for OptiCipher's self-contained header.

DESIGN RATIONALE
----------------
OptiCipher's distinguishing feature is that the encrypted image is
*self-contained*: everything the decryptor needs (except the user's passphrase)
travels INSIDE the image file. That metadata is the "header":

    magic + version + salt + iterations + dimensions + channels + strip_rows + HMAC

Early designs hid the header in the least-significant bits of the ciphertext
pixels. That is elegant but creates a subtle round-trip problem: the LSBs you
overwrite are themselves real ciphertext that must be decrypted exactly, and
recovering them leads to a self-referential ("snapshot of my own snapshot")
sizing paradox.

OptiCipher instead appends a small **reserved strip** of extra pixel rows to the
bottom of the scrambled+diffused image and writes the header bytes DIRECTLY into
that strip. Properties:

  * No self-reference, no paradox: the strip is dedicated storage.
  * Bit-exact round trip: the strip is removed on decryption, and the main image
    is transformed back to the precise original.
  * The main ciphertext stays visually intact; only a thin band at the bottom
    carries metadata (and that band is itself indistinguishable random-looking
    bytes for the HMAC/salt portions).

This module knows how to (a) size and append the strip, (b) write header bytes
into it, (c) read header bytes back, and (d) slice the strip off.

    SECURITY NOTE
    -------------
    The salt and iteration count in the strip are NOT secret — exactly like the
    plaintext salt stored beside a normal password hash. Confidentiality rests
    entirely on the passphrase via the KDF, the stream cipher, and the keyed
    permutation. The HMAC authenticates integrity and is only verifiable by
    someone who can re-derive the MAC key (i.e. who knows the passphrase).
"""

from __future__ import annotations

import numpy as np


def rows_needed(header_len: int, width: int, channels: int) -> int:
    """
    How many extra rows are needed to store `header_len` bytes.

    One row holds `width * channels` bytes. We round up so the header always
    fits, even if it leaves a few unused padding bytes in the last row.

    Raises
    ------
    ValueError
        If width or channels is non-positive (degenerate image).
    """
    if width <= 0 or channels <= 0:
        raise ValueError("width and channels must be positive")
    bytes_per_row = width * channels
    return (header_len + bytes_per_row - 1) // bytes_per_row  # ceil division


def append_strip(pixels: np.ndarray, header_bytes: bytes) -> np.ndarray:
    """
    Append a reserved strip below `pixels` and write `header_bytes` into it.

    Parameters
    ----------
    pixels:
        The scrambled+diffused main image, uint8, shape (H, W, C).
    header_bytes:
        The fully packed header to store.

    Returns
    -------
    np.ndarray
        A new image of shape (H + strip_rows, W, C). The first H rows are the
        untouched main ciphertext; the appended rows carry the header followed
        by zero padding.

    Notes
    -----
    The caller (core.py) is responsible for recording `strip_rows` inside the
    header itself so the decryptor can slice the strip off again.
    """
    h, w, channels = pixels.shape
    n_rows = rows_needed(len(header_bytes), w, channels)

    # Build the strip as a flat byte buffer, header first then zero padding.
    strip_capacity = n_rows * w * channels
    strip_flat = np.zeros(strip_capacity, dtype=np.uint8)
    strip_flat[: len(header_bytes)] = np.frombuffer(header_bytes, dtype=np.uint8)
    strip = strip_flat.reshape(n_rows, w, channels)

    return np.vstack([pixels, strip])


def read_strip(pixels: np.ndarray, strip_rows: int, header_len: int) -> bytes:
    """
    Read `header_len` header bytes from the bottom `strip_rows` rows.

    Parameters
    ----------
    pixels:
        The full encrypted image including the strip.
    strip_rows:
        How many rows form the strip (from the parsed header).
    header_len:
        How many bytes to read back (HEADER_SIZE).

    Returns
    -------
    bytes
        The header bytes.

    Raises
    ------
    ValueError
        If the image does not have enough rows for the claimed strip.
    """
    h = pixels.shape[0]
    if strip_rows <= 0 or strip_rows >= h:
        raise ValueError("invalid strip_rows for this image")
    strip = pixels[h - strip_rows :]
    return strip.reshape(-1).tobytes()[:header_len]


def peek_header_bytes(pixels: np.ndarray, header_len: int) -> bytes:
    """
    Read the first `header_len` bytes of the LAST row group, before we know how
    many strip rows there are.

    The header begins at the very start of the strip, and the strip is the LAST
    `strip_rows` rows. Since the header (with its `strip_rows` field) fits within
    the first row's worth of bytes for any reasonable width, we can read it from
    a candidate region. To stay simple and robust, core.py first reads enough
    bytes from the final rows to parse the fixed-size header.

    This helper reads the final `ceil(header_len / (W*C))` rows and returns the
    leading `header_len` bytes — which is exactly where the header sits because
    the header is written at the very top of the strip.
    """
    h, w, channels = pixels.shape
    bytes_per_row = w * channels
    candidate_rows = (header_len + bytes_per_row - 1) // bytes_per_row
    candidate_rows = min(candidate_rows, h - 1)  # never consume the whole image
    region = pixels[h - candidate_rows :]
    return region.reshape(-1).tobytes()[:header_len]


def remove_strip(pixels: np.ndarray, strip_rows: int) -> np.ndarray:
    """
    Return the main image with the bottom `strip_rows` rows removed.

    This yields the scrambled+diffused image exactly as it was before the strip
    was appended, ready for inverse diffusion and unscrambling.
    """
    h = pixels.shape[0]
    return pixels[: h - strip_rows].copy()
