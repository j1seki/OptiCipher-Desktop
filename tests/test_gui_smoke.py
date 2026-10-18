"""
test_gui_smoke.py
=================

Headless smoke tests for the desktop app wiring.

Runs Qt with the offscreen platform so it works on CI and servers with no
display. Jobs are executed synchronously (calling the worker's `run()`
directly) to keep the tests deterministic — the QThread plumbing itself is
exercised by launching the app manually.

What this guards:
  * the window constructs and the settings dialog populates device rows,
  * encrypt → decrypt through the GUI's JobWorker reproduces the original
    image bit-for-bit,
  * the analyze worker returns the expected report structure.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from opticipher import load_image, save_image

from app.window import MainWindow, SettingsDialog
from app.workers import AnalyzeWorker, JobWorker


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture()
def sample_image(tmp_path):
    rng = np.random.default_rng(211)
    img = rng.integers(0, 256, (64, 96, 3), dtype=np.uint8)
    path = tmp_path / "sample.png"
    save_image(img, str(path))
    return str(path), img


def test_main_window_constructs(qapp):
    window = MainWindow()
    assert window.tabs.count() == 3
    assert [window.tabs.tabText(i) for i in range(3)] == [
        "Encrypt",
        "Decrypt",
        "Analyze",
    ]
    # Device bar shows something for this machine.
    assert "Device:" in window.device_label.text()
    window.close()


def test_file_lists_cover_encrypt_and_decrypt(qapp):
    """
    Regression: _build_crypt_tab used to read a stale `_file_lists` name, so
    constructing the Decrypt tab silently discarded the Encrypt tab's list —
    encryption then hit KeyError and drag-and-drop landed in the analyze list.
    Both keys must exist, and each FileList must be the widget actually
    embedded in its tab (parented), not a detached instance.
    """
    window = MainWindow()
    assert set(window.file_lists) == {"encrypt", "decrypt"}
    for mode in ("encrypt", "decrypt"):
        assert window.file_lists[mode].parent() is not None
    window.close()


def test_settings_dialog_lists_devices(qapp):
    dialog = SettingsDialog()
    values = [dialog.device_combo.itemData(i) for i in range(dialog.device_combo.count())]
    assert "auto" in values
    assert "cpu" in values
    assert dialog.iter_spin.value() >= 10_000
    dialog.close()


def test_job_worker_roundtrip(qapp, sample_image, tmp_path):
    """The GUI's own worker path must produce a decryptable file."""
    src, original = sample_image
    out_dir = str(tmp_path / "out")
    os.makedirs(out_dir)

    enc = JobWorker("encrypt", [src], "gui passphrase", 10_000, out_dir)
    done = []
    enc.all_done.connect(lambda ok, bad: done.append((ok, bad)))
    enc.run()  # synchronous for determinism
    assert done == [(1, 0)]

    enc_path = os.path.join(out_dir, "sample_encrypted.png")
    assert os.path.isfile(enc_path)

    dec = JobWorker("decrypt", [enc_path], "gui passphrase", 0, out_dir)
    done.clear()
    dec.all_done.connect(lambda ok, bad: done.append((ok, bad)))
    dec.run()
    assert done == [(1, 0)]

    recovered = load_image(os.path.join(out_dir, "sample_decrypted.png"))
    assert np.array_equal(recovered, original)


def test_job_worker_wrong_passphrase_reports_error(qapp, sample_image, tmp_path):
    src, _ = sample_image
    out_dir = str(tmp_path / "out2")
    os.makedirs(out_dir)
    enc = JobWorker("encrypt", [src], "right", 10_000, out_dir)
    enc.run()
    enc_path = os.path.join(out_dir, "sample_encrypted.png")

    dec = JobWorker("decrypt", [enc_path], "wrong", 0, out_dir)
    statuses = []
    dec.file_done.connect(lambda path, status: statuses.append(status))
    dec.run()
    assert statuses and statuses[0].startswith("error:")


def test_analyze_worker_report(qapp, sample_image):
    src, _ = sample_image
    worker = AnalyzeWorker([src])
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results, "analysis produced no result"
    data = results[0]
    assert data["header"] is None  # plain image, not ciphertext
    assert "mean" in data["entropy"]
    assert 0.0 <= data["entropy"]["mean"] <= 8.0
    assert "channel_0" in data["correlation"]
    assert "horizontal" in data["correlation"]["channel_0"]
    assert len(data["histograms"]["channel_0"]) == 256
    assert data["npcr"] is None
