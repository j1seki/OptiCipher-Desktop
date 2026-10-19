"""
core.py
=======

The orchestration layer that wires every OptiCipher stage together.

PIPELINE OVERVIEW
-----------------
Encryption (encrypt_image):

    plaintext pixels (H x W x C)
        |  1. derive keys from passphrase + fresh salt        (keys.py)
        |  2. SCRAMBLE pixel positions                        (scramble.py)
        |  3. DIFFUSE colour values with ChaCha20             (diffusion.py)
        |  4. build header, compute HMAC over ciphertext      (this file)
        |  5. append a reserved strip carrying the header     (stego.py)
        v
    self-contained ciphertext image (H+strip_rows x W x C)

Decryption (decrypt_image):

    ciphertext image
        |  1. read + parse header from the reserved strip     (stego.py/header.py)
        |  2. re-derive keys from passphrase + embedded salt  (keys.py)
        |  3. strip removed -> recover main ciphertext        (stego.py)
        |  4. verify HMAC over the main ciphertext            (this file)
        |  5. UN-DIFFUSE, then UN-SCRAMBLE                     (diffusion/scramble)
        v
    exact original plaintext image

WHY THIS ORDERING IS SOUND
--------------------------
* "Encrypt-then-MAC": we authenticate the already-encrypted main image, the
  ordering cryptographers recommend. The header's metadata fields are included
  in the MAC too, so iteration count, dimensions, and strip size are all
  tamper-evident.
* The reserved strip is dedicated storage appended below the image, so writing
  the header never disturbs a single ciphertext pixel and the round trip is
  bit-exact (lossless), provided the file is stored in a lossless format (PNG).
* A wrong passphrase derives a wrong MAC key, so the HMAC check fails and we
  refuse to emit a bogus "decryption".
"""

from __future__ import annotations

import hashlib
import hmac as _hmac

import numpy as np

from . import diffusion, header, keys, scramble, stego
from .accel import get_backend


def _compute_hmac(
    mac_key: bytes,
    prehmac_header: bytes,
    main_cipher: np.ndarray,
) -> bytes:
    """
    HMAC-SHA256 over (pre-HMAC header bytes || raw bytes of the main ciphertext).

    The main ciphertext here is the scrambled+diffused image WITHOUT the reserved
    strip, so both sides authenticate the identical pixel block.
    """
    mac = _hmac.new(mac_key, digestmod=hashlib.sha256)
    mac.update(prehmac_header)
    mac.update(main_cipher.tobytes())
    return mac.digest()


# ---------------------------------------------------------------------------
# Public API: encryption.
# ---------------------------------------------------------------------------
def encrypt_image(
    pixels: np.ndarray,
    passphrase: str,
    iterations: int = keys.DEFAULT_ITERATIONS,
) -> np.ndarray:
    """
    Encrypt an image array into a self-contained OptiCipher ciphertext image.

    Parameters
    ----------
    pixels:
        uint8 array of shape (H, W, C) with C in {3, 4}.
    passphrase:
        The user's secret. UTF-8 friendly (supports Arabic, etc.).
    iterations:
        PBKDF2 iteration count to use and record in the header.

    Returns
    -------
    np.ndarray
        The encrypted image (taller than the input by the reserved strip).

    Raises
    ------
    ValueError
        On unsupported shapes/dtypes.
    """
    if pixels.dtype != np.uint8:
        raise ValueError("pixels must be a uint8 array")
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
        raise ValueError("pixels must have shape (H, W, 3) or (H, W, 4)")
    # The header stores iterations as uint32; reject anything struct.pack
    # would fail on late (struct.error) or that no decryptor would accept.
    if not (0 < iterations <= 0xFFFFFFFF):
        raise ValueError(
            f"iterations must be in 1..{0xFFFFFFFF}, got {iterations}"
        )

    h, w, channels = pixels.shape

    # 1. Fresh salt + derived keys (unique keystream/permutation per image).
    salt = keys.generate_salt()
    derived = keys.derive_keys(passphrase, salt, iterations)

    # 2. Spatial confusion: shuffle pixel positions.
    #    (Routed through the acceleration backend; the permutation itself is
    #    bit-identical to `scramble.scramble_pixels`.)
    scrambled = get_backend().scramble(pixels, derived.scramble_seed)

    # 3. Value diffusion: stream-cipher the colour bytes.
    #    (Routed through the acceleration backend; byte-identical to
    #    `diffusion.diffuse`.)
    diffused = get_backend().diffuse(scrambled, derived.stream_key, salt)

    # 4. Determine strip size, build the header, and authenticate the main image.
    strip_rows = stego.rows_needed(header.HEADER_SIZE, w, channels)
    hdr = header.Header(
        salt=salt,
        iterations=iterations,
        height=h,
        width=w,
        channels=channels,
        strip_rows=strip_rows,
    )
    hdr.hmac = _compute_hmac(derived.mac_key, hdr.pack_prehmac(), diffused)

    # 5. Append the reserved strip carrying the full (now authenticated) header.
    output = stego.append_strip(diffused, hdr.pack())

    return output


# ---------------------------------------------------------------------------
# Public API: decryption.
# ---------------------------------------------------------------------------
class DecryptionError(Exception):
    """
    Raised when decryption cannot be trusted.

    The most common cause is a wrong passphrase; the second most common is a
    corrupted or tampered file. We deliberately do NOT distinguish the two,
    because revealing "right passphrase but tampered" vs "wrong passphrase" can
    leak information to an attacker.
    """


def decrypt_image(pixels: np.ndarray, passphrase: str) -> np.ndarray:
    """
    Decrypt an OptiCipher ciphertext image back to its exact original.

    Parameters
    ----------
    pixels:
        The encrypted uint8 array (including the reserved strip).
    passphrase:
        The passphrase used at encryption time.

    Returns
    -------
    np.ndarray
        The recovered plaintext image, bit-for-bit identical to the original.

    Raises
    ------
    DecryptionError
        If the HMAC check fails (wrong passphrase or tampering).
    ValueError
        If the file is not a valid OptiCipher image.
    """
    if pixels.dtype != np.uint8:
        raise ValueError("pixels must be a uint8 array")
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
        raise ValueError("pixels must have shape (H, W, 3) or (H, W, 4)")

    # 1. The header sits at the TOP of the reserved strip, i.e. the leading bytes
    #    of the final rows. Read a candidate region big enough for the fixed
    #    header and parse it (this also yields strip_rows).
    candidate = stego.peek_header_bytes(pixels, header.HEADER_SIZE)
    hdr = header.parse(candidate)  # raises ValueError on bad magic/size

    # 1b. Cheap plausibility bounds on UNTRUSTED header fields BEFORE any
    #     expensive or structural work. None of these values are authenticated
    #     yet, so an attacker must not be able to force large CPU/memory cost
    #     ahead of the HMAC check (the iterations field alone could otherwise
    #     stall a victim for hours in PBKDF2). Genuine v1 files sit far below
    #     every bound; a file failing here is corrupt or crafted, and the
    #     generic error keeps the wrong-passphrase/tamper distinction hidden.
    if hdr.iterations <= 0 or hdr.iterations > keys.MAX_UNVERIFIED_ITERATIONS:
        raise DecryptionError(
            "integrity check failed: wrong passphrase or the file was modified."
        )
    if hdr.channels not in (3, 4) or hdr.width <= 0 or hdr.height <= 0:
        raise DecryptionError(
            "integrity check failed: wrong passphrase or the file was modified."
        )
    h_img, w_img = pixels.shape[0], pixels.shape[1]
    if hdr.strip_rows <= 0 or hdr.strip_rows >= h_img:
        raise DecryptionError(
            "integrity check failed: wrong passphrase or the file was modified."
        )
    # A valid strip holds at least a full header plus one row's worth of room
    # rounding; reject strip sizes that could not have been produced by the
    # format (rows_needed is ceil(HEADER_SIZE / (width * channels))).
    max_strip = stego.rows_needed(header.HEADER_SIZE, w_img, hdr.channels) + 1
    if hdr.strip_rows > max_strip:
        raise DecryptionError(
            "integrity check failed: wrong passphrase or the file was modified."
        )

    # 2. Re-derive keys from passphrase + embedded salt/iterations.
    derived = keys.derive_keys(passphrase, hdr.salt, hdr.iterations)

    # 3. Remove the reserved strip to recover the main ciphertext exactly.
    main_cipher = stego.remove_strip(pixels, hdr.strip_rows)

    # Sanity-check the recovered dimensions against the authenticated header.
    if main_cipher.shape[:2] != (hdr.height, hdr.width):
        raise DecryptionError(
            "image dimensions do not match the embedded header (corrupted file)."
        )

    # 4. Verify integrity / passphrase via HMAC over the main ciphertext.
    expected = _compute_hmac(derived.mac_key, hdr.pack_prehmac(), main_cipher)
    if not _hmac.compare_digest(expected, hdr.hmac):
        raise DecryptionError(
            "integrity check failed: wrong passphrase or the file was modified."
        )

    # 4b. Every header field is now authenticated, the format version included.
    #     Only against a verified HMAC is a version decision safe (a tampered
    #     version byte fails step 4 first; a genuine future-version file with a
    #     valid tag gets an explicit, actionable error instead of a confusing
    #     "wrong passphrase" one).
    if hdr.version != header.VERSION:
        raise ValueError(
            f"unsupported OptiCipher format version {hdr.version} — "
            f"this build reads version {header.VERSION}. "
            "Update OptiCipher to open this file."
        )

    # 5. Undo diffusion, then undo scrambling -> exact original.
    #    (Routed through the acceleration backend, same bytes as the
    #    reference `diffusion.undiffuse` / `scramble.unscramble_pixels`.)
    undiffused = get_backend().undiffuse(main_cipher, derived.stream_key, hdr.salt)
    restored = get_backend().unscramble(undiffused, derived.scramble_seed)

    return restored
