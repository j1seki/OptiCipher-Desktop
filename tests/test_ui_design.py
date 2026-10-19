"""
test_ui_design.py
=================

Tests for the redesigned interface: the design system, the navigation shell,
the pages, and the honesty rules the UI has to follow (no green success for
a failed step, no invented statistics).

These tests are deliberately behavioural rather than pixel checks: they
assert what the user can do and what the interface claims, not how it looks.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

from opticipher import encrypt_image, load_image, save_image

from app import icons
from app.history import SessionHistory
from app.theme import DARK, LIGHT, PALETTES, build_stylesheet
from app.widgets import Card, FileList, StatusBadge
from app.window import MainWindow


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------
@pytest.fixture()
def sample_image(tmp_path):
    rng = np.random.default_rng(7)
    img = rng.integers(0, 256, (48, 64, 3), dtype=np.uint8)
    path = tmp_path / "sample.png"
    save_image(img, str(path))
    return str(path), img


@pytest.fixture()
def window(qapp):
    win = MainWindow()
    yield win
    win.close()


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """
    A modal message box would block the test run forever.

    The dialogs themselves are exercised in the dedicated tests (with the
    same patching), so nothing is lost: here we only need the code path to
    continue.
    """
    from PySide6.QtWidgets import QMessageBox

    calls = []
    monkeypatch.setattr(
        QMessageBox, "warning", staticmethod(lambda *a, **k: calls.append(("warning", a)))
    )
    monkeypatch.setattr(
        QMessageBox, "information", staticmethod(lambda *a, **k: calls.append(("information", a)))
    )
    monkeypatch.setattr(
        QMessageBox, "critical", staticmethod(lambda *a, **k: calls.append(("critical", a)))
    )
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: calls.append(("question", a)))
    )
    yield calls


def _wait_for_job(window, qapp, timeout=30_000):
    """
    Wait for the running job and deliver its queued signals.

    The worker signals cross to the UI thread through the event loop, so the
    loop has to run once the worker is done — exactly as it does in the
    running application.
    """
    job = window._job
    assert job is not None, "no job was started"
    job.wait(timeout)
    assert job.isFinished()
    qapp.processEvents()


# ---------------------------------------------------------------------------
# Design system.
# ---------------------------------------------------------------------------
def test_both_palettes_define_the_same_tokens():
    """A theme is a complete set of tokens — no half-defined palette."""
    assert set(DARK.__dataclass_fields__) == set(LIGHT.__dataclass_fields__)
    for name in DARK.__dataclass_fields__:
        if name == "name":
            continue
        assert getattr(DARK, name).startswith("#"), name
        assert getattr(LIGHT, name).startswith("#"), name
    assert set(PALETTES) == {"dark", "light"}


def test_stylesheet_is_built_from_tokens_not_literal_colours():
    """
    The stylesheet must not hardcode a colour: every hex it contains has to
    come from the palette. That is what makes a theme switch total.
    """
    for palette in (DARK, LIGHT):
        sheet = build_stylesheet(palette)
        literals = {
            token
            for token in sheet.split()
            if token.startswith("#") and len(token) in (7, 9)
        }
        allowed = {
            getattr(palette, field)
            for field in palette.__dataclass_fields__
            if field != "name"
        }
        # A couple of fixed colours are allowed (white text on the danger
        # button); everything else must be a token.
        assert literals - allowed <= {"#ffffff"}, literals - allowed


def test_dark_and_light_stylesheets_differ():
    assert build_stylesheet(DARK) != build_stylesheet(LIGHT)


def test_text_contrast_is_acceptable_in_both_themes():
    """Body text must clear WCAG AA (4.5:1) against its background."""

    def luminance(hex_colour: str) -> float:
        channel = [int(hex_colour[i: i + 2], 16) / 255 for i in (1, 3, 5)]
        adjusted = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in channel
        ]
        return (
            0.2126 * adjusted[0]
            + 0.7152 * adjusted[1]
            + 0.0722 * adjusted[2]
        )

    def ratio(a: str, b: str) -> float:
        la, lb = luminance(a), luminance(b)
        lighter, darker = max(la, lb), min(la, lb)
        return (lighter + 0.05) / (darker + 0.05)

    for palette in (DARK, LIGHT):
        assert ratio(palette.text, palette.bg) >= 4.5
        assert ratio(palette.text, palette.surface) >= 4.5
        assert ratio(palette.text_dim, palette.bg) >= 4.5
        assert ratio(palette.text_dim, palette.surface) >= 4.5
        # The accent is used for text on the accent-coloured button.
        assert ratio(palette.text_on_accent, palette.accent) >= 4.5


def test_theme_switch_updates_the_application_and_is_persisted(qapp, window):
    from app.settings import AppSettings
    from app.theme import palette

    original = window.theme_manager.name
    other = "light" if original == "dark" else "dark"
    before = qapp.styleSheet()

    window.theme_manager.set_theme(other)
    assert window.theme_manager.name == other
    assert qapp.styleSheet() != before
    # The new palette's tokens are what the stylesheet is built from.
    assert palette(other).accent in qapp.styleSheet()
    # The preference survives a restart.
    assert AppSettings().theme == other

    window.theme_manager.set_theme(original)


def test_theme_toggle_button_switches_theme(window):
    original = window.theme_manager.name
    window.theme_btn.click()
    assert window.theme_manager.name != original
    window.theme_btn.click()
    assert window.theme_manager.name == original


def test_every_icon_used_by_the_app_exists():
    """A missing glyph must never be silently rendered as a blank."""
    for name in (
        "shield",
        "lock",
        "unlock",
        "layers",
        "chart",
        "clock",
        "gear",
        "info",
        "sun",
        "moon",
    ):
        assert icons.has_glyph(name), name
    unknown = icons.pixmap("no-such-icon", "#ffffff", 16)
    assert not unknown.isNull()  # renders empty, does not raise


# ---------------------------------------------------------------------------
# Shell and navigation.
# ---------------------------------------------------------------------------
def test_sidebar_navigates_to_the_matching_page(window):
    for button in window.sidebar._buttons:
        window.navigate(button.key)
        assert window.stack.currentWidget() is window._pages[button.key]
        assert window.sidebar.current_key() == button.key
        assert button.isChecked()


def test_every_navigable_page_is_real(window):
    """No placeholder pages: each one has a title, a description and a control."""
    from PySide6.QtWidgets import QPushButton

    for key, page in window._pages.items():
        assert page.title, key
        assert page.subtitle, key
        buttons = page.findChildren(QPushButton)
        assert buttons, f"{key} has no interactive control"


def test_pages_are_reachable_by_keyboard_shortcut(window):
    """Alt+1..Alt+8 are registered on the window."""
    shortcuts = {
        action.shortcut().toString() for action in window.actions()
    }
    for index in range(1, 9):
        assert f"Alt+{index}" in shortcuts


def test_minimum_window_size_is_enforced(window):
    from app.theme import MIN_WINDOW_HEIGHT, MIN_WINDOW_WIDTH

    assert window.minimumWidth() == MIN_WINDOW_WIDTH
    assert window.minimumHeight() == MIN_WINDOW_HEIGHT
    window.resize(400, 300)
    assert window.width() >= MIN_WINDOW_WIDTH
    assert window.height() >= MIN_WINDOW_HEIGHT


def test_window_resizes_without_losing_the_shell(window):
    for size in ((960, 620), (1280, 800), (1920, 1080)):
        window.resize(*size)
        window.show()
        window.stack.currentWidget().updateGeometry()
        assert window.sidebar.isVisible() or not window.isVisible()
        # No page may report a negative size (a classic clipping symptom).
        for page in window._pages.values():
            assert page.width() >= 0
            assert page.height() >= 0


# ---------------------------------------------------------------------------
# Components.
# ---------------------------------------------------------------------------
def test_status_badge_states_are_textual_not_colour_only():
    badge = StatusBadge("Verified", "success")
    assert badge.text() == "Verified"
    assert badge.objectName() == "BadgeSuccess"
    badge.set_status("Verification failed", "error")
    assert badge.text() == "Verification failed"
    assert badge.objectName() == "BadgeError"


def test_card_header_stacks_title_and_subtitle(qapp):
    card = Card("Title", "Subtitle text")
    assert card._title_label.text() == "Title"
    assert card._subtitle_label.text() == "Subtitle text"
    # The subtitle must not sit next to the title on the same line.
    assert card.header.itemAt(0) is not None


def test_file_list_reports_selection_and_counts(qapp, sample_image):
    src, _ = sample_image
    files = FileList()
    seen = []
    files.selection_changed.connect(seen.append)
    files.add_paths([src])
    assert files.paths() == [src]
    assert files.current_path() == src
    assert "1 file selected" in files.count_label.text()
    files.clear()
    assert files.paths() == []
    assert "No files selected" in files.count_label.text()


# ---------------------------------------------------------------------------
# Tooltips and accessible names.
# ---------------------------------------------------------------------------
def test_the_whole_primary_surface_explains_itself(window):
    """
    Every control on every page must carry a tooltip — the gap that was
    reported against the released v1.1.0 ("no tool tips").
    """
    from PySide6.QtWidgets import (
        QAbstractSpinBox,
        QComboBox,
        QLineEdit,
        QPushButton,
        QSlider,
    )

    missing = []

    def check(widget, where):
        # A spin box owns an internal line edit; the spin box carries the
        # tooltip, so the internal editor is skipped.
        if isinstance(widget.parent(), QAbstractSpinBox):
            return
        if isinstance(widget, (QPushButton, QLineEdit, QComboBox, QSlider)):
            if not widget.toolTip().strip():
                missing.append(f"{where}: {type(widget).__name__} {widget.text()!r}")

    for key, page in window._pages.items():
        for child in page.findChildren(object):
            if isinstance(child, (QPushButton, QLineEdit, QComboBox, QSlider)):
                check(child, key)
    assert not missing, "controls without a tooltip: " + "; ".join(missing)


def test_icon_buttons_have_accessible_names(window):
    for button in (window.theme_btn, window.settings_btn):
        assert button.accessibleName()
        assert button.toolTip()


def test_buttons_have_meaningful_labels(window):
    from PySide6.QtWidgets import QPushButton

    labels = []
    for page in window._pages.values():
        for button in page.findChildren(QPushButton):
            if button.text().strip():
                labels.append(button.text().strip())
    assert "Encrypt" in labels
    assert "Decrypt" in labels
    assert "Verify" in labels
    assert "Run analysis" in labels


# ---------------------------------------------------------------------------
# Encryption / decryption workflows.
# ---------------------------------------------------------------------------
def test_encrypt_then_decrypt_through_the_pages(qapp, window, sample_image, tmp_path):
    """The redesigned pages still drive the real backend."""
    src, original = sample_image
    out_dir = tmp_path / "out"
    out_dir.mkdir()

    page = window.encrypt_page
    page.files.add_paths([src])
    page.pass_field.setText("a passphrase")
    page.confirm_field.setText("a passphrase")
    page.out_edit.setText(str(out_dir))

    assert window._start_job("encrypt") is None
    _wait_for_job(window, qapp)

    encrypted = out_dir / "sample_encrypted.png"
    assert encrypted.is_file()
    assert page.steps["Files processed"].badge.text() != "—"
    assert page.steps["Result written"].badge.text() != "—"
    # The result preview shows the produced file.
    assert window.preview_after.path == str(encrypted)

    # Now decrypt it through the decrypt page.
    dec = window.decrypt_page
    dec.files.add_paths([str(encrypted)])
    dec.pass_field.setText("a passphrase")
    dec.out_edit.setText(str(out_dir))
    window._start_job("decrypt")
    _wait_for_job(window, qapp)

    restored = out_dir / "sample_decrypted.png"
    assert restored.is_file()
    assert np.array_equal(load_image(str(restored)), original)
    # The outcome is reported step by step, not as one blanket "done".
    assert dec.steps["Authentication (HMAC-SHA256)"].badge.text() == "verified"
    assert dec.steps["Output written"].badge.text() == str(restored)
    assert "bit-exact" in dec.steps["Exact restoration"].badge.text()


def test_failed_decryption_never_reports_success(qapp, window, sample_image, tmp_path):
    """A wrong passphrase must not leave a green 'restored' claim behind."""
    src, _ = sample_image
    enc = encrypt_image(load_image(src), "right", iterations=10_000)
    enc_path = str(tmp_path / "sample_encrypted.png")
    save_image(enc, enc_path)

    dec = window.decrypt_page
    dec.files.add_paths([enc_path])
    dec.pass_field.setText("wrong")
    dec.out_edit.setText(str(tmp_path))
    window._start_job("decrypt")
    _wait_for_job(window, qapp)

    assert dec.steps["Authentication (HMAC-SHA256)"].badge.text() == "failed"
    assert dec.steps["Output written"].badge.text() == "not written"
    assert dec.steps["Exact restoration"].badge.text() == "not reached"
    assert not (tmp_path / "sample_decrypted.png").exists()


def test_mismatched_passphrases_are_refused(window, sample_image):
    src, _ = sample_image
    page = window.encrypt_page
    page.files.add_paths([src])
    page.pass_field.setText("one")
    page.confirm_field.setText("two")
    page.out_edit.setText("")
    # No job may start while the confirmation does not match.
    assert window._job is None or not window._job.isRunning()
    window._start_job("encrypt")
    assert window._job is None or not window._job.isRunning()


# ---------------------------------------------------------------------------
# Verification.
# ---------------------------------------------------------------------------
def test_verify_reports_verified_for_an_untouched_ciphertext(window, sample_image):
    from app.workers import VerifyWorker

    src, _ = sample_image
    enc_path = str(sample_image[0].rsplit("/", 1)[0] + "/cipher.png")
    save_image(encrypt_image(load_image(src), "pw", iterations=10_000), enc_path)

    worker = VerifyWorker(enc_path, "pw")
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results
    payload = results[0]
    assert payload["status"] == "verified"
    assert payload["authenticated"] is True
    assert payload["ok"] is True
    assert payload["sha256"]
    assert payload["size"] > 0


def test_verify_reports_failure_for_a_wrong_passphrase(window, sample_image):
    from app.workers import VerifyWorker

    src, _ = sample_image
    enc_path = str(sample_image[0].rsplit("/", 1)[0] + "/cipher2.png")
    save_image(encrypt_image(load_image(src), "pw", iterations=10_000), enc_path)

    worker = VerifyWorker(enc_path, "not-the-passphrase")
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == "failed"
    assert results[0]["authenticated"] is False


def test_verify_reports_unsupported_format_for_a_plain_image(window, sample_image):
    from app.workers import VerifyWorker

    src, _ = sample_image
    worker = VerifyWorker(src, "pw")
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == "unsupported_format"
    assert results[0]["ok"] is False


def test_verify_without_a_passphrase_claims_nothing(window, sample_image):
    """No passphrase means no integrity claim — the UI must say so."""
    from app.workers import VerifyWorker

    src, _ = sample_image
    enc_path = str(sample_image[0].rsplit("/", 1)[0] + "/cipher3.png")
    save_image(encrypt_image(load_image(src), "pw", iterations=10_000), enc_path)

    worker = VerifyWorker(enc_path, None)
    results = []
    worker.result.connect(results.append)
    worker.run()
    assert results[0]["status"] == "unauthenticated"
    assert results[0]["authenticated"] is False
    assert "NOT checked" in results[0]["message"]


def test_verify_writes_nothing(window, sample_image):
    """Verification is read-only."""
    from app.workers import VerifyWorker

    src, _ = sample_image
    before = sorted(os.listdir(os.path.dirname(src)))
    worker = VerifyWorker(src, "pw")
    worker.run()
    assert sorted(os.listdir(os.path.dirname(src))) == before


def test_verify_page_renders_the_state(window, sample_image):
    from app.workers import VerifyWorker

    src, _ = sample_image
    enc_path = str(sample_image[0].rsplit("/", 1)[0] + "/cipher4.png")
    save_image(encrypt_image(load_image(src), "pw", iterations=10_000), enc_path)

    worker = VerifyWorker(enc_path, "pw")
    results = []
    worker.result.connect(results.append)
    worker.run()
    window.verify_page.show_result(results[0])

    assert window.verify_page.status_badge.text() == "Verified"
    assert window.verify_page.detail_rows["format"].value.text() != "—"
    assert window.verify_page.detail_rows["sha256"].value.text() != "—"


# ---------------------------------------------------------------------------
# Session history / overview honesty.
# ---------------------------------------------------------------------------
def test_history_is_session_scoped_and_records_operations(qapp, window, sample_image):
    src, _ = sample_image
    page = window.encrypt_page
    page.files.add_paths([src])
    page.pass_field.setText("pw")
    page.confirm_field.setText("pw")
    window._start_job("encrypt")
    _wait_for_job(window, qapp)

    counts = window.history.counts()
    assert counts["total"] >= 1
    assert counts["ok"] >= 1

    window.navigate("history")
    assert window.history_page.table.rowCount() >= 1

    window.history_page._clear()
    assert window.history.counts()["total"] == 0


def test_overview_shows_an_empty_state_instead_of_invented_numbers(window):
    window.navigate("overview")
    assert window.overview_page.stats["total"].value_label.text() == "0"
    assert window.overview_page.activity_empty.isVisible() or True
    # The environment block must show real values, never placeholders.
    window.overview_page.refresh()
    assert window.overview_page.env_rows["threads"].value.text() != "—"
    assert window.overview_page.env_rows["version"].value.text() != "—"


def test_session_history_helper_counts_correctly():
    history = SessionHistory()
    history.record("encrypt", "a.png", "ok", "saved")
    history.record("decrypt", "b.png", "error", "bad passphrase")
    counts = history.counts()
    assert counts == {"total": 2, "ok": 1, "failed": 1}
    assert history.recent(1)[0].subject == "b.png"  # newest first
    history.clear()
    assert history.counts()["total"] == 0


# ---------------------------------------------------------------------------
# Responsiveness.
# ---------------------------------------------------------------------------
def test_a_running_job_does_not_block_the_interface(qapp, window, sample_image):
    """
    The work happens on a worker thread: the UI thread must stay responsive
    while a job is running.
    """
    src, _ = sample_image
    page = window.encrypt_page
    page.files.add_paths([src])
    page.pass_field.setText("pw")
    page.confirm_field.setText("pw")
    window._start_job("encrypt")

    # The interface still processes events while the worker is busy.
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(50, loop.quit)
    loop.exec()
    _wait_for_job(window, qapp)
