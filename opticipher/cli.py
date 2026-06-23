"""
cli.py
======

Command-line interface for OptiCipher.

Usage examples
--------------
    # Encrypt
    python -m opticipher encrypt input.png output.png --passphrase "my secret"

    # Decrypt
    python -m opticipher decrypt output.png recovered.png --passphrase "my secret"

    # Print research metrics for an image
    python -m opticipher metrics some_image.png

If --passphrase is omitted for encrypt/decrypt, the CLI prompts for it securely
(without echoing) using getpass, which is safer than passing secrets on the
command line where they can leak into shell history and process listings.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import __version__, metrics
from .core import DecryptionError, decrypt_image, encrypt_image
from .io_image import load_image, save_image
from .keys import DEFAULT_ITERATIONS


def _get_passphrase(arg_value: str | None, confirm: bool) -> str:
    """
    Obtain the passphrase from --passphrase or an interactive secure prompt.

    Parameters
    ----------
    arg_value:
        Value passed via --passphrase, or None.
    confirm:
        If True (encryption), ask twice and require a match to catch typos.
    """
    if arg_value is not None:
        return arg_value
    first = getpass.getpass("Passphrase: ")
    if confirm:
        second = getpass.getpass("Confirm passphrase: ")
        if first != second:
            print("error: passphrases do not match", file=sys.stderr)
            sys.exit(2)
    return first


def _cmd_encrypt(args: argparse.Namespace) -> int:
    """Handle the `encrypt` subcommand."""
    passphrase = _get_passphrase(args.passphrase, confirm=True)
    pixels = load_image(args.input)
    encrypted = encrypt_image(pixels, passphrase, iterations=args.iterations)
    save_image(encrypted, args.output)
    print(f"encrypted -> {args.output}  (shape {encrypted.shape})")
    return 0


def _cmd_decrypt(args: argparse.Namespace) -> int:
    """Handle the `decrypt` subcommand."""
    passphrase = _get_passphrase(args.passphrase, confirm=False)
    pixels = load_image(args.input)
    try:
        restored = decrypt_image(pixels, passphrase)
    except DecryptionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    save_image(restored, args.output)
    print(f"decrypted -> {args.output}  (shape {restored.shape})")
    return 0


def _cmd_metrics(args: argparse.Namespace) -> int:
    """Handle the `metrics` subcommand: print entropy + correlation as JSON."""
    pixels = load_image(args.input)
    report = metrics.full_report(pixels)
    print(json.dumps(report, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """
    Construct the argument parser.

    Kept as a separate function so tests can import and exercise it directly.
    """
    parser = argparse.ArgumentParser(
        prog="opticipher",
        description="OptiCipher: open-source optical (perceptual) image encryption.",
    )
    parser.add_argument(
        "--version", action="version", version=f"OptiCipher {__version__}"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_enc = sub.add_parser("encrypt", help="encrypt an image")
    p_enc.add_argument("input", help="path to the plaintext image")
    p_enc.add_argument("output", help="path for the encrypted PNG")
    p_enc.add_argument(
        "--passphrase", help="passphrase (omit to be prompted securely)"
    )
    p_enc.add_argument(
        "--iterations",
        type=int,
        default=DEFAULT_ITERATIONS,
        help=f"PBKDF2 iterations (default {DEFAULT_ITERATIONS})",
    )
    p_enc.set_defaults(func=_cmd_encrypt)

    p_dec = sub.add_parser("decrypt", help="decrypt an image")
    p_dec.add_argument("input", help="path to the encrypted image")
    p_dec.add_argument("output", help="path for the recovered PNG")
    p_dec.add_argument(
        "--passphrase", help="passphrase (omit to be prompted securely)"
    )
    p_dec.set_defaults(func=_cmd_decrypt)

    p_met = sub.add_parser("metrics", help="print research metrics for an image")
    p_met.add_argument("input", help="path to the image to analyse")
    p_met.set_defaults(func=_cmd_metrics)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns a process exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
