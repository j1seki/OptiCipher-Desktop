"""
header.py
=========

Binary layout of OptiCipher's self-contained header.

The header is a small block of metadata stored inside every encrypted image. It
lets the decryptor reconstruct identical key material and verify integrity using
ONLY the image file plus the user's passphrase.

WHERE THE HEADER LIVES
----------------------
OptiCipher appends a thin "reserved strip" of extra pixel rows to the bottom of
the scrambled+diffused image and writes the header bytes DIRECTLY into that strip
(see core.py / stego.py). The strip is NOT scrambled or diffused, so the header
is recovered byte-for-byte with no ambiguity and no self-referential snapshot.
This keeps the main ciphertext visually intact and makes the round trip exactly
lossless.

LAYOUT (all multi-byte integers are big-endian / network order)
---------------------------------------------------------------
    Offset  Size  Field         Meaning
    ------  ----  ------------  ------------------------------------------------
       0     4    magic         b"OPTC" — identifies an OptiCipher image
       4     1    version       format version (currently 1)
       5    16    salt          PBKDF2 salt (keys.SALT_LENGTH bytes)
      21     4    iterations    PBKDF2 iteration count (uint32)
      25     4    height        ORIGINAL image height in pixels (uint32)
      29     4    width         ORIGINAL image width  in pixels (uint32)
      33     1    channels      number of colour channels (3 or 4)
      34     4    strip_rows    number of reserved rows appended (uint32)
      38    32    hmac          HMAC-SHA256 integrity tag (filled in last)
    ------  ----  ------------  ------------------------------------------------
    Total: 70 bytes.

WHY STORE DIMENSIONS AND STRIP_ROWS?
------------------------------------
`height`/`width` record the ORIGINAL image size so the decryptor knows exactly
how many rows to keep after removing the reserved strip. `strip_rows` records how
many rows were appended, so the decryptor can slice the strip off precisely.
Authenticating all of these under the HMAC prevents an attacker from reshaping
or cropping the image to confuse decryption.

WHY A MAGIC NUMBER AND VERSION?
-------------------------------
The magic lets tools reject non-OptiCipher files with a friendly error instead
of producing nonsense. The version byte future-proofs the on-disk format.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

#: Identifies an OptiCipher payload. Four ASCII bytes.
MAGIC: bytes = b"OPTC"

#: Current on-disk format version.
VERSION: int = 1

#: Size of the HMAC-SHA256 tag in bytes.
HMAC_LENGTH: int = 32

# struct format for the FIXED portion BEFORE the HMAC:
#   >    big-endian
#   4s   magic
#   B    version
#   16s  salt
#   I    iterations
#   I    height
#   I    width
#   B    channels
#   I    strip_rows
_PREHMAC_FORMAT: str = ">4sB16sIIIBI"

#: Number of bytes occupied by everything except the HMAC tag.
PREHMAC_SIZE: int = struct.calcsize(_PREHMAC_FORMAT)  # == 38

#: Total header size including the HMAC.
HEADER_SIZE: int = PREHMAC_SIZE + HMAC_LENGTH  # == 70


@dataclass
class Header:
    """
    Parsed, in-memory representation of an OptiCipher header.

    The `hmac` field is empty during construction because the encryptor builds
    the rest of the header first, computes the HMAC over the ciphertext, and
    only then sets the tag.
    """

    salt: bytes
    iterations: int
    height: int
    width: int
    channels: int
    strip_rows: int
    hmac: bytes = b""
    version: int = VERSION

    def pack_prehmac(self) -> bytes:
        """
        Serialise everything EXCEPT the HMAC tag.

        This is the exact byte string the HMAC is computed over (together with
        the main ciphertext), so both encryptor and decryptor must produce it
        identically.
        """
        return struct.pack(
            _PREHMAC_FORMAT,
            MAGIC,
            self.version,
            self.salt,
            self.iterations,
            self.height,
            self.width,
            self.channels,
            self.strip_rows,
        )

    def pack(self) -> bytes:
        """
        Serialise the FULL header (pre-HMAC fields followed by the 32-byte tag).

        Raises
        ------
        ValueError
            If the HMAC has not been set or is the wrong length, which indicates
            a programming error in the encryption pipeline.
        """
        if len(self.hmac) != HMAC_LENGTH:
            raise ValueError(
                f"hmac must be {HMAC_LENGTH} bytes before packing the full header"
            )
        return self.pack_prehmac() + self.hmac


def parse(raw: bytes) -> Header:
    """
    Parse a full header block.

    Parameters
    ----------
    raw:
        At least :data:`HEADER_SIZE` bytes read from the reserved strip. Extra
        trailing padding bytes (the strip is row-aligned and may be larger than
        the header) are ignored.

    Returns
    -------
    Header
        The parsed header.

    Raises
    ------
    ValueError
        If the block is too short or the magic number does not match, which
        usually means the file is not an OptiCipher image.
    """
    if len(raw) < HEADER_SIZE:
        raise ValueError(
            f"header needs {HEADER_SIZE} bytes, got {len(raw)}"
        )

    raw = raw[:HEADER_SIZE]
    pre = raw[:PREHMAC_SIZE]
    tag = raw[PREHMAC_SIZE:]

    (
        magic,
        version,
        salt,
        iterations,
        height,
        width,
        channels,
        strip_rows,
    ) = struct.unpack(_PREHMAC_FORMAT, pre)

    if magic != MAGIC:
        raise ValueError(
            "not an OptiCipher image (magic number mismatch). "
            "The file may be unencrypted, corrupted, or from another tool."
        )

    return Header(
        salt=salt,
        iterations=iterations,
        height=height,
        width=width,
        channels=channels,
        strip_rows=strip_rows,
        hmac=tag,
        version=version,
    )
