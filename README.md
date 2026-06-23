# OptiCipher

**Open-source optical (perceptual) image encryption — for research and education.**

OptiCipher turns an image into a real, viewable PNG that *looks* like pure noise,
yet still contains every bit of the original. Pixels are spatially **scrambled**
and their colour values are **diffused** with a stream cipher. Everything needed
to decrypt (except your passphrase) is embedded **inside the image itself**, so a
single PNG is fully self-contained. Decryption is **bit-exact**: you get back the
original image, pixel for pixel.

> **Status:** research / educational reference implementation. Read
> [Threat model & security notes](#threat-model--security-notes) before using it
> to protect anything that genuinely matters.

---

## Table of contents

- [What "optical encryption" means here](#what-optical-encryption-means-here)
- [Is this idea new?](#is-this-idea-new)
- [How it works (the algorithm)](#how-it-works-the-algorithm)
- [The self-contained header](#the-self-contained-header)
- [Project layout](#project-layout)
- [Installation](#installation)
- [Quick start](#quick-start)
- [Command-line usage](#command-line-usage)
- [Library usage](#library-usage)
- [Research metrics](#research-metrics)
- [Results on the bundled sample](#results-on-the-bundled-sample)
- [Threat model & security notes](#threat-model--security-notes)
- [Running the tests](#running-the-tests)
- [Benchmarking](#benchmarking)
- [Contributing](#contributing)
- [License](#license)

---

## What "optical encryption" means here

A normal cipher turns data into an opaque blob of bytes. OptiCipher instead keeps
the output as a **valid image**. The encrypted file is a PNG you can open in any
viewer; it simply shows visual noise. Two things are scrambled:

| Stage | What it hides | Effect |
|-------|---------------|--------|
| **Scramble** (permutation) | *where* each colour is | destroys shapes, edges, text |
| **Diffuse** (stream cipher) | *what* each colour is | flattens the histogram |

Together they remove both the spatial structure and the colour statistics of the
original, which is exactly what the standard "confusion + diffusion" principle of
cipher design asks for.

---

## Is this idea new?

**The building blocks are well established; the specific combination here is the
interesting part.** Image-encryption research dates back to the 1990s. You will
find extensive prior work on:

- **Pixel permutation / scrambling** — Arnold's Cat Map, chaotic maps, etc.
- **Value diffusion** — XOR with chaotic or cryptographic keystreams.
- **Visual / perceptual encryption** — keeping the ciphertext as an image.
- **LSB steganography and watermarking** — hiding data inside images.

What OptiCipher emphasises, and what is comparatively uncommon in one tidy
package, is being **fully self-contained and authenticated**:

1. A modern, audited stream cipher (**ChaCha20**) for diffusion rather than a
   home-rolled chaotic map.
2. A **size-agnostic keyed permutation** (Fisher–Yates) that works for any
   width × height — no square-image restriction like Arnold's Cat Map.
3. All decryption metadata (salt, iterations, dimensions) embedded **inside the
   image**, so there is no separate key file to manage.
4. **HMAC-SHA256 integrity**, so a wrong passphrase or any tampering is detected
   instead of silently producing garbage.

So: not a new primitive, but a clean, documented, reproducible synthesis that is
pleasant to study and to build on.

---

## How it works (the algorithm)

```
ENCRYPT
                          passphrase
                              │
                  ┌───────────▼───────────┐
   random salt ──►│  PBKDF2-HMAC-SHA256    │  (keys.py)
                  └───────────┬───────────┘
                              │  stream_key │ scramble_seed │ mac_key
  original ─► SCRAMBLE positions ─► DIFFUSE values ─► HMAC ─► append header strip
  (H×W×C)     (scramble.py)         (diffusion.py)   (core)   (stego.py)
                                                                  │
                                                                  ▼
                                                  self-contained ciphertext PNG
                                                       (H+strip rows × W × C)

DECRYPT
  ciphertext ─► read+parse header ─► re-derive keys ─► verify HMAC
                (stego/header)        (keys.py)         (core.py)
                              │ (fails fast on wrong passphrase / tampering)
                              ▼
             remove strip ─► UN-DIFFUSE ─► UN-SCRAMBLE ─► exact original
```

**Step by step:**

1. **Key derivation (`keys.py`).** Your passphrase plus a fresh random 16-byte
   salt are stretched by **PBKDF2-HMAC-SHA256** (default 200,000 iterations) into
   64 bytes, split into three role-specific sub-keys: a 32-byte stream key, a
   permutation seed, and a 16-byte MAC key. Same passphrase + salt ⇒ identical
   keys, which is what makes decryption possible.

2. **Scramble (`scramble.py`).** A keyed **Fisher–Yates** shuffle permutes pixel
   *positions* (colours travel with their pixel). It works for any image shape
   and is perfectly invertible.

3. **Diffuse (`diffusion.py`).** Every colour byte is XOR-ed with a **ChaCha20**
   keystream. Because each image gets a unique key (fresh salt), reusing a
   constant-derived nonce is safe. XOR is its own inverse, so the same routine
   encrypts and decrypts.

4. **Authenticate + embed (`core.py`, `header.py`, `stego.py`).** An
   **HMAC-SHA256** tag is computed over the header fields and the ciphertext
   ("encrypt-then-MAC"). The header is then written into a small **reserved
   strip** of extra pixel rows appended to the bottom of the image.

Decryption reverses everything and refuses to proceed unless the HMAC verifies.

---

## The self-contained header

Every encrypted image carries a 70-byte header in a thin appended strip:

| Field | Size | Purpose |
|-------|------|---------|
| magic `OPTC` | 4 | identify an OptiCipher file |
| version | 1 | format versioning |
| salt | 16 | re-derive the keys |
| iterations | 4 | PBKDF2 cost actually used |
| height / width | 4 + 4 | original dimensions |
| channels | 1 | 3 (RGB) or 4 (RGBA) |
| strip_rows | 4 | how many rows to remove on decrypt |
| HMAC-SHA256 | 32 | integrity / passphrase check |

The salt and iteration count are **not secret** — exactly like the plaintext salt
stored next to a password hash. All confidentiality comes from the passphrase.

> **Why a reserved strip and not LSB steganography?** Hiding the header in the
> least-significant bits of the ciphertext creates a self-referential sizing
> paradox (the bits you overwrite are themselves ciphertext that must be restored
> exactly). A dedicated strip sidesteps that entirely and guarantees a lossless
> round trip. The trade-off is a few extra pixel rows — invisible in practice.

---

## Project layout

```
OptiCipher/
├── opticipher/              # the library
│   ├── __init__.py          # public API
│   ├── __main__.py          # enables `python -m opticipher`
│   ├── keys.py              # PBKDF2 key derivation
│   ├── scramble.py          # keyed pixel permutation
│   ├── diffusion.py         # ChaCha20 value diffusion
│   ├── header.py            # binary header layout
│   ├── stego.py             # reserved-strip storage
│   ├── core.py              # encrypt/decrypt orchestration + HMAC
│   ├── io_image.py          # PNG load/save helpers
│   ├── metrics.py           # entropy, correlation, NPCR, UACI
│   └── cli.py               # command-line interface
├── tests/                   # pytest suite (run with `pytest`)
│   ├── test_roundtrip.py
│   ├── test_components.py
│   └── test_metrics_and_sample.py
├── samples/                 # the bundled "CLAUDE CODE" sample + outputs
│   ├── sample_claude_code.png
│   ├── sample_encrypted.png
│   └── sample_decrypted.png
├── examples/                # runnable demos
│   ├── demo.py
│   └── benchmark.py
├── docs/                    # extra documentation
│   ├── ALGORITHM.md
│   └── METRICS.md
├── pyproject.toml           # packaging / install metadata
├── requirements.txt
├── LICENSE                  # MIT
├── CONTRIBUTING.md
└── README.md
```

---

## Installation

Requires **Python 3.9+**.

```bash
git clone https://github.com/bio-colab/OptiCipher.git
cd OptiCipher

# Option A: install the package (gives you the `opticipher` command)
pip install -e .

# Option B: just install the dependencies and run in place
pip install -r requirements.txt
```

Dependencies are minimal and widely used: **NumPy**, **Pillow**, **cryptography**.

---

## Quick start

```bash
# Encrypt (you'll be prompted for a passphrase, twice)
opticipher encrypt samples/sample_claude_code.png encrypted.png

# Decrypt
opticipher decrypt encrypted.png recovered.png

# See the statistics for any image
opticipher metrics encrypted.png
```

Or run the guided demo:

```bash
python examples/demo.py
```

---

## Command-line usage

```
opticipher encrypt  <input> <output> [--passphrase PASS] [--iterations N]
opticipher decrypt  <input> <output> [--passphrase PASS]
opticipher metrics  <input>
```

- Omit `--passphrase` to be prompted **securely** (no echo, no shell history).
- `--iterations` lets you tune the PBKDF2 cost (default 200,000). The value is
  stored in the image so decryption uses the same count automatically.
- Output is always written as **lossless PNG** (a `.png` suffix is enforced),
  because a lossy format like JPEG would destroy the ciphertext.

---

## Library usage

```python
import numpy as np
from opticipher import load_image, save_image, encrypt_image, decrypt_image

# Load any image as a uint8 (H, W, C) array
img = load_image("photo.png")

# Encrypt
enc = encrypt_image(img, "my strong passphrase")
save_image(enc, "photo_encrypted.png")

# Decrypt (bit-exact)
dec = decrypt_image(load_image("photo_encrypted.png"), "my strong passphrase")
assert np.array_equal(img, dec)
```

A wrong passphrase or a tampered file raises `opticipher.DecryptionError`.

---

## Research metrics

`opticipher.metrics` implements the standard image-encryption diagnostics so you
can quantify quality rather than just eyeballing the noise. See
[`docs/METRICS.md`](docs/METRICS.md) for the formulas and interpretation.

| Metric | Function | Ideal for ciphertext |
|--------|----------|----------------------|
| Shannon entropy | `entropy_report` | ≈ 8.0 bits/byte |
| Adjacent-pixel correlation | `adjacent_correlation` | ≈ 0 |
| NPCR (pixel change rate) | `npcr` | ≈ 99.6 % |
| UACI (intensity change) | `uaci` | ≈ 33.4 % |
| Histogram | `histogram` | flat |

---

## Results on the bundled sample

Measured on `samples/sample_claude_code.png` (322 × 620 RGB). Reproduce with
`python examples/demo.py`.

| Metric | Original | Encrypted | Ideal |
|--------|---------:|----------:|------:|
| Mean Shannon entropy (bits/byte) | 2.475 | **7.999** | 8.000 |
| Correlation, horizontal (ch0) | 0.941 | **≈ 0.00** | 0 |
| Correlation, vertical (ch0) | 0.923 | **≈ 0.02** | 0 |
| Correlation, diagonal (ch0) | 0.870 | **≈ 0.01** | 0 |
| NPCR (1-pixel change) | — | **≈ 99.6 %** | 99.6 % |
| UACI (1-pixel change) | — | **≈ 33.5 %** | 33.4 % |
| Round-trip | — | **bit-exact** | exact |

Visually:

| Original | Encrypted | Decrypted |
|----------|-----------|-----------|
| `sample_claude_code.png` | `sample_encrypted.png` (noise) | `sample_decrypted.png` (identical) |

---

## Threat model & security notes

OptiCipher is an honest, well-documented **reference implementation**. Please read
this section before trusting it with anything important.

**What it provides**

- **Confidentiality** of image content against someone without the passphrase,
  via ChaCha20 diffusion keyed by PBKDF2.
- **Integrity / authenticity** via HMAC-SHA256 (encrypt-then-MAC). Tampering or a
  wrong passphrase is detected.
- **Per-image uniqueness** via a fresh random salt, so identical plaintexts do
  not produce identical ciphertexts.

**Known limitations and honest caveats**

- **PBKDF2 is memory-cheap**, so it is comparatively weak against GPU/ASIC
  brute-force. For high-value secrets, a memory-hard KDF (Argon2id, scrypt) would
  be stronger. PBKDF2 is used here to keep dependencies minimal and the code
  readable; the iteration count is exposed and benchmarked.
- The **permutation** is driven by NumPy's PRNG seeded from key material. It
  provides spatial confusion and contributes to the statistics, but the
  cryptographic confidentiality guarantee rests on **ChaCha20**, not on the
  permutation alone.
- The statistical metrics (entropy, correlation, NPCR, UACI) are **necessary but
  not sufficient** indicators. Passing them does not constitute a security proof.
- This project has **not** had a formal third-party cryptographic audit. Do not
  use it as the sole protection for safety-critical or legally sensitive data.

If you are a cryptographer or security researcher, contributions that harden or
formally analyse the scheme are very welcome — see below.

---

## Running the tests

```bash
pip install -e ".[dev]"     # installs pytest
pytest -v
```

The suite (34 tests) covers each component in isolation, full encrypt→decrypt
round trips across many image shapes (including RGBA and degenerate 1×N images),
Unicode passphrases, wrong-passphrase rejection, tamper detection, and the
statistical behaviour on the real sample image.

---

## Benchmarking

```bash
python examples/benchmark.py
```

Prints encryption/decryption throughput across image sizes, the isolated PBKDF2
cost, and the full statistical suite, and writes
`examples/benchmark_results.json` for further analysis.

---

## Contributing

**OptiCipher is open source and community contributions are warmly invited.**
Whether you are a student, a security researcher, or just curious, there is room
to help. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details. Good first issues
include:

- Adding **Argon2id** as an optional KDF.
- Adding new **metrics** (e.g. χ² histogram uniformity test, local Shannon
  entropy, key-sensitivity analysis).
- A **GUI** or web front-end over the library.
- Performance work (vectorisation, optional native backend).
- More **sample images** and reproducible metric reports.
- Independent **security analysis** and write-ups.

Please open an issue to discuss substantial changes first, keep the heavy
commenting style consistent with the existing code, and add tests for new
behaviour.

---

## License

Released under the **MIT License** — you are free to use, modify, and
redistribute it, including commercially, provided the copyright and licence
notice are retained. See [`LICENSE`](LICENSE).
