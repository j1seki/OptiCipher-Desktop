"""
keys.py
=======

Key derivation module for OptiCipher.

This module is responsible for turning a human-supplied passphrase into the
cryptographically strong material that the rest of the pipeline consumes.

WHY A KEY DERIVATION FUNCTION (KDF)?
------------------------------------
A passphrase like "hello123" has very little entropy and is the wrong length
to be used directly as a cipher key. A KDF stretches that passphrase into a
fixed-length, high-entropy key, and (crucially) makes brute-force guessing
expensive by forcing many internal iterations.

We use PBKDF2-HMAC-SHA256, which is part of the Python standard library
(`hashlib.pbkdf2_hmac`) and therefore adds no third-party dependency for the
key-derivation step itself. PBKDF2 is well understood, FIPS-approved, and
sufficient for a research/educational reference implementation.

    NOTE FOR RESEARCHERS
    --------------------
    PBKDF2 is *memory-cheap*, which means it is comparatively weak against
    attackers using GPUs or ASICs. For production-grade password hardening you
    would prefer a memory-hard KDF such as Argon2id or scrypt. We deliberately
    keep PBKDF2 here so the whole project runs on the standard library plus a
    minimal set of well-known packages, and so the algorithm is easy to read.
    The iteration count is exposed and documented so it can be benchmarked.

DETERMINISM
-----------
Given the SAME (passphrase, salt, iterations), this module ALWAYS produces the
SAME bytes. That determinism is the entire reason decryption is possible: the
decryptor re-derives identical key material from the user's passphrase plus the
salt that was embedded in the encrypted image.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

# ---------------------------------------------------------------------------
# Tunable constants.
# ---------------------------------------------------------------------------
# These are exposed as module-level constants so a researcher can change them in
# one place and measure the effect on security margin and runtime.

#: Length of the random salt in bytes. 16 bytes (128 bits) is the conventional
#: minimum; it ensures two users with the same passphrase get different keys.
SALT_LENGTH: int = 16

#: Number of PBKDF2 iterations. Higher = slower to brute force but slower to
#: run. 200_000 is a reasonable 2024-era default for SHA256. This value is
#: stored inside the image so the decryptor uses the exact same count.
DEFAULT_ITERATIONS: int = 200_000

#: Total length, in bytes, of the derived key material we ask PBKDF2 to produce.
#: We then split this block into sub-keys (see `DerivedKeys`). 64 bytes gives us
#: room for a 32-byte stream-cipher key, a 16-byte scrambling seed, and a
#: 16-byte MAC key, all from a single PBKDF2 call.
DERIVED_KEY_LENGTH: int = 64

#: Hash function PBKDF2 builds its HMAC on top of.
_HASH_NAME: str = "sha256"


@dataclass(frozen=True)
class DerivedKeys:
    """
    A bundle of independent sub-keys derived from one passphrase.

    Splitting one PBKDF2 output into several role-specific keys is standard
    practice: you never want to reuse the same key bytes for two different
    cryptographic purposes (here: stream encryption, pixel scrambling, and
    integrity authentication).

    Attributes
    ----------
    stream_key:
        32 bytes used to seed the RGB stream cipher (ChaCha20).
    scramble_seed:
        An integer seed used by the pixel-permutation stage. Derived from
        16 bytes of key material so the permutation is unpredictable without
        the passphrase.
    mac_key:
        16 bytes used as the key for the HMAC integrity tag.
    """

    stream_key: bytes
    scramble_seed: int
    mac_key: bytes


def generate_salt() -> bytes:
    """
    Produce a fresh cryptographically secure random salt.

    `os.urandom` draws from the operating system's CSPRNG, which is appropriate
    for security-sensitive randomness (unlike `random`, which is not).

    Returns
    -------
    bytes
        `SALT_LENGTH` random bytes.
    """
    return os.urandom(SALT_LENGTH)


def derive_keys(
    passphrase: str,
    salt: bytes,
    iterations: int = DEFAULT_ITERATIONS,
) -> DerivedKeys:
    """
    Derive the full set of sub-keys from a passphrase and salt.

    Parameters
    ----------
    passphrase:
        The user's secret. Encoded as UTF-8 before hashing so that non-ASCII
        (e.g. Arabic) passphrases are supported consistently across platforms.
    salt:
        Per-image random salt produced by :func:`generate_salt`. Must be stored
        alongside the ciphertext (we embed it in the image) so the same keys can
        be reproduced at decryption time.
    iterations:
        PBKDF2 iteration count. Defaults to :data:`DEFAULT_ITERATIONS`.

    Returns
    -------
    DerivedKeys
        The bundle of sub-keys.

    Raises
    ------
    ValueError
        If the salt is the wrong length or iterations is non-positive. These
        checks catch programmer/file-corruption errors early instead of
        silently producing a wrong (and undecryptable) key.
    """
    if len(salt) != SALT_LENGTH:
        raise ValueError(
            f"salt must be exactly {SALT_LENGTH} bytes, got {len(salt)}"
        )
    if iterations <= 0:
        raise ValueError("iterations must be a positive integer")

    # Single PBKDF2 call produces one long block of pseudo-random bytes.
    block = hashlib.pbkdf2_hmac(
        _HASH_NAME,
        passphrase.encode("utf-8"),
        salt,
        iterations,
        dklen=DERIVED_KEY_LENGTH,
    )

    # Partition the 64-byte block into role-specific slices.
    #   bytes  0..32  -> stream cipher key
    #   bytes 32..48  -> scramble seed (interpreted as a big-endian integer)
    #   bytes 48..64  -> MAC key
    stream_key = block[0:32]
    scramble_seed = int.from_bytes(block[32:48], byteorder="big")
    mac_key = block[48:64]

    return DerivedKeys(
        stream_key=stream_key,
        scramble_seed=scramble_seed,
        mac_key=mac_key,
    )
