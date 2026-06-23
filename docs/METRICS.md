# OptiCipher Metrics Reference

The `opticipher.metrics` module implements the statistical measures commonly used
to evaluate image-encryption schemes in the research literature. This document
defines each metric, gives its formula, and explains how to interpret it. These
metrics are **diagnostics**, not a security proof — see the README's threat-model
section.

---

## 1. Shannon entropy

**Function:** `shannon_entropy(channel)` and `entropy_report(pixels)`

For an 8-bit channel, with `p_i` the empirical frequency of byte value `i`:

```
H = − Σ_{i=0}^{255} p_i · log2(p_i)     (bits per byte)
```

- **Range:** 0 (constant) to 8 (perfectly uniform).
- **Ideal ciphertext:** close to **8.0**. A value near 8 means every byte value
  is roughly equally likely, i.e. the histogram is flat and leaks little.
- **Interpretation:** natural images have low-to-moderate entropy because colours
  cluster; good encryption pushes entropy toward the 8.0 ceiling.

On the bundled sample, mean entropy rises from ≈ 2.47 (the low-entropy text
image) to ≈ 7.999 after encryption.

---

## 2. Adjacent-pixel correlation

**Function:** `adjacent_correlation(channel, sample_size, seed)`

For randomly sampled neighbouring pixel pairs `(x_k, y_k)` in a given direction
(horizontal, vertical, diagonal), the Pearson correlation coefficient is:

```
r = Σ (x_k − x̄)(y_k − ȳ) / sqrt( Σ (x_k − x̄)² · Σ (y_k − ȳ)² )
```

- **Range:** −1 to +1.
- **Natural images:** strongly positive (≈ +0.9) — neighbouring pixels look alike.
- **Ideal ciphertext:** ≈ **0** in all three directions — no exploitable local
  structure remains.

Sampling (default 4096 pairs) keeps the computation fast on large images while
giving a stable estimate; the `seed` argument makes it reproducible.

---

## 3. NPCR — Number of Pixels Change Rate

**Function:** `npcr(cipher_a, cipher_b)`

Given two ciphertexts whose plaintexts differ by a single pixel:

```
NPCR = (100 / T) · Σ  [cipher_a(k) ≠ cipher_b(k)]     (percent)
```

where `T` is the total number of bytes and `[·]` is 1 when the bytes differ.

- **Ideal for 8-bit data:** ≈ **99.609 %**.
- **Interpretation:** measures how completely a tiny plaintext change propagates.
  High NPCR indicates strong **plaintext sensitivity** (avalanche), which defeats
  differential cryptanalysis.

---

## 4. UACI — Unified Average Changing Intensity

**Function:** `uaci(cipher_a, cipher_b)`

```
UACI = (100 / (255 · T)) · Σ |cipher_a(k) − cipher_b(k)|     (percent)
```

- **Ideal for 8-bit data:** ≈ **33.464 %**.
- **Interpretation:** measures the *average magnitude* of change between the two
  ciphertexts, complementing NPCR's *count* of changes.

---

## 5. Histogram

**Function:** `histogram(channel)`

Returns the 256-bin count of byte values in a channel. Plotting it is the quickest
visual check: plaintext images show sharp peaks; well-encrypted images show a
near-flat distribution. (A formal χ² uniformity test is a natural future
addition — contributions welcome.)

---

## Reproducing the numbers

```bash
python examples/demo.py        # quick before/after table
python examples/benchmark.py   # full suite + JSON output
```

Both operate on `samples/sample_claude_code.png`. Representative results:

| Metric | Original | Encrypted | Ideal |
|--------|---------:|----------:|------:|
| Mean entropy (bits/byte) | 2.475 | 7.999 | 8.000 |
| Correlation H (ch0) | 0.941 | ≈ 0.00 | 0 |
| Correlation V (ch0) | 0.923 | ≈ 0.02 | 0 |
| Correlation D (ch0) | 0.870 | ≈ 0.01 | 0 |
| NPCR | — | ≈ 99.6 % | 99.61 % |
| UACI | — | ≈ 33.5 % | 33.46 % |

Small run-to-run variation in correlation/NPCR/UACI is expected because each
encryption draws a fresh random salt.

---

## A note on what these metrics do and don't prove

Strong entropy, near-zero correlation, and ideal NPCR/UACI are **necessary**
properties of a good cipher, but they are **not sufficient** to establish
security. They characterise statistical quality only. A scheme can score well on
all of them and still be broken by structural cryptanalysis. Treat these numbers
as evidence of good diffusion/confusion behaviour, and rely on the underlying
audited primitive (ChaCha20) plus the HMAC for the actual security argument.
