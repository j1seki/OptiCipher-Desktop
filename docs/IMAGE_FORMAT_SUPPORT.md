# Google Photos image format compatibility

Google Photos documents these backup photo types: JPEG, HEIC, HEIF, PNG,
WebP, GIF, AVIF and most camera RAW files. The extension list is not a promise
that every camera RAW variant can be decoded; actual support depends on the
installed decoder and camera model.

## Platform coverage

| Format | Desktop | Web | Android |
|---|---|---|---|
| JPEG | Pillow | Browser native decoder | Android ImageDecoder / BitmapFactory |
| HEIC / HEIF | optional Pillow-HEIF | bundled icodec WebAssembly | Android ImageDecoder (Android 9+) |
| PNG | Pillow | exact OptiCipher PNG decoder; native fallback for valid source PNG variants | exact OptiCipher PNG decoder; native fallback for valid source PNG variants |
| WebP | Pillow | Browser native decoder | Android ImageDecoder / BitmapFactory |
| GIF | Pillow (first frame) | Browser native decoder (first frame) | Android ImageDecoder (first frame) |
| AVIF | optional Pillow-AVIF | bundled icodec WebAssembly | Android ImageDecoder (Android 12+) |
| Camera RAW | optional rawpy / LibRaw | bundled FlashRaw WebAssembly | embedded LibRaw via AndroidLibRaw |

The desktop picker and folder scanner include common raster and RAW extensions.
The Web and Android importers include the Google Photos backup extensions and
common camera RAW extensions. Unsupported RAW variants produce per-file
errors rather than being accepted based only on their filename.

## Desktop installation

Install the desktop extras with:

```bash
pip install -e ".[app]"
```

The `formats` extra is also available for library/CLI users:

```bash
pip install -e ".[formats]"
```

## Web build

```bash
cd web
npm install
npm test
npm run build
```

The HEIC/HEIF, AVIF and RAW WebAssembly decoders are bundled with the static
site. Image bytes are processed locally in the browser; they are not uploaded.

## Android build

```bash
cd android
./gradlew testDebugUnitTest
./gradlew assembleDebug
```

Android RAW decoding uses LibRaw. HEIC/HEIF decoding requires Android 9 or
newer; AVIF decoding requires Android 12 or newer. Older Android releases
cannot decode these formats through the platform decoder.

## Pixel and output guarantees

OptiCipher decodes source files to RGB/RGBA pixels. Encryption output and
restored output remain lossless PNG; the original container bytes, metadata,
and original RAW sensor data are not preserved. This is image-pixel encryption,
not byte-for-byte archival. Android bitmap decoding may premultiply
semi-transparent pixels; the exact PNG codec is retained for OptiCipher
ciphertext.

RAW support is best-effort. Google Photos itself says “most RAW files”; no
extension allowlist or third-party decoder can promise every camera model.
