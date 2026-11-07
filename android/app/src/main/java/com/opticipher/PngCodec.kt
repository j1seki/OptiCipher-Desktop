package com.opticipher

import java.io.ByteArrayInputStream
import java.util.zip.Deflater
import java.util.zip.Inflater
import java.nio.ByteBuffer
import java.nio.channels.Channels

// Lossless PNG codec (8-bit, non-interlaced) using java.util.zip — pixel-exact
// for RGB/RGBA ciphertexts. Greyscale/palette expand to RGB like Pillow.
private val PNG_SIG = byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10)
private val CRC_TABLE = IntArray(256) { n ->
    var c = n
    repeat(8) { c = if (c and 1 != 0) 0xedb88320.toInt() xor (c ushr 1) else c ushr 1 }
    c
}
private fun crc32(buf: ByteArray, off: Int = 0, len: Int = buf.size): Int {
    var c = -1
    for (i in off until off + len) c = CRC_TABLE[(c xor buf[i].toInt()) and 0xff] xor (c ushr 8)
    return c xor -1
}
private fun chunk(type: String, data: ByteArray): ByteArray {
    val out = ByteArray(12 + data.size)
    val tb = type.toByteArray(Charsets.US_ASCII)
    fun be(off: Int, v: Int) { out[off] = (v ushr 24).toByte(); out[off + 1] = (v ushr 16).toByte(); out[off + 2] = (v ushr 8).toByte(); out[off + 3] = v.toByte() }
    be(0, data.size); System.arraycopy(tb, 0, out, 4, 4); System.arraycopy(data, 0, out, 8, data.size)
    be(8 + data.size, crc32(out, 4, 4 + data.size))
    return out
}

fun encodePNG(pixels: ByteArray, width: Int, height: Int, channels: Int): ByteArray {
    val colorType = if (channels == 4) 6 else 2
    val ihdr = ByteArray(13)
    fun be(off: Int, v: Int) { ihdr[off] = (v ushr 24).toByte(); ihdr[off + 1] = (v ushr 16).toByte(); ihdr[off + 2] = (v ushr 8).toByte(); ihdr[off + 3] = v.toByte() }
    be(0, width); be(4, height); ihdr[8] = 8; ihdr[9] = colorType.toByte()
    val stride = width * channels
    val raw = ByteArray((stride + 1) * height)
    for (y in 0 until height) System.arraycopy(pixels, y * stride, raw, y * (stride + 1) + 1, stride)
    val deflater = Deflater(6)
    deflater.setInput(raw); deflater.finish()
    val buf = ByteArray(raw.size + 1024); var idatLen = 0
    while (!deflater.finished()) { val n = deflater.deflate(buf, idatLen, buf.size - idatLen); idatLen += n }
    deflater.end()
    val parts = listOf(PNG_SIG, chunk("IHDR", ihdr), chunk("IDAT", buf.copyOf(idatLen)), chunk("IEND", ByteArray(0)))
    val total = parts.sumOf { it.size }
    val out = ByteArray(total); var off = 0
    for (p in parts) { System.arraycopy(p, 0, out, off, p.size); off += p.size }
    return out
}

private fun paeth(a: Int, b: Int, c: Int): Int {
    val p = a + b - c; val pa = Math.abs(p - a); val pb = Math.abs(p - b); val pc = Math.abs(p - c)
    return if (pa <= pb && pa <= pc) a else if (pb <= pc) b else c
}

fun decodePNG(bytes: ByteArray): ImageData {
    require(bytes.size >= 8 && PNG_SIG.indices.all { bytes[it] == PNG_SIG[it] }) { "not a PNG file" }
    var off = 8; var width = 0; var height = 0; var bitDepth = 0; var colorType = 0; var interlace = 0
    var plte: ByteArray? = null; val idat = mutableListOf<ByteArray>()
    while (off + 8 <= bytes.size) {
        val len = ((bytes[off].toInt() and 0xff) shl 24) or ((bytes[off + 1].toInt() and 0xff) shl 16) or
            ((bytes[off + 2].toInt() and 0xff) shl 8) or (bytes[off + 3].toInt() and 0xff)
        val type = String(bytes, off + 4, 4, Charsets.US_ASCII)
        val data = bytes.copyOfRange(off + 8, off + 8 + len)
        when (type) {
            "IHDR" -> { width = be32(data, 0); height = be32(data, 4); requireProcessableImage(width, height); bitDepth = data[8].toInt(); colorType = data[9].toInt(); interlace = data[12].toInt() }
            "PLTE" -> plte = data
            "IDAT" -> idat.add(data)
            "IEND" -> break
        }
        off += 12 + len
    }
    require(bitDepth == 8) { "unsupported PNG bit depth $bitDepth (only 8-bit is pixel-exact here)" }
    require(interlace == 0) { "interlaced PNG not supported by the exact decoder" }
    val srcCh = mapOf(0 to 1, 2 to 3, 3 to 1, 4 to 2, 6 to 4)[colorType] ?: throw IllegalArgumentException("unsupported PNG colour type $colorType")
    val z = ByteArray(idat.sumOf { it.size }); var zo = 0
    for (p in idat) { System.arraycopy(p, 0, z, zo, p.size); zo += p.size }
    val inflater = Inflater(); inflater.setInput(z)
    val stride = width * srcCh
    val raw = ByteArray((stride + 1) * height + 1024)
    var rawLen = 0
    while (!inflater.finished()) { val n = inflater.inflate(raw, rawLen, raw.size - rawLen); if (n == 0) break; rawLen += n }
    inflater.end()
    val unfiltered = ByteArray(stride * height)
    var pos = 0
    for (y in 0 until height) {
        val filter = raw[pos++].toInt() and 0xff
        for (x in 0 until stride) {
            val left = if (x >= srcCh) unfiltered[y * stride + x - srcCh].toInt() and 0xff else 0
            val up = if (y > 0) unfiltered[(y - 1) * stride + x].toInt() and 0xff else 0
            val upLeft = if (y > 0 && x >= srcCh) unfiltered[(y - 1) * stride + x - srcCh].toInt() and 0xff else 0
            var v = raw[pos + x].toInt() and 0xff
            v = when (filter) {
                0 -> v; 1 -> v + left; 2 -> v + up; 3 -> v + ((left + up) ushr 1); 4 -> v + paeth(left, up, upLeft)
                else -> throw IllegalArgumentException("unknown PNG filter $filter")
            }
            unfiltered[y * stride + x] = (v and 0xff).toByte()
        }
        pos += stride
    }
    if (colorType == 2 || colorType == 6) return ImageData(unfiltered, width, height, srcCh)
    val pixels = ByteArray(width * height * 3)
    for (i in 0 until width * height) {
        val (r, g, b) = if (colorType == 3) {
            val idx = (unfiltered[i].toInt() and 0xff) * 3
            Triple(plte!![idx], plte[idx + 1], plte[idx + 2])
        } else { val v = unfiltered[i * srcCh]; Triple(v, v, v) }
        pixels[i * 3] = r; pixels[i * 3 + 1] = g; pixels[i * 3 + 2] = b
    }
    return ImageData(pixels, width, height, 3)
}
private fun be32(b: ByteArray, off: Int) =
    ((b[off].toInt() and 0xff) shl 24) or ((b[off + 1].toInt() and 0xff) shl 16) or
        ((b[off + 2].toInt() and 0xff) shl 8) or (b[off + 3].toInt() and 0xff)
