package com.opticipher

import java.math.BigInteger
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

// OptiCipher v1 core for Android — byte-compatible with opticipher/*.py and
// web/src/*.js. PCG64 (XSL RR 128/64) + NumPy SeedSequence, ChaCha20,
// PBKDF2-HMAC-SHA256, HMAC-SHA256, 70-byte header + reserved strip.

open class DecryptionError(msg: String) : Exception(msg)
class MalformedCiphertextError(msg: String) : DecryptionError(msg)

// --- SeedSequence (uint32 arithmetic, mirrors web/src/pcg64.js) ----------
private val INIT_A = 0x43b0d7e5.toInt()
private val MULT_A = 0x931e8875.toInt()
private val INIT_B = 0x8b51f9dd.toInt()
private val MULT_B = 0x58f38ded.toInt()
private val MIX_L = 0xca01f9dd.toInt()
private val MIX_R = 0x4973f715.toInt()

class SeedSequence(seed: Long) {
    val pool = IntArray(4)
    init {
        val entropy = mutableListOf<Int>()
        var n = seed
        if (n == 0L) entropy.add(0) else while (n != 0L) { entropy.add(n.toInt()); n = n ushr 32 }
        var hashConst = INIT_A
        fun hash(value: Int): Int {
            var v = value xor hashConst
            hashConst *= MULT_A
            v *= hashConst
            v = v xor (v ushr 16)
            return v
        }
        fun mix(x: Int, y: Int): Int {
            var r = MIX_L * x - MIX_R * y
            r = r xor (r ushr 16)
            return r
        }
        for (i in pool.indices) pool[i] = if (i < entropy.size) hash(entropy[i]) else hash(0)
        for (iSrc in pool.indices) for (iDst in pool.indices)
            if (iSrc != iDst) pool[iDst] = mix(pool[iDst], hash(pool[iSrc]))
        for (iSrc in pool.size until entropy.size) for (iDst in pool.indices)
            pool[iDst] = mix(pool[iDst], hash(entropy[iSrc]))
    }
    fun generateStateUint64(nWords: Int): LongArray {
        val total = nWords * 2
        val state = IntArray(total)
        var hashConst = INIT_B
        for (i in 0 until total) {
            var v = pool[i % pool.size] xor hashConst
            hashConst *= MULT_B
            v *= hashConst
            v = v xor (v ushr 16)
            state[i] = v
        }
        return LongArray(nWords) { i -> (state[2 * i].toLong() and 0xffffffffL) or ((state[2 * i + 1].toLong() and 0xffffffffL) shl 32) }
    }
}

// --- PCG64 -----------------------------------------------------------------
class PCG64(seed: Long) {
    private var state: BigInteger
    private val inc: BigInteger
    private var hasUint32 = false
    private var uinteger = 0

    companion object {
        private val MULT = BigInteger("2360ed051fc65da44385df649fccf645", 16)
        private val MASK128 = BigInteger.ONE.shiftLeft(128).subtract(BigInteger.ONE)
        private val MASK64 = BigInteger.ONE.shiftLeft(64).subtract(BigInteger.ONE)
    }

    init {
        val w = SeedSequence(seed).generateStateUint64(4)
        val initState = (BigInteger.valueOf(w[0]) and MASK64).shiftLeft(64).or(BigInteger.valueOf(w[1]) and MASK64)
        val initSeq = (BigInteger.valueOf(w[2]) and MASK64).shiftLeft(64).or(BigInteger.valueOf(w[3]) and MASK64)
        inc = initSeq.shiftLeft(1).or(BigInteger.ONE).and(MASK128)
        var s = inc // 0*MULT+inc
        s = s.add(initState).and(MASK128)
        s = s.multiply(MULT).add(inc).and(MASK128)
        state = s
    }

    private fun stepAndOutput(): Long {
        state = state.multiply(MULT).add(inc).and(MASK128)
        val hi = state.shiftRight(64)
        val lo = state.and(MASK64)
        val x = hi.xor(lo)
        val rot = hi.shiftRight(58).toInt() and 63
        if (rot == 0) return x.toLong()
        return x.shiftRight(rot).or(x.shiftLeft(64 - rot)).and(MASK64).toLong()
    }

    fun nextUint32(): Int {
        if (hasUint32) { hasUint32 = false; return uinteger }
        val next = stepAndOutput()
        hasUint32 = true
        uinteger = (next ushr 32).toInt()
        return next.toInt()
    }

    fun boundedUint32(bound: Int): Int {
        var mask = bound - 1
        mask = mask or (mask ushr 1); mask = mask or (mask ushr 2); mask = mask or (mask ushr 4)
        mask = mask or (mask ushr 8); mask = mask or (mask ushr 16)
        while (true) {
            val v = nextUint32() and mask
            if (v < bound) return v
        }
    }
}

fun permutation(n: Int, seed: Long): IntArray {
    val pcg = PCG64(seed)
    val a = IntArray(n) { it }
    for (i in n - 1 downTo 1) {
        val j = pcg.boundedUint32(i + 1)
        val t = a[i]; a[i] = a[j]; a[j] = t
    }
    return a
}

// --- ChaCha20 --------------------------------------------------------------
private fun rotl(v: Int, c: Int) = (v shl c) or (v ushr (32 - c))
private fun qr(s: IntArray, a: Int, b: Int, c: Int, d: Int) {
    s[a] += s[b]; s[d] = rotl(s[d] xor s[a], 16)
    s[c] += s[d]; s[b] = rotl(s[b] xor s[c], 12)
    s[a] += s[b]; s[d] = rotl(s[d] xor s[a], 8)
    s[c] += s[d]; s[b] = rotl(s[b] xor s[c], 7)
}

fun chachaXor(data: ByteArray, key: ByteArray, nonce16: ByteArray): ByteArray {
    val out = ByteArray(data.size)
    var counter = (nonce16[0].toInt() and 0xff) or ((nonce16[1].toInt() and 0xff) shl 8) or
        ((nonce16[2].toInt() and 0xff) shl 16) or ((nonce16[3].toInt() and 0xff) shl 24)
    val nonce12 = nonce16.copyOfRange(4, 16)
    var off = 0
    while (off < data.size) {
        val s = IntArray(16)
        s[0] = 0x61707865; s[1] = 0x3320646e; s[2] = 0x79622d32; s[3] = 0x6b206574
        for (i in 0 until 8) s[4 + i] = le32(key, i * 4)
        s[12] = counter
        for (i in 0 until 3) s[13 + i] = le32(nonce12, i * 4)
        val w = s.copyOf()
        repeat(10) {
            qr(w, 0, 4, 8, 12); qr(w, 1, 5, 9, 13); qr(w, 2, 6, 10, 14); qr(w, 3, 7, 11, 15)
            qr(w, 0, 5, 10, 15); qr(w, 1, 6, 11, 12); qr(w, 2, 7, 8, 13); qr(w, 3, 4, 9, 14)
        }
        val block = ByteArray(64)
        for (i in 0 until 16) putLe32(block, i * 4, w[i] + s[i])
        val n = minOf(64, data.size - off)
        for (i in 0 until n) out[off + i] = (data[off + i].toInt() xor (block[i].toInt() and 0xff)).toByte()
        off += 64; counter++
    }
    return out
}
private fun le32(b: ByteArray, off: Int) =
    (b[off].toInt() and 0xff) or ((b[off + 1].toInt() and 0xff) shl 8) or
        ((b[off + 2].toInt() and 0xff) shl 16) or ((b[off + 3].toInt() and 0xff) shl 24)
private fun putLe32(b: ByteArray, off: Int, v: Int) {
    b[off] = v.toByte(); b[off + 1] = (v ushr 8).toByte(); b[off + 2] = (v ushr 16).toByte(); b[off + 3] = (v ushr 24).toByte()
}

// --- OptiCipher core ---------------------------------------------------------
const val HEADER_SIZE = 70
const val PREHMAC_SIZE = 38
const val SALT_LENGTH = 16
const val DEFAULT_ITERATIONS = 200000
const val MAX_UNVERIFIED_ITERATIONS = 10000000

private data class Keys(val streamKey: ByteArray, val scrambleSeed: Long, val macKey: ByteArray)
private data class Header(
    val version: Int, val salt: ByteArray, val iterations: Int,
    val height: Int, val width: Int, val channels: Int, val stripRows: Int, val hmac: ByteArray
)

private fun deriveKeys(passphrase: String, salt: ByteArray, iterations: Int): Keys {
    val spec = PBEKeySpec(passphrase.toCharArray(), salt, iterations, 64 * 8)
    val block = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(spec).encoded
    // scramble_seed = big-endian uint128, masked to 64 bits like scramble.py
    var seed = 0L
    for (i in 40 until 48) seed = (seed shl 8) or (block[i].toLong() and 0xff)
    return Keys(block.copyOfRange(0, 32), seed, block.copyOfRange(48, 64))
}
private fun hmac(key: ByteArray, vararg parts: ByteArray): ByteArray {
    val mac = Mac.getInstance("HmacSHA256")
    mac.init(SecretKeySpec(key, "HmacSHA256"))
    for (p in parts) mac.update(p)
    return mac.doFinal()
}
private fun sha256(data: ByteArray) = java.security.MessageDigest.getInstance("SHA-256").digest(data)

private fun packPrehmac(h: Header): ByteArray {
    val b = ByteArray(PREHMAC_SIZE)
    b[0] = 0x4f; b[1] = 0x50; b[2] = 0x54; b[3] = 0x43; b[4] = h.version.toByte()
    System.arraycopy(h.salt, 0, b, 5, 16)
    putBe32(b, 21, h.iterations); putBe32(b, 25, h.height); putBe32(b, 29, h.width)
    b[33] = h.channels.toByte(); putBe32(b, 34, h.stripRows)
    return b
}
private fun putBe32(b: ByteArray, off: Int, v: Int) {
    b[off] = (v ushr 24).toByte(); b[off + 1] = (v ushr 16).toByte(); b[off + 2] = (v ushr 8).toByte(); b[off + 3] = v.toByte()
}
private fun be32(b: ByteArray, off: Int) =
    ((b[off].toInt() and 0xff) shl 24) or ((b[off + 1].toInt() and 0xff) shl 16) or
        ((b[off + 2].toInt() and 0xff) shl 8) or (b[off + 3].toInt() and 0xff)

private fun parseHeader(raw: ByteArray): Header {
    if (raw.size < HEADER_SIZE) throw IllegalArgumentException("header too short")
    if (raw[0] != 0x4f.toByte() || raw[1] != 0x50.toByte() || raw[2] != 0x54.toByte() || raw[3] != 0x43.toByte())
        throw IllegalArgumentException("not an OptiCipher image (magic number mismatch). The file may be unencrypted, corrupted, or from another tool.")
    return Header(raw[4].toInt() and 0xff, raw.copyOfRange(5, 21), be32(raw, 21), be32(raw, 25), be32(raw, 29), raw[33].toInt() and 0xff, be32(raw, 34), raw.copyOfRange(38, 70))
}
fun rowsNeeded(headerLen: Int, width: Int, channels: Int): Int {
    require(width > 0 && channels > 0)
    return (headerLen + width * channels - 1) / (width * channels)
}
private fun peekHeader(pixels: ByteArray, width: Int, channels: Int, height: Int): ByteArray {
    val bpr = width * channels
    var rows = (HEADER_SIZE + bpr - 1) / bpr
    rows = minOf(rows, height - 1)
    val start = (height - rows) * bpr
    return pixels.copyOfRange(start, start + HEADER_SIZE)
}

fun scramblePixels(pixels: ByteArray, width: Int, height: Int, channels: Int, seed: Long): ByteArray {
    val n = width * height
    val perm = permutation(n, seed)
    val out = ByteArray(pixels.size)
    for (i in 0 until n) {
        val src = perm[i] * channels; val dst = i * channels
        for (c in 0 until channels) out[dst + c] = pixels[src + c]
    }
    return out
}
fun unscramblePixels(pixels: ByteArray, width: Int, height: Int, channels: Int, seed: Long): ByteArray {
    val n = width * height
    val perm = permutation(n, seed)
    val out = ByteArray(pixels.size)
    for (i in 0 until n) {
        val dst = perm[i] * channels; val src = i * channels
        for (c in 0 until channels) out[dst + c] = pixels[src + c]
    }
    return out
}

data class ImageData(val pixels: ByteArray, val width: Int, val height: Int, val channels: Int)

// The encryption pipeline needs several full-size buffers (decoded bitmap,
// scrambled pixels, ciphertext, PNG scanlines and compressed output). A 4 MP
// cap keeps that peak safely below the 256 MB heap on typical Android phones.
const val MAX_PROCESS_PIXELS = 4_000_000
fun requireProcessableImage(width: Int, height: Int) {
    require(width > 0 && height > 0) { "invalid image dimensions" }
    val pixels = width.toLong() * height.toLong()
    require(pixels <= MAX_PROCESS_PIXELS) {
        "image is ${pixels / 1_000_000.0} MP; this phone can safely process images up to 4 MP. Resize it first to avoid running out of memory."
    }
}

fun encryptImage(img: ImageData, passphrase: String, iterations: Int = DEFAULT_ITERATIONS): ImageData {
    require(img.channels == 3 || img.channels == 4)
    requireProcessableImage(img.width, img.height)
    val salt = ByteArray(SALT_LENGTH).also { SecureRandom().nextBytes(it) }
    val derived = deriveKeys(passphrase, salt, iterations)
    val scrambled = scramblePixels(img.pixels, img.width, img.height, img.channels, derived.scrambleSeed)
    val nonce = sha256(salt).copyOf(16)
    val diffused = chachaXor(scrambled, derived.streamKey, nonce)
    val stripRows = rowsNeeded(HEADER_SIZE, img.width, img.channels)
    var hdr = Header(1, salt, iterations, img.height, img.width, img.channels, stripRows, ByteArray(32))
    hdr = hdr.copy(hmac = hmac(derived.macKey, packPrehmac(hdr), diffused))
    val headerBytes = packPrehmac(hdr) + hdr.hmac
    val out = ByteArray(diffused.size + stripRows * img.width * img.channels)
    System.arraycopy(diffused, 0, out, 0, diffused.size)
    System.arraycopy(headerBytes, 0, out, diffused.size, headerBytes.size)
    return ImageData(out, img.width, img.height + stripRows, img.channels)
}

private data class Auth(val hdr: Header, val mainCipher: ByteArray, val derived: Keys)
private fun authenticate(img: ImageData, passphrase: String): Auth {
    val hdr = try { parseHeader(peekHeader(img.pixels, img.width, img.channels, img.height)) }
        catch (e: IllegalArgumentException) { throw MalformedCiphertextError("integrity check failed: wrong passphrase or the file was modified.") }
    val generic = { MalformedCiphertextError("integrity check failed: wrong passphrase or the file was modified.") }
    if (hdr.iterations <= 0 || hdr.iterations > MAX_UNVERIFIED_ITERATIONS) throw generic()
    if (hdr.channels != 3 && hdr.channels != 4) throw generic()
    if (hdr.width <= 0 || hdr.height <= 0) throw generic()
    if (hdr.stripRows <= 0 || hdr.stripRows >= img.height) throw generic()
    if (hdr.stripRows > rowsNeeded(HEADER_SIZE, img.width, hdr.channels) + 1) throw generic()
    if (hdr.channels != img.channels) throw generic()
    val derived = deriveKeys(passphrase, hdr.salt, hdr.iterations)
    val mainLen = (img.height - hdr.stripRows) * img.width * img.channels
    val mainCipher = img.pixels.copyOf(mainLen)
    if (mainCipher.size != hdr.height * hdr.width * hdr.channels)
        throw DecryptionError("image dimensions do not match the embedded header (corrupted file).")
    val expected = hmac(derived.macKey, packPrehmac(hdr), mainCipher)
    if (!expected.contentEquals(hdr.hmac)) throw DecryptionError("integrity check failed: wrong passphrase or the file was modified.")
    return Auth(hdr, mainCipher, derived)
}

fun decryptImage(img: ImageData, passphrase: String): ImageData {
    val (hdr, mainCipher, derived) = authenticate(img, passphrase)
    if (hdr.version != 1) throw IllegalStateException("unsupported OptiCipher format version ${hdr.version} — this build reads version 1. Update OptiCipher to open this file.")
    val nonce = sha256(hdr.salt).copyOf(16)
    val undiffused = chachaXor(mainCipher, derived.streamKey, nonce)
    val restored = unscramblePixels(undiffused, hdr.width, hdr.height, hdr.channels, derived.scrambleSeed)
    return ImageData(restored, hdr.width, hdr.height, hdr.channels)
}

data class VerifyResult(val status: String, val authenticated: Boolean, val message: String)
fun verifyImage(img: ImageData, passphrase: String?): VerifyResult {
    val hdr = try { parseHeader(peekHeader(img.pixels, img.width, img.channels, img.height)) }
        catch (e: Exception) { return VerifyResult("unsupported_format", false, "Not an OptiCipher image — the file has no OptiCipher header.") }
    if (passphrase == null) return VerifyResult("unauthenticated", false, "OptiCipher format recognised, but no passphrase was supplied, so the authentication tag was NOT checked.")
    try { authenticate(img, passphrase) }
    catch (e: MalformedCiphertextError) { return VerifyResult("malformed", false, "The image is structurally invalid for the OptiCipher format — it is corrupt, or it was deliberately crafted.") }
    catch (e: DecryptionError) {
        if (e.message!!.contains("dimensions")) return VerifyResult("malformed", false, "The image dimensions do not match the embedded header (corrupted file).")
        return VerifyResult("failed", false, "The authentication tag did not match: the passphrase is wrong, or the file was modified after it was encrypted.")
    }
    if (hdr.version != 1) return VerifyResult("unsupported_version", false, "This file uses OptiCipher format version ${hdr.version}; this build reads version 1. Update OptiCipher to open this file.")
    return VerifyResult("verified", true, "Verified — the file's authentication tag matches its passphrase (HMAC-SHA256 over the ciphertext and the header).")
}
