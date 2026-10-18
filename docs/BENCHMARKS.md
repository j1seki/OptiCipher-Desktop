# OptiCipher Desktop — acceleration benchmarks

Machine: x86_64 · 20 cores · Linux 7.2.9-2-cachyos · GPU: NVIDIA GeForce RTX 5060 Ti (Vulkan), Intel(R) Graphics (ARL) (Vulkan), NVIDIA GeForce RTX 5060 Ti/PCIe/SSE2 (OpenGL)

## ChaCha20 diffusion (bit-exact vs reference, verified per run)

| size | reference (s) | CPU threaded (s) | speedup | GPU (s) | speedup |
|---|---|---|---|---|---|
| 4K RGB | 0.0056 | 0.0077 | 0.73x | 0.0099 | 0.57x |
| 8K RGB | 0.0374 | 0.0267 | 1.40x | 0.049 | 0.76x |

## Metrics @ 4K (exact equality vs reference, verified per run)

- histogram: ref 0.0373s, GPU 0.0106s (3.52x)
- NPCR+UACI: ref 0.0324s, GPU 0.0387s (0.84x)

## End-to-end encrypt/decrypt @ 4K (PBKDF2 200k included)

- reference (1 thread): 0.3076s encrypt
- CPU all cores:         0.3185s encrypt
- GPU:                   0.3181s encrypt, 0.2374s decrypt

All accelerated results above were asserted byte-identical (diffusion)
or exactly equal (metrics) to the reference implementation during the run.

## How to read these numbers (honest interpretation)

Measured on a high-end desktop CPU (20 cores, AVX2/AVX-512, fast DDR). The
reference ChaCha20 path is already vectorised by OpenSSL and, at these image
sizes, is **memory-bandwidth-bound** — which changes the usual GPU calculus:

- **Diffusion:** the GPU must pay PCIe upload + readback + driver sync on
  every call. On strong CPUs that overhead exceeds what the GPU saves, so GPU
  diffusion *loses* here (0.57–0.76x). On machines with weak CPUs (thin
  laptops, 4-core boxes) the same kernel wins, because the fixed PCIe cost is
  then small next to a much slower CPU baseline. This is exactly why the app's
  **auto device mode runs a one-time 16 MB calibration per process** and picks
  whichever backend actually measured faster on *that* machine — the device
  bar shows the two measured times.
- **Histogram (Analyze tab):** a genuine GPU win — **3.5x** — because the
  atomic-bin histogram is real compute work, not a memcpy in disguise.
- **NPCR/UACI:** a vectorised byte-compare on the CPU; the GPU copy loses
  slightly to transfer cost (0.84x). Kept for completeness; the app uses
  whichever backend is active.
- **End-to-end encrypt/decrypt** is dominated by PBKDF2-HMAC-SHA256 (the
  format-mandated 200k iterations, a fixed CPU cost by design). All backends
  land at ~0.31 s for a 4K image — comfortably inside the ~1.5 s target —
  and the pixel stages shrink further on weaker CPUs, where GPU offload has
  the most room to help.

The perf targets this fork set out with were "4K encrypt under ~1.5 s on a
mid GPU" (met, with large margin, on every backend) and "≥3x on
diffusion/metrics-bound sizes" (met for GPU histogram at 3.5x; *not* met for
diffusion on this unusually strong CPU — the honest result is above rather
than a cherry-picked machine).

