package com.opticipher

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.graphics.Bitmap
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.documentfile.provider.DocumentFile
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import java.util.UUID

internal data class BatchItem(val input: String, val message: String, val output: SavedImage? = null)

internal data class BatchState(
    val id: String,
    val title: String,
    val detail: String,
    val completed: Int,
    val total: Int,
    val done: Boolean,
    val results: List<BatchItem> = emptyList(),
    val preview: Bitmap? = null,
    val analysis: ImageAnalysis? = null,
    val canStop: Boolean = false,
)

internal class BatchSession : ViewModel() {
    val state = MutableLiveData<BatchState>()
    var sftp: SftpProfile? = null
    @Volatile private var stopRequested = false
    val isStopping: Boolean get() = stopRequested

    fun stopAfterCurrentFile() {
        stopRequested = true
    }

    fun start(ctx: Context, files: List<Uri>, mode: String, passphrase: String, iterations: Int,
              privateOutput: Boolean, outputUri: Uri?, mirror: SftpProfile? = null) {
        if (state.value?.done == false) return
        stopRequested = false
        val id = UUID.randomUUID().toString()
        val title = mode.replaceFirstChar { it.uppercase() }
        val jobName = "Batch $title"
        val journal = JobJournal.get(ctx)
        val canStop = mode != "analyze" && files.size > 1
        state.value = BatchState(id, "Batch $title", "Starting ${files.size} files", 0, files.size, false, canStop = canStop)
        viewModelScope.launch(Dispatchers.IO) {
            journal.begin(jobName, "Started · ${files.size} file(s)", id)
            val results = mutableListOf<BatchItem>()
            var preview: Bitmap? = null
            var analysis: ImageAnalysis? = null
            var succeeded = 0
            fun record(item: BatchItem, status: String = "OK") {
                results.add(item)
                journal.outcome(id, FileOutcome(item.input, status, item.message))
            }
            fun update(message: String, detail: String, done: Boolean = false) {
                val progress = BatchState(id, message, detail, results.size, files.size, done, results.toList(),
                    preview, analysis, canStop = canStop && !done)
                publish(ctx, progress)
                state.postValue(progress)
                if (done) journal.finish(id, jobName, "$message · $detail")
            }

            if (mode == "analyze") {
                update("Analyzing", "Reading the selected images")
                try {
                    val first = ImageInput.decode(ctx, files.first())
                    val second = files.getOrNull(1)?.let { ImageInput.decode(ctx, it) }
                    analysis = analyzeImages(first, second)
                    preview = thumbnail(first)
                    for (uri in files) record(BatchItem(displayName(ctx, uri), "Analyzed"))
                    val mean = analysis.channels.map { it.entropy }.average()
                    val comparison = if (analysis.npcr == null) "" else " · NPCR %.2f%% · UACI %.2f%%".format(analysis.npcr, analysis.uaci)
                    val detail = "${files.size} image(s) · Mean entropy %.4f bits/byte".format(mean) + comparison
                    update("Analysis complete", detail, done = true)
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    val detail = error.message ?: "Could not analyze these images"
                    journal.outcome(id, FileOutcome("Analysis", "ERROR", detail))
                    update("Analysis failed", detail, done = true)
                }
                return@launch
            }
            for (uri in files) {
                if (stopRequested) break
                ensureActive()
                val name = displayName(ctx, uri)
                update("Batch $title", "Processing ${results.size + 1} of ${files.size} · $name")
                try {
                    val image = ImageInput.decode(ctx, uri)
                    if (mode == "verify") {
                        val verification = verifyImage(image, passphrase.ifEmpty { null })
                        val header = inspectImage(image)?.let {
                            "\nFormat v${it.version} · ${it.width}×${it.height} · ${it.channels} channels · " +
                                "${it.stripRows} header rows · ${it.iterations} PBKDF2 iterations"
                        }.orEmpty()
                        val digest = runCatching { fileDigest(ctx, uri) }.getOrNull()
                        val hash = digest?.let { "\nSHA-256 $it" }.orEmpty()
                        val status = if (verification.authenticated) "OK" else if (verification.status == "unauthenticated") "INFO" else "ERROR"
                        record(BatchItem(name, "[${verification.status}] ${verification.message}$header$hash"), status)
                        if (verification.authenticated || verification.status == "unauthenticated") succeeded++
                    } else {
                        val encrypt = mode == "encrypt"
                        val result = if (encrypt) encryptImage(image, passphrase, iterations) else decryptImage(image, passphrase)
                        val stem = name.substringBeforeLast('.')
                        val outName = if (encrypt) "${stem}_encrypted.png" else "${stem.removeSuffix("_encrypted")}.png"
                        val png = encodePNG(result.pixels, result.width, result.height, result.channels, compress = !encrypt)
                        ensureActive()
                        val output = checkNotNull(ImageOutput.write(ctx, outputUri, outName, png,
                            OutputConflict.KEEP_BOTH, privateOutput, source = uri))
                        preview = thumbnail(result)
                        try {
                            val remote = mirror?.let { SftpMirror.upload(ctx, it, output.name, png) }
                            val message = if (remote == null) "Saved ${output.name} · Tap to share"
                                else "Saved ${output.name} · SFTP copied to $remote · Tap to share local file"
                            record(BatchItem(name, message, output))
                            succeeded++
                        } catch (error: Exception) {
                            val message = error.message ?: "Transfer failed"
                            record(BatchItem(name, "Saved ${output.name} locally · SFTP failed: $message · Tap to share", output), "ERROR")
                        }
                    }
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    val details = error.message ?: "Unknown error"
                    record(BatchItem(name, "Error · $details"), "ERROR")
                }
            }
            val skipped = files.size - results.size
            val summary = "$succeeded of ${files.size} succeeded" +
                if (skipped > 0) " · $skipped unprocessed" else ""
            for (uri in files.drop(results.size)) {
                journal.outcome(id, FileOutcome(displayName(ctx, uri), "SKIP", "Stopped before processing"))
            }
            update(if (skipped > 0) "Batch stopped" else "Batch complete", summary, done = true)
        }.invokeOnCompletion { cause ->
            if (cause != null) journal.finish(id, jobName, "Interrupted before completion")
        }
    }

    fun lastStatus(ctx: Context): BatchState? {
        if (state.value != null) return null
        val p = prefs(ctx)
        val title = p.getString("live_title", null) ?: return null
        val completed = p.getInt("live_current", 0)
        val total = p.getInt("live_total", 0)
        val done = p.getBoolean("live_done", completed >= total)
        return BatchState("", if (done) title else "Batch interrupted",
            if (done) p.getString("live_detail", "").orEmpty() else "$completed of $total processed. Re-add files to retry.",
            completed, total, true)
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences("scheduled_batch", Context.MODE_PRIVATE)

    private fun publish(ctx: Context, state: BatchState) {
        prefs(ctx).edit().putString("live_title", state.title).putString("live_detail", state.detail)
            .putInt("live_current", state.completed).putInt("live_total", state.total)
            .putBoolean("live_done", state.done).apply()
        val manager = ctx.getSystemService(NotificationManager::class.java)
        manager.createNotificationChannel(NotificationChannel("batch_progress", "Batch progress", NotificationManager.IMPORTANCE_LOW))
        val notification = NotificationCompat.Builder(ctx, "batch_progress")
            .setSmallIcon(R.drawable.ic_shield).setContentTitle(state.title).setContentText(state.detail)
            .setStyle(NotificationCompat.BigTextStyle().bigText(state.detail)).setOnlyAlertOnce(true)
            .setOngoing(!state.done).setAutoCancel(state.done)
            .setProgress(if (state.done) 0 else state.total, if (state.done) 0 else state.completed, false)
            .build()
        try { manager.notify(83, notification) } catch (_: SecurityException) { }
    }

    private fun displayName(ctx: Context, uri: Uri): String {
        val fallback = uri.lastPathSegment?.substringAfterLast('/')?.takeIf { it.isNotBlank() } ?: "image"
        if (uri.scheme == "raw" || uri.scheme == "file") return fallback
        return runCatching { DocumentFile.fromSingleUri(ctx, uri)?.name }.getOrNull() ?: fallback
    }

    private fun fileDigest(ctx: Context, uri: Uri): String {
        val digest = java.security.MessageDigest.getInstance("SHA-256")
        val stream = ctx.contentResolver.openInputStream(uri) ?: error("Cannot reopen the image to calculate its hash")
        stream.use {
            val buffer = ByteArray(64 * 1024)
            while (true) {
                val count = it.read(buffer)
                if (count < 0) break
                digest.update(buffer, 0, count)
            }
        }
        return digest.digest().joinToString("") { "%02x".format(it) }
    }

    private fun thumbnail(image: ImageData): Bitmap {
        val scale = minOf(1.0, 640.0 / maxOf(image.width, image.height))
        val width = (image.width * scale).toInt().coerceAtLeast(1)
        val height = (image.height * scale).toInt().coerceAtLeast(1)
        val argb = IntArray(width * height)
        for (y in 0 until height) {
            for (x in 0 until width) {
                val sourceY = (y.toLong() * image.height / height).toInt()
                val sourceX = (x.toLong() * image.width / width).toInt()
                val offset = (sourceY * image.width + sourceX) * image.channels
                val red = image.pixels[offset].toInt() and 255
                val green = image.pixels[offset + 1].toInt() and 255
                val blue = image.pixels[offset + 2].toInt() and 255
                val alpha = if (image.channels == 4) image.pixels[offset + 3].toInt() and 255 else 255
                argb[y * width + x] = (alpha shl 24) or (red shl 16) or (green shl 8) or blue
            }
        }
        return Bitmap.createBitmap(argb, width, height, Bitmap.Config.ARGB_8888)
    }
}
