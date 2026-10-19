"""
test_compat_matrix.py
=====================

Image-format & container compatibility matrix (audit Phase 5), as executable
tests rather than prose claims.

WHAT THE APPLICATION ENCRYPTS (architecture C in the audit taxonomy):
decoded pixel arrays in a custom authenticated layout, stored inside a PNG
container (see core.py / stego.py / docs/FORMAT.md). Not raw file bytes, not
pixels inside a transformed container.

Guarantees verified per format below:

  * pixel-exact   — decrypted pixels == the pixels load_image decoded from
                    the original file (the app's defined restoration
                    guarantee; run the pipeline in reverse to check).
  * NOT byte-exact — the restored FILE is a fresh PNG; original encoder
    bytes/metadata/mode are not preserved (asserted where observable).
  * destructive transformations are DETECTED, never silently accepted.
"""

from __future__ import annotations

import hashlib
import os
import zipfile
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image

from opticipher import load_image, save_image
from opticipher.core import DecryptionError, decrypt_image, encrypt_image

PASS = "matrix-pass"
ITER = 10_000


def _photo(seed: int = 21) -> np.ndarray:
    """A structured (not just random) RGB test image."""
    yy, xx = np.mgrid[0:48, 0:48]
    base = ((yy * 3 + xx * 5) % 256).astype(np.uint8)
    img = np.dstack([base, np.roll(base, 7, axis=1), np.roll(base, 13, axis=0)])
    rng = np.random.default_rng(seed)
    noise = rng.integers(0, 32, img.shape, dtype=np.uint16)
    return np.clip(img.astype(np.uint16) + noise, 0, 255).astype(np.uint8)


def _roundtrip(source: Path) -> np.ndarray:
    """encrypt -> PNG -> decrypt through the real on-disk path."""
    enc = encrypt_image(load_image(source), PASS, iterations=ITER)
    enc_path = save_image(enc, source.parent / "cipher.png")
    return decrypt_image(load_image(enc_path), PASS)


# ---------------------------------------------------------------------------
# 5.3 — per-format round trips (pixel-exact vs the decoded original).
# ---------------------------------------------------------------------------
def _save_rgb(path: Path, arr: np.ndarray, **kwargs) -> None:
    Image.fromarray(arr, "RGB").save(path, **kwargs)


@pytest.mark.parametrize("fmt", ["png", "jpeg", "bmp", "tiff", "webp"])
def test_roundtrip_pixels_match_decoded_source(tmp_path, fmt):
    arr = _photo()
    src = tmp_path / f"src.{ 'jpg' if fmt == 'jpeg' else fmt }"
    kwargs = {"quality": 95, "subsampling": 0} if fmt == "jpeg" else {}
    if fmt == "webp":
        kwargs = {"lossless": True}
    try:
        _save_rgb(src, arr, **kwargs)
    except OSError:
        pytest.skip(f"Pillow build lacks {fmt} support")

    decoded = load_image(src)  # ground truth = what the app actually reads
    restored = _roundtrip(src)
    assert restored.shape == decoded.shape
    assert np.array_equal(restored, decoded), f"{fmt}: pixel round trip broke"


def test_restored_file_is_png_and_bytes_differ_from_source(tmp_path):
    """Documented: restoration is pixel-exact, NOT byte-exact."""
    arr = _photo()
    src = tmp_path / "src.bmp"
    _save_rgb(src, arr)
    restored_path = _roundtrip_to_path(src, tmp_path)
    assert restored_path.suffix == ".png"
    assert hashlib.sha256(restored_path.read_bytes()).digest() != hashlib.sha256(
        src.read_bytes()
    ).digest()


def _roundtrip_to_path(source: Path, out_dir: Path) -> Path:
    enc = encrypt_image(load_image(source), PASS, iterations=ITER)
    enc_path = save_image(enc, out_dir / "cipher.png")
    restored = decrypt_image(load_image(enc_path), PASS)
    return save_image(restored, out_dir / "restored.png")


# ---------------------------------------------------------------------------
# Modes: L, P, RGBA, CMYK — documented conversions.
# ---------------------------------------------------------------------------
def test_grayscale_L_returns_rgb_matching_conversion(tmp_path):
    arr = _photo()[:, :, 0]  # single channel
    src = tmp_path / "gray.png"
    Image.fromarray(arr, "L").save(src)
    decoded = load_image(src)  # app converts L -> RGB
    restored = _roundtrip(src)
    assert restored.ndim == 3 and restored.shape[2] == 3
    assert np.array_equal(restored, np.asarray(Image.open(src).convert("RGB")))
    assert np.array_equal(restored, decoded)


def test_palette_P_returns_rgb_roundtrip(tmp_path):
    src = tmp_path / "pal.png"
    Image.fromarray(_photo(), "RGB").convert(
        "P", palette=Image.Palette.ADAPTIVE, colors=64
    ).save(src)
    decoded = load_image(src)
    restored = _roundtrip(src)
    assert restored.shape == decoded.shape
    assert np.array_equal(restored, decoded)


def test_rgba_alpha_channel_is_preserved(tmp_path):
    rng = np.random.default_rng(3)
    arr = rng.integers(0, 256, (32, 32, 4), dtype=np.uint8)
    src = tmp_path / "alpha.png"
    Image.fromarray(arr, "RGBA").save(src)
    restored = _roundtrip(src)
    assert restored.shape == (32, 32, 4)
    assert np.array_equal(restored[:, :, 3], arr[:, :, 3])  # alpha exact
    assert np.array_equal(restored, arr)


def test_cmyk_source_converts_to_rgb_and_roundtrips(tmp_path):
    src = tmp_path / "cmyk.tif"
    Image.fromarray(_photo(), "RGB").convert("CMYK").save(src)
    decoded = load_image(src)
    restored = _roundtrip(src)
    assert restored.shape == decoded.shape
    assert np.array_equal(restored, decoded)


# ---------------------------------------------------------------------------
# Metadata and animation — documented losses.
# ---------------------------------------------------------------------------
def test_exif_metadata_loss_is_observable_and_documented(tmp_path):
    src = tmp_path / "with_exif.jpg"
    exif = Image.Exif()
    exif[271] = "OptiCam-9000"  # Make
    _save_rgb(src, _photo(), exif=exif, quality=95)
    assert Image.open(src).getexif()[271] == "OptiCam-9000"  # sanity

    restored_path = _roundtrip_to_path(src, tmp_path)
    assert not Image.open(restored_path).getexif(), (
        "restored file carries no EXIF — encryption operates on pixels, "
        "metadata is not preserved (documented limitation)"
    )


def test_animated_gif_restores_first_frame_only(tmp_path):
    frames = [_photo(1), _photo(2), _photo(3)]
    src = tmp_path / "anim.gif"
    Image.fromarray(frames[0], "RGB").save(
        src,
        save_all=True,
        append_images=[Image.fromarray(f, "RGB") for f in frames[1:]],
        duration=100,
        loop=0,
    )
    assert Image.open(src).n_frames == 3  # sanity
    decoded = load_image(src)  # app reads the first frame
    restored = _roundtrip(src)
    assert np.array_equal(restored, decoded)


# ---------------------------------------------------------------------------
# 5.2 — container / lossless transformations of the CIPHERTEXT itself.
# ---------------------------------------------------------------------------
def test_zip_roundtrip_preserves_ciphertext_bytes(tmp_path):
    enc = encrypt_image(_photo(), PASS, iterations=ITER)
    enc_path = save_image(enc, tmp_path / "c.png")
    original_bytes = enc_path.read_bytes()

    with zipfile.ZipFile(tmp_path / "bundle.zip", "w") as zf:
        zf.write(enc_path, "c.png")
    with zipfile.ZipFile(tmp_path / "bundle.zip") as zf:
        zf.extractall(tmp_path / "unzipped")

    extracted = (tmp_path / "unzipped" / "c.png").read_bytes()
    assert extracted == original_bytes  # lossless archive reproduces bytes
    restored = decrypt_image(load_image(tmp_path / "unzipped" / "c.png"), PASS)
    assert np.array_equal(restored, _photo())


def test_ciphertext_survives_png_decode_reencode(tmp_path):
    """PNG re-encode of the SAME pixels is safe (pixel-lossless); a JPEG
    re-encode is destructive and must be detected."""
    enc = encrypt_image(_photo(), PASS, iterations=ITER)
    enc_path = save_image(enc, tmp_path / "c.png")

    # lossless PNG round trip (as an image editor 'save as PNG' would do)
    again = tmp_path / "re.png"
    Image.open(enc_path).save(again, format="PNG")
    restored = decrypt_image(load_image(again), PASS)
    assert np.array_equal(restored, _photo())


def test_jpeg_reencode_of_ciphertext_is_detected(tmp_path):
    enc = encrypt_image(_photo(), PASS, iterations=ITER)
    enc_path = save_image(enc, tmp_path / "c.png")
    jpg = tmp_path / "c.jpg"
    Image.open(enc_path).save(jpg, format="JPEG", quality=90)
    with pytest.raises((DecryptionError, ValueError, OSError)):
        decrypt_image(load_image(jpg), PASS)


def test_copy_rename_and_repeated_reopen_preserve_decryption(tmp_path):
    import shutil

    src_dir = tmp_path / "one"
    dst_dir = tmp_path / "two"
    src_dir.mkdir()
    dst_dir.mkdir()
    enc = encrypt_image(_photo(), PASS, iterations=ITER)
    enc_path = save_image(enc, src_dir / "c.png")
    shutil.copy(enc_path, dst_dir / "renamed cipher.png")

    for _ in range(2):  # reopen repeatedly
        restored = decrypt_image(load_image(dst_dir / "renamed cipher.png"), PASS)
        assert np.array_equal(restored, _photo())


# ---------------------------------------------------------------------------
# Golden vector — byte-stable v1 ciphertext for a fixed salt/passphrase.
# ---------------------------------------------------------------------------
def test_golden_ciphertext_v1_is_byte_stable(monkeypatch):
    """
    A format golden vector: with generate_salt pinned, encryption of a fixed
    image under a fixed passphrase/iterations MUST produce these exact bytes.
    Any drift means the v1 ciphertext layout or primitives changed — that is
    a format version bump, not a silent edit (audit Phase 8).
    """
    img = np.arange(8 * 8 * 3, dtype=np.uint8).reshape(8, 8, 3)
    monkeypatch.setattr(
        "opticipher.keys.generate_salt", lambda: bytes(range(16))
    )
    enc = encrypt_image(img, "golden-vector", iterations=ITER)
    assert enc.shape == (11, 8, 3)
    digest = hashlib.sha256(enc.tobytes()).hexdigest()
    assert digest == (
        "308566bd1c952c7e2f88665914369fd2055856fe10a139d384c7bbc1325e7f0f"
    )
    # The golden vector must also remain decryptable.
    assert np.array_equal(
        decrypt_image(enc, "golden-vector"), img
    )
