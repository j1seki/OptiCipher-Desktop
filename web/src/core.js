// OptiCipher v1 core — WebCrypto + PCG64 + ChaCha20 port of opticipher/*.py.
// Byte-compatible with the desktop format (header 70 bytes, reserved strip,
// PBKDF2-HMAC-SHA256, HMAC-SHA256, ChaCha20, NumPy-PCG64 permutation).

import { chachaXor } from './chacha20.js';
import { permutation } from './pcg64.js';

export const MAGIC = new TextEncoder().encode('OPTC');
export const VERSION = 1;
export const HEADER_SIZE = 70;
export const PREHMAC_SIZE = 38;
export const SALT_LENGTH = 16;
export const DEFAULT_ITERATIONS = 200000;
export const MAX_UNVERIFIED_ITERATIONS = 10000000;

export class DecryptionError extends Error {}
export class MalformedCiphertextError extends DecryptionError {}

const subtle = () => {
  const c = globalThis.crypto;
  if (!c || !c.subtle) throw new Error('WebCrypto (crypto.subtle) is required — serve over HTTPS or localhost.');
  return c.subtle;
};

async function sha256(data) { return new Uint8Array(await subtle().digest('SHA-256', data)); }

async function pbkdf2(passphrase, salt, iterations) {
  const enc = new TextEncoder();
  const key = await subtle().importKey('raw', enc.encode(passphrase), 'PBKDF2', false, ['deriveBits']);
  const bits = await subtle().deriveBits({ name: 'PBKDF2', salt, iterations, hash: 'SHA-256' }, key, 64 * 8);
  return new Uint8Array(bits);
}

async function hmacSha256(key, parts) {
  const cryptoKey = await subtle().importKey('raw', key, { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const total = parts.reduce((a, p) => a + p.length, 0);
  const buf = new Uint8Array(total);
  let off = 0; for (const p of parts) { buf.set(p, off); off += p.length; }
  return new Uint8Array(await subtle().sign('HMAC', cryptoKey, buf));
}

function splitKeys(block) {
  const streamKey = block.slice(0, 32);
  const scrambleSeed = BigInt('0x' + [...block.slice(32, 48)].map(b => b.toString(16).padStart(2, '0')).join(''));
  const macKey = block.slice(48, 64);
  return { streamKey, scrambleSeed, macKey };
}

function deriveNonce(salt) { // sync SHA-256 needed by ChaCha nonce — done via async caller
  throw new Error('use deriveNonceAsync');
}
async function deriveNonceAsync(salt) {
  const d = await sha256(salt);
  return d.slice(0, 16);
}

// --- header -----------------------------------------------------------------
function packPrehmac(h) {
  const b = new Uint8Array(PREHMAC_SIZE);
  const dv = new DataView(b.buffer);
  b.set(MAGIC, 0); b[4] = h.version; b.set(h.salt, 5);
  dv.setUint32(21, h.iterations); dv.setUint32(25, h.height); dv.setUint32(29, h.width);
  b[33] = h.channels; dv.setUint32(34, h.stripRows);
  return b;
}
function packHeader(h) {
  const b = new Uint8Array(HEADER_SIZE);
  b.set(packPrehmac(h), 0); b.set(h.hmac, PREHMAC_SIZE);
  return b;
}
export function parseHeader(raw) {
  if (raw.length < HEADER_SIZE) throw new ValueError('header too short');
  const dv = new DataView(raw.buffer, raw.byteOffset, HEADER_SIZE);
  const magic = raw.slice(0, 4);
  if (magic[0] !== 0x4f || magic[1] !== 0x50 || magic[2] !== 0x54 || magic[3] !== 0x43)
    throw new ValueError('not an OptiCipher image (magic number mismatch). The file may be unencrypted, corrupted, or from another tool.');
  return {
    version: raw[4], salt: raw.slice(5, 21),
    iterations: dv.getUint32(21), height: dv.getUint32(25), width: dv.getUint32(29),
    channels: raw[33], stripRows: dv.getUint32(34), hmac: raw.slice(38, 70),
  };
}
class ValueError extends Error {}

// --- stego ------------------------------------------------------------------
export function rowsNeeded(headerLen, width, channels) {
  if (width <= 0 || channels <= 0) throw new Error('width and channels must be positive');
  const bpr = width * channels;
  return Math.ceil(headerLen / bpr);
}
function appendStrip(pixels, width, channels, headerBytes) {
  const nRows = rowsNeeded(headerBytes.length, width, channels);
  const out = new Uint8Array(pixels.length + nRows * width * channels);
  out.set(pixels, 0);
  out.set(headerBytes, pixels.length);
  return { data: out, stripRows: nRows };
}
function peekHeaderBytes(pixels, width, channels, height, headerLen) {
  const bpr = width * channels;
  let candidateRows = Math.ceil(headerLen / bpr);
  candidateRows = Math.min(candidateRows, height - 1);
  const start = (height - candidateRows) * bpr;
  return pixels.slice(start, start + headerLen);
}

// --- scramble / diffuse -------------------------------------------------------
export function scramblePixels(pixels, width, height, channels, seed) {
  const n = width * height;
  const perm = permutation(n, seed);
  const out = new Uint8Array(pixels.length);
  for (let i = 0; i < n; i++) {
    const src = perm[i] * channels, dst = i * channels;
    for (let c = 0; c < channels; c++) out[dst + c] = pixels[src + c];
  }
  return out;
}
export function unscramblePixels(pixels, width, height, channels, seed) {
  const n = width * height;
  const perm = permutation(n, seed);
  const out = new Uint8Array(pixels.length);
  for (let i = 0; i < n; i++) {
    const dst = perm[i] * channels, src = i * channels;
    for (let c = 0; c < channels; c++) out[dst + c] = pixels[src + c];
  }
  return out;
}

// --- core ---------------------------------------------------------------------
// pixels: Uint8Array of H*W*C bytes (row-major). Returns {data, height, width, channels}.
export async function encryptImage(pixels, width, height, channels, passphrase, iterations = DEFAULT_ITERATIONS) {
  if (![3, 4].includes(channels)) throw new Error('pixels must have 3 or 4 channels');
  if (pixels.length !== width * height * channels) throw new Error('pixel buffer size mismatch');
  const salt = new Uint8Array(SALT_LENGTH);
  globalThis.crypto.getRandomValues(salt);
  const derived = splitKeys(await pbkdf2(passphrase, salt, iterations));
  const scrambled = scramblePixels(pixels, width, height, channels, derived.scrambleSeed);
  const nonce = await deriveNonceAsync(salt);
  const diffused = chachaXor(scrambled, derived.streamKey, nonce);
  const stripRows = rowsNeeded(HEADER_SIZE, width, channels);
  const hdr = { version: VERSION, salt, iterations, height, width, channels, stripRows, hmac: new Uint8Array(32) };
  hdr.hmac = await hmacSha256(derived.macKey, [packPrehmac(hdr), diffused]);
  const { data } = appendStrip(diffused, width, channels, packHeader(hdr));
  return { data, width, height: height + stripRows, channels };
}

async function authenticate(pixels, width, height, channels, passphrase) {
  const candidate = peekHeaderBytes(pixels, width, channels, height, HEADER_SIZE);
  let hdr;
  try { hdr = parseHeader(candidate); }
  catch (e) { throw new MalformedCiphertextError('integrity check failed: wrong passphrase or the file was modified.'); }
  const generic = () => new MalformedCiphertextError('integrity check failed: wrong passphrase or the file was modified.');
  if (hdr.iterations <= 0 || hdr.iterations > MAX_UNVERIFIED_ITERATIONS) throw generic();
  if (![3, 4].includes(hdr.channels) || hdr.width <= 0 || hdr.height <= 0) throw generic();
  if (hdr.stripRows <= 0 || hdr.stripRows >= height) throw generic();
  const maxStrip = rowsNeeded(HEADER_SIZE, width, hdr.channels) + 1;
  if (hdr.stripRows > maxStrip) throw generic();
  if (hdr.channels !== channels) throw generic();
  const derived = splitKeys(await pbkdf2(passphrase, hdr.salt, hdr.iterations));
  const mainLen = (height - hdr.stripRows) * width * channels;
  const mainCipher = pixels.slice(0, mainLen);
  if (mainCipher.length !== hdr.height * hdr.width * hdr.channels)
    throw new DecryptionError('image dimensions do not match the embedded header (corrupted file).');
  const expected = await hmacSha256(derived.macKey, [packPrehmac(hdr), mainCipher]);
  let eq = expected.length === hdr.hmac.length;
  if (eq) for (let i = 0; i < expected.length; i++) if (expected[i] !== hdr.hmac[i]) { eq = false; break; }
  if (!eq) throw new DecryptionError('integrity check failed: wrong passphrase or the file was modified.');
  return { hdr, mainCipher, derived };
}

export async function decryptImage(pixels, width, height, channels, passphrase) {
  const { hdr, mainCipher, derived } = await authenticate(pixels, width, height, channels, passphrase);
  if (hdr.version !== VERSION)
    throw new Error(`unsupported OptiCipher format version ${hdr.version} — this build reads version ${VERSION}. Update OptiCipher to open this file.`);
  const nonce = await deriveNonceAsync(hdr.salt);
  const undiffused = chachaXor(mainCipher, derived.streamKey, nonce);
  const restored = unscramblePixels(undiffused, hdr.width, hdr.height, hdr.channels, derived.scrambleSeed);
  return { data: restored, width: hdr.width, height: hdr.height, channels: hdr.channels };
}

export const VERIFY_VERIFIED = 'verified', VERIFY_FAILED = 'failed', VERIFY_MALFORMED = 'malformed',
  VERIFY_UNSUPPORTED_FORMAT = 'unsupported_format', VERIFY_UNSUPPORTED_VERSION = 'unsupported_version',
  VERIFY_UNAUTHENTICATED = 'unauthenticated';

export async function verifyImage(pixels, width, height, channels, passphrase = null) {
  let hdr;
  try {
    const candidate = peekHeaderBytes(pixels, width, channels, height, HEADER_SIZE);
    hdr = parseHeader(candidate);
  } catch { return { status: VERIFY_UNSUPPORTED_FORMAT, authenticated: false, message: 'Not an OptiCipher image — the file has no OptiCipher header.' }; }
  const info = { version: hdr.version, iterations: hdr.iterations, width: hdr.width, height: hdr.height, channels: hdr.channels, stripRows: hdr.stripRows };
  if (passphrase === null || passphrase === undefined)
    return { status: VERIFY_UNAUTHENTICATED, authenticated: false, message: 'OptiCipher format recognised, but no passphrase was supplied, so the authentication tag was NOT checked.', ...info };
  try { await authenticate(pixels, width, height, channels, passphrase); }
  catch (e) {
    if (e instanceof MalformedCiphertextError) return { status: VERIFY_MALFORMED, authenticated: false, message: 'The image is structurally invalid for the OptiCipher format — it is corrupt, or it was deliberately crafted.', ...info };
    if (String(e.message).includes('dimensions')) return { status: VERIFY_MALFORMED, authenticated: false, message: 'The image dimensions do not match the embedded header (corrupted file).', ...info };
    return { status: VERIFY_FAILED, authenticated: false, message: 'The authentication tag did not match: the passphrase is wrong, or the file was modified after it was encrypted.', ...info };
  }
  if (hdr.version !== VERSION) return { status: VERIFY_UNSUPPORTED_VERSION, authenticated: false, message: `This file uses OptiCipher format version ${hdr.version}; this build reads version ${VERSION}. Update OptiCipher to open this file.`, ...info };
  return { status: VERIFY_VERIFIED, authenticated: true, message: 'Verified — the file\'s authentication tag matches its passphrase (HMAC-SHA256 over the ciphertext and the header).', ...info };
}

// --- metrics (port of metrics.py; correlation uses deterministic sampling) ---
export function shannonEntropy(channel) {
  const counts = new Float64Array(256);
  for (let i = 0; i < channel.length; i++) counts[channel[i]]++;
  let h = 0;
  for (let i = 0; i < 256; i++) if (counts[i] > 0) { const p = counts[i] / channel.length; h -= p * Math.log2(p); }
  return h;
}
export function entropyReport(pixels, width, height, channels) {
  const rep = {};
  for (let c = 0; c < channels; c++) {
    const ch = new Uint8Array(width * height);
    for (let i = 0; i < width * height; i++) ch[i] = pixels[i * channels + c];
    rep[`channel_${c}`] = shannonEntropy(ch);
  }
  const vals = Object.values(rep);
  rep.mean = vals.reduce((a, b) => a + b, 0) / vals.length;
  return rep;
}
function pearson(a, b) {
  const n = a.length; let ma = 0, mb = 0;
  for (let i = 0; i < n; i++) { ma += a[i]; mb += b[i]; }
  ma /= n; mb /= n;
  let num = 0, da = 0, db = 0;
  for (let i = 0; i < n; i++) { const x = a[i] - ma, y = b[i] - mb; num += x * y; da += x * x; db += y * y; }
  const den = Math.sqrt(da * db);
  return den === 0 ? 0 : num / den;
}
// Deterministic LCG sampling (seed 0) mirroring metrics.sample_size behaviour.
export function adjacentCorrelation(pixels, width, height, channels, chIdx, sampleSize = 4096) {
  const get = (r, c) => pixels[(r * width + c) * channels + chIdx];
  let s = 0; const rand = (n) => { s = (s * 1664525 + 1013904223) >>> 0; return s % n; };
  const out = {};
  if (width > 1) {
    const a = new Float64Array(sampleSize), b = new Float64Array(sampleSize);
    for (let i = 0; i < sampleSize; i++) { const r = rand(height), c = rand(width - 1); a[i] = get(r, c); b[i] = get(r, c + 1); }
    out.horizontal = pearson(a, b);
  } else out.horizontal = 0;
  if (height > 1) {
    const a = new Float64Array(sampleSize), b = new Float64Array(sampleSize);
    for (let i = 0; i < sampleSize; i++) { const r = rand(height - 1), c = rand(width); a[i] = get(r, c); b[i] = get(r + 1, c); }
    out.vertical = pearson(a, b);
  } else out.vertical = 0;
  if (height > 1 && width > 1) {
    const a = new Float64Array(sampleSize), b = new Float64Array(sampleSize);
    for (let i = 0; i < sampleSize; i++) { const r = rand(height - 1), c = rand(width - 1); a[i] = get(r, c); b[i] = get(r + 1, c + 1); }
    out.diagonal = pearson(a, b);
  } else out.diagonal = 0;
  return out;
}
export function npcr(a, b) {
  if (a.length !== b.length) throw new Error('images must have the same shape for NPCR');
  let d = 0; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) d++;
  return d / a.length * 100;
}
export function uaci(a, b) {
  if (a.length !== b.length) throw new Error('images must have the same shape for UACI');
  let s = 0; for (let i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]);
  return (s / a.length) / 255 * 100;
}
export function histogram(pixels, width, height, channels, chIdx) {
  const h = new Uint32Array(256);
  for (let i = 0; i < width * height; i++) h[pixels[i * channels + chIdx]]++;
  return h;
}
