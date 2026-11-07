# Desktop image format support

The desktop edition accepts the following source extensions in its file picker,
folder import, and image loader:

| Format family | Extensions | Decoder |
|---|---|---|
| Common raster | PNG, JPEG, BMP, GIF, TIFF, WebP | Pillow (WebP/TIFF/GIF support depends on the Pillow build) |
| HEIF | HEIC, HEIF | optional `pillow-heif` plugin |
| AVIF | AVIF | optional `pillow-avif-plugin` |
| Camera RAW | DNG, CR2, CR3, NEF, ARW, ORF, RW2, RAF, PEF, SRW and other listed LibRaw extensions | optional `rawpy` / LibRaw; exact camera support depends on LibRaw |

Install the desktop extras with:

```bash
pip install -e ".[app]"
```

The `formats` extra is also available for library/CLI users:

```bash
pip install -e ".[formats]"
```

RAW support is necessarily best-effort: an extension allowlist cannot guarantee
that every camera model or RAW variant is supported by the installed LibRaw
version. A decoder error is reported for an unsupported file.

OptiCipher decodes source files to RGB/RGBA pixels. Encryption output and
restored output remain lossless PNG; the original container bytes and metadata
are not preserved. This is not byte-for-byte file archival.

This document describes the **desktop** decoder path only. Web browsers and
Android devices have different native decoder capabilities; support in this
desktop change must not be interpreted as universal Web/Android support.
