// PCG64 (XSL RR 128/64) + NumPy SeedSequence — byte-exact port of
// numpy.random.default_rng(seed).permutation(n) used by opticipher/scramble.py.
// Reference: numpy/random/src/pcg64/pcg64.h and the SeedSequence spec
// (Melissa O'Neill seed_seq, NEP 19). Verified against NumPy 2.5.4.

const MASK32 = 0xffffffff;
const INIT_A = 0x43b0d7e5, MULT_A = 0x931e8875;
const INIT_B = 0x8b51f9dd, MULT_B = 0x58f38ded;
const MIX_MULT_L = 0xca01f9dd, MIX_MULT_R = 0x4973f715;

function u32(x) { return x >>> 0; }
function mul32(a, b) { return Math.imul(a >>> 0, b >>> 0) >>> 0; }

// --- SeedSequence ---------------------------------------------------------
export class SeedSequence {
  constructor(seed) {
    // seed is a BigInt (already masked to 64 bits by caller, like Python).
    // Convert to uint32 array, little-endian words (coerce_to_uint32_array).
    const entropy = [];
    if (seed === 0n) entropy.push(0);
    else { let n = seed; while (n > 0n) { entropy.push(Number(n & 0xffffffffn)); n >>= 32n; } }
    this.pool = new Uint32Array(4);
    let hashConst = INIT_A >>> 0;
    const hash = (value) => {
      let v = (value >>> 0) ^ hashConst;
      hashConst = mul32(hashConst, MULT_A);
      v = mul32(v, hashConst);
      v ^= v >>> 16;
      return v >>> 0;
    };
    const mix = (x, y) => {
      let result = (mul32(MIX_MULT_L, x) - mul32(MIX_MULT_R, y)) >>> 0;
      result ^= result >>> 16;
      return result >>> 0;
    };
    const pool = this.pool;
    for (let i = 0; i < pool.length; i++)
      pool[i] = i < entropy.length ? hash(entropy[i]) : hash(0);
    for (let iSrc = 0; iSrc < pool.length; iSrc++)
      for (let iDst = 0; iDst < pool.length; iDst++)
        if (iSrc !== iDst) pool[iDst] = mix(pool[iDst], hash(pool[iSrc]));
    for (let iSrc = pool.length; iSrc < entropy.length; iSrc++)
      for (let iDst = 0; iDst < pool.length; iDst++)
        pool[iDst] = mix(pool[iDst], hash(entropy[iSrc]));
  }
  // Returns Uint32Array of length nWords*2 as uint64 pairs lo/hi? We return
  // BigInt[] uint64 words like generate_state(n, uint64) (little-endian view).
  generateStateUint64(nWords) {
    const total = nWords * 2;
    const state = new Uint32Array(total);
    let hashConst = INIT_B >>> 0;
    for (let i = 0; i < total; i++) {
      let dataVal = this.pool[i % this.pool.length] >>> 0;
      dataVal ^= hashConst;
      hashConst = mul32(hashConst, MULT_B);
      dataVal = mul32(dataVal, hashConst);
      dataVal ^= dataVal >>> 16;
      state[i] = dataVal >>> 0;
    }
    const out = [];
    for (let i = 0; i < nWords; i++)
      out.push(BigInt(state[2 * i]) | (BigInt(state[2 * i + 1]) << 32n));
    return out;
  }
}

// --- PCG64 ----------------------------------------------------------------
// 128-bit state held as two uint64 BigInts (hi, lo) to keep it simple and
// exact. BigInt multiplication is fine for permutation generation.
const MULT_HI = 2549297995355413924n; // 0x2360ed051fc65da4
const MULT_LO = 4865540595714422341n; // 0x4385df649fccf645
const MULT = (MULT_HI << 64n) | MULT_LO;
const MASK128 = (1n << 128n) - 1n;
const MASK64 = (1n << 64n) - 1n;

export class PCG64 {
  constructor(seedBigInt) {
    const ss = new SeedSequence(seedBigInt & MASK64);
    const w = ss.generateStateUint64(4);
    const initState = (w[0] << 64n) | w[1];
    const initSeq = (w[2] << 64n) | w[3];
    // pcg_setseq_128_srandom_r
    this.inc = ((initSeq << 1n) | 1n) & MASK128;
    // state = 0; step; state += initState; step
    let state = this.inc; // 0*MULT + inc
    state = (state + initState) & MASK128;
    state = (state * MULT + this.inc) & MASK128;
    this.state = state;
    this.hasUint32 = false;
    this.uinteger = 0;
  }
  stepAndOutput() {
    this.state = (this.state * MULT + this.inc) & MASK128;
    const hi = this.state >> 64n;
    const lo = this.state & MASK64;
    const x = hi ^ lo;
    const rot = Number(hi >> 58n) & 63;
    if (rot === 0) return x & MASK64;
    return ((x >> BigInt(rot)) | (x << BigInt(64 - rot))) & MASK64;
  }
  nextUint64() { return this.stepAndOutput(); }
  nextUint32() {
    if (this.hasUint32) { this.hasUint32 = false; return this.uinteger; }
    const next = this.stepAndOutput();
    this.hasUint32 = true;
    this.uinteger = Number(next >> 32n) & MASK32;
    return Number(next & 0xffffffffn);
  }
  // Bounded uint32 with mask rejection — what NumPy's shuffle (random_interval)
  // uses. bound in [1, 2^32].
  boundedUint32(bound) {
    let mask = bound - 1;
    mask |= mask >> 1; mask |= mask >> 2; mask |= mask >> 4; mask |= mask >> 8; mask |= mask >> 16;
    mask >>>= 0;
    for (;;) {
      const v = (this.nextUint32() & mask) >>> 0;
      if (v < bound) return v;
    }
  }
}

// Fisher-Yates, descending — identical to numpy Generator.permutation(n).
export function permutation(n, seedBigInt) {
  const pcg = new PCG64(seedBigInt);
  const a = new Uint32Array(n);
  for (let i = 0; i < n; i++) a[i] = i;
  for (let i = n - 1; i > 0; i--) {
    const j = pcg.boundedUint32(i + 1);
    const t = a[i]; a[i] = a[j]; a[j] = t;
  }
  return a;
}
