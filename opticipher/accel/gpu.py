"""
accel/gpu.py
============

The WebGPU backend: ChaCha20 diffusion and the full-image metrics (histogram,
NPCR, UACI) on the GPU, via `wgpu` (wgpu-native).

WHY WEBGPU
----------
One compute-shader codebase reaches every target OS's native GPU API:
Metal on macOS (including Apple Silicon), Vulkan on Linux, and DX12 or
Vulkan on Windows — no CUDA toolkit, no vendor lock-in. `wgpu` ships
prebuilt native binaries in its wheels, so end users install nothing extra.

BIT-EXACTNESS
-------------
The ChaCha20 kernel implements the RFC 8439 block function and reproduces
`cryptography`'s convention exactly: the 16-byte nonce's first 4 bytes are the
little-endian initial block counter, the remaining 12 are the nonce proper.
Full 64-byte blocks run on the GPU; the (always < 64 byte) tail runs through
the reference CPU cipher at the correct block offset. `tests/test_gpu_accel.py`
pins the GPU keystream against the CPU reference byte-for-byte, so any drift
fails CI.

The pixel permutation stays on the CPU even in this backend: it is driven by
NumPy's PCG64 stream, which the GPU cannot cheaply reproduce, and it is not
the bottleneck (the reference shuffle is already a fast C loop). Reusing the
CPU permutation guarantees identical bytes for free.

METRICS
-------
Histogram, NPCR and UACI are full-image reductions — exact integer
arithmetic — so they map perfectly onto GPU partial reductions with a CPU
finalize, and the results are exactly equal to the reference implementation.
Adjacent-pixel *correlation* is deliberately left on the CPU: the reference
already subsamples a fixed number of random pairs (cheap on any machine), so
a GPU version would add transfer cost for no win. That is an informed choice,
not an omission.

Small inputs (< _GPU_MIN_BYTES) skip the GPU in `diffuse()` because PCIe
upload/readback would cost more than the work itself; the golden-vector tests
call the low-level path directly so the kernel is verified at every size.
"""

from __future__ import annotations

from typing import Dict, Optional

import numpy as np

from .backend import AccelerationBackend
from .cpu import _derive_nonce, _permute

_BLOCK: int = 64
#: Below this payload size the CPU path wins; GPU transfer overhead dominates.
_GPU_MIN_BYTES: int = 256 * 1024
#: Cap on dispatched workgroups (each with 64 threads); the kernel strides
#: internally so fewer workgroups still cover the whole payload.
_MAX_WORKGROUPS: int = 1024


# ---------------------------------------------------------------------------
# WGSL shaders (inline so they bundle into PyInstaller builds without
# resource-file plumbing).
# ---------------------------------------------------------------------------
_CHACHA_WGSL = """
// ChaCha20 XOR kernel: one invocation per 64-byte block, strided over the
// payload. Reproduces the reference keystream bit-for-bit.
//
// params layout (array<u32>):
//   [0..8)   key words (little-endian)
//   [8..11)  nonce words (12 bytes proper)
//   [11]     initial block counter
//   [12]     total number of full 64-byte blocks
@group(0) @binding(0) var<storage, read> params: array<u32>;
@group(0) @binding(1) var<storage, read> data_in: array<u32>;
@group(0) @binding(2) var<storage, read_write> data_out: array<u32>;

fn rotl(x: u32, y: u32) -> u32 {
    return (x << y) | (x >> (32u - y));
}

fn qr(s: ptr<function, array<u32, 16>>, a: u32, b: u32, c: u32, d: u32) {
    (*s)[a] = (*s)[a] + (*s)[b]; (*s)[d] = rotl((*s)[d] ^ (*s)[a], 16u);
    (*s)[c] = (*s)[c] + (*s)[d]; (*s)[b] = rotl((*s)[b] ^ (*s)[c], 12u);
    (*s)[a] = (*s)[a] + (*s)[b]; (*s)[d] = rotl((*s)[d] ^ (*s)[a], 8u);
    (*s)[c] = (*s)[c] + (*s)[d]; (*s)[b] = rotl((*s)[b] ^ (*s)[c], 7u);
}

@compute @workgroup_size(64)
fn main(@builtin(global_invocation_id) gid: vec3<u32>,
        @builtin(num_workgroups) nwg: vec3<u32>) {
    let total: u32 = params[12];
    let stride: u32 = nwg.x * 64u;
    var block: u32 = gid.x;
    while (block < total) {
        var s: array<u32, 16>;
        s[0] = 0x61707865u; s[1] = 0x3320646eu; s[2] = 0x79622d32u; s[3] = 0x6b206574u;
        for (var k: u32 = 0u; k < 8u; k = k + 1u) { s[4u + k] = params[k]; }
        s[12] = params[11] + block;
        s[13] = params[8]; s[14] = params[9]; s[15] = params[10];
        let init = s;
        for (var i: u32 = 0u; i < 10u; i = i + 1u) {
            qr(&s, 0u, 4u, 8u, 12u); qr(&s, 1u, 5u, 9u, 13u);
            qr(&s, 2u, 6u, 10u, 14u); qr(&s, 3u, 7u, 11u, 15u);
            qr(&s, 0u, 5u, 10u, 15u); qr(&s, 1u, 6u, 11u, 12u);
            qr(&s, 2u, 7u, 8u, 13u); qr(&s, 3u, 4u, 9u, 14u);
        }
        let base = block * 16u;
        for (var k2: u32 = 0u; k2 < 16u; k2 = k2 + 1u) {
            data_out[base + k2] = data_in[base + k2] ^ (s[k2] + init[k2]);
        }
        block = block + stride;
    }
}
"""

_HISTOGRAM_WGSL = """
// Per-channel byte histogram via atomic counters.
// info_buf: [0]=total bytes, [1]=channels. hist: 256*4 atomic u32 (C rows used).
@group(0) @binding(0) var<storage, read> data: array<u32>;
@group(0) @binding(1) var<storage, read> info_buf: array<u32>;
@group(0) @binding(2) var<storage, read_write> hist: array<atomic<u32>>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>,
        @builtin(num_workgroups) nwg: vec3<u32>) {
    let n: u32 = info_buf[0];
    let ch: u32 = info_buf[1];
    let stride: u32 = nwg.x * 256u;
    var i: u32 = gid.x;
    while (i < n) {
        let word = data[i >> 2u];
        let shift = (i & 3u) * 8u;
        let byte_val = (word >> shift) & 0xffu;
        let c = i % ch;
        atomicAdd(&hist[c * 256u + byte_val], 1u);
        i = i + stride;
    }
}
"""

_NPCR_UACI_WGSL = """
// Joint NPCR (differing-byte count) + UACI (sum of |a-b|) partial reduction.
// One vec2<u32> partial per workgroup; the CPU finalize sums them in u64.
// info_buf: [0]=total bytes. Inputs padded to u32 multiples; padded tail bytes
// are zero in both buffers so they never affect the counts.
@group(0) @binding(0) var<storage, read> a: array<u32>;
@group(0) @binding(1) var<storage, read> b: array<u32>;
@group(0) @binding(2) var<storage, read> info_buf: array<u32>;
@group(0) @binding(3) var<storage, read_write> partials: array<vec2<u32>>;

var<workgroup> wg_diff: atomic<u32>;
var<workgroup> wg_sum: atomic<u32>;

@compute @workgroup_size(256)
fn main(@builtin(global_invocation_id) gid: vec3<u32>,
        @builtin(local_invocation_index) lid: u32,
        @builtin(num_workgroups) nwg: vec3<u32>,
        @builtin(workgroup_id) wid: vec3<u32>) {
    if (lid == 0u) {
        atomicStore(&wg_diff, 0u);
        atomicStore(&wg_sum, 0u);
    }
    workgroupBarrier();
    let n: u32 = info_buf[0];
    let stride: u32 = nwg.x * 256u;
    var i: u32 = gid.x;
    while (i < n) {
        let wa = a[i >> 2u];
        let wb = b[i >> 2u];
        let sh = (i & 3u) * 8u;
        let ba = (wa >> sh) & 0xffu;
        let bb = (wb >> sh) & 0xffu;
        if (ba != bb) { atomicAdd(&wg_diff, 1u); }
        atomicAdd(&wg_sum, max(ba, bb) - min(ba, bb));
        i = i + stride;
    }
    workgroupBarrier();
    if (lid == 0u) {
        partials[wid.x] = vec2<u32>(atomicLoad(&wg_diff), atomicLoad(&wg_sum));
    }
}
"""


class GpuBackend(AccelerationBackend):
    """
    WebGPU implementation of the heavy pixel operations.

    Construction is cheap and side-effect free; the device is created lazily
    on first use so merely probing for a GPU (the settings dialog does) never
    pays driver startup cost. `usable` performs the real probe.
    """

    name = "gpu"

    def __init__(self) -> None:
        self._device = None
        self._adapter_info: Optional[Dict[str, object]] = None
        self._chacha_pipeline = None
        self._hist_pipeline = None
        self._npcr_uaci_pipeline = None
        self._init_error: Optional[str] = None
        # Reusable device buffers keyed by (kind, size): WebGPU buffer
        # creation is not free, and batch jobs repeatedly process similar
        # sizes. Entries are dropped on size mismatch (never resized in
        # place — allocation is cheap relative to a dispatch).
        self._buf_cache: Dict[tuple, object] = {}

    # -- device management --------------------------------------------------
    def _ensure_device(self) -> None:
        """Create the device and compile pipelines on first use."""
        if self._device is not None:
            return
        if self._init_error is not None:
            raise RuntimeError(self._init_error)
        try:
            import wgpu

            adapter = wgpu.gpu.request_adapter_sync(power_preference="high-performance")
            self._adapter_info = dict(adapter.info)
            device = adapter.request_device_sync()

            def _on_error(error):  # pragma: no cover - driver-dependent path
                # Record rather than crash: a mid-run driver hiccup must fall
                # back to CPU on the next call, not take the app down.
                self._init_error = f"GPU error: {error}"

            try:
                device.set_uncaptured_error_callback(_on_error)
            except Exception:
                pass

            def _pipe(code: str, entry: str):
                module = device.create_shader_module(code=code)
                return device.create_compute_pipeline(
                    layout="auto",
                    compute={"module": module, "entry_point": entry},
                )

            self._chacha_pipeline = _pipe(_CHACHA_WGSL, "main")
            self._hist_pipeline = _pipe(_HISTOGRAM_WGSL, "main")
            self._npcr_uaci_pipeline = _pipe(_NPCR_UACI_WGSL, "main")
            self._device = device
        except Exception as exc:  # no adapter, driver missing, shader rejected…
            self._init_error = f"GPU init failed: {exc}"
            raise RuntimeError(self._init_error) from exc

    @property
    def usable(self) -> bool:
        """True when a device can be created and pipelines compile."""
        try:
            self._ensure_device()
            return self._init_error is None
        except Exception:
            return False

    # -- helpers ------------------------------------------------------------
    def _get_buffer(self, key: tuple, size: int, usage) -> object:
        """Cached device buffer lookup; creates on miss (key includes size)."""
        import wgpu

        device = self._device
        cached = self._buf_cache.get(key)
        if cached is not None and cached.size == size:
            return cached
        buf = device.create_buffer(label=key[0], size=size, usage=usage)
        self._buf_cache[key] = buf
        return buf

    def _run(self, pipeline, workgroups: int, bind_entries) -> None:
        """Encode one compute pass and submit it (no explicit wait needed:
        mapping the later readback buffer waits for prior submissions)."""
        device = self._device
        layout = pipeline.get_bind_group_layout(0)
        bind_group = device.create_bind_group(
            layout=layout,
            entries=[{"binding": i, "resource": b} for i, b in enumerate(bind_entries)],
        )
        encoder = device.create_command_encoder()
        cpass = encoder.begin_compute_pass()
        cpass.set_pipeline(pipeline)
        cpass.set_bind_group(0, bind_group)
        cpass.dispatch_workgroups(workgroups)
        cpass.end()
        device.queue.submit([encoder.finish()])

    def _readback(self, device, buf, nbytes: int) -> bytes:
        buf.map_sync(_map_read())
        try:
            return bytes(buf.read_mapped()[:nbytes])
        finally:
            buf.unmap()

    # -- diffusion ----------------------------------------------------------
    def diffuse(self, pixels: np.ndarray, stream_key: bytes, salt: bytes) -> np.ndarray:
        """
        ChaCha20 XOR over every byte: full blocks on the GPU, tail on CPU.
        Byte-identical to the reference implementation.
        """
        original_shape = pixels.shape
        flat = np.ascontiguousarray(pixels).reshape(-1)
        data = memoryview(flat).cast("B")
        out = self.diffuse_bytes(data, stream_key, salt)
        return np.frombuffer(out, dtype=np.uint8).reshape(original_shape)

    def diffuse_bytes(self, data: memoryview, stream_key: bytes, salt: bytes) -> bytes:
        """
        Low-level entry used by tests at every size (including tiny payloads
        that `diffuse()` would route to the CPU for speed).
        """
        import wgpu
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        nonce = _derive_nonce(salt)
        n = len(data)
        n_blocks = n // _BLOCK
        tail_len = n - n_blocks * _BLOCK

        if n_blocks == 0:
            # Pure tail: single reference context, block-aligned start.
            enc = Cipher(
                algorithms.ChaCha20(stream_key, nonce), mode=None
            ).encryptor()
            return enc.update(data) + enc.finalize()

        self._ensure_device()
        device = self._device
        wgpu_buf = wgpu

        # Params: key words, nonce words, initial counter, block count.
        key_words = np.frombuffer(stream_key, dtype="<u4")
        nonce_words = np.frombuffer(nonce[4:], dtype="<u4")
        counter0 = int.from_bytes(nonce[:4], "little")
        params = np.zeros(16, dtype="<u4")
        params[0:8] = key_words
        params[8:11] = nonce_words
        params[11] = counter0
        params[12] = n_blocks

        # One pad copy into a word-aligned array; upload straight from it.
        padded_len = n_blocks * _BLOCK
        data_words = np.zeros(padded_len // 4, dtype="<u4")
        data_words.view(np.uint8)[:n_blocks * _BLOCK] = data[: padded_len]

        usage_st = wgpu_buf.BufferUsage.STORAGE | wgpu_buf.BufferUsage.COPY_DST
        usage_sr = wgpu_buf.BufferUsage.STORAGE | wgpu_buf.BufferUsage.COPY_SRC
        buf_params = self._get_buffer(("chacha_params", 64), 64, usage_st)
        buf_in = self._get_buffer(("chacha_in", padded_len), padded_len, usage_st)
        buf_out = self._get_buffer(("chacha_out", padded_len), padded_len, usage_sr)
        buf_read = self._get_buffer(
            ("chacha_read", padded_len),
            padded_len,
            wgpu_buf.BufferUsage.MAP_READ | wgpu_buf.BufferUsage.COPY_DST,
        )
        device.queue.write_buffer(buf_params, 0, params.tobytes())
        device.queue.write_buffer(buf_in, 0, data_words)

        workgroups = max(1, min(_MAX_WORKGROUPS, (n_blocks + 63) // 64))
        self._run(
            self._chacha_pipeline,
            workgroups,
            [buf_params, buf_in, buf_out],
        )

        encoder = device.create_command_encoder()
        encoder.copy_buffer_to_buffer(buf_out, 0, buf_read, 0, data_words.nbytes)
        device.queue.submit([encoder.finish()])
        block_bytes = self._readback(device, buf_read, padded_len)

        if tail_len:
            # XOR the tail with the keystream at the correct block offset.
            tail_nonce = (counter0 + n_blocks).to_bytes(4, "little") + nonce[4:]
            enc = Cipher(
                algorithms.ChaCha20(stream_key, tail_nonce), mode=None
            ).encryptor()
            tail_out = enc.update(data[padded_len:n]) + enc.finalize()
            return block_bytes + tail_out
        return block_bytes[:n]

    # -- permutation (CPU, bit-exact by construction) -----------------------
    def scramble(self, pixels: np.ndarray, seed: int) -> np.ndarray:
        return _permute(pixels, seed, inverse=False)

    def unscramble(self, pixels: np.ndarray, seed: int) -> np.ndarray:
        return _permute(pixels, seed, inverse=True)

    # -- metrics ------------------------------------------------------------
    def histograms(self, pixels: np.ndarray) -> np.ndarray:
        """
        Per-channel byte histogram on the GPU: returns (C, 256) uint64 counts,
        exactly equal to `np.bincount` per channel.
        """
        import wgpu

        self._ensure_device()
        device = self._device
        h, w = pixels.shape[:2]
        channels = pixels.shape[2] if pixels.ndim == 3 else 1
        flat = np.ascontiguousarray(pixels).reshape(-1)
        n = int(flat.size)

        padded = np.zeros(n + (-n % 4), dtype=np.uint8)
        padded[:n] = flat
        words = np.frombuffer(padded.tobytes(), dtype="<u4").copy()

        meta = np.array([n, channels], dtype="<u4")
        hist = np.zeros(256 * 4, dtype="<u4")  # 4 channel slots max

        usage_st = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST
        usage_sr = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC
        b_data = device.create_buffer(size=words.nbytes, usage=usage_st)
        b_meta = device.create_buffer(size=meta.nbytes, usage=usage_st)
        b_hist = device.create_buffer(size=hist.nbytes, usage=usage_sr)
        b_read = device.create_buffer(
            size=hist.nbytes,
            usage=wgpu.BufferUsage.MAP_READ | wgpu.BufferUsage.COPY_DST,
        )
        device.queue.write_buffer(b_data, 0, words.tobytes())
        device.queue.write_buffer(b_meta, 0, meta.tobytes())
        # (WebGPU guarantees newly created buffers are zero-initialized, so
        # the histogram buffer needs no explicit baseline write.)

        workgroups = max(1, min(_MAX_WORKGROUPS, (n + 255) // 256))
        self._run(self._hist_pipeline, workgroups, [b_data, b_meta, b_hist])

        encoder = device.create_command_encoder()
        encoder.copy_buffer_to_buffer(b_hist, 0, b_read, 0, hist.nbytes)
        device.queue.submit([encoder.finish()])
        counts = np.frombuffer(self._readback(device, b_read, hist.nbytes), dtype="<u4")
        return counts.reshape(4, 256)[:channels].astype(np.uint64)

    def npcr(self, cipher_a: np.ndarray, cipher_b: np.ndarray) -> float:
        """NPCR (%) — exact match to `metrics.npcr`."""
        diff, _ = self._npcr_uaci_partial(cipher_a, cipher_b)
        total = cipher_a.size
        return float(diff / total * 100.0)

    def uaci(self, cipher_a: np.ndarray, cipher_b: np.ndarray) -> float:
        """UACI (%) — exact match to `metrics.uaci`."""
        _, absum = self._npcr_uaci_partial(cipher_a, cipher_b)
        total = cipher_a.size
        return float((absum / total) / 255.0 * 100.0)

    def _npcr_uaci_partial(
        self, cipher_a: np.ndarray, cipher_b: np.ndarray
    ) -> "tuple[int, int]":
        """One GPU pass yielding (differing-byte count, sum |a-b|) in u64."""
        import wgpu

        if cipher_a.shape != cipher_b.shape:
            raise ValueError("images must have the same shape")
        self._ensure_device()
        device = self._device

        n = int(cipher_a.size)
        pa = np.zeros(n + (-n % 4), dtype=np.uint8)
        pb = np.zeros(n + (-n % 4), dtype=np.uint8)
        pa[:n] = cipher_a.reshape(-1)
        pb[:n] = cipher_b.reshape(-1)
        wa = np.frombuffer(pa.tobytes(), dtype="<u4").copy()
        wb = np.frombuffer(pb.tobytes(), dtype="<u4").copy()

        meta = np.array([n], dtype="<u4")
        workgroups = max(1, min(_MAX_WORKGROUPS, (n + 255) // 256))
        partials = np.zeros(workgroups * 2, dtype="<u4")

        usage_st = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_DST
        usage_sr = wgpu.BufferUsage.STORAGE | wgpu.BufferUsage.COPY_SRC
        b_a = device.create_buffer(size=wa.nbytes, usage=usage_st)
        b_b = device.create_buffer(size=wb.nbytes, usage=usage_st)
        b_meta = device.create_buffer(size=meta.nbytes, usage=usage_st)
        b_part = device.create_buffer(size=partials.nbytes, usage=usage_sr)
        b_read = device.create_buffer(
            size=partials.nbytes,
            usage=wgpu.BufferUsage.MAP_READ | wgpu.BufferUsage.COPY_DST,
        )
        device.queue.write_buffer(b_a, 0, wa.tobytes())
        device.queue.write_buffer(b_b, 0, wb.tobytes())
        device.queue.write_buffer(b_meta, 0, meta.tobytes())

        self._run(
            self._npcr_uaci_pipeline,
            workgroups,
            [b_a, b_b, b_meta, b_part],
        )
        encoder = device.create_command_encoder()
        encoder.copy_buffer_to_buffer(b_part, 0, b_read, 0, partials.nbytes)
        device.queue.submit([encoder.finish()])
        got = np.frombuffer(self._readback(device, b_read, partials.nbytes), dtype="<u4")
        pairs = got.reshape(workgroups, 2).astype(np.uint64)
        return int(pairs[:, 0].sum()), int(pairs[:, 1].sum())

    # -- introspection ------------------------------------------------------
    def info(self) -> Dict[str, object]:
        """Device-panel row: adapter name, API backend, vendor."""
        row: Dict[str, object] = {"name": self.name, "available": False}
        try:
            self._ensure_device()
            info = self._adapter_info or {}
            row["available"] = True
            row["adapter"] = info.get("device", "unknown GPU")
            row["vendor"] = info.get("vendor", "")
            row["backend_type"] = info.get("backend_type", "")
            row["detail"] = (
                f"{info.get('device', 'GPU')} via {info.get('backend_type', '?')}"
            )
            if getattr(self, "calibration_note", ""):
                row["calibration"] = self.calibration_note
        except Exception as exc:
            row["detail"] = str(exc)
        return row


def _map_read():
    """The wgpu MapMode.READ flag (kept in one place for version quirks)."""
    import wgpu

    return wgpu.MapMode.READ
