"""
benchmark.py
============

Performance and statistical benchmark for OptiCipher, aimed at researchers who
want reproducible numbers for a report or paper.

It measures, across a range of image sizes:
  * encryption throughput   (megapixels / second and MB / second)
  * decryption throughput
  * key-derivation cost      (isolated, since PBKDF2 dominates small images)

and, on the bundled sample, the full statistical suite (entropy, correlation,
NPCR, UACI). Results print as a table and are also written to
examples/benchmark_results.json for further analysis.

Run from the project root:

    python examples/benchmark.py
"""

import json
import time
from pathlib import Path

import numpy as np

from opticipher import decrypt_image, encrypt_image, load_image
from opticipher import keys, metrics

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_claude_code.png"
OUT_JSON = ROOT / "examples" / "benchmark_results.json"

# Sizes (height, width) to benchmark. Kept modest so the script finishes quickly;
# scale these up for heavier measurements.
SIZES = [(128, 128), (256, 256), (512, 512), (1024, 1024)]

# Use a low iteration count for throughput tests so PBKDF2 does not dominate and
# obscure the per-pixel transform cost. The statistical tests use the default.
FAST_ITERS = 1_000


def time_call(fn, *args, repeats: int = 3):
    """Return the best (minimum) wall-clock time over `repeats` runs."""
    best = float("inf")
    result = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        result = fn(*args)
        dt = time.perf_counter() - t0
        best = min(best, dt)
    return best, result


def throughput_table() -> list[dict]:
    rows = []
    rng = np.random.default_rng(0)
    for h, w in SIZES:
        img = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
        megapixels = (h * w) / 1e6
        megabytes = img.nbytes / 1e6

        enc_t, enc = time_call(encrypt_image, img.copy(), "pw", FAST_ITERS)
        dec_t, _ = time_call(decrypt_image, enc, "pw")

        rows.append(
            {
                "size": f"{w}x{h}",
                "megapixels": round(megapixels, 3),
                "encrypt_s": round(enc_t, 4),
                "decrypt_s": round(dec_t, 4),
                "encrypt_MPx_per_s": round(megapixels / enc_t, 2),
                "decrypt_MPx_per_s": round(megapixels / dec_t, 2),
                "encrypt_MB_per_s": round(megabytes / enc_t, 2),
            }
        )
    return rows


def kdf_cost() -> dict:
    """Isolate the PBKDF2 cost at the default iteration count."""
    salt = keys.generate_salt()
    t, _ = time_call(
        keys.derive_keys, "benchmark-pass", salt, keys.DEFAULT_ITERATIONS,
        repeats=5,
    )
    return {
        "iterations": keys.DEFAULT_ITERATIONS,
        "seconds_per_derivation": round(t, 5),
    }


def statistical_suite() -> dict:
    if not SAMPLE.exists():
        return {"note": "sample image missing; skipped statistical suite"}

    original = load_image(SAMPLE)
    enc_main = encrypt_image(original.copy(), "stats")[: original.shape[0]]

    twin = original.copy()
    twin[0, 0, 0] ^= 1
    e1 = encrypt_image(original.copy(), "k")[: original.shape[0]]
    e2 = encrypt_image(twin, "k")[: original.shape[0]]

    return {
        "image": SAMPLE.name,
        "shape": list(original.shape),
        "entropy_original": metrics.entropy_report(original),
        "entropy_encrypted": metrics.entropy_report(enc_main),
        "correlation_original_ch0": metrics.adjacent_correlation(
            original[:, :, 0]
        ),
        "correlation_encrypted_ch0": metrics.adjacent_correlation(
            enc_main[:, :, 0]
        ),
        "npcr_percent": round(metrics.npcr(e1, e2), 4),
        "uaci_percent": round(metrics.uaci(e1, e2), 4),
    }


def main() -> None:
    print("Running OptiCipher benchmark...\n")

    print("== Throughput ==")
    rows = throughput_table()
    header = f"{'size':>10} {'MPx':>7} {'enc s':>8} {'dec s':>8} {'enc MPx/s':>11} {'dec MPx/s':>11}"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['size']:>10} {r['megapixels']:>7} {r['encrypt_s']:>8} "
            f"{r['decrypt_s']:>8} {r['encrypt_MPx_per_s']:>11} "
            f"{r['decrypt_MPx_per_s']:>11}"
        )

    print("\n== Key derivation cost (default iterations) ==")
    kdf = kdf_cost()
    print(f"{kdf['iterations']} iterations -> "
          f"{kdf['seconds_per_derivation']} s per derivation")

    print("\n== Statistical suite (sample image) ==")
    stats = statistical_suite()
    if "npcr_percent" in stats:
        print(f"entropy original  mean : "
              f"{stats['entropy_original']['mean']:.4f}")
        print(f"entropy encrypted mean : "
              f"{stats['entropy_encrypted']['mean']:.4f}")
        print(f"NPCR : {stats['npcr_percent']} %")
        print(f"UACI : {stats['uaci_percent']} %")

    results = {
        "throughput": rows,
        "kdf_cost": kdf,
        "statistics": stats,
    }
    OUT_JSON.write_text(json.dumps(results, indent=2))
    print(f"\nFull results written to {OUT_JSON}")


if __name__ == "__main__":
    main()
