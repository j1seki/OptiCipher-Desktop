"""
Capture README screenshots of the running desktop app.

Drives the real widgets on a real display (not offscreen): loads the bundled
sample, performs a real encryption, decryption and analysis so every panel
shows genuine data, then grabs the window with QWidget.grab().

    python packaging/screenshots.py

Writes docs/screenshots/{overview,encrypt,decrypt,verify,analyze,settings}.png
"""

import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.window import MainWindow  # noqa: E402
from app.workers import AnalyzeWorker, JobWorker  # noqa: E402

OUT = os.path.join(_ROOT, "docs", "screenshots")
SAMPLE = os.path.join(_ROOT, "samples", "sample_claude_code.png")
PASSPHRASE = "correct-horse-battery-staple"


def settle(app, ms=500):
    app.processEvents()
    time.sleep(ms / 1000.0)
    app.processEvents()


def grab(widget, name):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name)
    widget.grab().save(path)
    print("wrote", path)


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(1360, 860)
    win.show()
    win.theme_manager.set_theme("dark")
    settle(app, 700)

    tmp = tempfile.mkdtemp(prefix="opticipher_shots_")

    # --- Encrypt: sample loaded, a real encryption done, previews shown ---
    win.navigate("encrypt")
    win.file_lists["encrypt"].add_paths([SAMPLE])
    win._encrypt_pass.setText(PASSPHRASE)
    win._encrypt_confirm.setText(PASSPHRASE)
    win.iter_slider.setValue(4)  # 200,000 iterations label
    enc_out = JobWorker._default_output(SAMPLE, "encrypt", tmp)

    worker = JobWorker("encrypt", [SAMPLE], PASSPHRASE, 200_000, tmp)
    worker.progress.connect(
        lambda pct, msg: win._on_progress("encrypt", pct, msg)
    )
    worker.file_done.connect(win._on_file_done)
    worker.all_done.connect(lambda ok, bad: win._on_all_done("encrypt", ok, bad))
    worker.run()
    assert os.path.isfile(enc_out), f"encryption output missing: {enc_out}"
    win._set_preview("before", SAMPLE)
    settle(app, 700)
    grab(win, "encrypt.png")

    # --- Decrypt: a real decryption, with the step-by-step outcome ---------
    win.navigate("decrypt")
    win.file_lists["decrypt"].add_paths([enc_out])
    win._decrypt_pass.setText(PASSPHRASE)
    win.decrypt_page.out_edit.setText(tmp)
    dec_worker = JobWorker("decrypt", [enc_out], PASSPHRASE, 0, tmp)
    dec_worker.progress.connect(
        lambda pct, msg: win._on_progress("decrypt", pct, msg)
    )
    dec_worker.file_done.connect(win._on_file_done)
    dec_worker.all_done.connect(lambda ok, bad: win._on_all_done("decrypt", ok, bad))
    dec_worker.run()
    settle(app, 700)
    grab(win, "decrypt.png")

    # --- Verify: a real integrity check on the same ciphertext -------------
    win.navigate("verify")
    win.verify_files.add_paths([enc_out])
    win.verify_page.pass_field.setText(PASSPHRASE)
    from app.workers import VerifyWorker

    verify = VerifyWorker(enc_out, PASSPHRASE)
    results = []
    verify.result.connect(results.append)
    verify.run()
    assert results, "verification produced no result"
    win._on_verify_result(results[0])
    settle(app, 700)
    grab(win, "verify.png")

    # --- Analyze: original vs its ciphertext -> full metrics incl NPCR/UACI -
    win.navigate("analyze")
    win.analyze_files.add_paths([SAMPLE, enc_out])
    analysis = AnalyzeWorker([SAMPLE, enc_out])
    analysis_results, failures = [], []
    analysis.result.connect(analysis_results.append)
    analysis.failed.connect(failures.append)
    analysis.run()
    assert analysis_results, f"analysis failed: {failures}"
    win._on_analyze_result(analysis_results[0])
    settle(app, 700)
    grab(win, "analyze.png")

    # --- Overview ----------------------------------------------------------
    win.navigate("overview")
    settle(app, 500)
    grab(win, "overview.png")

    # --- Settings ----------------------------------------------------------
    win.navigate("settings")
    settle(app, 500)
    grab(win, "settings.png")

    win.close()
    print("done")


if __name__ == "__main__":
    main()
