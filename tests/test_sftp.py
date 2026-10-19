"""
test_sftp.py
============

SFTP output locations (app/sftp.py + the JobWorker/MainWindow wiring).

Every path is exercised against an in-process fake SSH client — no live
server, no network. What is pinned here:

  * URL parsing: forms accepted, credentials refused in the URL, clear
    errors for missing host / bad port / wrong scheme.
  * Upload safety: `.part` staging, remote size verification before the
    real filename is occupied, overwrite of an existing remote copy,
    remote directory creation, `.part` cleanup on failure, fallback rename
    when posix_rename is unsupported.
  * Mirror semantics: the local file ALWAYS survives an upload; a failed
    upload is reported as an error (never a fake success) and the local
    copy stays put.
  * No credentials ever reach QSettings — session memory only.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest
from PySide6.QtCore import QObject, Signal

from app.sftp import (
    SftpError,
    SftpTarget,
    SftpUploader,
    is_sftp_output,
    parse_sftp_url,
    upload_file,
)

# Test-created QObjects (e.g. RecordingJob workers with live signal
# connections) are kept alive for the whole session: letting Python delete
# them directly mid-run is what Qt warns about ("shared QObject was deleted
# directly") and what can segfault the interpreter at teardown on Linux CI.
_KEEPALIVE: list = []


# ---------------------------------------------------------------------------
# URL parsing.
# ---------------------------------------------------------------------------
def test_parse_full_form():
    t = parse_sftp_url("sftp://alice@example.com:2222/backups/2026")
    assert t == SftpTarget(
        host="example.com", port=2222, user="alice", path="/backups/2026"
    )
    assert t.remote_file("x.png") == "/backups/2026/x.png"
    assert "alice@example.com:2222" in t.describe()


def test_parse_defaults():
    t = parse_sftp_url("sftp://example.com")
    assert t.port == 22 and t.user == "" and t.path == "/"
    assert t.remote_file("f.png") == "/f.png"


def test_parse_collapses_path_junk():
    assert parse_sftp_url("sftp://h/a//b/").path == "/a/b"
    assert parse_sftp_url("sftp://h").path == "/"
    assert parse_sftp_url("sftp://h/.").path == "/"  # '.' == root, normalized


def test_password_in_url_refused():
    with pytest.raises(ValueError, match="password"):
        parse_sftp_url("sftp://alice:hunter2@example.com/x")
    with pytest.raises(ValueError, match="password"):
        parse_sftp_url("sftp://alice:hunter2@example.com:22/x")


@pytest.mark.parametrize(
    "bad,expect",
    [
        ("/home/alice/out", "sftp://"),
        ("sftp:/example.com", "sftp://"),
        ("", "sftp://"),
        ("sftp:///only/path", "host"),
        ("sftp://example.com:70000/x", "port"),
        ("sftp://example.com:abc/x", "port"),
    ],
)
def test_malformed_urls_give_actionable_errors(bad, expect):
    with pytest.raises(ValueError, match=expect):
        parse_sftp_url(bad)


def test_is_sftp_output():
    assert is_sftp_output("sftp://h/path")
    assert is_sftp_output("  SFTP://h/path  ")  # case-insensitive
    assert not is_sftp_output("/home/out")
    assert not is_sftp_output("")


# ---------------------------------------------------------------------------
# Fake SSH machinery.
# ---------------------------------------------------------------------------
class FakeSFTP:
    """In-memory SFTP server with paramiko-shaped methods."""

    def __init__(self):
        self.files: dict = {}  # remote path -> bytes
        self.dirs = {"/"}
        self.made_dirs: list = []
        self.renames: list = []
        self.put_short = False  # simulate a truncated PUT
        self.closed = False

    def mkdir(self, path):
        if path in self.dirs:
            raise OSError(17, "File exists")
        self.dirs.add(path)
        self.made_dirs.append(path)

    def put(self, local, remote):
        data = open(local, "rb").read()
        if self.put_short:
            data = data[: max(0, len(data) // 2)]
        self.files[remote] = data

    def stat(self, path):
        if path not in self.files:
            raise OSError(2, "No such file")
        return SimpleNamespace(st_size=len(self.files[path]))

    def posix_rename(self, old, new):
        self.files[new] = self.files.pop(old)
        self.renames.append((old, new, "posix"))

    def rename(self, old, new):
        if new in self.files:
            raise OSError(17, "File exists")
        self.files[new] = self.files.pop(old)
        self.renames.append((old, new, "plain"))

    def remove(self, path):
        if path not in self.files:
            raise OSError(2, "No such file")  # paramiko raises IOError here
        del self.files[path]

    def close(self):
        self.closed = True


class NoPosixSFTP(FakeSFTP):
    """Older servers: no posix-rename extension."""

    @property
    def posix_rename(self):  # noqa: N802
        raise AttributeError("posix-rename not supported")


class FakeClient:
    def __init__(self, sftp=None, fail_connect=None):
        self.sftp = sftp or FakeSFTP()
        self.fail_connect = fail_connect
        self.connect_kwargs = None
        self.closed = False

    def connect(self, host, port=None, username=None, password=None,
                key_filename=None, timeout=None, **kwargs):
        if self.fail_connect is not None:
            raise self.fail_connect
        self.connect_kwargs = dict(
            host=host,
            port=port,
            username=username,
            password=password,
            key_filename=key_filename,
            timeout=timeout,
            **kwargs,
        )

    def open_sftp(self):
        return self.sftp

    def close(self):
        self.closed = True


@pytest.fixture()
def target():
    return SftpTarget(host="srv", port=22, user="alice", path="/out")


@pytest.fixture()
def local_file(tmp_path):
    p = tmp_path / "ciphertext.png"
    p.write_bytes(os.urandom(4096))
    return str(p)


# ---------------------------------------------------------------------------
# Upload behaviour.
# ---------------------------------------------------------------------------
def test_upload_success_mirror_and_verification(target, local_file):
    client = FakeClient()
    remote = upload_file(
        local_file, target, password="pw",
        client_factory=lambda: client,
    )
    assert remote == "/out/ciphertext.png"
    # Remote bytes match local exactly; no .part left behind.
    assert client.sftp.files[remote] == open(local_file, "rb").read()
    assert not any(k.endswith(".part") for k in client.sftp.files)
    # Connection used the right identity (password passed as password, not URL).
    assert client.connect_kwargs["username"] == "alice"
    assert client.connect_kwargs["password"] == "pw"
    assert client.connect_kwargs["key_filename"] is None
    assert client.closed and client.sftp.closed
    # The local file still exists (mirror, never move).
    assert os.path.exists(local_file)


def test_upload_creates_remote_directories(target, local_file):
    target = SftpTarget(host="srv", port=22, user="a", path="/a/b/c")
    client = FakeClient()
    upload_file(local_file, target, client_factory=lambda: client)
    for d in ("/a", "/a/b", "/a/b/c"):
        assert d in client.sftp.made_dirs


def test_truncated_upload_detected_and_part_removed(target, local_file):
    sftp = FakeSFTP()
    sftp.put_short = True
    client = FakeClient(sftp)
    with pytest.raises(SftpError, match="verification failed"):
        upload_file(local_file, target, client_factory=lambda: client)
    # Neither the real filename nor a .part survives on the server.
    assert "/out/ciphertext.png" not in sftp.files
    assert not any(k.endswith(".part") for k in sftp.files)
    # And the local file is untouched.
    assert os.path.exists(local_file)


def test_overwrite_existing_remote_copy(target, local_file):
    sftp = FakeSFTP()
    sftp.files["/out/ciphertext.png"] = b"OLD-CONTENT"
    client = FakeClient(sftp)
    upload_file(local_file, target, client_factory=lambda: client)
    assert sftp.files["/out/ciphertext.png"] == open(local_file, "rb").read()
    assert sftp.renames[-1][2] == "posix"


def test_plain_rename_fallback_when_posix_unsupported(target, local_file):
    sftp = NoPosixSFTP()
    client = FakeClient(sftp)
    upload_file(local_file, target, client_factory=lambda: client)
    assert sftp.files["/out/ciphertext.png"] == open(local_file, "rb").read()
    assert sftp.renames[-1][2] == "plain"


def test_connect_failure_message_is_credential_free(target, local_file):
    client = FakeClient(fail_connect=OSError("auth banner timeout"))
    with pytest.raises(SftpError) as exc:
        upload_file(
            local_file, target, password="super-secret-pw",
            client_factory=lambda: client,
        )
    msg = str(exc.value)
    assert "srv" in msg and "auth banner timeout" in msg
    assert "super-secret-pw" not in msg  # never leak the secret
    assert client.closed


def test_missing_paramiko_gives_install_advice(target, local_file, monkeypatch):
    """When no client_factory is given and paramiko is absent, the error
    must tell the user how to get it (simulated via a failing import)."""
    import builtins

    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "paramiko":
            raise ImportError("no paramiko")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(SftpError, match="paramiko"):
        SftpUploader(target, password="x").upload(local_file)


# ---------------------------------------------------------------------------
# JobWorker integration — mirror upload, error honesty, local survival.
# ---------------------------------------------------------------------------
@pytest.fixture()
def tiny_png(tmp_path):
    import numpy as np
    from PIL import Image

    arr = np.random.default_rng(1).integers(0, 256, (16, 16, 3), dtype=np.uint8)
    p = tmp_path / "in.png"
    Image.fromarray(arr, "RGB").save(p)
    return str(p)


def test_jobworker_sftp_flow_uploads_and_keeps_local_file(tiny_png, tmp_path):
    from app.workers import JobWorker

    client = FakeClient()
    statuses, counts = [], []
    worker = JobWorker(
        "encrypt",
        [tiny_png],
        "pw",
        10_000,
        "sftp://alice@srv/out",
        sftp={"user": "", "password": "pw", "client_factory": lambda: client},
    )
    worker.file_done.connect(lambda p, s: statuses.append(s))
    worker.all_done.connect(lambda ok, bad: counts.append((ok, bad)))
    worker.run()

    assert counts == [(1, 0)]
    assert len(statuses) == 1 and statuses[0].startswith("ok: ")
    local, uploaded = statuses[0][4:].split(" → ")
    # Local mirror written NEXT TO THE INPUT (sftp:// is not a local dir)…
    assert os.path.dirname(local) == os.path.dirname(tiny_png)
    assert os.path.exists(local)
    # …and the remote copy exists with identical bytes under a display URL.
    assert uploaded == "uploaded sftp://alice@srv/out/in_encrypted.png"
    remote_name = "/out/in_encrypted.png"
    assert client.sftp.files[remote_name] == open(local, "rb").read()


def test_jobworker_upload_failure_reports_error_local_survives(
    tiny_png, tmp_path
):
    from app.workers import JobWorker

    client = FakeClient(fail_connect=OSError("connection refused"))
    statuses, counts = [], []
    worker = JobWorker(
        "encrypt",
        [tiny_png],
        "pw",
        10_000,
        "sftp://alice@srv/out",
        sftp={"password": "pw", "client_factory": lambda: client},
    )
    worker.file_done.connect(lambda p, s: statuses.append(s))
    worker.all_done.connect(lambda ok, bad: counts.append((ok, bad)))
    worker.run()

    # Failure is NOT a fake success: counted as failed, message says the
    # file is safe locally and names the reason (credential-free).
    assert counts == [(0, 1)]
    assert statuses[0].startswith("error: saved locally to")
    assert "connection refused" in statuses[0]
    local = statuses[0].split("saved locally to ", 1)[1].split(", but")[0]
    assert os.path.exists(local)


def test_jobworker_without_sftp_is_unchanged(tiny_png):
    """No sftp cfg -> plain status, no uploads (regression guard)."""
    from app.workers import JobWorker

    statuses = []
    worker = JobWorker("encrypt", [tiny_png], "pw", 10_000, "")
    worker.file_done.connect(lambda p, s: statuses.append(s))
    worker.run()
    assert statuses[0].startswith("ok: ")
    assert "uploaded" not in statuses[0]


# ---------------------------------------------------------------------------
# MainWindow wiring — validation, credentials flow, persistence.
# ---------------------------------------------------------------------------
def _fill_encrypt(window, src):
    window.file_lists["encrypt"].add_paths([src])
    window._encrypt_pass.setText("pw")
    window._encrypt_confirm.setText("pw")


def test_window_rejects_invalid_sftp_url_before_starting(qapp, tiny_png, monkeypatch):
    import app.window as wmod

    warnings = []
    monkeypatch.setattr(
        wmod.QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: warnings.append(a)),
    )
    window = wmod.MainWindow()
    _fill_encrypt(window, tiny_png)
    window._encrypt_out.setText("sftp://example.com:notaport/x")
    window._start_job("encrypt")
    assert len(warnings) == 1
    assert "Invalid SFTP location" in warnings[0][1]
    assert window._job is None  # nothing started
    window.close()


def test_window_prompts_for_credentials_once_per_session(qapp, tiny_png, monkeypatch):
    import app.window as wmod

    window = wmod.MainWindow()
    _fill_encrypt(window, tiny_png)
    window._encrypt_out.setText("sftp://alice@srv:2200/remote/dir")

    prompt_count = []

    class StubDialog:
        def __init__(self, target, parent=None):
            self.target = target
            prompt_count.append((target.host, target.port, target.user))

        def exec(self):
            return wmod.QDialog.Accepted

        def credentials(self):
            return {"user": "alice", "password": "hunter2", "key_file": None}

    created = {}

    class RecordingJob(QObject):
        progress = Signal(int, str)
        file_done = Signal(str, str)
        all_done = Signal(int, int)

        def __init__(self, mode, files, pw, iters, out, parent=None, *, sftp=None):
            super().__init__()
            created.update(mode=mode, out=out, sftp=sftp, files=list(files))

        def isRunning(self):
            return False

        def start(self):
            pass

    monkeypatch.setattr(wmod, "SftpCredentialsDialog", StubDialog)
    monkeypatch.setattr(wmod, "JobWorker", RecordingJob)

    window._start_job("encrypt")
    _KEEPALIVE.extend([window, window._job])
    # Credentials collected once…
    assert prompt_count == [("srv", 2200, "alice")]
    # …and handed to the worker (memory only, never settings).
    assert created["sftp"]["password"] == "hunter2"
    assert created["sftp"]["user"] == "alice"

    # Second run on the same target: no second prompt.
    window._start_job("encrypt")
    _KEEPALIVE.append(window._job)
    assert prompt_count == [("srv", 2200, "alice")]
    window.close()


def test_sftp_credentials_never_reach_qsettings(qapp, tiny_png, monkeypatch):
    """The session cache lives on the window; QSettings stays clean."""
    from PySide6.QtCore import QSettings

    import app.window as wmod
    from app.settings import APP, ORG

    window = wmod.MainWindow()
    _fill_encrypt(window, tiny_png)
    window._encrypt_out.setText("sftp://alice@srv/remote/dir")

    class StubDialog:
        def __init__(self, target, parent=None):
            pass

        def exec(self):
            return wmod.QDialog.Accepted

        def credentials(self):
            return {"user": "alice", "password": "hunter2-SECRET", "key_file": None}

    class RecordingJob(QObject):
        progress = Signal(int, str)
        file_done = Signal(str, str)
        all_done = Signal(int, int)

        def __init__(self, *a, **k):
            super().__init__()

        def isRunning(self):
            return False

        def start(self):
            pass

    monkeypatch.setattr(wmod, "SftpCredentialsDialog", StubDialog)
    monkeypatch.setattr(wmod, "JobWorker", RecordingJob)
    window._start_job("encrypt")
    _KEEPALIVE.extend([window, window._job])

    # In memory: present.
    assert any(
        v.get("password") == "hunter2-SECRET"
        for v in window._sftp_sessions.values()
    )
    # On disk: nowhere. Sweep every stored value.
    qs = QSettings(ORG, APP)
    stored = {str(v) for v in qs.allKeys()} | {
        str(qs.value(k)) for k in qs.allKeys()
    }
    blob = " ".join(stored)
    assert "hunter2-SECRET" not in blob
    assert "password" not in blob.lower() or "hunter2" not in blob
    window.close()


def test_status_payload_splits_local_from_uploaded(qapp):
    """Preview/status must use the LOCAL path from 'ok: <local> → uploaded …'."""
    import app.window as wmod

    window = wmod.MainWindow()
    seen = {}

    def fake_set(which, path):
        seen[which] = path

    window._set_preview = fake_set
    window._on_file_done(
        "/x/in.png", "ok: /local/out.png → uploaded sftp://a@h/out/in.png"
    )
    assert seen["after"] == "/local/out.png"
    assert "uploaded sftp://a@h/out/in.png" in window.statusBar().currentMessage()
    window.close()
