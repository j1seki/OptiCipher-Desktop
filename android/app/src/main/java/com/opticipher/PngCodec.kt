package com.opticipher

import java.io.ByteArrayOutputStream
import java.io.OutputStream
import java.util.zip.CRC32
import java.util.zip.Deflater
import java.util.zip.DeflaterOutputStream
import java.util.zip.Inflater

// Lossless PNG codec (8-bit, non-interlaced) using java.util.zip — pixel-exact
// for RGB/RGBA ciphertexts. Greyscale/palette expand to RGB like Pillow.
private val PNG_SIG = byteArrayOf(137.toByte(), 80, 78, 71, 13, 10, 26, 10)
private fun crc32(buf: ByteArray, off: Int, len: Int): Int =
    CRC32().apply { update(buf, off, len) }.value.toInt()

private fun chunk(type: String, data: ByteArray): ByteArray {
    val out = ByteArray(12 + data.size)
    val tb = type.toByteArray(Charsets.US_ASCII)
    fun be(off: Int, v: Int) { out[off] = (v ushr 24).toByte(); out[off + 1] = (v ushr 16).toByte(); out[off + 2] = (v ushr 8).toByte(); out[off + 3] = v.toByte() }
    be(0, data.size); System.arraycopy(tb, 0, out, 4, 4); System.arraycopy(data, 0, out, 8, data.size)
    be(8 + data.size, crc32(out, 4, 4 + data.size))
    return out
}

fun encodePNG(pixels: ByteArray, width: Int, height: Int, channels: Int, compress: Boolean = true): ByteArray {
    val colorType = if (channels == 4) 6 else 2
    val ihdr = ByteArray(13)
    fun be(off: Int, v: Int) { ihdr[off] = (v ushr 24).toByte(); ihdr[off + 1] = (v ushr 16).toByte(); ihdr[off + 2] = (v ushr 8).toByte(); ihdr[off + 3] = v.toByte() }
    be(0, width); be(4, height); ihdr[8] = 8; ihdr[9] = colorType.toByte()
    val stride = width * channels
    val output = ByteArrayOutputStream()
    output.write(PNG_SIG)
    output.write(chunk("IHDR", ihdr))
    val idat = object : OutputStream() {
        override fun write(value: Int) = write(byteArrayOf(value.toByte()), 0, 1)
        override fun write(data: ByteArray, offset: Int, size: Int) {
            output.write(chunk("IDAT", data.copyOfRange(offset, offset + size)))
        }
    }
    val deflater = Deflater(if (compress) 6 else Deflater.NO_COMPRESSION)
    try {
        DeflaterOutputStream(idat, deflater, 64 * 1024).use { stream ->
            for (y in 0 until height) {
                stream.write(0) // Unfiltered row
                stream.write(pixels, y * stride, stride)
            }
        }
    } finally {
        deflater.end()
    }
    output.write(chunk("IEND", ByteArray(0)))
    return output.toByteArray()
}

private fun paeth(a: Int, b: Int, c: Int): Int {
    val p = a + b - c; val pa = Math.abs(p - a); val pb = Math.abs(p - b); val pc = Math.abs(p - c)
    return if (pa <= pb && pa <= pc) a else if (pb <= pc) b else c
}

fun decodePNG(bytes: ByteArray): ImageData {
    require(bytes.size >= 8 && PNG_SIG.indices.all { bytes[it] == PNG_SIG[it] }) { "not a PNG file" }
    var off = 8; var width = 0; var height = 0; var bitDepth = 0; var colorType = 0; var interlace = 0
    var ended = false
    var plte: ByteArray? = null; val idat = mutableListOf<ByteArray>()
    while (off <= bytes.size - 12) {
        val len = be32(bytes, off)
        require(len in 0..(bytes.size - off - 12)) { "truncated PNG chunk" }
        val type = String(bytes, off + 4, 4, Charsets.US_ASCII)
        require(crc32(bytes, off + 4, len + 4) == be32(bytes, off + 8 + len)) { "invalid PNG chunk checksum" }
        val data = bytes.copyOfRange(off + 8, off + 8 + len)
        when (type) {
            "IHDR" -> {
                require(off == 8 && len == 13) { "invalid PNG header" }
                width = be32(data, 0)
                height = be32(data, 4)
                bitDepth = data[8].toInt()
                colorType = data[9].toInt()
                interlace = data[12].toInt()
            }
            "PLTE" -> plte = data
            "IDAT" -> idat.add(data)
            "IEND" -> { ended = len == 0; break }
        }
        off += 12 + len
    }
    require(bitDepth == 8) { "unsupported PNG bit depth $bitDepth (only 8-bit is pixel-exact here)" }
    require(interlace == 0) { "interlaced PNG not supported by the exact decoder" }
    require(ended && idat.isNotEmpty()) { "incomplete PNG data" }
    val srcCh = mapOf(0 to 1, 2 to 3, 3 to 1, 4 to 2, 6 to 4)[colorType] ?: throw IllegalArgumentException("unsupported PNG colour type $colorType")
    // RGB/RGBA ciphertext can exceed the source limit by its header strip.
    require(width in 1..MAX_PROCESS_PIXELS) { "invalid PNG width" }
    val stripPixels = if (colorType == 2 || colorType == 6) rowsNeeded(HEADER_SIZE, width, srcCh).toLong() * width else 0L
    requireProcessableImage(width, height, MAX_PROCESS_PIXELS + stripPixels)
    val z = ByteArray(idat.sumOf { it.size }); var zo = 0
    for (p in idat) { System.arraycopy(p, 0, z, zo, p.size); zo += p.size }
    val stride = width * srcCh
    val expectedSize = (stride + 1) * height
    val raw = ByteArray(expectedSize + 1)
    val inflater = Inflater()
    try {
        inflater.setInput(z)
        var rawLen = 0
        while (!inflater.finished() && rawLen < raw.size) {
            val count = inflater.inflate(raw, rawLen, raw.size - rawLen)
            if (count == 0) break
            rawLen += count
        }
        require(inflater.finished() && rawLen == expectedSize) { "PNG data does not match its dimensions" }
    } finally {
        inflater.end()
    }
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
