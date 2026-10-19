"""
test_file_safety.py
===================

Safe file operations and non-destructive behaviour (audit Phase 3).

Pinned guarantees:

  * Existing destination files are NEVER silently replaced (unique-name
    allocation unless the caller explicitly passes overwrite=True).
  * Writes are atomic: temp file in the destination directory -> fsync ->
    os.replace. A failed save leaves no temp file and no torn output.
  * The ORIGINAL input file is never modified by encrypt or decrypt.
  * Failures (unwritable directory, simulated disk-full) surface as OSError
    and never as a fake success, and never destroy the previous file.
  * save_image reports the path it ACTUALLY wrote (suffix forcing included).
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PIL import Image

from opticipher import load_image, save_image
from opticipher.core import decrypt_image, encrypt_image

PASS = "safety-pass"
ITER = 10_000


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _img(seed: int = 0, shape=(24, 24, 3)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, shape, dtype=np.uint8)


# ---------------------------------------------------------------------------
# save_image: no clobbering, honest paths, atomicity.
# ---------------------------------------------------------------------------
def test_save_never_clobbers_existing_file(tmp_path):
    path = tmp_path / "out.png"
    first = _img(1)
    second = _img(2)

    written1 = save_image(first, path)
    digest_before = _sha256(written1)

    written2 = save_image(second, path)  # same requested path
    assert written1 == path
    assert written2 != path and written2.name == "out_2.png"
    # The first file is untouched, the second holds different pixels.
    assert _sha256(path) == digest_before
    assert np.array_equal(load_image(written1), first)
    assert np.array_equal(load_image(written2), second)


def test_save_overwrite_true_replaces_atomically(tmp_path):
    path = tmp_path / "out.png"
    save_image(_img(1), path)
    new = _img(2)
    written = save_image(new, path, overwrite=True)
    assert written == path  # exact path, no _2 suffix
    assert np.array_equal(load_image(path), new)


def test_save_forces_png_and_reports_actual_path(tmp_path):
    # A caller asking for .jpg must be told where the PNG really went.
    written = save_image(_img(), tmp_path / "ciphertext.jpg")
    assert written.suffix == ".png"
    assert written.exists()
    assert not (tmp_path / "ciphertext.jpg").exists()


def test_save_leaves_no_temp_files_behind(tmp_path):
    save_image(_img(), tmp_path / "clean.png")
    leftovers = [
        p for p in tmp_path.iterdir() if p.name != "clean.png"
    ]
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_failed_save_keeps_previous_file_and_no_partial(tmp_path, monkeypatch):
    """Simulated disk-full: previous output survives, no torn/partial file."""
    path = tmp_path / "valuable.png"
    original = _img(1)
    save_image(original, path)
    before = _sha256(path)

    def exploding_save(self, fp, *args, **kwargs):
        fp.write(b"PARTIAL")
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(Image.Image, "save", exploding_save)

    with pytest.raises(OSError, match="No space left"):
        save_image(_img(2), path, overwrite=True)

    monkeypatch.undo()
    # The old file is byte-identical; the failed attempt's temp is gone.
    assert _sha256(path) == before
    assert [p for p in tmp_path.iterdir() if ".tmp" in p.name] == []


def test_save_to_missing_directory_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        save_image(_img(), tmp_path / "no" / "such" / "dir.png")


@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.skipif(
    hasattr(os, "geteuid") and os.geteuid() == 0,
    reason="root ignores directory permissions",
)
def test_save_to_readonly_directory_raises_oserror(tmp_path):
    locked = tmp_path / "ro"
    locked.mkdir()
    os.chmod(locked, 0o500)
    try:
        with pytest.raises(OSError):
            save_image(_img(), locked / "x.png")
    finally:
        os.chmod(locked, 0o700)


def test_save_accepts_unicode_filenames(tmp_path):
    weird = tmp_path / "图片-ß-🔐-plain.png"
    written = save_image(_img(), weird)
    assert written == weird
    assert load_image(written).shape == (24, 24, 3)


# ---------------------------------------------------------------------------
# End-to-end non-destructive behaviour.
# ---------------------------------------------------------------------------
def test_original_input_never_modified_by_encrypt_decrypt(tmp_path):
    src = tmp_path / "precious.png"
    save_image(_img(3), src)
    src_digest = _sha256(src)

    # encrypt: input intact, ciphertext written elsewhere (even in the SAME
    # directory the original lives in).
    enc_pixels = encrypt_image(load_image(src), PASS, iterations=ITER)
    enc_path = save_image(enc_pixels, src.with_name("precious_encrypted.png"))
    assert _sha256(src) == src_digest

    # decrypt into the same directory: the ciphertext must not be clobbered
    # either, and the source stays intact.
    out = decrypt_image(load_image(enc_path), PASS)
    dec_path = save_image(out, src.with_name("precious_encrypted.png"))
    assert dec_path.name == "precious_encrypted_2.png"
    assert _sha256(src) == src_digest
    assert np.array_equal(load_image(dec_path), load_image(src))


def test_batch_rerun_creates_unique_outputs_not_overwrites(tmp_path):
    """Two encrypt runs into one output dir produce two distinct files."""
    from app.workers import JobWorker

    src = tmp_path / "in.png"
    save_image(_img(4), src)
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    statuses = []
    for _ in range(2):
        worker = JobWorker("encrypt", [str(src)], PASS, ITER, str(out_dir))
        worker.file_done.connect(lambda f, s: statuses.append(s))
        worker.run()  # synchronous for determinism

    assert len(statuses) == 2 and all(s.startswith("ok:") for s in statuses)
    produced = sorted(p.name for p in out_dir.iterdir())
    assert produced == ["in_encrypted.png", "in_encrypted_2.png"]
    # Each status reports the file it ACTUALLY wrote.
    assert "in_encrypted.png" in statuses[0]
    assert "in_encrypted_2.png" in statuses[1]


def test_output_paths_with_unicode_and_spaces_roundtrip(tmp_path):
    src = tmp_path / "my photo ß.png"
    save_image(_img(5), src)
    enc_path = save_image(
        encrypt_image(load_image(src), PASS, iterations=ITER),
        tmp_path / "encrypted copy.png",
    )
    assert enc_path.name == "encrypted copy.png"
    out = decrypt_image(load_image(enc_path), PASS)
    dec_path = save_image(out, tmp_path / "recovered copy.png")
    assert np.array_equal(load_image(dec_path), load_image(src))
