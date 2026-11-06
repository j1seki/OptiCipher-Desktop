// Lossless PNG codec (8-bit, non-interlaced) — pixel-exact, unlike <canvas>
// which premultiplies alpha and would corrupt RGBA ciphertexts.
// Uses pako (zlib) for inflate/deflate. Decode supports colour types
// 0 (grey), 2 (RGB), 3 (palette), 4 (grey+alpha), 6 (RGBA); greyscale and
// palette are expanded to RGB like Pillow's convert("RGB") in io_image.py.

import { deflate as deflateSync, inflate as inflateSync } from 'pako';

const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; }
  return t;
})();
function crc32(buf) {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function chunk(type, data) {
  const out = new Uint8Array(12 + data.length);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, data.length);
  for (let i = 0; i < 4; i++) out[4 + i] = type.charCodeAt(i);
  out.set(data, 8);
  dv.setUint32(8 + data.length, crc32(out.slice(4, 8 + data.length)));
  return out;
}
const PNG_SIG = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10]);

export function encodePNG(pixels, width, height, channels) {
  const colorType = channels === 4 ? 6 : 2;
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, width); dv.setUint32(4, height);
  ihdr[8] = 8; ihdr[9] = colorType; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const stride = width * channels;
  const raw = new Uint8Array((stride + 1) * height);
  for (let y = 0; y < height; y++) {
    raw[y * (stride + 1)] = 0;
    raw.set(pixels.slice(y * stride, (y + 1) * stride), y * (stride + 1) + 1);
  }
  const idat = deflateSync(raw, { level: 6 });
  const parts = [PNG_SIG, chunk('IHDR', ihdr), chunk('IDAT', idat), chunk('IEND', new Uint8Array(0))];
  const total = parts.reduce((a, p) => a + p.length, 0);
  const out = new Uint8Array(total);
  let off = 0; for (const p of parts) { out.set(p, off); off += p.length; }
  return out;
}

function paeth(a, b, c) {
  const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  if (pa <= pb && pa <= pc) return a; if (pb <= pc) return b; return c;
}

export function decodePNG(bytes) {
  if (bytes.length < 8 || bytes.slice(0, 8).some((b, i) => b !== PNG_SIG[i]))
    throw new Error('not a PNG file');
  let off = 8, width = 0, height = 0, bitDepth = 0, colorType = 0, interlace = 0;
  let plte = null; const idatParts = [];
  while (off + 8 <= bytes.length) {
    const dv = new DataView(bytes.buffer, bytes.byteOffset + off, 8);
    const len = dv.getUint32(0);
    const type = String.fromCharCode(bytes[off + 4], bytes[off + 5], bytes[off + 6], bytes[off + 7]);
    const data = bytes.slice(off + 8, off + 8 + len);
    if (type === 'IHDR') {
      const d = new DataView(data.buffer, data.byteOffset, 13);
      width = d.getUint32(0); height = d.getUint32(4);
      bitDepth = data[8]; colorType = data[9]; interlace = data[12];
    } else if (type === 'PLTE') plte = data;
    else if (type === 'IDAT') idatParts.push(data);
    else if (type === 'IEND') break;
    off += 12 + len;
  }
  if (bitDepth !== 8) throw new Error(`unsupported PNG bit depth ${bitDepth} (only 8-bit is pixel-exact here)`);
  if (interlace !== 0) throw new Error('interlaced PNG not supported by the exact decoder — open it via the canvas fallback');
  const srcChannels = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 }[colorType];
  if (!srcChannels) throw new Error(`unsupported PNG colour type ${colorType}`);
  const total = idatParts.reduce((a, p) => a + p.length, 0);
  const z = new Uint8Array(total); let zo = 0; for (const p of idatParts) { z.set(p, zo); zo += p.length; }
  const raw = inflateSync(z);
  const stride = width * srcChannels;
  if (raw.length < (stride + 1) * height) throw new Error('truncated PNG data');
  // Unfilter into `unfiltered` (srcChannels per pixel).
  const unfiltered = new Uint8Array(stride * height);
  let pos = 0;
  for (let y = 0; y < height; y++) {
    const filter = raw[pos++];
    const rowStart = pos;
    for (let x = 0; x < stride; x++) {
      const left = x >= srcChannels ? unfiltered[y * stride + x - srcChannels] : 0;
      const up = y > 0 ? unfiltered[(y - 1) * stride + x] : 0;
      const upLeft = y > 0 && x >= srcChannels ? unfiltered[(y - 1) * stride + x - srcChannels] : 0;
      let v = raw[rowStart + x];
      if (filter === 1) v = (v + left) & 0xff;
      else if (filter === 2) v = (v + up) & 0xff;
      else if (filter === 3) v = (v + ((left + up) >> 1)) & 0xff;
      else if (filter === 4) v = (v + paeth(left, up, upLeft)) & 0xff;
      else if (filter !== 0) throw new Error(`unknown PNG filter ${filter}`);
      unfiltered[y * stride + x] = v;
    }
    pos += stride;
  }
  // Expand to RGB/RGBA like Pillow: grey/palette -> RGB (alpha dropped for LA).
  let channels, pixels;
  if (colorType === 2 || colorType === 6) { channels = srcChannels; pixels = unfiltered; }
  else {
    channels = 3; pixels = new Uint8Array(width * height * 3);
    for (let i = 0; i < width * height; i++) {
      let r, g, b;
      if (colorType === 0 || colorType === 4) { r = g = b = unfiltered[i * srcChannels]; }
      else { const idx = unfiltered[i] * 3; r = plte[idx]; g = plte[idx + 1]; b = plte[idx + 2]; }
      pixels[i * 3] = r; pixels[i * 3 + 1] = g; pixels[i * 3 + 2] = b;
    }
  }
  return { pixels, width, height, channels };
}
