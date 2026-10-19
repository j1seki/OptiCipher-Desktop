# OptiCipher encrypted-image format (v1)

This document is the normative description of the on-disk format produced by
OptiCipher-Desktop and the `opticipher` CLI. It exists so that any independent
implementation can read our files, and so that our own guarantees are testable
rather than folklore. Every rule below is pinned by a test in `tests/`
(`test_integrity_matrix.py`, `test_corruption.py`, `test_compat_matrix.py`,
`test_file_safety.py`).

Status: **v1, stable.** File format version byte = `1`.

---

## 1. What is encrypted (architecture)

OptiCipher encrypts **decoded pixel arrays**, not raw file bytes:

```
any input format ──load_image──▶ uint8 (H,W,C) ──scramble──▶ ──diffuse──▶
      ──HMAC──▶ append reserved strip ──save──▶ lossless PNG (ciphertext)
```

1. **Scramble** — keyed Fisher–Yates permutation of pixel *positions*
   (`opticipher/scramble.py`). Colour values untouched.
2. **Diffuse** — ChaCha20 keystream XOR over the colour bytes
   (`opticipher/diffusion.py`), making the histogram flat.
3. **Authenticate** — encrypt-then-MAC: HMAC-SHA256 over
   `header-without-tag ‖ main-ciphertext-pixels` (`opticipher/core.py`).
4. **Container** — a *reserved strip* of extra pixel rows is appended below
   the image; the header bytes are written at the top of that strip
   (`opticipher/stego.py`). The result is written as a **lossless PNG**.

The ciphertext is therefore a normal, viewable PNG of size
`(H + strip_rows) × W × C`.

### Key schedule

```
PBKDF2-HMAC-SHA256(passphrase, salt, iterations, dklen=64)
    ├── bytes  0..31  stream_key   → ChaCha20 keystream (diffusion)
    ├── bytes 32..47  scramble_key → uint64 seed for the permutation
    └── bytes 48..63  mac_key      → HMAC-SHA256 key (separate from cipher)
```

* `salt` — 16 fresh random bytes (`os.urandom`) per encryption. Because the
  stream key is derived from the salt, the ChaCha20 nonce (constant per
  document) is **unique under every key**: no nonce reuse is possible across
  files.
* Keys/passwords are never written to files, logs or status messages.

---

## 2. Header layout

70 bytes, big-endian, stored at the beginning of the reserved strip (i.e. the
leading bytes of the final `strip_rows` pixel rows, row-major):

| Offset | Size | Field        | Meaning / constraints                                  |
|-------:|-----:|--------------|--------------------------------------------------------|
| 0      | 4    | `magic`      | `b"OPTC"`                                              |
| 4      | 1    | `version`    | format version — `1` for this document                 |
| 5      | 16   | `salt`       | PBKDF2 salt (random per encryption)                    |
| 21     | 4    | `iterations` | PBKDF2 cost, uint32, `1 … 2^32-1` (readers: see §4)    |
| 25     | 4    | `height`     | original image height (pixels), uint32                 |
| 29     | 4    | `width`      | original image width (pixels), uint32                  |
| 33     | 1    | `channels`   | `3` (RGB) or `4` (RGBA)                                |
| 34     | 4    | `strip_rows` | reserved-strip height = `ceil(70 / (width·channels))`  |
| 38     | 32   | `hmac`       | HMAC-SHA256 (see §3)                                   |

Strip sizing: the strip must hold the 70-byte header plus its row alignment,
so `strip_rows = ceil(70 / (width · channels))` (≥ 1 row; e.g. 1 row for any
image wider than ~23 px in RGB).

---

## 3. What is authenticated

The MAC input is:

```
HMAC-SHA256(mac_key,  pack_header_without_hmac_field  ‖  main_ciphertext_pixels)
```

where `main_ciphertext_pixels` is the image **with the reserved strip
removed** (scrambled+diffused pixels, exactly what the cipher produced).

Covered: every header field above (magic, version, salt, iterations, dims,
channels, strip_rows) **and** every payload byte. Verification uses
`hmac.compare_digest`; decryption output is produced only after this check
passes — no unauthenticated plaintext is ever released.

### Deliberately NOT covered (defined rules, each tested)

| Rule | Rationale | Test |
|------|-----------|------|
| **Strip padding** after byte 70 is ignored/unauthenticated. It is unused storage; its content cannot affect restoration. | Keeping it out of the MAC keeps the header free of self-reference. | `test_strip_padding_after_header_is_ignored_by_design` |
| **Trailing bytes appended to the PNG file** (after `IEND`) are container-level and never delivered to the pixels; decryption succeeds unchanged. The payload itself still cannot be altered undetected. | OptiCipher authenticates the pixel payload, not the container's slack space. | `test_trailing_file_bytes_are_container_level_and_ignored` |
| **Rows appended to the pixel array** become the header tail → parse/bounds failure → rejection. | They change the payload. | `test_appended_pixel_rows_rejected` |

Zip/archive round-trips are safe *iff* they are byte-lossless — which ZIP and
copy/rename always are (`test_zip_roundtrip_preserves_ciphertext_bytes`,
`test_copy_rename_and_repeated_reopen_preserve_decryption`).

---

## 4. Reader obligations (untrusted input)

The header arrives from an untrusted file and is **not authenticated yet**
when the reader starts work. To prevent a crafted file from forcing
unbounded cost, the reader MUST reject, *before* key derivation and before
any other expensive step, any header where:

* `iterations > 10_000_000` (5× the 2 000 000 GUI/CLI ceiling; a crafted
  uint32-max value would otherwise burn ~hours of CPU in PBKDF2 before the
  HMAC check could fail), or `iterations < 1`;
* `channels ∉ {3, 4}`, `height < 1`, `width < 1`;
* `strip_rows < 1`, `≥ image height`, or `> ceil(70/(width·channels)) + 1`.

All of these surface as the same generic error as an HMAC failure (§6), so
pre-authentication failures reveal nothing about the passphrase. Then:
re-derive keys → strip removal → dimension check → **HMAC verification** →
and only against a *verified* HMAC, the version check.

---

## 5. Restoration guarantees

| Guarantee | Status |
|-----------|--------|
| **Pixel-exact** | ✅ For RGB/RGBA inputs read from lossless containers: decrypted pixels equal exactly what Pillow decoded from the original file. Verified per format in `test_compat_matrix.py`. |
| **Byte-exact (file)** | ❌ Not provided. The restored file is a fresh PNG written by Pillow. Original encoder bytes, EXIF, ICC profiles, palette mode and other metadata are **not preserved** — encryption operates on the pixel array, and that array is all that is authenticated. |
| **Mode preservation** | ❌ Inputs in `L`/`P`/`CMYK` are converted to RGB (documented); RGBA alpha is preserved exactly. |
| **Animation** | GIF inputs restore the **first frame only** (as decoded). |

### Compatibility matrix (all tested — `tests/test_compat_matrix.py`)

| Input format | Encrypt | Pixel-exact restore | Notes |
|---|---|---|---|
| PNG (RGB/RGBA) | ✅ | ✅ | lossless; alpha preserved |
| JPEG | ✅ | ✅ vs decoded pixels | source is lossy; EXIF not carried over |
| BMP, TIFF, WebP (lossless) | ✅ | ✅ vs decoded pixels | |
| GIF (animated) | ✅ | ✅ first frame only | |
| L / P / CMYK | ✅ | ✅ after documented RGB conversion | mode itself not restored |
| **Ciphertext → ZIP → extract** | — | ✅ byte-identical ciphertext → decrypts | any lossless archive |
| **Ciphertext re-saved as PNG** | — | ✅ safe (pixel-lossless) | |
| **Ciphertext re-encoded as JPEG** | — | 🛑 **destructive, detected** — decryption fails with a clear error | never silently accepted |

---

## 6. Error semantics

| Condition | Exception / message |
|-----------|--------------------|
| Not an OptiCipher file (bad magic / too small) | `ValueError` — “not an OptiCipher image …” |
| Wrong passphrase **or** payload/header tamper **or** any §4 bound failure | `DecryptionError` — *identical* message: “integrity check failed: wrong passphrase or the file was modified.” (deliberately indistinguishable — no password oracle) |
| Corrupt dimensions vs payload | `DecryptionError` — “image dimensions do not match the embedded header (corrupted file)” |
| Valid MAC but `version ≠ 1` (a future format) | `ValueError` — “unsupported OptiCipher format version N … Update OptiCipher to open this file.” (checked **after** authentication, so a tampered version byte fails the MAC first) |

Authentication failures never produce a success message, and no code path
returns pixels that did not pass the MAC.

---

## 7. Compatibility & evolution

* **Golden vector** — `test_golden_ciphertext_v1_is_byte_stable` fixes a
  deterministic salt, passphrase, iterations and input image and asserts the
  exact ciphertext SHA-256
  (`308566bd1c952c7e2f88665914369fd2055856fe10a139d384c7bbc1325e7f0f`).
  Any change to the primitives or the layout breaks this test — that is a
  **format version bump**, not a silent edit.
* **Version policy** — readers accept `version == 1` only, and say so
  explicitly for other versions *after* verifying the MAC. A future v2 may
  keep v1 files readable (additive change) or require a migrator; migration
  must never destroy the only copy of an old-format file.
* **Writes are safe** — outputs are written to a temp file in the destination
  directory, fsync'd, then published with atomic `os.replace`; an existing
  file is never overwritten unless the caller explicitly opts in (otherwise a
  `stem_2.png` name is chosen). See `docs/FORMAT.md` §5 of the audit and
  `tests/test_file_safety.py`.

## 8. Known limitations

* PBKDF2 is memory-cheap: strong against casual attacks, weaker against
  GPU/ASIC cracking than Argon2id/scrypt. The iteration cost is stored per
  file so parameters can improve without breaking old files.
* Password loss is unrecoverable by design (no key escrow).
* File-metadata (EXIF/ICC/palette) is not part of what is encrypted — see §5.
* Durability: file data is fsync'd before publish; the directory entry is not
  fsync'd on every platform (no portable API on Windows), so power loss in
  the instant after a save can lose the new directory entry while the old
  file remains.
* Ciphertext PNGs must not be transformed through lossy encoders (JPEG) or
  geometric edits — §5's matrix.
