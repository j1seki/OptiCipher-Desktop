// ChaCha20 stream cipher (IETF, 32-byte key, 16-byte nonce where the first
// 4 bytes are the little-endian initial block counter — exactly how
// `cryptography`'s ChaCha20 is used in opticipher/diffusion.py).
// Encryption == decryption (XOR with keystream).

function rotl(v, c) { return ((v << c) | (v >>> (32 - c))) >>> 0; }

function qr(s, a, b, c, d) {
  s[a] = (s[a] + s[b]) >>> 0; s[d] ^= s[a]; s[d] = rotl(s[d], 16);
  s[c] = (s[c] + s[d]) >>> 0; s[b] ^= s[c]; s[b] = rotl(s[b], 12);
  s[a] = (s[a] + s[b]) >>> 0; s[d] ^= s[a]; s[d] = rotl(s[d], 8);
  s[c] = (s[c] + s[d]) >>> 0; s[b] ^= s[c]; s[b] = rotl(s[b], 7);
}

const CONSTANTS = [0x61707865, 0x3320646e, 0x79622d32, 0x6b206574];

function chachaBlock(key, counter, nonce12, out /*Uint32Array(16)*/) {
  const s = new Uint32Array(16);
  s[0] = CONSTANTS[0]; s[1] = CONSTANTS[1]; s[2] = CONSTANTS[2]; s[3] = CONSTANTS[3];
  const dv = new DataView(key.buffer, key.byteOffset, 32);
  for (let i = 0; i < 8; i++) s[4 + i] = dv.getUint32(i * 4, true);
  s[12] = counter >>> 0;
  const ndv = new DataView(nonce12.buffer, nonce12.byteOffset, 12);
  s[13] = ndv.getUint32(0, true); s[14] = ndv.getUint32(4, true); s[15] = ndv.getUint32(8, true);
  const w = Uint32Array.from(s);
  for (let i = 0; i < 10; i++) {
    qr(w, 0, 4, 8, 12); qr(w, 1, 5, 9, 13); qr(w, 2, 6, 10, 14); qr(w, 3, 7, 11, 15);
    qr(w, 0, 5, 10, 15); qr(w, 1, 6, 11, 12); qr(w, 2, 7, 8, 13); qr(w, 3, 4, 9, 14);
  }
  for (let i = 0; i < 16; i++) out[i] = (w[i] + s[i]) >>> 0;
}

// XOR data (Uint8Array) with ChaCha20 keystream. Returns new Uint8Array.
// nonce16: 16 bytes; nonce16[0..4) = LE initial counter, [4..16) = 12-byte nonce.
export function chachaXor(data, key, nonce16) {
  const out = new Uint8Array(data.length);
  const counter0 = new DataView(nonce16.buffer, nonce16.byteOffset, 16).getUint32(0, true);
  const nonce12 = nonce16.slice(4, 16);
  const block = new Uint32Array(16);
  const blockBytes = new Uint8Array(block.buffer);
  let counter = counter0;
  for (let off = 0; off < data.length; off += 64) {
    chachaBlock(key, counter, nonce12, block);
    // blockBytes view is over the ArrayBuffer of `block` (little-endian on all
    // supported platforms; DataView writes above/below use LE explicitly, and
    // Uint32Array storage is platform-endian — x86/ARM are LE, which covers
    // every browser/Android target).
    const n = Math.min(64, data.length - off);
    for (let i = 0; i < n; i++) out[off + i] = data[off + i] ^ blockBytes[i];
    counter = (counter + 1) >>> 0;
  }
  return out;
}
