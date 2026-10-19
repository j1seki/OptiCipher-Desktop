"""
app.workers
===========

QThread workers that run the heavy library calls off the UI thread.

Two worker kinds:

  * JobWorker    — encrypt or decrypt a batch of files, one after another,
                   reporting per-file status and honouring a cancel flag
                   between files (PBKDF2 itself is uninterruptible, so a
                   cancel takes effect at the next file boundary).
  * AnalyzeWorker— compute the research metrics for the selected file(s):
                   OptiCipher-header detection, per-channel entropy, adjacent
                   correlation (reference sampling), histograms (GPU-accel
                   when the GPU backend is active), and NPCR/UACI when two
                   images are selected.

Both expose plain-data results through Qt signals so the window stays a dumb
renderer. Every computation runs against whatever backend `get_backend()`
resolves at call time — the settings dialog can switch CPU/GPU between jobs
without restarting anything.
"""

from __future__ import annotations

import os
import traceback
from typing import Dict, List, Optional, Tuple

import numpy as np
from PySide6.QtCore import QThread, Signal

from opticipher import DecryptionError, decrypt_image, encrypt_image, load_image, save_image
from opticipher import accel
from opticipher import header as _header
from opticipher import metrics as ref_metrics
from opticipher import stego as _stego


def detect_opticipher_header(pixels: np.ndarray) -> Optional[Dict[str, object]]:
    """
    Best-effort read of the embedded v1 header. Returns None when the image
    is not an OptiCipher ciphertext (bad magic / too small / corrupt).
    """
    try:
        candidate = _stego.peek_header_bytes(pixels, _header.HEADER_SIZE)
        hdr = _header.parse(candidate)
    except Exception:
        return None
    return {
        "version": hdr.version,
        "height": hdr.height,
        "width": hdr.width,
        "channels": hdr.channels,
        "iterations": hdr.iterations,
        "strip_rows": hdr.strip_rows,
    }


def match_ciphertext_pair(
    a: np.ndarray, b: np.ndarray
) -> Optional[Tuple[np.ndarray, np.ndarray]]:
    """
    Align an (original, ciphertext) pair onto the common plaintext region.

    An OptiCipher ciphertext is the original pixels plus the reserved header
    strip appended at the bottom, so the natural pair a user selects in the
    Analyze tab (a plain image and its encrypted file) never has identical
    dimensions. When one image's header records the other image's exact size,
    crop the strip rows off the ciphertext and return the aligned pair;
    otherwise None (the caller keeps its strict same-shape rule).
    """
    for plain, cipher in ((a, b), (b, a)):
        if cipher.ndim != plain.ndim or cipher.shape[1:] != plain.shape[1:]:
            continue
        if cipher.shape[0] <= plain.shape[0]:
            continue
        info = detect_opticipher_header(cipher)
        if (
            info
            and int(info["height"]) == plain.shape[0]
            and int(info["width"]) == plain.shape[1]
        ):
            return plain, cipher[: plain.shape[0]]
    return None


class JobWorker(QThread):
    """
    Sequential batch encrypt/decrypt worker.

    Signals
    -------
    progress(int, str)   overall percent, human message
    file_done(str, str)  input path, "ok: <output>" or "error: <reason>"
    all_done(int, int)   succeeded count, failed count
    """

    progress = Signal(int, str)
    file_done = Signal(str, str)
    all_done = Signal(int, int)

    def __init__(
        self,
        mode: str,  # "encrypt" | "decrypt"
        files: List[str],
        passphrase: str,
        iterations: int,
        output_dir: str,
        parent=None,
        *,
        sftp: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.mode = mode
        self.files = list(files)
        self.passphrase = passphrase
        self.iterations = iterations
        self.output_dir = output_dir
        # Optional SFTP destination for output_dir ("sftp://…"): carries the
        # session credentials {user, password, key_file} (+ client_factory for
        # tests). The local file is ALWAYS written first and never deleted —
        # upload is a verified mirror copy (see app/sftp.py).
        self.sftp = sftp or None
        self._cancel = False

    def cancel(self) -> None:
        """Request cancellation; takes effect before the next file starts."""
        self._cancel = True

    @staticmethod
    def _default_output(input_path: str, mode: str, out_dir: str) -> str:
        stem = os.path.splitext(os.path.basename(input_path))[0]
        if mode == "decrypt" and stem.endswith("_encrypted"):
            stem = stem[: -len("_encrypted")]
        suffix = "_encrypted" if mode == "encrypt" else "_decrypted"
        # An sftp:// output is a REMOTE location — it is never a local
        # directory to join paths against. The local mirror copy therefore
        # lands next to the input (the "empty output" rule), and the upload
        # sends it to the remote location afterwards.
        from .sftp import is_sftp_output

        if out_dir and not is_sftp_output(out_dir):
            directory = out_dir
        else:
            directory = os.path.dirname(input_path)
        return os.path.join(directory, f"{stem}{suffix}.png")

    def _upload_to_sftp(self, local_path: str) -> str:
        """Mirror `local_path` to the sftp:// output location.

        Returns a display URL ("sftp://user@host/path/file") for status text.
        The dialog-provided username overrides an empty URL user; otherwise an
        explicit user in the URL wins. Raises app.sftp.SftpError (or a lower
        level error) with a credential-free message.
        """
        from .sftp import SftpTarget, SftpUploader, parse_sftp_url

        target = parse_sftp_url(self.output_dir)
        user = (self.sftp or {}).get("user") or target.user
        if user != target.user:
            target = SftpTarget(
                host=target.host, port=target.port, user=user, path=target.path
            )
        uploader = SftpUploader(
            target,
            password=(self.sftp or {}).get("password"),
            key_file=(self.sftp or {}).get("key_file"),
            client_factory=(self.sftp or {}).get("client_factory"),
        )
        remote = uploader.upload(local_path)
        user_part = f"{target.user}@" if target.user else ""
        port_part = f":{target.port}" if target.port != 22 else ""
        return f"sftp://{user_part}{target.host}{port_part}{remote}"

    def run(self) -> None:  # executes in the worker thread
        ok = 0
        failed = 0
        total = max(1, len(self.files))
        for index, path in enumerate(self.files):
            if self._cancel:
                self.file_done.emit(path, "error: cancelled")
                failed += 1
                continue
            try:
                self.progress.emit(int(index / total * 100), os.path.basename(path))
                pixels = load_image(path)
                if self.mode == "encrypt":
                    out_pixels = encrypt_image(pixels, self.passphrase, self.iterations)
                else:
                    out_pixels = decrypt_image(pixels, self.passphrase)
                out_path = self._default_output(path, self.mode, self.output_dir)
                # save_image picks a non-clobbering name atomically and returns
                # the path it really wrote — report that one, never a guess.
                written = save_image(out_pixels, out_path)
                if self.sftp:
                    # Mirror-upload after the local write succeeded. Failure is
                    # an error status (the file itself is safe locally) — we
                    # never claim a finished upload that did not verify.
                    try:
                        remote = self._upload_to_sftp(written)
                    except Exception as exc:  # noqa: BLE001
                        failed += 1
                        traceback.print_exc()
                        self.file_done.emit(
                            path,
                            f"error: saved locally to {written}, but SFTP "
                            f"upload failed: {exc}",
                        )
                        continue
                    ok += 1
                    self.file_done.emit(
                        path, f"ok: {written} \u2192 uploaded {remote}"
                    )
                else:
                    ok += 1
                    self.file_done.emit(path, f"ok: {written}")
            except DecryptionError as exc:
                failed += 1
                self.file_done.emit(path, f"error: {exc}")
            except Exception as exc:  # noqa: BLE001 - report anything to the UI
                failed += 1
                self.file_done.emit(path, f"error: {exc}")
                traceback.print_exc()
        self.progress.emit(100, "done")
        self.all_done.emit(ok, failed)


class AnalyzeWorker(QThread):
    """
    Metrics worker for the Analyze tab.

    result carries a plain dict:
        {
          "files": [str, ...],
          "header": dict | None,          # of the first file
          "entropy": {channel_x: float, mean: float},
          "correlation": {channel_x: {horizontal, vertical, diagonal}},
          "histograms": {channel_x: [256 ints]},
          "npcr": float | None,           # only when two files given
          "uaci": float | None,
          "backend": str,                 # which accel backend ran it
        }
    """

    result = Signal(dict)
    failed = Signal(str)

    def __init__(self, files: List[str], parent=None) -> None:
        super().__init__(parent)
        self.files = list(files)

    def run(self) -> None:
        try:
            backend = accel.get_backend()
            first = load_image(self.files[0])

            header_info = detect_opticipher_header(first)

            # Entropy: per-channel + mean (reference formula on exact counts;
            # GPU backend contributes its accelerated histogram when active).
            if hasattr(backend, "histograms"):
                counts = backend.histograms(first)  # (C, 256) uint64
                entropy: Dict[str, float] = {}
                for c in range(counts.shape[0]):
                    entropy[f"channel_{c}"] = _entropy_from_counts(counts[c])
                entropy["mean"] = float(
                    np.mean([v for k, v in entropy.items() if k != "mean"])
                )
                histograms = {
                    f"channel_{c}": counts[c].tolist() for c in range(counts.shape[0])
                }
            else:
                entropy = ref_metrics.entropy_report(first)
                histograms = {
                    f"channel_{c}": ref_metrics.histogram(first[:, :, c]).tolist()
                    for c in range(first.shape[2])
                }

            # Adjacent correlation: reference sampling path (bounded cost by
            # design — see opticipher/accel/gpu.py for the rationale).
            correlation: Dict[str, Dict[str, float]] = {}
            for c in range(first.shape[2]):
                correlation[f"channel_{c}"] = ref_metrics.adjacent_correlation(
                    first[:, :, c]
                )

            npcr_val: Optional[float] = None
            uaci_val: Optional[float] = None
            if len(self.files) >= 2:
                second = load_image(self.files[1])
                first_cmp = first
                if second.shape != first.shape:
                    # Ciphertexts carry the reserved strip (taller than the
                    # plaintext) — align the natural original+encrypted pair
                    # before comparing.
                    pair = match_ciphertext_pair(first, second)
                    if pair is None:
                        raise ValueError(
                            "the two images must have identical dimensions "
                            "(or be an original and its OptiCipher ciphertext)"
                        )
                    first_cmp, second = pair
                if hasattr(backend, "npcr"):
                    npcr_val = backend.npcr(first_cmp, second)
                    uaci_val = backend.uaci(first_cmp, second)
                else:
                    npcr_val = ref_metrics.npcr(first_cmp, second)
                    uaci_val = ref_metrics.uaci(first_cmp, second)

            self.result.emit(
                {
                    "files": self.files,
                    "header": header_info,
                    "entropy": entropy,
                    "correlation": correlation,
                    "histograms": histograms,
                    "npcr": npcr_val,
                    "uaci": uaci_val,
                    "backend": backend.name,
                }
            )
        except Exception as exc:  # noqa: BLE001 - surface to the UI
            traceback.print_exc()
            self.failed.emit(str(exc))


def _entropy_from_counts(counts: np.ndarray) -> float:
    """Shannon entropy from exact histogram counts (same math as reference)."""
    total = float(counts.sum())
    if total == 0:
        return 0.0
    probs = counts.astype(np.float64) / total
    nz = probs[probs > 0]
    return float(-np.sum(nz * np.log2(nz)))
