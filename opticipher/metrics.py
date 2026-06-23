"""
metrics.py
==========

Quantitative image-encryption metrics for researchers.

OptiCipher is intended as much for STUDY as for use, so this module computes the
standard statistical measures that appear in the image-encryption literature.
Each function works on plain NumPy arrays and returns plain Python floats/dicts
so results are easy to log, tabulate, or feed into a report.

METRICS INCLUDED
----------------
1. Shannon entropy (per channel and global)
       Ideal ciphertext entropy for an 8-bit channel is 8.0 bits/byte. Values
       close to 8.0 indicate a near-uniform histogram (good diffusion).

2. Adjacent-pixel correlation (horizontal, vertical, diagonal)
       Natural images have correlation ~+0.9 between neighbouring pixels. Good
       encryption drives this toward 0 (no exploitable local structure).

3. NPCR and UACI
       Differential-attack resistance metrics measured between two ciphertexts
       whose plaintexts differ by a single pixel:
         * NPCR (Number of Pixels Change Rate): % of differing pixels. Ideal
           ~99.6% for 8-bit RGB.
         * UACI (Unified Average Changing Intensity): mean normalised intensity
           difference. Ideal ~33.4%.
       High NPCR/UACI mean a one-pixel plaintext change avalanches across the
       whole ciphertext, defeating differential cryptanalysis.

4. Histogram
       Raw per-channel counts, useful for plotting flat-vs-peaked distributions.

    These metrics characterise STATISTICAL quality. They are necessary but not
    sufficient for security; they do not, by themselves, prove the scheme is
    cryptographically secure. Treat them as research diagnostics.
"""

from __future__ import annotations

import math
from typing import Dict

import numpy as np


def shannon_entropy(channel: np.ndarray) -> float:
    """
    Compute Shannon entropy (bits per byte) of a single 2-D uint8 channel.

    Entropy H = -sum(p_i * log2 p_i) over the 256 possible byte values, where
    p_i is the empirical probability of value i. Result lies in [0, 8].
    """
    values = channel.reshape(-1)
    counts = np.bincount(values, minlength=256).astype(np.float64)
    total = counts.sum()
    if total == 0:
        return 0.0
    probs = counts / total
    nonzero = probs[probs > 0]  # 0*log0 is treated as 0
    return float(-np.sum(nonzero * np.log2(nonzero)))


def entropy_report(pixels: np.ndarray) -> Dict[str, float]:
    """
    Per-channel and mean Shannon entropy for an (H, W, C) image.

    Returns a dict like {"channel_0": 7.99, ..., "mean": 7.99}.
    """
    report: Dict[str, float] = {}
    channels = pixels.shape[2]
    for c in range(channels):
        report[f"channel_{c}"] = shannon_entropy(pixels[:, :, c])
    report["mean"] = float(np.mean(list(report.values())))
    return report


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    """
    Pearson correlation coefficient between two equal-length 1-D samples.

    Returns 0.0 if either sample has zero variance (avoids divide-by-zero, which
    happens for constant regions).
    """
    a = a.astype(np.float64)
    b = b.astype(np.float64)
    a_c = a - a.mean()
    b_c = b - b.mean()
    denom = math.sqrt(float(np.sum(a_c**2)) * float(np.sum(b_c**2)))
    if denom == 0.0:
        return 0.0
    return float(np.sum(a_c * b_c) / denom)


def adjacent_correlation(
    channel: np.ndarray, sample_size: int = 4096, seed: int = 0
) -> Dict[str, float]:
    """
    Estimate horizontal/vertical/diagonal adjacent-pixel correlation.

    For efficiency on large images we randomly sample up to `sample_size` pixel
    pairs rather than using every pair. The seed makes sampling reproducible.

    Parameters
    ----------
    channel:
        2-D uint8 array (one colour channel).
    sample_size:
        Number of random pixel pairs to sample per direction.
    seed:
        RNG seed for reproducible sampling.

    Returns
    -------
    dict
        {"horizontal": r_h, "vertical": r_v, "diagonal": r_d}.
    """
    h, w = channel.shape
    rng = np.random.default_rng(seed)
    out: Dict[str, float] = {}

    # Horizontal pairs: (r, c) with (r, c+1)
    if w > 1:
        rows = rng.integers(0, h, size=sample_size)
        cols = rng.integers(0, w - 1, size=sample_size)
        out["horizontal"] = _correlation(
            channel[rows, cols], channel[rows, cols + 1]
        )
    else:
        out["horizontal"] = 0.0

    # Vertical pairs: (r, c) with (r+1, c)
    if h > 1:
        rows = rng.integers(0, h - 1, size=sample_size)
        cols = rng.integers(0, w, size=sample_size)
        out["vertical"] = _correlation(
            channel[rows, cols], channel[rows + 1, cols]
        )
    else:
        out["vertical"] = 0.0

    # Diagonal pairs: (r, c) with (r+1, c+1)
    if h > 1 and w > 1:
        rows = rng.integers(0, h - 1, size=sample_size)
        cols = rng.integers(0, w - 1, size=sample_size)
        out["diagonal"] = _correlation(
            channel[rows, cols], channel[rows + 1, cols + 1]
        )
    else:
        out["diagonal"] = 0.0

    return out


def npcr(cipher_a: np.ndarray, cipher_b: np.ndarray) -> float:
    """
    Number of Pixels Change Rate (%) between two ciphertext images.

    Counts the fraction of byte positions that differ, expressed as a
    percentage. Inputs must have identical shape.
    """
    if cipher_a.shape != cipher_b.shape:
        raise ValueError("images must have the same shape for NPCR")
    diff = cipher_a != cipher_b
    return float(np.count_nonzero(diff) / diff.size * 100.0)


def uaci(cipher_a: np.ndarray, cipher_b: np.ndarray) -> float:
    """
    Unified Average Changing Intensity (%) between two ciphertext images.

    Mean absolute difference of byte values, normalised by 255 and expressed as
    a percentage. Inputs must have identical shape.
    """
    if cipher_a.shape != cipher_b.shape:
        raise ValueError("images must have the same shape for UACI")
    a = cipher_a.astype(np.int16)
    b = cipher_b.astype(np.int16)
    return float(np.mean(np.abs(a - b)) / 255.0 * 100.0)


def histogram(channel: np.ndarray) -> np.ndarray:
    """
    Return the 256-bin value histogram of a single channel as an int array.
    """
    return np.bincount(channel.reshape(-1), minlength=256)


def full_report(pixels: np.ndarray, sample_size: int = 4096) -> Dict[str, object]:
    """
    Convenience aggregator: entropy + adjacent correlation for every channel.

    Returns a nested dict suitable for printing or JSON serialisation. Does NOT
    include NPCR/UACI because those require a *pair* of ciphertexts; compute
    them separately with :func:`npcr` / :func:`uaci`.
    """
    report: Dict[str, object] = {"entropy": entropy_report(pixels)}
    corr: Dict[str, Dict[str, float]] = {}
    for c in range(pixels.shape[2]):
        corr[f"channel_{c}"] = adjacent_correlation(
            pixels[:, :, c], sample_size=sample_size
        )
    report["adjacent_correlation"] = corr
    return report
