import { heic, avif } from 'icodec';
import { FlashRaw, init as initFlashRaw } from 'flashraw';
import heicWasmUrl from 'icodec/heic-dec.wasm';
import avifWasmUrl from 'icodec/avif-dec.wasm';
import flashRawWasmUrl from 'flashraw/wasm/simd';
import { decodePNG } from './png.js';

export const GOOGLE_PHOTOS_EXTENSIONS = Object.freeze([
  '.jpg', '.jpeg', '.heic', '.heif', '.png', '.webp', '.gif', '.avif',
  '.dng', '.cr2', '.cr3', '.crw', '.nef', '.nrw', '.arw', '.sr2', '.srf',
  '.raf', '.rw2', '.rwl', '.orf', '.ori', '.pef', '.srw', '.mrw', '.iiq',
  '.mos', '.3fr', '.fff', '.kdc', '.dcr', '.dcs', '.erf', '.mef', '.x3f',
  '.ari'
]);

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
  const codec = isAvif ? avif : heic;
  const ready = isAvif ? (avifReady ??= codec.loadDecoder(avifWasmUrl))
    : (heicReady ??= codec.loadDecoder(heicWasmUrl));
  await ready;
  const decoded = codec.decode(new Uint8Array(await file.arrayBuffer()));
  return toImage(new Uint8Array(decoded.data.buffer, decoded.data.byteOffset, decoded.data.byteLength),
    decoded.width, decoded.height, file.name);
}

async function decodeRaw(file) {
  rawReady ??= initFlashRaw({ wasm: fetch(flashRawWasmUrl), threads: false });
  await rawReady;
  const raw = await FlashRaw.open(file);
  try {
    const frame = await raw.decode({ output: 'rgba8' });
    return toImage(frame.data, frame.width, frame.height, file.name);
  } finally { raw.close(); }
}

export async function loadImage(file) {
  const ext = (file.name.match(/\.[^.]+$/)?.[0] || '').toLowerCase();
  const bytes = new Uint8Array(await file.arrayBuffer());
  if (ext === '.png' || file.type === 'image/png') {
    try { return { ...decodePNG(bytes), name: file.name }; }
    catch (error) { throw new Error(`PNG could not be decoded losslessly: ${error.message}`); }
  }
  if (ext === '.heic' || ext === '.heif') return decodeHeif(file, false);
  if (ext === '.avif') return decodeHeif(file, true);
  if (RAW_EXTENSIONS.has(ext)) return decodeRaw(file);
  try { return await decodeNative(file); }
  catch (error) { throw new Error(`No decoder could read ${ext || 'this image'} in this browser: ${error.message}`); }
}
