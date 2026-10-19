# OptiCipher

> **This repository is the OptiCipher Desktop fork** — a cross-platform desktop
> app and hardware-accelerated build of [bio-colab/OptiCipher](https://github.com/bio-colab/OptiCipher)
> (MIT). The encryption algorithm, file format and CLI are unchanged: encrypted
> PNGs are **bit-for-bit interchangeable** with the original tool in both
> directions, proven by a test suite that pins every compute backend to the
> reference bytes. See [OptiCipher Desktop](#opticipher-desktop-this-fork) below.

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

## OptiCipher Desktop (this fork)

A PySide6 desktop app over the same library, with pluggable hardware
acceleration and per-OS installers.

### Screenshots

Real captures from the running app (regenerate with
`python packaging/screenshots.py`).

**Encrypt tab** — sample loaded, encryption finished, before/after preview,
KDF cost, live device bar:

![OptiCipher Desktop — Encrypt tab](docs/screenshots/main-window.png)

**Analyze tab** — entropy, adjacent-pixel correlation, NPCR/UACI and the
per-channel histogram for an original/ciphertext pair:

![OptiCipher Desktop — Analyze tab](docs/screenshots/analyze.png)

**Settings dialog** — compute device, threads, RAM budget, PBKDF2 cost, and
what this machine offers:

![OptiCipher Desktop — Settings dialog](docs/screenshots/settings.png)

### What the desktop app adds

| Feature | Details |
|---|---|
| **Encrypt / Decrypt / Analyze** | drag-and-drop, batch queues, before/after preview |
| **Metrics dashboard** | entropy, H/V/D adjacent correlation, NPCR/UACI, 256-bin histograms |
| **Compute device picker** | Auto / GPU / CPU, CPU thread count, RAM budget — Auto runs a one-time per-machine calibration and picks the faster backend |
| **KDF cost slider** | PBKDF2 iterations (the format-legal cost knob; higher = slower brute-force, slower encrypt) |
| **Background jobs** | every job runs on a worker thread with progress + cancel; the UI never blocks |
| **Device info panel** | shows the exact GPU adapter and API in use (Metal / Vulkan / DX12) |

### Hardware acceleration, without breaking the format

`opticipher/accel/` adds compute backends under the unchanged public API:

- **CPU backend** — multi-core ChaCha20 (band-split with exact counter-seek so
  the keystream is *identical* to the single-context reference) and RAM-budget
  band sizing.
- **GPU backend** — WebGPU via `wgpu` (WGSL compute shaders): Metal on macOS
  (incl. Apple Silicon), Vulkan on Linux, DX12/Vulkan on Windows. ChaCha20
  full blocks on the GPU, tail via the reference cipher; histogram / NPCR /
  UACI kernels for the Analyze tab. No CUDA toolkit needed — `wgpu` ships its
  own native binaries in its wheels.
- **Automatic CPU fallback** — no GPU, no Vulkan, or a driver problem? Every
  job still runs, on the CPU backend, with the reason shown in the UI.

**The hard rule, enforced by tests:** every backend must produce
byte-identical output to the upstream reference implementation.
`tests/test_accel.py` + `tests/test_gpu_accel.py` pin the keystream against
OpenSSL golden vectors across block boundaries and sizes — any single-byte
drift fails CI before it can touch a user's file. Measured numbers and their
honest interpretation live in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

### Installation (desktop app)

**Option A — download a release build (no Python required).**

Grab the artifact for your OS from
[Releases](https://github.com/j1seki/OptiCipher-Desktop/releases):

| OS | Artifact | Notes |
|---|---|---|
| **Linux** | `OptiCipherDesktop-linux-x64.tar.gz` or `.AppImage` | tar.gz needs the distro's usual GL/glib runtime libraries (table below); the AppImage is self-contained (needs FUSE, or run `./…AppImage --appimage-extract`) |
| **macOS** (Apple Silicon) | `…-macos-arm64.dmg` | unsigned build — right-click the app → **Open** on first launch to bypass Gatekeeper |
| **Windows** | `…-windows-x64.zip` | unzip and run `OptiCipherDesktop.exe` |

Linux: builds are produced on **Ubuntu 22.04 (glibc 2.35)**, so they start on
every current distribution — Arch/CachyOS, Debian 12+, Ubuntu 22.04+, Fedora,
and derivatives. The GUI needs the standard desktop runtime libraries:

| Distro | Install command |
|---|---|
| Debian / Ubuntu / Linux Mint | `sudo apt install libegl1 libgl1 libglib2.0-0 libxkbcommon0 libdbus-1-3 libfontconfig1` |
| Arch / CachyOS / Manjaro | `sudo pacman -S mesa libglvnd glib2 libxkbcommon dbus fontconfig` |
| Fedora | `sudo dnf install mesa-libEGL mesa-libGL glib2 libxkbcommon dbus-libs fontconfig` |

```bash
tar -xzf OptiCipherDesktop-linux-x64.tar.gz
./OptiCipherDesktop/OptiCipherDesktop
```

This is tested, not assumed: every CI push runs the packaged binary
headlessly in **Ubuntu 22.04 & 24.04, Debian 12 & 13, Arch and Fedora**
containers before the artifact is uploaded.

**Where releases come from:** pushing a version tag (`git tag v1.0.0 && git
push origin v1.0.0`) runs the full build + distro-test matrix and then
publishes everything as a [GitHub Release](https://github.com/j1seki/OptiCipher-Desktop/releases)
automatically. (The per-run *Actions artifacts* expire after 90 days — always
download from the Releases page.)

**Option B — install from source (Python 3.9+).**

```bash
git clone https://github.com/j1seki/OptiCipher-Desktop.git
cd OptiCipher-Desktop
python -m venv .venv && source .venv/bin/activate
pip install -e ".[app]"      # library + PySide6 + wgpu
python -m app.main           # launch the desktop app
```

Extras: `.[dev]` (tests), `.[gpu]` (wgpu only, no GUI), `.[app]` (GUI + wgpu).

**Option C — library & CLI only.**

```bash
pip install -e .
```

**Build the package yourself.**

```bash
pip install pyinstaller
pyinstaller packaging/opticipher-desktop.spec --noconfirm
./dist/OptiCipherDesktop/OptiCipherDesktop --smoke   # headless check
```

### How to use the desktop app

**Encrypt**

1. Open the **Encrypt** tab and add files or whole folders (*Add files…* /
   *Add folder…*, or drag-and-drop into the list).
2. Type a passphrase and repeat it in the confirmation box.
3. Optionally adjust the **KDF cost** slider — higher costs more to encrypt
   and far more to attack; 200,000 iterations is the default.
4. Optionally pick an **Output** folder; empty means "next to the input",
   writing `<name>_encrypted.png`.
5. Press **Start**. The progress bar and the *before → after* preview update
   live; the status bar reports how many files succeeded.

**Decrypt**

1. Switch to **Decrypt** and add the encrypted PNGs.
2. Enter the passphrase (one box — decryption is verified, not guessed).
3. Press **Start** — the original is recovered next to the ciphertext as
   `<name>_decrypted.png`. A wrong passphrase or a tampered file is detected
   via HMAC and reported per file; you never get silent garbage.

**Analyze**

1. Go to the **Analyze** tab.
2. Add **one** image for entropy, adjacent-pixel correlation and the 256-bin
   histogram…
3. …or add an image **and its OptiCipher ciphertext** (the app aligns the
   reserved header strip automatically) to also get **NPCR** and **UACI**.
4. Press **Run analysis** — results render as metric bars, a correlation
   table and a selectable per-channel histogram; the status bar names the
   compute backend that ran it.

**Settings & the device bar**

- *Settings → Compute device*: **Auto** (a one-time per-machine calibration
  picks the faster of CPU/GPU), **GPU** (WebGPU — Metal on macOS, Vulkan on
  Linux, DX12/Vulkan on Windows) or **CPU**; plus CPU thread count, RAM
  budget and the default PBKDF2 cost.
- The bottom **device bar** always shows what actually ran: adapter, API,
  threads, RAM budget and the calibration result.

All jobs run on background worker threads — the UI never blocks, and Cancel
stops a batch at the next file boundary.

### Attribution & license

MIT, unchanged from upstream — © [bio-colab](https://github.com/bio-colab)
(see [LICENSE](LICENSE)). This fork adds the `app/`, `opticipher/accel/` and
`packaging/` trees and keeps every upstream file's behaviour intact; the
original algorithm, CLI and docs below are theirs.

---

## Table of contents

- [OptiCipher Desktop (this fork)](#opticipher-desktop-this-fork)
  - [Screenshots](#screenshots)
  - [Installation (desktop app)](#installation-desktop-app)
  - [How to use the desktop app](#how-to-use-the-desktop-app)
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
│   ├── cli.py               # command-line interface
│   └── accel/               # (fork) compute backends — bit-exact layers
│       ├── backend.py       # backend interface, settings, auto-calibration
│       ├── cpu.py           # threaded ChaCha20 + int32 permutation
│       └── gpu.py           # WebGPU/WGSL kernels + adapter discovery
├── app/                     # (fork) PySide6 desktop application
│   ├── main.py              # entry point (python -m app.main)
│   ├── window.py            # main window, settings dialog
│   ├── workers.py           # QThread job + analysis workers
│   ├── settings.py          # QSettings persistence → accel config
│   ├── device.py            # CPU/RAM/GPU introspection
│   └── charts.py            # histogram & metric bar widgets
├── packaging/               # (fork) PyInstaller spec, icons, entry
├── .github/workflows/       # (fork) 3-OS CI build + smoke tests
├── tests/                   # pytest suite (run with `pytest`)
│   ├── test_roundtrip.py
│   ├── test_components.py
│   ├── test_metrics_and_sample.py
│   ├── test_accel.py            # (fork) CPU-backend parity vs reference
│   ├── test_gpu_accel.py        # (fork) GPU golden-vector parity
│   └── test_gui_smoke.py        # (fork) headless GUI wiring tests
├── samples/                 # the bundled "CLAUDE CODE" sample + outputs
│   ├── sample_claude_code.png
│   ├── sample_encrypted.png
│   └── sample_decrypted.png
├── examples/                # runnable demos
│   ├── demo.py
│   ├── benchmark.py
│   └── benchmark_accel.py   # (fork) CPU-vs-GPU acceleration benchmark
├── docs/                    # extra documentation
│   ├── ALGORITHM.md
│   ├── METRICS.md
│   └── BENCHMARKS.md        # (fork) acceleration benchmark report
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
git clone <this-repository>
cd OptiCipher

# Option A: library + CLI only
pip install -e .

# Option B: desktop app (adds PySide6 + wgpu)
pip install -e ".[app]"

# Option C: just install the dependencies and run in place
pip install -r requirements.txt
```

Core dependencies are minimal and widely used: **NumPy**, **Pillow**,
**cryptography**. Optional extras (see `pyproject.toml`): `.[dev]` (pytest),
`.[gpu]` (WebGPU acceleration only), `.[app]` (GUI + WebGPU).

Launch the desktop app with `python -m app.main`, or use the CLI exactly as
upstream documents below — the two share the same library and the same
bit-exact v1 file format.

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
pip install -e ".[app,dev]"  # pytest + GUI/GPU test deps
pytest -v
```

The suite (100 tests in this fork) covers each component in isolation, full
encrypt→decrypt round trips across many image shapes (including RGBA and
degenerate 1×N images), Unicode passphrases, wrong-passphrase rejection, tamper
detection, and the statistical behaviour on the real sample image — plus the
fork's parity layers:

- `test_accel.py` — CPU backend byte-parity vs the reference (thread counts,
  band/counter-seek edge cases, permutation identity, selection/fallback).
- `test_gpu_accel.py` — GPU golden-vector keystream parity vs OpenSSL and exact
  metric equality (auto-skips when no WebGPU adapter is present, e.g. CI).
- `test_gui_smoke.py` — headless (offscreen) desktop-app wiring: window
  construction, per-tab file lists, settings, worker round-trip, analysis
  report shape, and original+ciphertext pair alignment for NPCR/UACI.

Every encrypted file in these tests is checked for bit-exact compatibility with
the upstream algorithm in both directions — the format promise is a test, not
a hope.

---

## Benchmarking

```bash
python examples/benchmark.py        # upstream throughput baseline
python examples/benchmark_accel.py  # fork: reference vs threaded CPU vs GPU
```

The upstream script prints encryption/decryption throughput across image
sizes, the isolated PBKDF2 cost, and the full statistical suite, writing
`examples/benchmark_results.json`.

The fork's acceleration benchmark compares the reference, threaded-CPU and
GPU backends on diffusion (4K/8K), metrics and end-to-end encrypt/decrypt,
asserts bit-exactness while it measures, and writes
[`docs/BENCHMARKS.md`](docs/BENCHMARKS.md) — including an honest section on
where the GPU wins (histograms, weak CPUs) and where transfer overhead makes
the CPU the better choice.

---

## Contributing

**OptiCipher is open source and community contributions are warmly invited.**
Whether you are a student, a security researcher, or just curious, there is room
to help. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details. Good first issues
include:

- Adding **Argon2id** as an optional KDF.
- Adding new **metrics** (e.g. χ² histogram uniformity test, local Shannon
  entropy, key-sensitivity analysis).
- A **GUI** or web front-end over the library. *(shipped in this fork: the
  PySide6 desktop app — new front-end ideas still welcome)*
- Performance work (vectorisation, optional native backend). *(WebGPU +
  threaded CPU shipped in this fork; more ideas welcome)*
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

Copyright © [bio-colab](https://github.com/bio-colab) and contributors
(upstream OptiCipher). This Desktop fork preserves the MIT license and the
upstream copyright notice; the added application, acceleration and packaging
code is likewise MIT-licensed.
