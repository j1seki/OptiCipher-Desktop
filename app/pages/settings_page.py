"""
app.pages.settings_page
=======================

Compute, crypto and appearance settings.

The form itself lives in :class:`SettingsPanel`, which is reused verbatim by
the modal settings dialog (``app.window.SettingsDialog``) — so the dialog and
the page can never drift apart.

Two rules make the page usable rather than merely present:

  * **Appearance applies immediately.** A theme switch that needs an "Apply"
    click feels broken; the radio switches the theme on the spot.
  * **Compute changes are explicit, but never hidden.** The action bar is
    pinned to the bottom of the page (always visible, at any window size),
    it says how many values are pending, and it offers both Apply and
    Revert. Nothing is applied behind the user's back, and nothing is lost
    silently.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import device as _device
from ..theme import GAP_MD, GAP_SM
from ..widgets import (
    Card,
    Field,
    GhostButton,
    InfoRow,
    PrimaryButton,
    StatusBadge,
)
from .base import BasePage

CONTROL_WIDTH = 260


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

        compute = Card(
            "Compute",
            "Where the heavy work runs. Changes apply to the next job.",
        )

        self.device_combo = QComboBox()
        self._fill_devices()
        compute.body.addWidget(
            self._field(
                "Compute device",
                self.device_combo,
                "Where the heavy work runs. Auto does a one-time speed test "
                "on this machine and picks the faster of GPU and CPU. GPU "
                "uses WebGPU — Metal on macOS, Vulkan on Linux, DirectX 12 "
                "on Windows — and falls back to CPU when no adapter exists.",
            )
        )

        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(0, 256)
        self.threads_spin.setValue(self.settings.threads)
        self.threads_spin.setSpecialValueText("Auto (all cores)")
        compute.body.addWidget(
            self._field(
                "CPU threads",
                self.threads_spin,
                "Worker threads for the CPU backend. Auto uses every core. "
                "The GPU backend ignores this setting.",
            )
        )

        self.ram_spin = QSpinBox()
        self.ram_spin.setRange(16, 65536)
        self.ram_spin.setSingleStep(64)
        self.ram_spin.setSuffix(" MB")
        self.ram_spin.setValue(self.settings.ram_budget_mb)
        compute.body.addWidget(
            self._field(
                "RAM budget",
                self.ram_spin,
                "Upper bound on the working memory a single image may use. "
                "Images that would exceed it still process, but the backend "
                "may fall back to a slower path — raise this if very large "
                "images fail or crawl.",
            )
        )
        layout.addWidget(compute)

        crypto = Card(
            "Crypto",
            "The key-derivation cost written into every NEW ciphertext. "
            "Decryption always reads the real cost from the file header.",
        )
        self.iter_spin = QSpinBox()
        self.iter_spin.setRange(10_000, 2_000_000)
        self.iter_spin.setSingleStep(50_000)
        self.iter_spin.setValue(self.settings.iterations)
        crypto.body.addWidget(
            self._field(
                "PBKDF2 iterations",
                self.iter_spin,
                "How many times the passphrase is stretched before use. "
                "Higher makes guessing the passphrase far slower and "
                "encryption a little slower. This setting never affects "
                "decryption.",
            )
        )
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

    # -- layout helpers -----------------------------------------------------
    @staticmethod
    def _field(label: str, control: QWidget, hint: str) -> Field:
        """A labelled control with a hint under it, in the design system."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_SM)
        control.setMinimumWidth(160)
        control.setMaximumWidth(CONTROL_WIDTH)
        # The tooltip goes on the control itself as well as the row, so
        # hovering either one explains the setting.
        control.setToolTip(hint)
        row.addWidget(control)
        row.addStretch(1)
        return Field(label, holder, hint)

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

    # -- values -------------------------------------------------------------
    def current_values(self) -> dict:
        """The values currently shown in the widgets."""
        return {
            "device": self.device_combo.currentData(),
            "threads": self.threads_spin.value(),
            "ram_budget_mb": self.ram_spin.value(),
            "iterations": self.iter_spin.value(),
        }

    def stored_values(self) -> dict:
        """The values currently saved in the settings store."""
        return {
            "device": self.settings.device,
            "threads": self.settings.threads,
            "ram_budget_mb": self.settings.ram_budget_mb,
            "iterations": self.settings.iterations,
        }

    def pending_changes(self) -> dict:
        """Which values differ from the saved ones."""
        current = self.current_values()
        stored = self.stored_values()
        return {
            key: (stored[key], current[key])
            for key in current
            if stored[key] != current[key]
        }

    # -- actions ------------------------------------------------------------
    def apply(self) -> None:
        """Persist the values and push them into the acceleration layer."""
        self.settings.device = self.device_combo.currentData()
        self.settings.threads = self.threads_spin.value()
        self.settings.ram_budget_mb = self.ram_spin.value()
        self.settings.iterations = self.iter_spin.value()
        self.settings.apply_to_accel()
        self.reload()

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
    subtitle = (
        "Compute, crypto and appearance. Compute changes apply to the next "
        "job; the theme switches immediately."
    )

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()

    def _build(self) -> None:
        # The settings body can be taller than the window (three cards of
        # controls plus the machine facts), so it scrolls; the action bar
        # stays pinned at the bottom and is always reachable.
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(GAP_MD)

        self.panel = SettingsPanel()
        body_layout.addWidget(self.panel)

        # -- appearance (applies instantly) ----------------------------------
        appearance = Card(
            "Appearance",
            "The theme is remembered between runs and switches immediately.",
        )
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
                "design systems — this takes effect immediately"
            )
            radio.toggled.connect(self._on_theme_toggled)
            self.theme_group.addButton(radio)
            row.addWidget(radio)
        row.addStretch(1)
        appearance.body.addLayout(row)
        body_layout.addWidget(appearance)
        body_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.content.addWidget(scroll, 1)

        # -- action bar (always visible) --------------------------------------
        bar = QFrame()
        bar.setObjectName("StatusStrip")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(14, 10, 14, 10)
        bar_layout.setSpacing(GAP_MD)

        self.pending_badge = StatusBadge("No pending changes", "neutral")
        bar_layout.addWidget(self.pending_badge)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        bar_layout.addWidget(self.status_label, 1)

        self.revert_btn = GhostButton("Revert")
        self.revert_btn.setObjectName("settings_revert")
        self.revert_btn.setToolTip(
            "Discard the unsaved changes and show the saved values again"
        )
        self.revert_btn.clicked.connect(self._revert)
        bar_layout.addWidget(self.revert_btn)

        self.apply_btn = PrimaryButton("Apply changes")
        self.apply_btn.setObjectName("settings_apply")
        self.apply_btn.setToolTip(
            "Save these settings and apply them to the next job"
        )
        self.apply_btn.clicked.connect(self._apply)
        bar_layout.addWidget(self.apply_btn)

        self.content.addWidget(bar)
        self._bar = bar
        # Keep the pending indicator honest while the user edits.
        self.panel.device_combo.currentIndexChanged.connect(self._update_pending)
        for spin in (
            self.panel.threads_spin,
            self.panel.ram_spin,
            self.panel.iter_spin,
        ):
            spin.valueChanged.connect(self._update_pending)

        self._sync_theme()

    # -- behaviour ----------------------------------------------------------
    def refresh(self) -> None:
        self.panel.reload()
        self._sync_theme()
        self._update_pending()

    def _sync_theme(self) -> None:
        manager = getattr(self.window, "theme_manager", None)
        name = manager.name if manager is not None else "dark"
        # Block the signal: this is a sync, not a user choice.
        for radio in (self.dark_radio, self.light_radio):
            radio.blockSignals(True)
        (self.dark_radio if name == "dark" else self.light_radio).setChecked(True)
        for radio in (self.dark_radio, self.light_radio):
            radio.blockSignals(False)

    def _on_theme_toggled(self, checked: bool) -> None:
        """The theme switches the moment it is chosen — no Apply needed."""
        if not checked:
            return
        manager = getattr(self.window, "theme_manager", None)
        if manager is None:
            return
        chosen = "light" if self.light_radio.isChecked() else "dark"
        if manager.name != chosen:
            manager.set_theme(chosen)
        self.status_label.setText("Theme switched.")
        self._update_pending()

    def _update_pending(self) -> None:
        pending = self.panel.pending_changes()
        count = len(pending)
        if count:
            self.pending_badge.set_status(
                f"{count} unsaved change" + ("s" if count > 1 else ""), "warning"
            )
            self.apply_btn.setEnabled(True)
            self.revert_btn.setEnabled(True)
        else:
            self.pending_badge.set_status("No pending changes", "neutral")
            self.apply_btn.setEnabled(False)
            self.revert_btn.setEnabled(False)

    def _apply(self) -> None:
        self.panel.apply()
        self.status_label.setText("Settings applied — they take effect on the next job.")
        self._update_pending()
        if self.window is not None:
            self.window.refresh_device_summary()

    def _revert(self) -> None:
        self.panel.reload()
        self.status_label.setText("Changes discarded.")
        self._update_pending()
