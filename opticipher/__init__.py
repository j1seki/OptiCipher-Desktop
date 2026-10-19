"""
OptiCipher
==========

A research-oriented, fully open-source library for *optical* (perceptual) image
encryption. OptiCipher produces a real, viewable PNG whose pixels have been
spatially scrambled and value-diffused, with all metadata needed for decryption
embedded inside the image itself (self-contained), authenticated by an HMAC.

Public API
----------
    encrypt_image(pixels, passphrase, iterations=...) -> np.ndarray
    decrypt_image(pixels, passphrase)                 -> np.ndarray
    verify_image(pixels, passphrase=None)             -> VerificationResult
    DecryptionError                                   (exception)

Plus convenient file helpers:
    load_image(path)  -> np.ndarray
    save_image(pixels, path)

And research tooling in `opticipher.metrics`.

See the project README for the full algorithm description, threat model, and
metric definitions.
"""

from .core import (
    DecryptionError,
    MalformedCiphertextError,
    VerificationResult,
    decrypt_image,
    encrypt_image,
    verify_image,
)
from .io_image import load_image, save_image

__all__ = [
    "encrypt_image",
    "decrypt_image",
    "verify_image",
    "VerificationResult",
    "DecryptionError",
    "MalformedCiphertextError",
    "load_image",
    "save_image",
]

__version__ = "1.3.0"
