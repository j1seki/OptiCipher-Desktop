"""
app.pages.settings_page
=======================

Compute, crypto and appearance settings.

The form itself lives in :class:`SettingsPanel`, which is reused verbatim by
the modal settings dialog (``app.window.SettingsDialog``) — so the dialog and
the page can never drift apart.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import device as _device
from ..theme import GAP_MD
from ..widgets import Card, InfoRow, PrimaryButton, SectionTitle
from .base import BasePage


def _tipped_row(label_text: str, tip: str, widget: QWidget):
    """A form row whose label and widget both carry the same tooltip."""
    label = QLabel(label_text)
    label.setObjectName("FieldLabel")
    label.setToolTip(tip)
    widget.setToolTip(tip)
    return label, widget


class SettingsPanel(QWidget):
    """
    The settings form (compute + crypto).

    `apply()` writes the values into :class:`app.settings.AppSettings` and
    pushes the compute settings into the acceleration layer. It is called by
    the page's Apply button and by the dialog's accept().
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        from ..settings import AppSettings

        self.settings = AppSettings()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(GAP_MD)

        compute = Card("Compute", "Where the heavy work runs.")
        form = QFormLayout()
        form.setSpacing(12)
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.device_combo = QComboBox()
        self._fill_devices()
        form.addRow(
            *_tipped_row(
                "Compute device",
                "Where the heavy work runs. Auto does a one-time speed test "
                "on this machine and picks the faster of GPU and CPU. GPU "
                "uses WebGPU — Metal on macOS, Vulkan on Linux, DirectX 12 "
                "on Windows — and falls back to CPU when no adapter exists.",
                self.device_combo,
            )
        )

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 256)
        self.threads_spin.setValue(self.settings.threads)
        self.threads_spin.setSpecialValueText("Auto (all cores)")
        form.addRow(
            *_tipped_row(
                "CPU threads",
                "Worker threads for the CPU backend. Auto uses every core. "
                "The GPU backend ignores this setting.",
                self.threads_spin,
            )
        )

        self.ram_spin = QSpinBox()
        self.ram_spin.setRange(16, 65536)
        self.ram_spin.setSingleStep(64)
        self.ram_spin.setSuffix(" MB")
        self.ram_spin.setValue(self.settings.ram_budget_mb)
        form.addRow(
            *_tipped_row(
                "RAM budget",
                "Upper bound on the working memory a single image may use. "
                "Images that would exceed it still process, but the backend "
                "may fall back to a slower path — raise this if very large "
                "images fail or crawl.",
                self.ram_spin,
            )
        )
        compute.body.addLayout(form)
        layout.addWidget(compute)

        crypto = Card("Crypto", "Used for newly encrypted files.")
        crypto_form = QFormLayout()
        crypto_form.setSpacing(12)
        crypto_form.setLabelAlignment(Qt.AlignLeft)
        crypto_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(10_000, 2_000_000)
        self.iter_spin.setSingleStep(50_000)
        self.iter_spin.setValue(self.settings.iterations)
        crypto_form.addRow(
            *_tipped_row(
                "PBKDF2 iterations",
                "Key-derivation cost stored in every NEW ciphertext: how "
                "many times the passphrase is stretched before use. Higher "
                "makes guessing the passphrase far slower and encryption a "
                "little slower. Decryption always reads the stored value "
                "from the image header — this setting never affects it.",
                self.iter_spin,
            )
        )
        crypto.body.addLayout(crypto_form)
        layout.addWidget(crypto)

        machine = Card("This machine", "Read-only information.")
        self.machine_rows = {}
        for key, label in (
            ("cores", "CPU cores"),
            ("ram", "System RAM"),
            ("platform", "Platform"),
        ):
            row = InfoRow(label, "—")
            self.machine_rows[key] = row
            machine.body.addWidget(row)
        self._fill_machine()
        layout.addWidget(machine)
        layout.addStretch(1)

    # -- data ---------------------------------------------------------------
    def _fill_devices(self) -> None:
        self.device_combo.clear()
        rows = _device.compute_backends()
        gpu_rows = [r for r in rows if r.get("name") == "gpu" and r.get("available")]
        cpu_rows = [r for r in rows if r.get("name") == "cpu"]
        self.device_combo.addItem("Auto (prefer GPU)", "auto")
        for row in gpu_rows:
            self.device_combo.addItem(f"GPU — {row.get('detail', '')}", "gpu")
        for row in cpu_rows:
            self.device_combo.addItem(
                f"CPU — {row.get('detail', 'processor')}", "cpu"
            )
        # Grey-out note when no GPU is present.
        if not gpu_rows:
            self.device_combo.setItemData(
                1, "No usable GPU adapter detected", Qt.ToolTipRole
            )
        current = self.settings.device
        index = self.device_combo.findData(current)
        self.device_combo.setCurrentIndex(max(0, index))

    def _fill_machine(self) -> None:
        self.machine_rows["cores"].set_value(str(_device.cpu_count()))
        ram = _device.total_ram_mb()
        self.machine_rows["ram"].set_value(
            f"{ram / 1024:.1f} GiB" if ram else "unknown"
        )
        self.machine_rows["platform"].set_value(_device.platform_summary())

    # -- actions ------------------------------------------------------------
    def apply(self) -> None:
        """Persist the values and push them into the acceleration layer."""
        self.settings.device = self.device_combo.currentData()
        self.settings.threads = self.threads_spin.value()
        self.settings.ram_budget_mb = self.ram_spin.value()
        self.settings.iterations = self.iter_spin.value()
        self.settings.apply_to_accel()

    def reload(self) -> None:
        """Re-read the stored values into the widgets."""
        self.settings = type(self.settings)()
        self._fill_devices()
        self.threads_spin.setValue(self.settings.threads)
        self.ram_spin.setValue(self.settings.ram_budget_mb)
        self.iter_spin.setValue(self.settings.iterations)


class SettingsPage(BasePage):
    """The settings screen."""

    key = "settings"
    title = "Settings"
    subtitle = "Compute, crypto and appearance. Changes apply to the next job."

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()

    def _build(self) -> None:
        self.panel = SettingsPanel()
        self.content.addWidget(self.panel)

        # -- appearance -------------------------------------------------------
        appearance = Card("Appearance", "The theme is remembered between runs.")
        self.theme_group = QButtonGroup(self)
        self.theme_group.setExclusive(True)
        row = QHBoxLayout()
        row.setSpacing(GAP_MD)
        self.dark_radio = QRadioButton("Dark")
        self.light_radio = QRadioButton("Light")
        for radio in (self.dark_radio, self.light_radio):
            radio.setCursor(Qt.PointingHandCursor)
            radio.setToolTip(
                "Switch the whole application between the dark and light "
                "design systems"
            )
            self.theme_group.addButton(radio)
            row.addWidget(radio)
        row.addStretch(1)
        appearance.body.addLayout(row)
        self.content.addWidget(appearance)

        # -- actions ----------------------------------------------------------
        actions = QHBoxLayout()
        actions.setSpacing(GAP_MD)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Faint")
        actions.addWidget(self.status_label, 1)
        apply_btn = PrimaryButton("Apply")
        apply_btn.setObjectName("settings_apply")
        apply_btn.setToolTip("Save these settings and apply them to the next job")
        apply_btn.clicked.connect(self._apply)
        actions.addWidget(apply_btn)
        self.content.addLayout(actions)

        self._sync_theme()

    def refresh(self) -> None:
        self.panel.reload()
        self._sync_theme()

    def _sync_theme(self) -> None:
        manager = getattr(self.window, "theme_manager", None)
        name = manager.name if manager is not None else "dark"
        (self.dark_radio if name == "dark" else self.light_radio).setChecked(True)

    def _apply(self) -> None:
        self.panel.apply()
        manager = getattr(self.window, "theme_manager", None)
        if manager is not None:
            chosen = "light" if self.light_radio.isChecked() else "dark"
            manager.set_theme(chosen)
        self.status_label.setText("Settings applied.")
        if self.window is not None:
            self.window.refresh_device_summary()
