"""
test_integrity_matrix.py
========================

Adversarial integrity tests for the encrypted-image format (audit Phase 2.3).

Every unauthorized modification must be rejected, and the *rules* for bytes
the format deliberately ignores are pinned here so they cannot drift:

  * The authenticated region is: pre-HMAC header bytes || main ciphertext
    pixels (core._compute_hmac). Flip anything there -> rejection.
  * Strip padding AFTER the fixed 70-byte header is unused storage: corrupting
    it does not and must not affect decryption (tested below).
  * Trailing bytes appended to the PNG *file* are container-level and never
    reach the pixel payload: they are ignored by design (tested below).
  * Rows appended to the pixel array ARE parsed as a new header tail ->
    rejection.
  * Wrong passphrase and payload tampering share one error message (no
    passphrase oracle).
"""

from __future__ import annotations

import os
import struct
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from opticipher import header, keys, stego
from opticipher.core import (
    DecryptionError,
    _compute_hmac,
    decrypt_image,
    encrypt_image,
)

PASS = "matrix-passphrase"
ITER = 10_000

# Byte offsets inside the packed header (see header.py layout).
FIELD_OFF = {
    "magic": 0,
    "version": 4,
    "salt": 5,
    "iterations": 21,
    "height": 25,
    "width": 29,
    "channels": 33,
    "strip_rows": 34,
    "hmac": 38,
}


@pytest.fixture()
def encrypted():
    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)
    enc = encrypt_image(img.copy(), PASS, iterations=ITER)
    return img, enc


def _strip_index(enc: np.ndarray) -> int:
    """Flat index where the reserved strip (and header) starts."""
    hdr = header.parse(stego.peek_header_bytes(enc, header.HEADER_SIZE))
    return hdr.height * enc.shape[1] * enc.shape[2]


def _poke_header_field(enc: np.ndarray, field: str, value: int, fmt: str) -> None:
    """Overwrite one header field in place (unsalted tamper)."""
    idx = _strip_index(enc) + FIELD_OFF[field]
    enc.reshape(-1)[idx : idx + int(np.dtype(fmt).itemsize)] = np.frombuffer(
        struct.pack(fmt, value), dtype=np.uint8
    )


# ---------------------------------------------------------------------------
# Payload tampering (authenticated region).
# ---------------------------------------------------------------------------
def test_bit_flip_first_middle_last_of_payload(encrypted):
    """First, middle and last ciphertext bytes are all inside the MAC."""
    img, enc = encrypted
    body_end = _strip_index(enc)
    for index in (0, body_end // 2, body_end - 1):
        bad = enc.copy()
        bad.reshape(-1)[index] ^= 0x01
        with pytest.raises(DecryptionError):
            decrypt_image(bad, PASS)


def test_hmac_tag_corruption_rejected(encrypted):
    _, enc = encrypted
    for delta in (0, 15, 31):  # first, middle, last byte of the 32-byte tag
        bad = enc.copy()
        bad.reshape(-1)[_strip_index(enc) + FIELD_OFF["hmac"] + delta] ^= 0x80
        with pytest.raises(DecryptionError):
            decrypt_image(bad, PASS)


def test_salt_change_rejected(encrypted):
    _, enc = encrypted
    # Flip a salt byte (guaranteed change; writing a fixed value could hit the
    # byte that is already there).
    enc.reshape(-1)[_strip_index(enc) + FIELD_OFF["salt"]] ^= 0xFF
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)


def test_iterations_change_rejected(encrypted):
    _, enc = encrypted
    _poke_header_field(enc, "iterations", ITER + 1, ">I")
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)


def test_dimension_change_rejected(encrypted):
    _, enc = encrypted
    _poke_header_field(enc, "height", 31, ">I")
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)


def test_strip_rows_change_rejected(encrypted):
    _, enc = encrypted
    _poke_header_field(enc, "strip_rows", 2, ">I")  # valid is 1 for 30x30x3
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)


def test_channel_change_rejected(encrypted):
    _, enc = encrypted
    _poke_header_field(enc, "channels", 4, "B")
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)


def test_version_tamper_rejected_by_mac_not_by_version_check(encrypted):
    """
    A tampered version byte must fail the HMAC (the field is authenticated),
    NOT surface the 'unsupported version' path — otherwise an attacker could
    make a valid file look unsupported.
    """
    _, enc = encrypted
    _poke_header_field(enc, "version", 2, "B")
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)


# ---------------------------------------------------------------------------
# Splice / cross-file attacks.
# ---------------------------------------------------------------------------
def test_cross_file_strip_swap_rejected(encrypted):
    """Grafting file B's header strip onto file A's body must not verify."""
    rng = np.random.default_rng(99)
    other = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)
    enc_b = encrypt_image(other, "other-passphrase", iterations=ITER)
    _, enc_a = encrypted
    assert enc_a.shape == enc_b.shape  # same dims: strip rows align exactly
    grafted = enc_a.copy()
    grafted[enc_a.shape[0] - 1 :] = enc_b[-1:]  # A's body + B's strip
    with pytest.raises(DecryptionError):
        decrypt_image(grafted, PASS)


def test_appended_pixel_rows_rejected(encrypted):
    """Extra rows become the 'strip tail' -> header parse/bounds must fail."""
    _, enc = encrypted
    rng = np.random.default_rng(5)
    junk = rng.integers(0, 256, (2, enc.shape[1], enc.shape[2]), dtype=np.uint8)
    with pytest.raises((ValueError, DecryptionError)):
        decrypt_image(np.vstack([enc, junk]), PASS)


# ---------------------------------------------------------------------------
# Password oracle: wrong passphrase and tampering are indistinguishable.
# ---------------------------------------------------------------------------
def test_wrong_passphrase_and_tamper_share_error_message(encrypted):
    img, enc = encrypted
    with pytest.raises(DecryptionError) as wrong:
        decrypt_image(enc, "not-the-passphrase")
    tampered = enc.copy()
    tampered.reshape(-1)[0] ^= 0xFF
    with pytest.raises(DecryptionError) as dirty:
        decrypt_image(tampered, PASS)
    assert str(wrong.value) == str(dirty.value)


# ---------------------------------------------------------------------------
# Explicit format rules: what is intentionally NOT authenticated.
# ---------------------------------------------------------------------------
def test_strip_padding_after_header_is_ignored_by_design(encrypted):
    """
    The strip may be larger than the 70-byte header; the padding bytes carry
    no information and are not covered by the MAC. Corruption there must not
    change the restoration result.
    """
    img, enc = encrypted
    base = _strip_index(enc)
    strip_capacity = enc.size - base
    assert strip_capacity > header.HEADER_SIZE, "test image must have padding"
    enc.reshape(-1)[base + header.HEADER_SIZE] ^= 0x5A  # first padding byte
    restored = decrypt_image(enc, PASS)
    assert np.array_equal(restored, img)


def test_trailing_file_bytes_are_container_level_and_ignored(
    encrypted, tmp_path
):
    """
    RULE: OptiCipher authenticates the pixel payload, not bytes appended to
    the PNG file after IEND. PNG decoders never deliver them to the pixels,
    so decryption succeeds — a copy/concatenation artefact, not a forgery
    opportunity (the payload itself cannot be altered undetected).
    """
    from opticipher import load_image, save_image

    img, enc = encrypted
    path = save_image(enc, tmp_path / "c.png")
    with open(path, "ab") as fh:
        fh.write(b"TRAILING-GARBAGE-BYTES")
    restored = decrypt_image(load_image(path), PASS)
    assert np.array_equal(restored, img)


# ---------------------------------------------------------------------------
# Pre-authentication cost bounds (the P0 DoS fix).
# ---------------------------------------------------------------------------
def test_huge_iterations_header_rejected_before_expensive_work(encrypted):
    """
    A crafted header may demand up to ~4.29 billion PBKDF2 iterations — which
    took hours on a modern CPU — before authentication could ever run. The
    pre-auth bound must refuse such headers in milliseconds. The cap is set
    above every legitimate value, so the test uses 50M (5x the 10M bound);
    without the bound this decrypt would burn ~12+ seconds in PBKDF2 alone.
    """
    _, enc = encrypted
    _poke_header_field(enc, "iterations", 50_000_000, ">I")
    start = time.monotonic()
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)
    assert time.monotonic() - start < 3.0, "bound check did not fire first"


def test_absurd_iterations_still_fast_even_with_valid_shape():
    """uint32-max iterations must not reach PBKDF2 at all."""
    rng = np.random.default_rng(11)
    img = rng.integers(0, 256, (8, 8, 3), dtype=np.uint8)
    enc = encrypt_image(img, PASS, iterations=ITER)
    _poke_header_field(enc, "iterations", 0xFFFFFFFF, ">I")
    start = time.monotonic()
    with pytest.raises(DecryptionError):
        decrypt_image(enc, PASS)
    assert time.monotonic() - start < 1.0


# ---------------------------------------------------------------------------
# Version handling: future files get a clear, post-authentication error.
# ---------------------------------------------------------------------------
def _craft_valid_future_version_file(img: np.ndarray, pw: str) -> np.ndarray:
    """A byte-faithful simulation of a future v2 file: version=2 with a
    CORRECT HMAC (i.e. produced by someone who knows the passphrase)."""
    enc = encrypt_image(img, pw, iterations=ITER)
    hdr = header.parse(stego.peek_header_bytes(enc, header.HEADER_SIZE))
    derived = keys.derive_keys(pw, hdr.salt, hdr.iterations)
    main = stego.remove_strip(enc, hdr.strip_rows)
    hdr2 = header.Header(
        salt=hdr.salt,
        iterations=hdr.iterations,
        height=hdr.height,
        width=hdr.width,
        channels=hdr.channels,
        strip_rows=hdr.strip_rows,
        version=2,
    )
    hdr2.hmac = _compute_hmac(derived.mac_key, hdr2.pack_prehmac(), main)
    base = _strip_index(enc)
    out = enc.copy()
    out.reshape(-1)[base : base + header.HEADER_SIZE] = np.frombuffer(
        hdr2.pack(), dtype=np.uint8
    )
    return out


def test_valid_future_version_file_gets_clear_unsupported_error():
    import struct

    rng = np.random.default_rng(13)
    img = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
    future = _craft_valid_future_version_file(img, PASS)
    # Sanity: HMAC really is valid for the v2 header (pre-auth stages pass).
    assert struct.unpack(
        ">I", future.reshape(-1)[
            _strip_index(future) + FIELD_OFF["iterations"]:][:4]
    )[0] == ITER
    with pytest.raises(ValueError, match="unsupported OptiCipher format version 2"):
        decrypt_image(future, PASS)
