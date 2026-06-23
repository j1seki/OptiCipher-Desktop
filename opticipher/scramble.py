"""
scramble.py
===========

Spatial permutation (pixel scrambling) for OptiCipher.

GOAL
----
This stage takes the 2-D grid of pixels and shuffles their POSITIONS without
changing any pixel's colour. That destroys the spatial structure of the image:
edges, shapes, and text become noise, even though the exact same set of pixels
is still present. This is the "optical" half of OptiCipher — the result is a
real, viewable image that simply looks scrambled.

WHY A KEYED PERMUTATION INSTEAD OF ARNOLD'S CAT MAP?
---------------------------------------------------
The classic chaos-based choice for image scrambling is Arnold's Cat Map. It is
elegant and famous in the literature, but it has two practical drawbacks for a
general-purpose tool:

  1. It is only defined for SQUARE images (N x N). Real images are rarely square,
     so you must pad/crop, which complicates exact reconstruction.
  2. It is *periodic*: after some number of iterations it returns to the original
     image. The period depends on N in a non-obvious way, so the effective key
     space (the iteration count) is limited and image-size-dependent.

Instead we use a **keyed Fisher–Yates shuffle** of the flattened pixel index
array. Properties:

  * Works for ANY width x height (no padding).
  * The key space is effectively the seed space of the PRNG (huge).
  * It is a true uniform-ish permutation, so there is no "looks partly decrypted"
    intermediate state and no short period to worry about.
  * It is perfectly invertible: applying the inverse permutation restores every
    pixel to its exact original coordinate (lossless).

DETERMINISTIC RNG
-----------------
We drive the shuffle with NumPy's `default_rng` seeded by the `scramble_seed`
derived from the passphrase. Same seed -> same permutation -> exact inverse is
reproducible at decryption time. We use NumPy's PRNG (PCG64) purely as a
*permutation generator*; it is not the source of cryptographic confidentiality
on its own — the integrity tag and the stream cipher provide the cryptographic
guarantees. Here the PRNG's job is to be a fast, well-distributed,
seed-reproducible shuffler.

    RESEARCH NOTE
    -------------
    For a deeper security analysis you would study how seed entropy maps to
    permutation entropy, and the correlation between adjacent pixels before and
    after scrambling (a common image-encryption metric). The `metrics.py` module
    computes adjacent-pixel correlation precisely for this purpose.
"""

from __future__ import annotations

import numpy as np


def _permutation_for(seed: int, n: int) -> np.ndarray:
    """
    Build the forward permutation array of length `n` for a given seed.

    The returned array `perm` is interpreted as:
        scrambled_flat[i] = original_flat[perm[i]]

    Parameters
    ----------
    seed:
        Integer seed (from the derived scramble seed). We mask it to 64 bits
        because NumPy's SeedSequence expects non-negative integers and we want
        deterministic behaviour across platforms.
    n:
        Number of elements (pixels) to permute.

    Returns
    -------
    np.ndarray
        A 1-D int64 array that is a permutation of range(n).
    """
    # NumPy's Generator.permutation gives us a uniform random permutation that is
    # fully determined by the seed. Masking to 64 bits keeps the seed in range.
    rng = np.random.default_rng(seed & 0xFFFFFFFFFFFFFFFF)
    return rng.permutation(n)


def scramble_pixels(pixels: np.ndarray, seed: int) -> np.ndarray:
    """
    Forward scramble: shuffle pixel POSITIONS, keep colours intact.

    Parameters
    ----------
    pixels:
        A NumPy array of shape (H, W, C) where C is the number of channels
        (3 for RGB, 4 for RGBA). dtype is expected to be uint8.
    seed:
        Deterministic permutation seed.

    Returns
    -------
    np.ndarray
        A new array of identical shape/dtype with pixels relocated.

    Notes
    -----
    We flatten only the spatial dimensions (H*W) and keep each pixel's channel
    vector together, so a pixel's colour travels with it as a unit.
    """
    h, w = pixels.shape[:2]
    channels = pixels.shape[2] if pixels.ndim == 3 else 1

    # Collapse the (H, W) grid into a single axis of length H*W, preserving the
    # channel axis. Each row is one pixel's full colour.
    flat = pixels.reshape(h * w, channels)

    perm = _permutation_for(seed, h * w)

    # Gather: the i-th output pixel is taken from position perm[i] of the input.
    scrambled = flat[perm]

    return scrambled.reshape(h, w, channels)


def unscramble_pixels(pixels: np.ndarray, seed: int) -> np.ndarray:
    """
    Inverse scramble: send every pixel back to its original coordinate.

    Parameters
    ----------
    pixels:
        Scrambled array of shape (H, W, C), uint8.
    seed:
        The SAME seed used during scrambling. A different seed yields garbage,
        which is exactly the desired behaviour for a wrong passphrase.

    Returns
    -------
    np.ndarray
        The de-scrambled array, identical to the pre-scramble image.

    How the inverse works
    ---------------------
    If forward did `scrambled[i] = original[perm[i]]`, then to invert we place
    each scrambled pixel back where it came from:
        original[perm[i]] = scrambled[i]
    NumPy lets us express that with fancy-index assignment.
    """
    h, w = pixels.shape[:2]
    channels = pixels.shape[2] if pixels.ndim == 3 else 1

    flat = pixels.reshape(h * w, channels)
    perm = _permutation_for(seed, h * w)

    restored = np.empty_like(flat)
    # Scatter: pixel i of the scrambled image belongs at index perm[i].
    restored[perm] = flat

    return restored.reshape(h, w, channels)
