// Parity tests: web core must be byte-compatible with the desktop Python core.
// Run: npm test   (Node >= 20, WebCrypto available globally)
import test from 'node:test';
import assert from 'node:assert/strict';
import { permutation } from '../src/pcg64.js';
import { chachaXor } from '../src/chacha20.js';
import { encryptImage, decryptImage, verifyImage } from '../src/core.js';
import { encodePNG, decodePNG } from '../src/png.js';

test('PCG64 permutation matches NumPy default_rng', () => {
  assert.deepEqual([...permutation(10, 42n)], [5, 6, 0, 7, 3, 2, 4, 9, 1, 8]);
  assert.deepEqual([...permutation(10, 0n)], [4, 6, 2, 7, 3, 5, 9, 0, 8, 1]);
  assert.deepEqual([...permutation(10, 1n)], [8, 4, 7, 0, 1, 2, 5, 9, 6, 3]);
});

test('ChaCha20 zero keystream (RFC 8439)', () => {
  const ks = chachaXor(new Uint8Array(64), new Uint8Array(32), new Uint8Array(16));
  assert.equal([...ks.slice(0, 16)].map(x => x.toString(16).padStart(2, '0')).join(''), '76b8e0ada0f13d90405d6ae55386bd28');
});

test('encrypt/decrypt round-trip, verify, wrong passphrase', async () => {
  const img = new Uint8Array(8 * 8 * 3); for (let i = 0; i < img.length; i++) img[i] = i % 256;
  const enc = await encryptImage(img, 8, 8, 3, 'golden-vector', 1000);
  assert.equal(enc.height, 11);
  const dec = await decryptImage(enc.data, enc.width, enc.height, enc.channels, 'golden-vector');
  assert.deepEqual([...dec.data], [...img]);
  assert.equal((await verifyImage(enc.data, enc.width, enc.height, enc.channels, 'golden-vector')).status, 'verified');
  assert.equal((await verifyImage(enc.data, enc.width, enc.height, enc.channels, 'wrong')).status, 'failed');
  assert.equal((await verifyImage(enc.data, enc.width, enc.height, enc.channels)).status, 'unauthenticated');
  await assert.rejects(() => decryptImage(enc.data, enc.width, enc.height, enc.channels, 'wrong'), /integrity check failed/);
});

test('PNG codec is pixel-exact (incl. RGBA)', () => {
  const px = new Uint8Array([255, 0, 0, 128, 0, 255, 0, 0, 0, 0, 255, 255, 10, 20, 30, 40]);
  const back = decodePNG(encodePNG(px, 2, 2, 4));
  assert.deepEqual([...back.pixels], [...px]);
  assert.equal(back.channels, 4);
});
