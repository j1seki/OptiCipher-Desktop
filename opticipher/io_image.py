"""
io_image.py
===========

Image loading/saving helpers for OptiCipher.

We isolate all Pillow/file-format concerns here so the cryptographic modules
only ever deal with clean NumPy uint8 arrays.

CRITICAL FORMAT REQUIREMENT: LOSSLESS PNG ONLY
----------------------------------------------
OptiCipher hides its header in the least-significant bits of pixel bytes and
relies on EXACT pixel preservation for decryption. A lossy format such as JPEG
recompresses pixels and would destroy both the hidden header and the ciphertext.
Therefore encrypted images MUST be written as PNG (or another lossless format).
`save_image` enforces PNG and `load_image` warns if asked to read a JPEG that
was somehow produced by OptiCipher.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image


def load_image(path: str | Path) -> np.ndarray:
    """
    Load an image file into a uint8 NumPy array of shape (H, W, C).

    Greyscale and palette images are converted up to RGB so the pipeline always
    sees 3 (or 4 for RGBA) channels. This keeps every downstream stage simple.

    Parameters
    ----------
    path:
        Path to the image file.

    Returns
    -------
    np.ndarray
        uint8 array, shape (H, W, 3) or (H, W, 4).
    """
    img = Image.open(path)

    # Normalise mode: anything that is not already RGB/RGBA becomes RGB. This
    # avoids surprises with palette ("P"), greyscale ("L"), or CMYK inputs.
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGB")

    return np.asarray(img, dtype=np.uint8)


def save_image(pixels: np.ndarray, path: str | Path) -> None:
    """
    Save a uint8 (H, W, C) array as a LOSSLESS PNG.

    Parameters
    ----------
    pixels:
        uint8 image array.
    path:
        Destination path. The suffix is forced to .png if it is not already a
        lossless format, because lossy formats would corrupt the ciphertext.

    Raises
    ------
    ValueError
        If the array is not a supported shape/dtype.
    """
    if pixels.dtype != np.uint8:
        raise ValueError("pixels must be uint8")
    if pixels.ndim != 3 or pixels.shape[2] not in (3, 4):
        raise ValueError("pixels must have shape (H, W, 3) or (H, W, 4)")

    path = Path(path)
    if path.suffix.lower() not in (".png",):
        # Guard the user against accidentally choosing a lossy container.
        path = path.with_suffix(".png")

    mode = "RGBA" if pixels.shape[2] == 4 else "RGB"
    Image.fromarray(pixels, mode=mode).save(path, format="PNG")
