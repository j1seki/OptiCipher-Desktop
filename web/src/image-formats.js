import { heic, avif } from 'icodec';
import { FlashRaw, init as initFlashRaw, simdSupported } from 'flashraw';
import heicWasmUrl from 'icodec/heic-dec.wasm';
import avifWasmUrl from 'icodec/avif-dec.wasm';
import flashRawWasmUrl from 'flashraw/wasm/simd';
import flashRawFallbackWasmUrl from 'flashraw/wasm/fallback';
import { decodePNG } from './png.js';
import { GOOGLE_PHOTOS_EXTENSIONS } from './image-format-list.js';
export { GOOGLE_PHOTOS_EXTENSIONS } from './image-format-list.js';

const RAW_EXTENSIONS = new Set(GOOGLE_PHOTOS_EXTENSIONS.filter(ext =>
  !['.jpg', '.jpeg', '.heic', '.heif', '.png', '.webp', '.gif', '.avif'].includes(ext)
));
let heicReady;
let avifReady;
let rawReady;

function toImage(pixels, width, height, name) {
  const rgba = pixels instanceof Uint8Array ? pixels : new Uint8Array(pixels);
  if (rgba.length !== width * height * 4) throw new Error('decoder returned an unexpected pixel buffer');
  let opaque = true;
  for (let i = 3; i < rgba.length; i += 4) {
    if (rgba[i] !== 255) { opaque = false; break; }
  }
  if (!opaque) return { pixels: rgba, width, height, channels: 4, name };
  const rgb = new Uint8Array(width * height * 3);
  for (let i = 0, j = 0; i < rgba.length; i += 4, j += 3) {
    rgb[j] = rgba[i]; rgb[j + 1] = rgba[i + 1]; rgb[j + 2] = rgba[i + 2];
  }
  return { pixels: rgb, width, height, channels: 3, name };
}

async function decodeNative(file) {
  if (typeof createImageBitmap !== 'function') throw new Error('native image decoding is unavailable');
  const bmp = await createImageBitmap(file);
  try {
    const canvas = document.createElement('canvas');
    canvas.width = bmp.width; canvas.height = bmp.height;
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) throw new Error('could not create a pixel-reading canvas');
    ctx.drawImage(bmp, 0, 0);
    const data = ctx.getImageData(0, 0, bmp.width, bmp.height);
    return toImage(new Uint8Array(data.data.buffer, data.data.byteOffset, data.data.byteLength),
      bmp.width, bmp.height, file.name);
  } finally { bmp.close?.(); }
}

async function decodeHeif(file, isAvif) {
  if (!simdSupported()) return decodeNative(file);
  const codec = isAvif ? avif : heic;
  const ready = isAvif ? (avifReady ??= codec.loadDecoder(avifWasmUrl))
    : (heicReady ??= codec.loadDecoder(heicWasmUrl));
  await ready;
  const decoded = codec.decode(new Uint8Array(await file.arrayBuffer()));
  let pixels;
  const depth = decoded.depth ?? 8;
  if (depth > 8) {
    // icodec exposes high-depth RGBA as little-endian 16-bit channel bytes,
    // with the source bit depth on the ImageDataLike object.
    const words = new Uint16Array(decoded.data.buffer, decoded.data.byteOffset, decoded.data.byteLength / 2);
    const maximum = (2 ** depth) - 1;
    pixels = new Uint8Array(words.length);
    for (let i = 0; i < words.length; i++) pixels[i] = Math.round(words[i] * 255 / maximum);
  } else {
    pixels = new Uint8Array(decoded.data.buffer, decoded.data.byteOffset, decoded.data.byteLength);
  }
  return toImage(pixels, decoded.width, decoded.height, file.name);
}

async function decodeRaw(file) {
  rawReady ??= initFlashRaw({ wasm: fetch(simdSupported() ? flashRawWasmUrl : flashRawFallbackWasmUrl), threads: false });
  await rawReady;
  const raw = await FlashRaw.open(file);
  try {
    const frame = await raw.decode({ output: 'rgba8' });
    return toImage(frame.data, frame.width, frame.height, file.name);
  } finally { raw.close(); }
}

export async function loadImage(file) {
  const ext = (file.name.match(/\.[^.]+$/)?.[0] || '').toLowerCase();
  if (ext === '.png' || file.type === 'image/png') {
    const bytes = new Uint8Array(await file.arrayBuffer());
    try {
      return { ...decodePNG(bytes), name: file.name };
    } catch (error) {
      // Plain 16-bit/interlaced PNGs are valid sources outside the exact
      // ciphertext codec. Valid OptiCipher ciphertexts use the exact path.
      try { return await decodeNative(file); }
      catch { throw new Error(`PNG could not be decoded: ${error.message}`); }
    }
  }
  if (ext === '.heic' || ext === '.heif') return decodeHeif(file, false);
  if (ext === '.avif') return decodeHeif(file, true);
  if (RAW_EXTENSIONS.has(ext)) return decodeRaw(file);
  try { return await decodeNative(file); }
  catch (error) { throw new Error(`No decoder could read ${ext || 'this image'} in this browser: ${error.message}`); }
}
