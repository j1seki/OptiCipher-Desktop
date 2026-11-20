"""Independent desktop folder watches for the current application session."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, time, timedelta
from pathlib import Path
import json

from PySide6.QtCore import QObject, QSettings, QThread, QTimer, Signal, Slot

from opticipher import decrypt_image, encrypt_image, load_image, save_image

from .private_storage import private_folder
from .settings import APP, ORG
from .widgets import IMAGE_EXTENSIONS
from .workers import detect_opticipher_header

MODES = ("encrypt", "decrypt")
INTERVALS = (15, 60, 360, 720, 1440)
KEYRING_SERVICE = "OptiCipher Desktop folder watch"


@dataclass(frozen=True)
class WatchConfig:
    inbox: str = ""
    output: str = ""
    interval: int = 15
    weekday: int = 0
    clock: str = "09:00"
    include_existing: bool = True
    overwrite: bool = False
    remember: bool = False
    enabled: bool = False

    def next_at(self, now: datetime) -> datetime:
        if self.interval:
            return now + timedelta(minutes=self.interval)
        day = now.date() + timedelta(days=(self.weekday - now.weekday()) % 7)
        due = datetime.combine(day, time.fromisoformat(self.clock))
        return due if due > now else due + timedelta(days=7)


def _keyring():
    """Select a credential backend that uses the OS's protected store."""
    import sys

    if sys.platform == "darwin":
        from keyring.backends.macOS import Keyring
    elif sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring as Keyring
    else:
        from keyring.backends.SecretService import Keyring
    return Keyring()


def _files(folder: Path, mode: str):
    extensions = IMAGE_EXTENSIONS if mode == "encrypt" else (".png",)
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() not in extensions or path.is_symlink():
            continue
        try:
            info = path.stat()
            if path.is_file():
                yield path, (info.st_mtime_ns, info.st_size)
        except OSError:
            continue


class ScanWorker(QThread):
    report = Signal(str, str, str, str)

    def __init__(self, mode, config, passphrase, processed):
        super().__init__()
        self.mode = mode
        self.config = config
        self.passphrase = passphrase
        self.processed = dict(processed)

    def run(self):
        try:
            inbox = Path(self.config.inbox).resolve()
            out = Path(self.config.output).resolve() if self.config.output else private_folder()
            if not out.is_dir():
                raise OSError("Output folder is unavailable.")
            candidates = dict(_files(inbox, self.mode))
            self.processed = {path: value for path, value in self.processed.items() if path in candidates}
            for source, fingerprint in candidates.items():
                if self.isInterruptionRequested():
                    break
                if self.processed.get(source) == fingerprint:
                    continue
                try:
                    status, detail = self._process(source, out)
                except Exception as error:
                    self.report.emit(source.name, "error", str(error), "")
                    continue
                self.processed[source] = fingerprint
                self.report.emit(source.name, status, detail, str(out / detail) if status == "ok" else "")
        except Exception as error:
            self.report.emit("Folder watch", "error", str(error), "")
        finally:
            self.passphrase = ""

    def _process(self, source, out):
        image = load_image(source)
        fingerprint = detect_opticipher_header(image)
        encrypt = self.mode == "encrypt"
        if encrypt == bool(fingerprint):
            return "skip", "Already encrypted" if encrypt else "No OptiCipher header"
        stem = source.stem if encrypt else source.stem.removesuffix("_encrypted")
        target = out / (f"{stem}_encrypted.png" if encrypt else f"{stem}.png")
        if target.resolve() == source.resolve():
            raise ValueError("Output would replace the input file. Choose a different output folder.")
        if target.exists() and not self.config.overwrite:
            return "skip", f"{target.name} already exists"
        result = encrypt_image(image, self.passphrase) if encrypt else decrypt_image(image, self.passphrase)
        if self.isInterruptionRequested():
            raise ValueError("Watch stopped before saving this file.")
        try:
            written = save_image(result, target, overwrite=self.config.overwrite, keep_both=False)
        except FileExistsError:
            return "skip", f"{target.name} already exists"
        return "ok", written.name


class FolderWatcher(QObject):
    changed = Signal(str)
    activity = Signal(str, str, str, str, str)
    scan_started = Signal(str)
    scan_finished = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings(ORG, APP)
        self.configs = {mode: self._load(mode) for mode in MODES}
        self.workers = {}
        self.secrets = {}
        self.due = {}
        self.processed = {mode: {} for mode in MODES}
        self.status = {mode: "Off" for mode in MODES}
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)

    def _load(self, mode):
        try:
            return WatchConfig(**json.loads(self.settings.value(f"watches/{mode}", "{}")))
        except (TypeError, ValueError):
            return WatchConfig()

    def _store(self, mode, config):
        self.configs[mode] = config
        self.settings.setValue(f"watches/{mode}", json.dumps(asdict(config)))

    def restore(self):
        for mode, config in self.configs.items():
            if not (config.enabled and config.remember):
                continue
            try:
                password = _keyring().get_password(KEYRING_SERVICE, mode)
                if not password:
                    raise RuntimeError("The saved passphrase is unavailable.")
                self._enable(mode, config, password)
            except Exception as error:
                self.status[mode] = f"Off · {error}"
                self.changed.emit(mode)

    def start(self, mode, config, passphrase):
        if mode in self.workers:
            raise ValueError("Wait for the current scan to finish.")
        if not passphrase:
            raise ValueError("Enter a passphrase.")
        self._validate_folders(config)
        if config.remember:
            _keyring().set_password(KEYRING_SERVICE, mode, passphrase)
        elif self.configs[mode].remember:
            self.forget(mode)
        self._enable(mode, config, passphrase)

    @staticmethod
    def _validate_folders(config):
        inbox = Path(config.inbox).resolve()
        if not config.inbox or not inbox.is_dir():
            raise ValueError("Choose an accessible input folder.")
        if config.output and not Path(config.output).is_dir():
            raise ValueError("Choose an accessible output folder.")
        return inbox

    def _enable(self, mode, config, passphrase):
        inbox = self._validate_folders(config)
        enabled = replace(config, enabled=True)
        self.processed[mode] = {} if config.include_existing else dict(_files(inbox, mode))
        self.secrets[mode] = passphrase
        self._store(mode, enabled)
        self.due[mode] = config.next_at(datetime.now())
        self.status[mode] = self._scheduled_status(mode)
        self.changed.emit(mode)
        if config.interval:
            self.run_now(mode)

    def forget(self, mode):
        store = _keyring()
        if store.get_password(KEYRING_SERVICE, mode) is not None:
            store.delete_password(KEYRING_SERVICE, mode)
        self._store(mode, replace(self.configs[mode], remember=False))
        self.changed.emit(mode)

    def stop(self, mode):
        self.secrets.pop(mode, None)
        self.due.pop(mode, None)
        worker = self.workers.get(mode)
        if worker:
            worker.requestInterruption()
        self._store(mode, replace(self.configs[mode], enabled=False))
        self.status[mode] = "Stopping…" if worker else "Off"
        self.changed.emit(mode)

    def _scheduled_status(self, mode):
        due = self.due[mode].strftime("%a %H:%M")
        return f"On · Next check {due}"

    def _tick(self):
        now = datetime.now()
        for mode, due in tuple(self.due.items()):
            if now >= due and mode not in self.workers:
                self.due[mode] = self.configs[mode].next_at(now)
                self.run_now(mode)

    def run_now(self, mode):
        if mode not in self.secrets or mode in self.workers:
            return
        worker = ScanWorker(mode, self.configs[mode], self.secrets[mode], self.processed[mode])
        self.workers[mode] = worker
        worker.report.connect(self._report)
        worker.finished.connect(self._finished)
        self.status[mode] = "Scanning…"
        self.changed.emit(mode)
        self.scan_started.emit(mode)
        worker.start()

    @Slot(str, str, str, str)
    def _report(self, name, status, detail, output):
        self.activity.emit(self.sender().mode, name, status, detail, output)

    @Slot()
    def _finished(self):
        mode = self.sender().mode
        worker = self.workers.pop(mode)
        self.processed[mode] = worker.processed
        self.status[mode] = self._scheduled_status(mode) if mode in self.due else "Off"
        self.scan_finished.emit(mode, "Scan stopped" if mode not in self.due else "Scan finished")
        self.changed.emit(mode)
        worker.deleteLater()
