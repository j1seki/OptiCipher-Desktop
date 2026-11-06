# Web & Android versions

Two additional editions of OptiCipher, both **100% client-side** and
**bit-for-bit compatible** with the desktop v1 format (a ciphertext produced
by any edition decrypts in all of them — proven by the golden-vector tests
on each side).

## Web (`web/`) — GitHub Pages

Yes, it hosts on GitHub Pages: the app is pure static HTML/CSS/JS, needs no
server, and nothing is uploaded — files are processed in the browser tab.

```bash
cd web
npm install
npm test        # parity: PCG64 vs NumPy, ChaCha20 RFC vector, round-trip, PNG
npm run build   # -> web/dist (deploy this folder)
```

Deploy: `.github/workflows/pages.yml` builds and publishes `web/dist` on every
push to `main` (Settings → Pages → GitHub Actions). HTTPS is provided by
Pages, which WebCrypto requires.

How parity is achieved:

| Python (`opticipher/`) | Web (`web/src/`) |
|---|---|
| `keys.py` PBKDF2-HMAC-SHA256 | WebCrypto `PBKDF2` |
| `core.py` HMAC-SHA256 | WebCrypto `HMAC` |
| `diffusion.py` ChaCha20 (`cryptography`) | `chacha20.js` — pure JS ChaCha20, 16-byte nonce (4-byte LE counter + 12-byte nonce) |
| `scramble.py` `numpy.default_rng(seed).permutation()` | `pcg64.js` — NumPy **SeedSequence + PCG64 XSL-RR** re-implemented exactly (incl. the two-step `srandom` seeding and uint32 mask-rejection Fisher–Yates), verified against NumPy |
| `io_image.py` Pillow PNG | `png.js` — lossless PNG codec (pako zlib). Deliberately **not** `<canvas>`, which premultiplies alpha and would corrupt RGBA ciphertexts |

Screens: Encrypt, Decrypt, Verify, Analyze (entropy / correlation / NPCR /
UACI / histogram). Non-PNG inputs (JPEG/WebP) fall back to canvas decoding;
PNGs always take the exact path. Large photos are slow in pure JS — a WASM
ChaCha20 is the natural next optimisation.

## Android (`android/`) — APK

Native Kotlin app (no WebView, so folder watching and background work are
real). Same crypto core, ported 1:1 and unit-tested against a desktop-produced
golden ciphertext.

```bash
cd android
./gradlew testDebugUnitTest   # parity vs desktop golden vector
./gradlew assembleDebug       # -> app/build/outputs/apk/debug/*.apk
```

`.github/workflows/android.yml` runs the tests and uploads the debug APK.

### Folder watching — what Android allows

Android's scoped storage (10+) has **no general "watch any folder"**. The app
uses the supported path:

1. **SAF tree picker** (`ACTION_OPEN_DOCUMENT_TREE`) — the user picks an
   *Inbox* folder; the app keeps a **persistable URI permission** (survives
   reboot, no broad storage permission needed — this is why `MANAGE_EXTERNAL_STORAGE`
   / all-files access is deliberately avoided: Play policy would reject it).
2. A **`ContentObserver`** on that tree queues new/changed files, plus a
   **WorkManager periodic poll (15 min)** as a fallback for OEM file managers
   that don't fire change events. Doze rules out a permanent foreground
   service, so WorkManager is the right primitive.
3. Each new PNG is checked for an existing **`OPTC` header** (by content, not
   filename) so already-encrypted files are never re-encrypted; the output
   folder is excluded to prevent loops.
4. Outputs go to the chosen *output tree* (or app storage), **never
   overwriting** (`_2`, `_3`…), matching desktop behaviour. Originals are
   copied by default; "move originals" is an opt-in toggle.

**Passphrase:** needed to process anything. Default is *in-memory only* —
the watcher then queues files and notifies "open the app to process". Enabling
**"Remember passphrase"** stores it in `EncryptedSharedPreferences` (AES-256)
so background processing works unattended. Nothing is ever sent anywhere.

**Permission flow** (asked lazily, in this order):

| When | What | Why |
|---|---|---|
| Picking folders | none (system picker grants it) | SAF tree + persistable URI |
| First media access | `READ_MEDIA_IMAGES` (13+) / `READ_EXTERNAL_STORAGE` (≤12) / partial `READ_MEDIA_VISUAL_USER_SELECTED` (14+) | camera-roll style sources |
| Background work | `POST_NOTIFICATIONS` (13+), battery-optimisation exemption prompt | completion notice; WorkManager not throttled |
| During a batch | `FOREGROUND_SERVICE_DATA_SYNC` (14+, declared in manifest) | long batches |

### Known limitations

- Semi-transparent RGBA via `BitmapFactory` is lossy (Android premultiplies
  alpha); opaque photos and all PNG ciphertexts (exact codec) are unaffected —
  the same caveat applies to the web canvas fallback.
- The pure-Kotlin PCG64 uses `BigInteger` for 128-bit state; fine for photos,
  worth optimising if batch-processing very large libraries.
- Same threat model as desktop: PBKDF2 is memory-cheap. Read the README
  before protecting anything sensitive.
