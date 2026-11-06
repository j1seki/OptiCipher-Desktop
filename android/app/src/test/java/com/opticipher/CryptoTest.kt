package com.opticipher

import org.junit.Assert.*
import org.junit.Test

class CryptoTest {
    @Test fun permutationMatchesNumpy() {
        assertTrue(permutation(10, 42L).contentEquals(intArrayOf(5, 6, 0, 7, 3, 2, 4, 9, 1, 8)))
        assertTrue(permutation(10, 0L).contentEquals(intArrayOf(4, 6, 2, 7, 3, 5, 9, 0, 8, 1)))
    }
    @Test fun chachaZeroKeystream() {
        val ks = chachaXor(ByteArray(16), ByteArray(32), ByteArray(16))
        assertEquals("76b8e0ada0f13d90405d6ae55386bd28", ks.joinToString("") { "%02x".format(it) })
    }
    @Test fun roundTripAndVerify() {
        val img = ImageData(ByteArray(8 * 8 * 3) { it.toByte() }, 8, 8, 3)
        val enc = encryptImage(img, "golden-vector", 1000)
        assertEquals(11, enc.height)
        val dec = decryptImage(enc, "golden-vector")
        assertTrue(img.pixels.contentEquals(dec.pixels))
        assertEquals("verified", verifyImage(enc, "golden-vector").status)
        assertEquals("failed", verifyImage(enc, "wrong").status)
        try { decryptImage(enc, "wrong"); fail("expected DecryptionError") } catch (_: DecryptionError) {}
    }
    // Ciphertext produced by the desktop Python core (salt = bytes(range(16)),
    // passphrase "golden-vector", 1000 iterations, 8x8 arange image).
    // SHA-256 of the pixel bytes: d7b1165ba6e08effc93a9d0e829e6f9d01cd9e25ca38239070f87ab7e00797ba
    @Test fun decryptsDesktopGoldenVector() {
        val hex = "d51c04ba9e3ebf9d815fbfb50a37781f9358f5f9ea2931adbe3c6abe6e727ab771824fbabea7b732df3cc945e5289e384cf6c03cb4b4d9341929d615c8469a1baf3c551567dd21cfdc6e3bd8526be702a447d0ddeca425a17614abc86421c2e48306545323d3eb7e539c91f2fb633982416a0663d85ec3e70164deeab590e5211cb1ea7d425c374dcbf9d9769498491e178e2bb14c277a20b0aa50bc017add83533afe8279eb02b60ab63e4179bcad0cc7b3b16c7d53c98834915a525dcc37e94f50544301000102030405060708090a0b0c0d0e0f000003e800000008000000080300000003a98a5e43010f2c76eb85d55b5ac269af1e0d85082475b05f867a34b69291a0550000"
        val bytes = hex.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
        val dec = decryptImage(ImageData(bytes, 8, 11, 3), "golden-vector")
        val expected = ByteArray(8 * 8 * 3) { it.toByte() }
        assertTrue(expected.contentEquals(dec.pixels))
    }
    @Test fun pngRoundTrip() {
        val px = byteArrayOf(255.toByte(), 0, 0, 128.toByte(), 0, 255.toByte(), 0, 0, 0, 0, 255.toByte(), 255.toByte(), 10, 20, 30, 40)
        val back = decodePNG(encodePNG(px, 2, 2, 4))
        assertTrue(px.contentEquals(back.pixels))
        assertEquals(4, back.channels)
    }
}
