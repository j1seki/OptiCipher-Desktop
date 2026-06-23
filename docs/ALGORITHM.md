# OptiCipher Algorithm Reference

This document describes the OptiCipher scheme in enough detail to re-implement or
analyse it. It complements the heavily-commented source code; where the two ever
disagree, the **code is authoritative**.

## Notation

- `P` — plaintext image, a `uint8` array of shape `(H, W, C)`, `C ∈ {3, 4}`.
- `K` — the user passphrase (UTF-8).
- `salt` — 16 random bytes, fresh per encryption.
- `iters` — PBKDF2 iteration count (default 200,000).
- `||` — byte concatenation.

## 1. Key derivation (`keys.py`)

```
block        = PBKDF2_HMAC_SHA256(K, salt, iters, dklen = 64)
stream_key   = block[0:32]                       # ChaCha20 key
scramble_seed= int_big_endian(block[32:48])      # permutation seed
mac_key      = block[48:64]                       # HMAC key
```

The single PBKDF2 call is split into three role-separated sub-keys. Reusing key
bytes across roles is avoided on principle.

## 2. Spatial permutation (`scramble.py`)

Let `N = H · W`. Flatten the spatial grid to `N` pixels (each keeping its `C`
colour channels). Generate a permutation `π` of `{0, …, N−1}` deterministically
from `scramble_seed` using NumPy's PCG64 generator:

```
π = Generator(PCG64(scramble_seed)).permutation(N)
scrambled[i] = flat[π[i]]          # forward
```

Inverse (used in decryption):

```
restored[π[i]] = scrambled[i]      # scatter back to original positions
```

This keyed Fisher–Yates-style shuffle works for **any** `H × W` (no square-image
constraint) and has no short period, unlike Arnold's Cat Map.

## 3. Value diffusion (`diffusion.py`)

A ChaCha20 keystream is generated from `(stream_key, nonce)` where

```
nonce = SHA256(salt)[0:16]
```

and XOR-ed over the raw pixel bytes:

```
cipher_bytes = plain_bytes ⊕ ChaCha20_keystream(stream_key, nonce)
```

XOR is involutive, so decryption is the identical operation. Because `stream_key`
is unique per image (fresh salt → fresh PBKDF2 output), deriving the nonce from
the salt does not cause a dangerous `(key, nonce)` reuse.

## 4. Header and integrity (`header.py`, `core.py`)

Build the pre-HMAC header `Hpre` (38 bytes) containing magic, version, salt,
iters, height, width, channels, strip_rows. Compute:

```
tag = HMAC_SHA256(mac_key, Hpre || cipher_bytes)
header = Hpre || tag            # 70 bytes
```

This is **encrypt-then-MAC**: the tag covers the already-diffused ciphertext plus
the header metadata, so any change to either is detected.

## 5. Reserved-strip embedding (`stego.py`)

Compute `strip_rows = ceil(70 / (W · C))`. Append `strip_rows` new pixel rows
below the diffused image and write the 70 header bytes into the start of that
strip (remaining bytes are zero padding). The result has shape
`(H + strip_rows, W, C)` and is saved as **lossless PNG**.

## Decryption

```
1. Read the leading 70 bytes of the final strip rows → parse header (magic check).
2. Re-derive keys from (K, salt, iters).
3. Remove the strip → recover the exact diffused ciphertext; check (H, W) match.
4. Recompute tag' = HMAC(mac_key, Hpre || cipher_bytes); require tag' == tag
   (constant-time). Abort with DecryptionError otherwise.
5. UN-diffuse (XOR same keystream), then UN-scramble (inverse permutation).
6. Output is bit-identical to P.
```

## Correctness argument (lossless round trip)

- The strip is **dedicated** storage appended below the image; writing the header
  never modifies a ciphertext pixel.
- Diffusion is XOR with a reproducible keystream ⇒ exactly invertible.
- The permutation `π` is a bijection reproduced from the same seed ⇒ exactly
  invertible.
- Therefore `decrypt(encrypt(P, K), K) == P` for every valid `P`, which the test
  suite verifies across many shapes including RGBA and 1×N edge cases.

## Format versioning

The 1-byte `version` field allows future changes (e.g. swapping PBKDF2 for
Argon2id, or adding a compression stage) while letting tools recognise and handle
older files gracefully.
