package com.opticipher

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.Build
import android.system.ErrnoException
import com.homesoft.photo.libraw.LibRaw
import java.io.File
import java.nio.ByteBuffer

/**
 * Shared decoder for manual imports and folder watching.
 * PNG ciphertext uses the exact codec; camera RAW uses LibRaw; modern Android
 * uses ImageDecoder for HEIF/AVIF and other platform image formats.
 */
object ImageInput {
    fun decode(context: Context, uri: Uri): ImageData {
        val name = queryName(context, uri)
        if (ImageFormats.isRaw(name)) {
            val descriptor = context.contentResolver.openFileDescriptor(uri, "r")
                ?: error("cannot open RAW image")
            descriptor.use { pfd ->
                LibRaw().use { raw ->
                    val status = raw.openFd(pfd.fileDescriptor.fd)
                    if (status != 0) throw ErrnoException("LibRaw openFd", status)
                    val bitmap = raw.decodeBitmap(BitmapFactory.Options().apply {
                        inPreferredConfig = Bitmap.Config.ARGB_8888
                    })
                    return bitmapToImage(bitmap)
                }
            }
        }
        val bytes = context.contentResolver.openInputStream(uri)?.use { it.readBytes() }
            ?: error("cannot read image")
        return decodeBytes(context, bytes, name)
    }

    fun decodeBytes(context: Context, bytes: ByteArray, name: String): ImageData {
        if (bytes.size >= 8 && bytes[0] == 137.toByte() &&
            bytes[1] == 80.toByte() && bytes[2] == 78.toByte() && bytes[3] == 71.toByte()
        ) return decodePNG(bytes)

        if (ImageFormats.isRaw(name)) {
            val extension = name.substringAfterLast('.', "raw").let { ".$it" }
            val temp = File.createTempFile("opticipher-raw-", extension, context.cacheDir)
            try {
                temp.writeBytes(bytes)
                LibRaw().use { raw ->
                    val bitmap = raw.decodeBitmap(temp.absolutePath, BitmapFactory.Options().apply {
                        inPreferredConfig = Bitmap.Config.ARGB_8888
                    })
                    return bitmapToImage(bitmap)
                }
            } finally {
                temp.delete()
            }
        }

        val bitmap = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            try {
                ImageDecoder.decodeBitmap(ImageDecoder.createSource(ByteBuffer.wrap(bytes))) { decoder, _, _ ->
                    decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                    decoder.isMutableRequired = false
                }
            } catch (error: Exception) {
                throw IllegalArgumentException(
                    "Android could not decode this image. HEIC/HEIF requires Android 9+; AVIF requires Android 12+. Details: ${error.message}",
                    error
                )
            }
        } else {
            BitmapFactory.decodeByteArray(bytes, 0, bytes.size)
                ?: error("unsupported image format on this Android version")
        }
        return bitmapToImage(bitmap)
    }

    private fun bitmapToImage(source: Bitmap): ImageData {
        val bitmap = if (source.config == Bitmap.Config.HARDWARE)
            source.copy(Bitmap.Config.ARGB_8888, false) ?: error("could not copy decoded image")
        else source
        try {
            requireProcessableImage(bitmap.width, bitmap.height)
            val argb = IntArray(bitmap.width * bitmap.height)
            bitmap.getPixels(argb, 0, bitmap.width, 0, 0, bitmap.width, bitmap.height)
            val opaque = argb.all { it ushr 24 == 0xff }
            val channels = if (opaque) 3 else 4
            val pixels = ByteArray(argb.size * channels)
            for (index in argb.indices) {
                pixels[index * channels] = ((argb[index] ushr 16) and 255).toByte()
                pixels[index * channels + 1] = ((argb[index] ushr 8) and 255).toByte()
                pixels[index * channels + 2] = (argb[index] and 255).toByte()
                if (!opaque) pixels[index * 4 + 3] = ((argb[index] ushr 24) and 255).toByte()
            }
            return ImageData(pixels, bitmap.width, bitmap.height, channels)
        } finally {
            if (bitmap !== source) bitmap.recycle()
            source.recycle()
        }
    }

    private fun queryName(context: Context, uri: Uri): String {
        val cursor = context.contentResolver.query(
            uri, arrayOf(android.provider.OpenableColumns.DISPLAY_NAME), null, null, null
        )
        return cursor?.use { if (it.moveToFirst()) it.getString(0) else null }
            ?: uri.lastPathSegment.orEmpty()
    }
}
