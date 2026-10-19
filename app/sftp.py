"""
app.sftp
========

SFTP output locations for OptiCipher Desktop: an output field may contain

    sftp://user@host[:port][/remote/directory]

and every completed file is then UPLOADED as a verified copy to that remote
directory in addition to its normal local write.

DESIGN DECISIONS (data safety first, per the reliability audit):

  * **Mirror, never move.** The local output is written first (atomically,
    see opticipher.io_image.save_image) and is NEVER deleted after upload.
    A flaky network can therefore never cost the user their file; the SFTP
    copy is an extra. Status text distinguishes "saved" from "uploaded".
  * **Verify before claiming success.** The upload goes to a `.part` name
    and is only renamed into place after the remote size matches the local
    file byte-for-byte in length — so a truncated upload never occupies the
    real filename.
  * **No credentials in URLs, files, or logs.** The URL syntax refuses
    embedded passwords (`sftp://user:pass@host` is an error); passwords and
    key paths live only in memory for the session (MainWindow), never in
    QSettings, and never appear in error messages.
  * **paramiko is imported lazily**, so environments without it still start,
    run tests, and pass --smoke; uploads then fail with one clear message.

Unit tests inject a fake SSH client (`client_factory`) — no live server is
required to exercise every code path here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Optional
from urllib.parse import urlsplit

SCHEME = "sftp://"
DEFAULT_PORT = 22


class SftpError(RuntimeError):
    """Any SFTP configuration/connect/transfer failure (message is
    user-facing and must never contain credentials)."""


@dataclass(frozen=True)
class SftpTarget:
    """A parsed sftp:// output location."""

    host: str
    port: int
    user: str  # may be "" (SSH will use the local username)
    path: str  # remote directory, absolute, "/" for root

    def describe(self) -> str:
        user = f"{self.user}@" if self.user else ""
        port = f":{self.port}" if self.port != DEFAULT_PORT else ""
        return f"{user}{self.host}{port}{self.path}"

    def remote_file(self, filename: str) -> str:
        base = PurePosixPath(self.path)
        return str(base / filename)


def is_sftp_output(output_dir: str) -> bool:
    """True when the output field asks for an SFTP destination."""
    return output_dir.strip().lower().startswith(SCHEME)


def parse_sftp_url(url: str) -> SftpTarget:
    """
    Parse ``sftp://user@host[:port][/path]`` into an :class:`SftpTarget`.

    Raises :class:`ValueError` with an actionable message on anything
    malformed. Embedded credentials are refused outright so passwords never
    travel through text fields, history files, or settings.
    """
    raw = url.strip()
    if not raw.lower().startswith(SCHEME):
        raise ValueError(
            "An SFTP output must start with sftp:// "
            "(e.g. sftp://alice@server.example.com/backups)."
        )
    parts = urlsplit(raw)
    if parts.password is not None:
        raise ValueError(
            "Do not put a password in the URL — the sftp:// location takes "
            "only user@host. Enter the password in the connection dialog."
        )

    host = parts.hostname
    if not host:
        raise ValueError("The sftp:// location is missing a host name.")
    try:
        port = parts.port or DEFAULT_PORT
    except ValueError:
        raise ValueError(
            f"Invalid port in {raw!r} — use sftp://user@host:port/path."
        ) from None
    if not (1 <= port <= 65535):
        raise ValueError(f"Port {port} is out of range (1–65535).")
    user = parts.username or ""

    path = parts.path or "/"
    if not path.startswith("/"):
        path = "/" + path
    norm = str(PurePosixPath(path))  # collapses //, ., and trailing slashes
    if norm != "/" and norm.endswith("/."):  # pragma: no cover - PurePosixPath
        norm = norm[:-2]
    if any(ch in norm for ch in ("\n", "\r", "\x00")):
        raise ValueError("The remote path contains invalid characters.")
    return SftpTarget(host=host, port=port, user=user, path=norm or "/")


def _default_client():
    """Build the real paramiko SSH client (lazy import — see module doc)."""
    try:
        import paramiko
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise SftpError(
            "SFTP support needs the 'paramiko' package. Install it with "
            "'pip install paramiko' — official OptiCipher releases bundle it."
        ) from exc
    return paramiko.SSHClient()


class SftpUploader:
    """
    One connected upload session against a single :class:`SftpTarget`.

    ``client_factory`` exists purely for tests: it must return an object
    with paramiko's ``SSHClient`` interface (connect/open_sftp/close).
    """

    def __init__(
        self,
        target: SftpTarget,
        *,
        password: Optional[str] = None,
        key_file: Optional[str] = None,
        client_factory: Optional[Callable[[], object]] = None,
        timeout: float = 30.0,
    ) -> None:
        self.target = target
        self.password = password
        self.key_file = key_file or None
        self._client_factory = client_factory or _default_client
        self.timeout = timeout

    # -- internals ----------------------------------------------------------
    @staticmethod
    def _mkdirs(sftp, path: str) -> None:
        """Create the remote directory chain, ignoring existing ones.

        Best-effort: any failure here surfaces with the server's own message
        when the PUT runs immediately afterwards.
        """
        current = PurePosixPath("/")
        for part in PurePosixPath(path).parts[1:]:
            current = current / part
            try:
                sftp.mkdir(str(current))
            except Exception:  # noqa: BLE001 — exists / not permitted / etc.
                pass

    def _connect_client(self):
        client = self._client_factory()
        try:
            client.connect(
                self.target.host,
                port=self.target.port,
                username=self.target.user or None,
                password=self.password,
                key_filename=self.key_file,
                timeout=self.timeout,
                banner_timeout=self.timeout,
                auth_timeout=self.timeout,
                allow_agent=self.password is None and not self.key_file,
                look_for_keys=self.password is None and not self.key_file,
            )
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            raise SftpError(
                f"could not connect to {self.target.host}:{self.target.port} "
                f"as {self.target.user or '(current user)'}: {exc}"
            ) from exc
        return client

    # -- public -------------------------------------------------------------
    def upload(self, local_path: str | os.PathLike) -> str:
        """
        Upload `local_path` into the target directory and return the remote
        path it now occupies.

        Safety: writes to `<name>.part` first, verifies the remote size
        matches the local file, then renames into place. A failed or
        interrupted transfer therefore never occupies the real filename and
        never leaves a *believable* partial file.
        """
        local_path = str(local_path)
        local_size = os.path.getsize(local_path)
        filename = os.path.basename(local_path)
        remote = self.target.remote_file(filename)
        part = remote + ".part"

        client = self._connect_client()
        try:
            sftp = client.open_sftp()
        except Exception as exc:
            try:
                client.close()
            except Exception:
                pass
            raise SftpError(
                f"could not open an SFTP channel to {self.target.describe()}: {exc}"
            ) from exc
        try:
            self._mkdirs(sftp, self.target.path)
            sftp.put(local_path, part)
            remote_size = sftp.stat(part).st_size
            if remote_size != local_size:
                raise SftpError(
                    f"upload verification failed for {filename}: remote has "
                    f"{remote_size} bytes, local file has {local_size}"
                )
            # Publish: atomic-ish rename. posix_rename overwrites any previous
            # remote copy; the plain fallback removes the old one first.
            try:
                sftp.posix_rename(part, remote)
            except (OSError, IOError, AttributeError):
                try:
                    sftp.remove(remote)
                except OSError:
                    pass
                sftp.rename(part, remote)
        except SftpError:
            self._discard_part(sftp, part)
            raise
        except Exception as exc:
            self._discard_part(sftp, part)
            raise SftpError(
                f"upload of {filename} to {self.target.describe()} failed: {exc}"
            ) from exc
        finally:
            try:
                sftp.close()
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
        return remote

    @staticmethod
    def _discard_part(sftp, part: str) -> None:
        """Best-effort removal of an incomplete `.part` remote file."""
        try:
            sftp.remove(part)
        except Exception:  # noqa: BLE001 — remote may be gone or read-only
            pass


def upload_file(
    local_path: str | os.PathLike,
    target: SftpTarget,
    *,
    password: Optional[str] = None,
    key_file: Optional[str] = None,
    client_factory: Optional[Callable[[], object]] = None,
) -> str:
    """Convenience wrapper: one upload, connection closed afterwards."""
    return SftpUploader(
        target, password=password, key_file=key_file, client_factory=client_factory
    ).upload(local_path)
