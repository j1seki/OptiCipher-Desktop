"""
accel/backend.py
================

The compute-backend interface, the global configuration, and device selection.

DESIGN
------
A backend is an object that can perform the three heavy pixel operations:

    scramble(pixels, seed)          spatial permutation (keyed)
    diffuse(pixels, key, salt)      ChaCha20 value diffusion
    undiffuse(pixels, key, salt)    identical to diffuse (XOR is its inverse)
    unscramble(pixels, seed)        inverse permutation

...and, once the GPU path lands, the research metrics. Everything else (key
derivation, HMAC, header embedding) stays on the CPU in the upstream modules:
it is already C-fast (OpenSSL) and is not where the throughput goes.

The backend does NOT change the algorithm. It changes only HOW the same
algorithm's arithmetic is executed (one core, many cores, or a GPU compute
queue). Byte-parity with the reference implementation is a hard requirement,
enforced by tests.

SELECTION
---------
Users pick a device preference — "auto", "gpu", or "cpu" — and the resolver
picks a concrete backend. "auto" prefers the GPU when one is usable and falls
back to the CPU transparently (headless Linux boxes, missing Vulkan runtimes,
or remote sessions without a GPU must still work). A requested "gpu" that is
unavailable also falls back, recording the reason so the GUI can tell the user
what happened instead of failing their job.

THREAD SAFETY
-------------
`configure()` swaps the global configuration atomically under a lock;
`get_backend()` is safe to call from worker threads. Backends themselves hold
no mutable per-call state.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, replace
from typing import Dict, List, Optional

import numpy as np


# ---------------------------------------------------------------------------
# Backend interface.
# ---------------------------------------------------------------------------
class AccelerationBackend:
    """
    Base class for compute backends.

    Subclasses implement the pixel operations with the SAME semantics as the
    upstream reference functions in `scramble.py` / `diffusion.py`, just faster.
    """

    #: Short identifier shown in the UI, e.g. "cpu" or "gpu".
    name: str = "base"

    def scramble(self, pixels: np.ndarray, seed: int) -> np.ndarray:
        """Forward pixel permutation; must match `scramble.scramble_pixels`."""
        raise NotImplementedError

    def unscramble(self, pixels: np.ndarray, seed: int) -> np.ndarray:
        """Inverse pixel permutation; must match `scramble.unscramble_pixels`."""
        raise NotImplementedError

    def diffuse(self, pixels: np.ndarray, stream_key: bytes, salt: bytes) -> np.ndarray:
        """ChaCha20 XOR over every byte; must match `diffusion.diffuse`."""
        raise NotImplementedError

    def undiffuse(self, pixels: np.ndarray, stream_key: bytes, salt: bytes) -> np.ndarray:
        """Identical to `diffuse` (XOR is its own inverse)."""
        return self.diffuse(pixels, stream_key, salt)

    def info(self) -> Dict[str, object]:
        """
        Human-readable description of this backend for the settings/device
        panel: which hardware it uses, how many threads, and any fallback
        reason. Plain data so the GUI can render it without importing backend
        internals.
        """
        return {"name": self.name}


# ---------------------------------------------------------------------------
# Global configuration.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class AccelConfig:
    """
    The user's hardware settings.

    Attributes
    ----------
    device:
        Preference: "auto" (pick the best available), "gpu", or "cpu".
    threads:
        CPU worker threads for the CPU backend. None means "use the machine's
        CPU count".
    ram_budget_mb:
        Soft cap on working memory for pixel processing. Bands/tiles are sized
        so concurrent workers stay within roughly this budget, which keeps
        huge images from ballooning RAM. None means "use a sane default".
    """

    device: str = "auto"
    threads: Optional[int] = None
    ram_budget_mb: Optional[int] = None

    def resolved_threads(self) -> int:
        """Effective thread count: user choice, else machine CPU count."""
        if self.threads is not None and self.threads >= 1:
            return int(self.threads)
        return max(1, os.cpu_count() or 1)

    def resolved_ram_bytes(self) -> int:
        """Effective RAM budget in bytes for band sizing."""
        mb = self.ram_budget_mb if self.ram_budget_mb is not None else 512
        return max(1, int(mb)) * 1024 * 1024


_LOCK = threading.Lock()
_CONFIG = AccelConfig()
_BACKEND_CACHE: Optional[AccelerationBackend] = None

# Calibration payload for "auto" device selection: one deterministic random
# block per process, timed once on each backend (see `_calibrate_auto`).
_CAL_PAYLOAD: Optional[np.ndarray] = None
_CAL_RESULT: Optional[str] = None
_CAL_NOTE: str = ""


def configure(
    device: Optional[str] = None,
    threads: Optional[int] = None,
    ram_budget_mb: Optional[int] = None,
) -> None:
    """
    Update the global hardware settings and invalidate the cached backend.

    Any parameter left as None keeps its current value. Changing settings
    simply drops the cached backend; the next `get_backend()` re-resolves.
    """
    global _CONFIG, _BACKEND_CACHE
    with _LOCK:
        updates: Dict[str, object] = {}
        if device is not None:
            if device not in ("auto", "gpu", "cpu"):
                raise ValueError("device must be one of: auto, gpu, cpu")
            updates["device"] = device
        if threads is not None:
            if threads < 1:
                raise ValueError("threads must be >= 1")
            updates["threads"] = threads
        if ram_budget_mb is not None:
            if ram_budget_mb < 16:
                raise ValueError("ram_budget_mb must be >= 16")
            updates["ram_budget_mb"] = ram_budget_mb
        _CONFIG = replace(_CONFIG, **updates)
        _BACKEND_CACHE = None


def shutdown() -> None:
    """
    Release the cached backend's resources now, in a controlled order.

    Apps should call this before interpreter finalization (the GUI does, in
    `app.main`): the GPU backend holds WebGPU buffers/device whose cyclic-GC
    destruction order is *undefined* during `Py_Finalize`, and it can race
    with Qt's own finalization teardown. That race showed up as sporadic
    heap corruption at process exit (`corrupted double-linked list`,
    `malloc_consolidate(): unaligned fastbin chunk detected`), taking the
    app down after the work was already done.

    Dropping everything here — while Qt and the wgpu runtime are both fully
    alive — makes the order deterministic: GPU buffers, then pipelines, then
    device, then nothing left for finalization to race over. Safe to call
    more than once; a later `get_backend()` simply re-resolves.
    """
    global _BACKEND_CACHE, _CAL_PAYLOAD, _CAL_RESULT, _CAL_NOTE
    with _LOCK:
        backend = _BACKEND_CACHE
        _BACKEND_CACHE = None
        _CAL_PAYLOAD = None
        _CAL_RESULT = None
        _CAL_NOTE = ""
    if backend is not None:
        close = getattr(backend, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # closing must never raise at exit
                pass
    # Break any remaining reference cycles (e.g. device -> error-callback
    # closure -> backend) so the dropped objects are freed right now.
    import gc

    gc.collect()


def get_config() -> Dict[str, object]:
    """
    Snapshot of the current settings for the GUI device panel.

    Includes the resolved thread count and RAM budget so the UI can show what
    will actually be used, not just the raw preference.
    """
    with _LOCK:
        cfg = _CONFIG
    return {
        "device": cfg.device,
        "threads": cfg.threads,
        "resolved_threads": cfg.resolved_threads(),
        "ram_budget_mb": cfg.ram_budget_mb,
        "resolved_ram_mb": cfg.resolved_ram_bytes() // (1024 * 1024),
    }


# ---------------------------------------------------------------------------
# Backend resolution.
# ---------------------------------------------------------------------------
def _try_gpu_backend() -> Optional[AccelerationBackend]:
    """
    Attempt to construct the GPU backend, or return None.

    Kept as a lazy import so machines without `wgpu` installed (or with no
    usable adapter) never pay for it and never crash: GPU acceleration is an
    enhancement, never a requirement.
    """
    try:
        from .gpu import GpuBackend  # local import on purpose

        backend = GpuBackend()
        if backend.usable:
            return backend
    except Exception:
        # Any import failure, driver problem, or missing adapter means "no GPU
        # here" — that is a normal configuration, not an error.
        pass
    return None


def _calibrate_auto(cpu: AccelerationBackend, gpu: AccelerationBackend) -> AccelerationBackend:
    """
    Pick the faster of CPU/GPU for diffusion with a one-time micro-benchmark.

    Transfer/sync overhead makes the GPU win on some machines (weak CPUs,
    large images) and lose on others (strong multi-core CPUs where OpenSSL's
    vectorised ChaCha20 is memory-bandwidth-bound already). Rather than
    guessing, time a fixed 16 MB payload on both backends once per process
    (a few tens of milliseconds) and let the data decide. The winner and the
    measured times are recorded on `calibration_note` for the device panel.
    """
    global _CAL_PAYLOAD, _CAL_RESULT, _CAL_NOTE
    import time

    with _LOCK:
        payload = _CAL_PAYLOAD
        cached = _CAL_RESULT
        note = _CAL_NOTE
    if payload is None:
        rng = np.random.default_rng(0xC0FFEE)
        payload = rng.integers(0, 256, (2048, 2560, 3), dtype=np.uint8)
        with _LOCK:
            _CAL_PAYLOAD = payload
    if cached is not None:
        chosen = cpu if cached == "cpu" else gpu
        chosen.calibration_note = note  # type: ignore[attr-defined]
        return chosen

    key = b"\x42" * 32
    salt = b"\x24" * 16
    try:
        t0 = time.perf_counter()
        cpu.diffuse(payload, key, salt)
        t_cpu = time.perf_counter() - t0

        gpu.diffuse(payload, key, salt)  # warmup (pipeline/buffers)
        t0 = time.perf_counter()
        gpu.diffuse(payload, key, salt)
        t_gpu = time.perf_counter() - t0

        winner = "cpu" if t_cpu <= t_gpu else "gpu"
        note = f"auto-calibrated: cpu {t_cpu*1000:.1f} ms vs gpu {t_gpu*1000:.1f} ms @ 16 MB"
    except Exception as exc:  # calibration failure must never break selection
        winner = "cpu"
        note = f"auto-calibration fell back to cpu ({exc})"

    with _LOCK:
        _CAL_RESULT = winner
        _CAL_NOTE = note
    chosen = cpu if winner == "cpu" else gpu
    chosen.calibration_note = note  # type: ignore[attr-defined]
    return chosen


def get_backend() -> AccelerationBackend:
    """
    Resolve (and cache) the backend for the current configuration.

    Selection rules:
      * "cpu"  -> always the threaded CPU backend.
      * "gpu"  -> the WebGPU backend when a usable adapter exists, else fall
                  back to CPU (the fallback reason is available via the
                  backend's info so the UI can explain it).
      * "auto" -> GPU if present, else CPU.
    """
    global _BACKEND_CACHE
    with _LOCK:
        cached = _BACKEND_CACHE
        cfg = _CONFIG
    if cached is not None:
        return cached

    from .cpu import CpuBackend

    def _make_cpu() -> CpuBackend:
        return CpuBackend(
            threads=cfg.resolved_threads(), ram_budget_bytes=cfg.resolved_ram_bytes()
        )

    backend: AccelerationBackend
    if cfg.device == "cpu":
        backend = _make_cpu()
    elif cfg.device == "gpu":
        gpu = _try_gpu_backend()
        if gpu is not None:
            backend = gpu
        else:
            cpu = _make_cpu()
            # Remember why we fell back so the settings dialog can say
            # "GPU requested but no usable adapter found — used CPU".
            cpu.fallback_reason = "no usable GPU adapter (wgpu unavailable or no device)"
            backend = cpu
    else:  # "auto": let a one-time micro-benchmark decide CPU vs GPU
        gpu = _try_gpu_backend()
        if gpu is not None:
            backend = _calibrate_auto(_make_cpu(), gpu)
        else:
            backend = _make_cpu()

    with _LOCK:
        # Another thread may have raced us; either cached instance is fine
        # because backends are stateless per call.
        if _BACKEND_CACHE is None:
            _BACKEND_CACHE = backend
        return _BACKEND_CACHE


def list_backends() -> List[Dict[str, object]]:
    """
    Enumerate every backend this build could use, for the settings dialog.

    The GPU row reports availability (and why not, when it is missing) so the
    UI can grey it out with an explanation instead of silently failing later.
    """
    from .cpu import CpuBackend

    rows: List[Dict[str, object]] = [
        CpuBackend(threads=AccelConfig().resolved_threads(), ram_budget_bytes=AccelConfig().resolved_ram_bytes()).info()
    ]
    gpu = _try_gpu_backend()
    if gpu is not None:
        rows.insert(0, gpu.info())
    else:
        rows.insert(0, {"name": "gpu", "available": False, "detail": "no usable WebGPU adapter"})
    return rows
