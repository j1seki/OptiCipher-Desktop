"""
Capture README screenshots of the running desktop app.

Drives the real widgets on a real display (not offscreen): loads the bundled
sample, performs a real encryption and a real analysis so every panel shows
genuine data, then grabs each widget with QWidget.grab().

    python packaging/screenshots.py

Writes docs/screenshots/{main-window,analyze,settings}.png
"""

import os
import sys
import tempfile
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.window import MainWindow, SettingsDialog  # noqa: E402
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
    win.resize(1320, 820)
    win.show()
    settle(app, 700)

    tmp = tempfile.mkdtemp(prefix="opticipher_shots_")

    # --- Encrypt tab: sample loaded, real encryption done, previews shown ---
    win.tabs.setCurrentIndex(0)
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
    grab(win, "main-window.png")

    # --- Analyze tab: original vs its ciphertext -> full metrics incl NPCR/UACI ---
    win.tabs.setCurrentIndex(2)
    win.analyze_files.add_paths([SAMPLE, enc_out])
    analysis = AnalyzeWorker([SAMPLE, enc_out])
    results, failures = [], []
    analysis.result.connect(results.append)
    analysis.failed.connect(failures.append)
    analysis.run()
    assert results, f"analysis failed: {failures}"
    win._on_analyze_result(results[0])
    settle(app, 700)
    grab(win, "analyze.png")

    # --- Settings dialog ---
    dialog = SettingsDialog(win)
    dialog.show()
    settle(app, 500)
    grab(dialog, "settings.png")
    dialog.close()
    win.close()
    print("done")


if __name__ == "__main__":
    main()
