"""
test_corruption.py
==================

Malformed / corrupted INPUT handling (audit Phase 4).

Expected behaviour for every case: a clear exception (translated by callers
into a per-file error), no crash of the process, no hang, no unreasonable
allocation, no source modification, and never a "successfully restored" result
for data that failed validation.
"""

from __future__ import annotations

import os
import struct
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image

from opticipher import header, load_image, stego
from opticipher.core import DecryptionError, decrypt_image, encrypt_image

# Every malformed input must fail FAST — a generous but bounded ceiling that
# any real corruption path comfortably beats (and that a hang would fail).
FAST = 5.0


def _timed(fn, *args, **kwargs):
    start = time.monotonic()
    with pytest.raises(Exception) as exc:  # noqa: B017 - any clear exception
        fn(*args, **kwargs)
    elapsed = time.monotonic() - start
    assert elapsed < FAST, f"took {elapsed:.1f}s — not a clean fast failure"
    # SystemExit / KeyboardInterrupt would be a bug; pytest.raises(Exception)
    # already excludes BaseException like SystemExit? SystemExit IS a
    # BaseException, not Exception — so it would escape and fail the test.
    return exc.value


# ---------------------------------------------------------------------------
# File-level garbage: never decodable, must raise cleanly.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "payload",
    [
        b"",  # empty file
        b"\x00",  # one byte
        b"OPTC",  # our own magic, nothing else
        b"\x89PNG\r\n\x1a\n",  # PNG signature only, no chunks
        b"not an image at all, just text " * 100,
        os.urandom(4096),  # random binary
        b"\xff\xd8\xff\xe0" + b"\x00" * 64,  # JPEG signature, truncated
    ],
    ids=["empty", "one-byte", "magic-only", "png-sig", "text", "random", "jpeg-sig"],
)
def test_undecodable_files_raise_cleanly(tmp_path, payload):
    path = tmp_path / "input.bin"
    path.write_bytes(payload)
    err = _timed(load_image, str(path))
    assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# Truncated real PNGs (container integrity lost before crypto runs).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("keep_fraction", [0.1, 0.5, 0.9, 0.99])
def test_truncated_png_raises(tmp_path, keep_fraction):
    rng = np.random.default_rng(1)
    img = rng.integers(0, 256, (40, 40, 3), dtype=np.uint8)
    Image.fromarray(img, "RGB").save(tmp_path / "full.png")
    data = (tmp_path / "full.png").read_bytes()
    (tmp_path / "cut.png").write_bytes(data[: int(len(data) * keep_fraction)])
    err = _timed(load_image, str(tmp_path / "cut.png"))
    assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# Ciphertext arrays damaged at structural boundaries.
# ---------------------------------------------------------------------------
@pytest.fixture()
def small_cipher():
    rng = np.random.default_rng(2)
    img = rng.integers(0, 256, (8, 8, 3), dtype=np.uint8)
    return img, encrypt_image(img, "pw", iterations=10_000)


@pytest.mark.parametrize("cut_rows", [1, 3, 10, 100])
def test_row_truncation_never_succeeds(small_cipher, cut_rows):
    _, enc = small_cipher
    if cut_rows >= enc.shape[0]:
        damaged = enc[:0]  # everything gone
    else:
        damaged = enc[: enc.shape[0] - cut_rows]
    _timed(decrypt_image, damaged, "pw")


def test_column_truncation_never_succeeds(small_cipher):
    _, enc = small_cipher
    _timed(decrypt_image, enc[:, :-1, :], "pw")


def test_corrupted_image_bytes_never_succeeds(small_cipher):
    _, enc = small_cipher
    damaged = enc.copy()
    damaged[:, :4, :] = 0  # wipe the left third (header strip untouched)
    _timed(decrypt_image, damaged, "pw")


# ---------------------------------------------------------------------------
# Crafted header extremes: bounds must hold without hangs or wild claims.
# ---------------------------------------------------------------------------
def _strip_index(enc: np.ndarray) -> int:
    hdr = header.parse(stego.peek_header_bytes(enc, header.HEADER_SIZE))
    return hdr.height * enc.shape[1] * enc.shape[2]


# Byte offsets inside the packed header (see header.py layout) — kept in sync
# with the layout table in header.py.
FIELD_OFF = {
    "version": 4,
    "salt": 5,
    "iterations": 21,
    "height": 25,
    "width": 29,
    "channels": 33,
    "strip_rows": 34,
}


@pytest.mark.parametrize(
    "field,value,fmt",
    [
        ("width", 0, ">I"),
        ("height", 0, ">I"),
        ("width", 0xFFFFFFFF, ">I"),
        ("height", 0xFFFFFFFF, ">I"),
        ("channels", 0, "B"),
        ("channels", 255, "B"),
        ("strip_rows", 0, ">I"),
        ("strip_rows", 0xFFFFFFFF, ">I"),
        ("iterations", 0, ">I"),
        ("iterations", 0xFFFFFFFF, ">I"),
        ("version", 0, "B"),
        ("version", 255, "B"),
    ],
)
def test_hostile_header_fields_rejected(small_cipher, field, value, fmt):
    """Untrusted metadata cannot trigger unbounded work or a fake success."""
    _, enc = small_cipher
    idx = _strip_index(enc) + FIELD_OFF[field]
    enc.reshape(-1)[idx : idx + int(np.dtype(fmt).itemsize)] = np.frombuffer(
        struct.pack(fmt, value), dtype=np.uint8
    )
    _timed(decrypt_image, enc, "pw")


def test_decryption_never_returns_unauthenticated_data(small_cipher):
    """
    Positive control: when decryption *does* return, the bytes must be the
    exact original — there is no code path that returns partially verified
    pixels.
    """
    img, enc = small_cipher
    out = decrypt_image(enc, "pw")
    assert np.array_equal(out, img)


def test_pillow_decompression_bomb_guard_stays_enabled():
    """
    We rely on Pillow's default MAX_IMAGE_PIXELS guard for absurd dimensions;
    nothing in the app may disable it (Image.MAX_IMAGE_PIXELS must remain set).
    """
    assert Image.MAX_IMAGE_PIXELS, "Pillow bomb guard was disabled"
