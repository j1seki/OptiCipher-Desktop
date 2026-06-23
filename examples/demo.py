"""
demo.py
=======

A self-contained walk-through of OptiCipher on the bundled sample image.

Run it from the project root with:

    python examples/demo.py

It will:
  1. Load samples/sample_claude_code.png
  2. Encrypt it -> examples/out_encrypted.png
  3. Decrypt it -> examples/out_decrypted.png
  4. Confirm the round trip is bit-exact
  5. Print before/after research metrics (entropy + correlation)
  6. Print NPCR/UACI for a one-pixel plaintext change

This is the quickest way to see what the tool does and to eyeball the numbers a
researcher cares about.
"""

from pathlib import Path

import numpy as np

from opticipher import decrypt_image, encrypt_image, load_image, save_image
from opticipher import metrics

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "samples" / "sample_claude_code.png"
ENC_OUT = ROOT / "examples" / "out_encrypted.png"
DEC_OUT = ROOT / "examples" / "out_decrypted.png"

PASSPHRASE = "OptiCipher-Demo-2025"


def banner(title: str) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


def main() -> None:
    banner("1) Load")
    original = load_image(SAMPLE)
    print(f"loaded {SAMPLE.name}  shape={original.shape}  dtype={original.dtype}")

    banner("2) Encrypt")
    encrypted = encrypt_image(original.copy(), PASSPHRASE)
    save_image(encrypted, ENC_OUT)
    print(f"wrote {ENC_OUT.name}  shape={encrypted.shape}")

    banner("3) Decrypt")
    decrypted = decrypt_image(encrypted, PASSPHRASE)
    save_image(decrypted, DEC_OUT)
    print(f"wrote {DEC_OUT.name}  shape={decrypted.shape}")

    banner("4) Verify lossless round trip")
    exact = np.array_equal(original, decrypted)
    print(f"decrypted == original : {exact}")
    if not exact:
        raise SystemExit("ROUND TRIP FAILED")

    # Compare metrics on the main (non-strip) region for a fair comparison.
    enc_main = encrypted[: original.shape[0]]

    banner("5) Statistical metrics (original vs encrypted)")
    eo = metrics.entropy_report(original)
    ee = metrics.entropy_report(enc_main)
    print("Shannon entropy (bits/byte, ideal 8.0):")
    print(f"  original  mean = {eo['mean']:.4f}")
    print(f"  encrypted mean = {ee['mean']:.4f}")

    co = metrics.adjacent_correlation(original[:, :, 0])
    ce = metrics.adjacent_correlation(enc_main[:, :, 0])
    print("\nAdjacent-pixel correlation, channel 0 (ideal ~0):")
    print(f"  original  H/V/D = {co['horizontal']:.4f} / "
          f"{co['vertical']:.4f} / {co['diagonal']:.4f}")
    print(f"  encrypted H/V/D = {ce['horizontal']:.4f} / "
          f"{ce['vertical']:.4f} / {ce['diagonal']:.4f}")

    banner("6) Differential metrics (one-pixel plaintext change)")
    twin = original.copy()
    twin[0, 0, 0] ^= 1
    e1 = encrypt_image(original.copy(), "k")[: original.shape[0]]
    e2 = encrypt_image(twin, "k")[: original.shape[0]]
    print(f"NPCR = {metrics.npcr(e1, e2):.4f} %   (ideal ~99.6)")
    print(f"UACI = {metrics.uaci(e1, e2):.4f} %   (ideal ~33.4)")

    print("\nDone. Open the PNGs in examples/ to see the visual result.")


if __name__ == "__main__":
    main()
