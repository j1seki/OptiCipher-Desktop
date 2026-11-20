"""Parity coverage for the desktop folder watch."""

from dataclasses import replace
from datetime import datetime

import numpy as np

from app.watch import ScanWorker, WatchConfig, _files
from opticipher import load_image, save_image


def test_weekly_schedule_uses_the_next_local_occurrence():
    monday = datetime(2026, 11, 16, 10, 0)
    schedule = WatchConfig(interval=0, weekday=0, clock="10:00")
    assert schedule.next_at(monday) == datetime(2026, 11, 23, 10, 0)
    assert replace(schedule, weekday=6).next_at(monday) == datetime(2026, 11, 22, 10, 0)


def test_watches_roundtrip_and_continue_after_an_unreadable_input(tmp_path):
    inbox = tmp_path / "in"
    ciphertext = tmp_path / "cipher"
    restored = tmp_path / "restored"
    for folder in (inbox, ciphertext, restored):
        folder.mkdir()
    pixels = np.arange(48, dtype=np.uint8).reshape(4, 4, 3)
    (inbox / "a-bad.png").write_bytes(b"not a png")
    save_image(pixels, inbox / "b-photo.png")

    encrypt = ScanWorker("encrypt", WatchConfig(str(inbox), str(ciphertext)), "watch", {})
    reports = []
    encrypt.report.connect(lambda *args: reports.append(args))
    encrypt.run()
    assert [report[1] for report in reports] == ["error", "ok"]
    np.testing.assert_array_equal(load_image(inbox / "b-photo.png"), pixels)

    decrypt = ScanWorker("decrypt", WatchConfig(str(ciphertext), str(restored)), "watch", {})
    decrypt.run()
    np.testing.assert_array_equal(load_image(restored / "b-photo.png"), pixels)


def test_watch_skips_preexisting_files_and_existing_output(tmp_path):
    inbox = tmp_path / "in"
    output = tmp_path / "out"
    inbox.mkdir()
    output.mkdir()
    pixels = np.zeros((4, 4, 3), dtype=np.uint8)
    save_image(pixels, inbox / "earlier.png")
    initial = dict(_files(inbox, "encrypt"))
    save_image(pixels, inbox / "new.png")
    existing = output / "new_encrypted.png"
    existing.write_bytes(b"existing data")
    worker = ScanWorker("encrypt", WatchConfig(str(inbox), str(output)), "watch", initial)
    worker.run()
    assert sorted(path.name for path in output.iterdir()) == ["new_encrypted.png"]
    assert existing.read_bytes() == b"existing data"
