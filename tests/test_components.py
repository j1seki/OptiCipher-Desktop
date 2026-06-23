"""
test_components.py
==================

Unit tests for the individual building blocks, so that if the end-to-end test
ever breaks we can localise the failure quickly.
"""

import numpy as np
import pytest

from opticipher import diffusion, header, keys, scramble, stego


# ---------------------------------------------------------------------------
# keys.py
# ---------------------------------------------------------------------------
def test_key_derivation_is_deterministic():
    salt = b"0123456789abcdef"  # 16 bytes
    a = keys.derive_keys("pw", salt, iterations=1000)
    b = keys.derive_keys("pw", salt, iterations=1000)
    assert a == b


def test_key_derivation_changes_with_salt():
    a = keys.derive_keys("pw", b"0000000000000000", iterations=1000)
    b = keys.derive_keys("pw", b"1111111111111111", iterations=1000)
    assert a.stream_key != b.stream_key
    assert a.scramble_seed != b.scramble_seed


def test_key_derivation_rejects_bad_salt():
    with pytest.raises(ValueError):
        keys.derive_keys("pw", b"too short", iterations=1000)


def test_generate_salt_length_and_randomness():
    s1 = keys.generate_salt()
    s2 = keys.generate_salt()
    assert len(s1) == keys.SALT_LENGTH
    assert s1 != s2  # astronomically unlikely to collide


# ---------------------------------------------------------------------------
# scramble.py
# ---------------------------------------------------------------------------
def test_scramble_is_invertible():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (16, 24, 3), dtype=np.uint8)
    seed = 0xDEADBEEF
    scrambled = scramble.scramble_pixels(img, seed)
    restored = scramble.unscramble_pixels(scrambled, seed)
    assert np.array_equal(restored, img)


def test_scramble_actually_moves_pixels():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (16, 24, 3), dtype=np.uint8)
    scrambled = scramble.scramble_pixels(img, 123)
    # The multiset of pixels is preserved, but their arrangement should differ.
    assert not np.array_equal(scrambled, img)
    assert sorted(img.reshape(-1).tolist()) == sorted(
        scrambled.reshape(-1).tolist()
    )


def test_wrong_seed_does_not_restore():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
    scrambled = scramble.scramble_pixels(img, 1)
    wrong = scramble.unscramble_pixels(scrambled, 2)
    assert not np.array_equal(wrong, img)


# ---------------------------------------------------------------------------
# diffusion.py
# ---------------------------------------------------------------------------
def test_diffusion_is_invertible():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (10, 10, 3), dtype=np.uint8)
    key = b"k" * 32
    salt = b"s" * 16
    enc = diffusion.diffuse(img, key, salt)
    dec = diffusion.undiffuse(enc, key, salt)
    assert np.array_equal(dec, img)


def test_diffusion_changes_values():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (10, 10, 3), dtype=np.uint8)
    enc = diffusion.diffuse(img, b"k" * 32, b"s" * 16)
    assert not np.array_equal(enc, img)


def test_diffusion_wrong_key_fails_to_recover():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (10, 10, 3), dtype=np.uint8)
    enc = diffusion.diffuse(img, b"a" * 32, b"s" * 16)
    dec = diffusion.undiffuse(enc, b"b" * 32, b"s" * 16)
    assert not np.array_equal(dec, img)


# ---------------------------------------------------------------------------
# header.py
# ---------------------------------------------------------------------------
def test_header_pack_parse_roundtrip():
    hdr = header.Header(
        salt=b"S" * 16,
        iterations=200000,
        height=322,
        width=620,
        channels=3,
        strip_rows=1,
        hmac=b"H" * 32,
    )
    packed = hdr.pack()
    assert len(packed) == header.HEADER_SIZE
    parsed = header.parse(packed)
    assert parsed.salt == hdr.salt
    assert parsed.iterations == hdr.iterations
    assert parsed.height == hdr.height
    assert parsed.width == hdr.width
    assert parsed.channels == hdr.channels
    assert parsed.strip_rows == hdr.strip_rows
    assert parsed.hmac == hdr.hmac


def test_header_rejects_bad_magic():
    bad = b"XXXX" + bytes(header.HEADER_SIZE - 4)
    with pytest.raises(ValueError):
        header.parse(bad)


def test_header_pack_requires_hmac():
    hdr = header.Header(
        salt=b"S" * 16,
        iterations=1,
        height=1,
        width=1,
        channels=3,
        strip_rows=1,
    )
    with pytest.raises(ValueError):
        hdr.pack()  # hmac not set


# ---------------------------------------------------------------------------
# stego.py
# ---------------------------------------------------------------------------
def test_strip_append_read_remove():
    rng = np.random.default_rng(0)
    img = rng.integers(0, 256, (20, 30, 3), dtype=np.uint8)
    payload = bytes(range(header.HEADER_SIZE))
    rows = stego.rows_needed(len(payload), 30, 3)

    with_strip = stego.append_strip(img, payload)
    assert with_strip.shape[0] == img.shape[0] + rows

    read_back = stego.read_strip(with_strip, rows, len(payload))
    assert read_back == payload

    removed = stego.remove_strip(with_strip, rows)
    assert np.array_equal(removed, img)


def test_rows_needed_rounds_up():
    # 70 header bytes, width 30 channels 3 -> 90 bytes/row -> 1 row.
    assert stego.rows_needed(70, 30, 3) == 1
    # width 10 channels 3 -> 30 bytes/row -> ceil(70/30) = 3 rows.
    assert stego.rows_needed(70, 10, 3) == 3
