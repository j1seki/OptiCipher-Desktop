"""
io_image.py
===========

Image loading/saving helpers for OptiCipher.

We isolate all Pillow/file-format concerns here so the cryptographic modules
only ever deal with clean NumPy uint8 arrays.

CRITICAL FORMAT REQUIREMENT: LOSSLESS PNG ONLY
----------------------------------------------
OptiCipher encrypts decoded pixels; the encrypted result (main ciphertext plus
the reserved header strip — see stego.py) must round-trip bit-exactly.
A lossy format such as JPEG recompresses pixels and would destroy both the
header strip and the ciphertext. Therefore encrypted images MUST be written as
PNG (another lossless container could be supported, but only PNG is tested).
`save_image` forces a `.png` suffix and always writes PNG regardless of input
suffix. Files claimed to be OptiCipher ciphertexts in lossy containers are
detected at decryption time by the header/HMAC checks, which fail cleanly.

WHAT IS GUARANTEED
------------------
* **Pixel-exact**: decrypt(save(load(p))) restores exactly the uint8 pixels
  Pillow decoded from the original file (for RGB/RGBA originals in lossless
  containers).
* **Not byte-exact**: the restored *file* is a fresh PNG written by Pillow.
  Original encoder bytes, EXIF, ICC profiles, palette mode and other metadata
  of the original file are NOT preserved — encryption operates on the pixel
  array, and that array is all that is authenticated. See docs/FORMAT.md.

SAFE FILE WRITING
-----------------
`save_image` never destroys existing data:

* A destination that already exists is not overwritten — a unique name
  (`stem_2.png`, `stem_3.png`, …) is chosen instead, unless the caller
  explicitly passes ``overwrite=True``.
* Data is written to a temporary file in the destination directory, flushed
  and fsync'd, then published with an atomic ``os.replace``. A crash mid-save
  therefore cannot tear an existing file, and no half-written file ever
  occupies the published name.

Durability limitation: the file *data* is fsync'd before publish, but the
directory entry itself is not fsync'd on every platform (Windows has no
portable way to do so). Power loss immediately after a save can, on some
filesystems, lose the new directory entry while the old file remains.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Union

import numpy as np
from PIL import Image

PathLike = Union[str, Path]


def load_image(path: PathLike) -> np.ndarray:
    """
    Load an image file into a uint8 NumPy array of shape (H, W, C).

    Greyscale and palette images are converted up to RGB so the pipeline always
    sees 3 (or 4 for RGBA) channels. This keeps every downstream stage simple —
    but it also means the original file *mode* (L, P, CMYK) is not part of what
    encryption preserves; the guarantee is the decoded RGB/RGBA pixels.

    Parameters
    ----------
    path:
        Path to the image file.

    Returns
    -------
    np.ndarray
        uint8 array, shape (H, W, 3) or (H, W, 4).

    Raises
    ------
    OSError, PIL.UnidentifiedImageError, …
        Anything that is not a decodable image; callers translate these into
        per-file errors. Pillow's decompression-bomb guard stays active by
        default, so absurd dimensions are refused rather than allocated.
    """
    img = Image.open(path)

    # Normalise mode: anything that is not already RGB/RGBA becomes RGB. This
    # avoids surprises with palette ("P"), greyscale ("L"), or CMYK inputs.
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    return np.asarray(img, dtype=np.uint8)


def _unique_path(path: Path) -> Path:
    """Return `path` itself if free, else `stem_2.png`, `stem_3.png`, …"""
    if not path.exists():
        return path
    for n in range(2, 1_000_000):
        candidate = path.with_name(f"{path.stem}_{n}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"no free filename found next to {path}")


def _apply_umask(path: Path) -> None:
    """Give the temp-created file normal (umask-derived) permissions."""
    try:
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(path, 0o666 & ~umask)
    except OSError:  # pragma: no cover - platforms without chmod semantics
        pass


def save_image(pixels: np.ndarray, path: PathLike, *, overwrite: bool = False) -> Path:
    """
    Save a uint8 (H, W, C) array as a LOSSLESS PNG, atomically.

    Parameters
    ----------
    pixels:
        uint8 image array.
    path:
        Destination path. The suffix is forced to `.png` if it is not already
        `.png`, because lossy formats would corrupt the ciphertext.
    overwrite:
        When False (the default) an existing destination is *never* replaced —
        a unique name is chosen instead. When True the caller explicitly
        authorises atomic replacement.

    Returns
    -------
    pathlib.Path
        The path actually written (after suffix forcing and, unless
        ``overwrite=True``, unique-name selection). Callers must report THIS
        path, not the one they passed in.

    Raises
    ------
    ValueError
        If the array is not a supported shape/dtype.
    OSError
        On permission/disk-space/directory failures; the temporary file is
        removed first, so no partial output is left behind.
    """
    if pixels.dtype != np.uint8:
        raise ValueError("pixels must be uint8")
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
        raise ValueError("pixels must have shape (H, W, 3) or (H, W, 4)")

    path = Path(path)
    if path.suffix.lower() != ".png":
        # Guard the user against accidentally choosing a lossy container.
        path = path.with_suffix(".png")
    if not overwrite:
        path = _unique_path(path)

    mode = "RGBA" if pixels.shape[2] == 4 else "RGB"
    img = Image.fromarray(pixels, mode=mode)

    # Temp file in the *destination directory* (same filesystem, so the final
    # rename is atomic), fsync'd before publish. On any failure the temp is
    # unlinked: an existing file at `path` is only ever touched by the final
    # os.replace, which is all-or-nothing.
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as fh:
            img.save(fh, format="PNG")
            fh.flush()
            os.fsync(fh.fileno())
        _apply_umask(tmp)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path
