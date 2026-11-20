package com.opticipher

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.net.Uri
import android.provider.DocumentsContract
import androidx.core.app.NotificationCompat
import androidx.documentfile.provider.DocumentFile
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Operation
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.currentCoroutineContext
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/**
 * Two independent SAF folder-watch jobs: one encrypts incoming plain PNGs and
 * one decrypts incoming OptiCipher PNGs.  A SAF tree grant is the Android
 * folder permission; it is scoped to the selected folder and survives reboot.
 */
object FolderWatcher {
    const val ENCRYPT = "encrypt"
    const val DECRYPT = "decrypt"
    val MODES = listOf(ENCRYPT, DECRYPT)
    private const val PREFS = "folder_watch"
    private const val INBOX = "inbox_uri"
    private const val OUT = "out_uri"
    private const val REMEMBER = "remember"
    private const val MOVE = "move_original"
    private const val WATCHING = "watching"
    private const val INTERVAL = "interval_minutes"
    private const val EXISTING = "process_existing"
    private const val CONFLICT = "conflict" // skip or overwrite; background cannot prompt
    private const val PROCESSED = "processed"

    private fun key(mode: String, name: String) = "${mode}_$name"
    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun work(mode: String) = "opticipher-${mode}-folder-watch"
    private fun nowWork(mode: String) = "${work(mode)}-now"

    fun setInbox(ctx: Context, mode: String, uri: Uri) = prefs(ctx).edit().putString(key(mode, INBOX), uri.toString()).apply()
    fun getInbox(ctx: Context, mode: String): Uri? = prefs(ctx).getString(key(mode, INBOX), null)?.let(Uri::parse)
    fun setOutputTree(ctx: Context, mode: String, uri: Uri) = prefs(ctx).edit().putString(key(mode, OUT), uri.toString()).apply()
    fun getOutputTree(ctx: Context, mode: String): Uri? = prefs(ctx).getString(key(mode, OUT), null)?.let(Uri::parse)
    fun setRememberPassphrase(ctx: Context, mode: String, on: Boolean) = prefs(ctx).edit().putBoolean(key(mode, REMEMBER), on).apply()
    fun isRemembering(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, REMEMBER), false)
    fun isMoveOriginal(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, MOVE), false)
    fun setIntervalMinutes(ctx: Context, mode: String, minutes: Int) = prefs(ctx).edit().putInt(key(mode, INTERVAL), minutes).apply()
    fun getIntervalMinutes(ctx: Context, mode: String) = prefs(ctx).getInt(key(mode, INTERVAL), 15).coerceAtLeast(15)
    fun isWeekly(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, "weekly"), false)
    fun setWeekly(ctx: Context, mode: String, day: Int, hour: Int, minute: Int) {
        prefs(ctx).edit().putBoolean(key(mode, "weekly"), true).putInt(key(mode, "day"), day)
            .putInt(key(mode, "hour"), hour).putInt(key(mode, "minute"), minute).apply()
    }
    fun setIntervalSchedule(ctx: Context, mode: String) = prefs(ctx).edit().putBoolean(key(mode, "weekly"), false).apply()
    internal fun weeklyTime(ctx: Context, mode: String): WeeklyTime {
        val p = prefs(ctx)
        return WeeklyTime(p.getInt(key(mode, "day"), 2).coerceIn(1, 7),
            p.getInt(key(mode, "hour"), 9).coerceIn(0, 23), p.getInt(key(mode, "minute"), 0).coerceIn(0, 59))
    }
    fun weeklyLabel(ctx: Context, mode: String): String {
        val time = weeklyTime(ctx, mode)
        val day = java.text.DateFormatSymbols().weekdays[time.day]
        val local = java.time.LocalTime.of(time.hour, time.minute)
        val format = java.time.format.DateTimeFormatter.ofPattern(if (android.text.format.DateFormat.is24HourFormat(ctx)) "HH:mm" else "h:mm a")
        return "Every $day at ${local.format(format)}"
    }
    fun setProcessExisting(ctx: Context, mode: String, on: Boolean) = prefs(ctx).edit().putBoolean(key(mode, EXISTING), on).apply()
    fun processExisting(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, EXISTING), true)
    fun setConflictPolicy(ctx: Context, mode: String, policy: String) = prefs(ctx).edit().putString(key(mode, CONFLICT), policy).apply()
    fun getConflictPolicy(ctx: Context, mode: String) = prefs(ctx).getString(key(mode, CONFLICT), "skip") ?: "skip"
    fun isWatching(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, WATCHING), false) && getInbox(ctx, mode) != null

    /**
     * EncryptedSharedPreferences can fail after a device restore or keystore
     * reset (the master key is intentionally not backed up). Treat that as
     * "no stored passphrase" instead of crashing the app or the worker.
     */
    private fun encPrefs(ctx: Context): android.content.SharedPreferences? = try {
        val masterKey = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        EncryptedSharedPreferences.create(ctx, "opticipher_secrets", masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
    } catch (_: Exception) { null }

    /** Returns false when the passphrase could not be stored securely. */
    fun storePassphraseIfEnabled(ctx: Context, mode: String, passphrase: String): Boolean {
        if (!isRemembering(ctx, mode)) return false
        return try {
            val prefs = encPrefs(ctx) ?: return false
            prefs.edit().putString("${mode}_watch_passphrase", passphrase).commit()
        } catch (_: Exception) { false }
    }

    fun restorePassphraseIfEnabled(ctx: Context, mode: String): String? {
        if (!isRemembering(ctx, mode)) return null
        return try { encPrefs(ctx)?.getString("${mode}_watch_passphrase", null) } catch (_: Exception) { null }
    }

    /** Forget a remembered passphrase when the user turns "Remember" off. */
    fun clearStoredPassphrase(ctx: Context, mode: String) {
        try { encPrefs(ctx)?.edit()?.remove("${mode}_watch_passphrase")?.apply() } catch (_: Exception) { }
    }

    /** Mark files already in the selected folder as intentionally ignored. */
    fun markExistingProcessed(ctx: Context, mode: String) {
        val tree = getInbox(ctx, mode)?.let { DocumentFile.fromTreeUri(ctx, it) } ?: return
        val processed = processed(ctx, mode)
        tree.listFiles().filter { it.isFile && ImageFormats.isSupported(it.name) }
            .forEach { processed.add(it.uri.toString()) }
        saveProcessed(ctx, mode, processed)
    }

    /** Clear previous scan results so "Include existing" really reprocesses the folder. */
    fun resetProcessed(ctx: Context, mode: String) = saveProcessed(ctx, mode, emptySet())

    fun startWatching(ctx: Context, mode: String) {
        if (getInbox(ctx, mode) == null) return
        prefs(ctx).edit().putBoolean(key(mode, WATCHING), true).apply()
        val app = ctx.applicationContext
        val manager = WorkManager.getInstance(app)
        WeeklyWatch.reset(app, mode)
        if (isWeekly(app, mode)) {
            manager.cancelUniqueWork(work(mode))
            return
        }
        enqueue(app, mode, replace = true)
        val interval = getIntervalMinutes(app, mode).toLong()
        val request = PeriodicWorkRequestBuilder<WatchWorker>(interval, TimeUnit.MINUTES)
            .setInputData(Data.Builder().putString("mode", mode).build())
            .setInitialDelay(interval, TimeUnit.MINUTES)
            .build()
        manager.enqueueUniquePeriodicWork(work(mode), ExistingPeriodicWorkPolicy.CANCEL_AND_REENQUEUE, request)
    }

    fun stopWatching(ctx: Context, mode: String) {
        prefs(ctx).edit().putBoolean(key(mode, WATCHING), false).apply()
        WeeklyWatch.reset(ctx, mode)
        WorkManager.getInstance(ctx).cancelUniqueWork(work(mode))
        WorkManager.getInstance(ctx).cancelUniqueWork(nowWork(mode))
    }

    fun enqueue(ctx: Context, mode: String, replace: Boolean = false): Operation {
        val request = OneTimeWorkRequestBuilder<WatchWorker>()
            .setInputData(Data.Builder().putString("mode", mode).build()).build()
        // REPLACE cancels an active large-photo encryption every time the
        // foreground watcher polls. KEEP lets it finish; the next poll catches
        // anything that arrived during the scan.
        val policy = if (replace) ExistingWorkPolicy.REPLACE else ExistingWorkPolicy.KEEP
        return WorkManager.getInstance(ctx).enqueueUniqueWork(nowWork(mode), policy, request)
    }

    fun progress(ctx: Context, mode: String, text: String, current: Int, total: Int, done: Boolean = false) {
        prefs(ctx).edit().putString("${mode}_live", text).apply()
        val manager = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel("watch_progress", "Watch progress", NotificationManager.IMPORTANCE_LOW))
        val note = NotificationCompat.Builder(ctx, "watch_progress").setSmallIcon(R.drawable.ic_shield)
            .setContentTitle("Auto-$mode").setContentText(text).setOnlyAlertOnce(true)
            .setOngoing(!done).setAutoCancel(done)
            .setProgress(if (done) 0 else total.coerceAtLeast(1), if (done) 0 else current, !done && total == 0).build()
        try { manager.notify(if (mode == ENCRYPT) 84 else 85, note) } catch (_: SecurityException) { }
    }

    internal fun processed(ctx: Context, mode: String): MutableSet<String> =
        prefs(ctx).getStringSet(key(mode, PROCESSED), emptySet())!!.toMutableSet()
    internal fun saveProcessed(ctx: Context, mode: String, items: Set<String>) =
        prefs(ctx).edit().putStringSet(key(mode, PROCESSED), items.toSet()).apply()

    fun log(ctx: Context, text: String) = JobJournal.get(ctx).log("[INFO] $text")
}

class WatchWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val mode = inputData.getString("mode") ?: return@withContext Result.failure()
        val lock = locks[mode] ?: return@withContext Result.failure()
        lock.withLock { scan(mode) }
    }

    private suspend fun scan(mode: String): Result {
        val ctx = applicationContext
        val journal = JobJournal.get(ctx)
        val jobName = "Auto-$mode"
        var jobId: String? = null
        try {
            if (!FolderWatcher.isWatching(ctx, mode)) return Result.success()
            val inboxUri = FolderWatcher.getInbox(ctx, mode) ?: return Result.success()
            val scanId = journal.begin(jobName, "Scan started")
            jobId = scanId
            val passphrase = FolderWatcher.restorePassphraseIfEnabled(ctx, mode)
            check(!passphrase.isNullOrEmpty()) { "Remember a passphrase to run this watch" }
            val inbox = DocumentFile.fromTreeUri(ctx, inboxUri) ?: error("Input folder unavailable")
            check(inbox.isDirectory && inbox.canRead()) { "Input folder unavailable. Choose it again to restore access." }
            val outputUri = FolderWatcher.getOutputTree(ctx, mode)
            val overwrite = FolderWatcher.getConflictPolicy(ctx, mode) == "overwrite"
            val processed = FolderWatcher.processed(ctx, mode)
            val sources = inbox.listFiles().filter { source ->
                val name = source.name
                name != null && !name.startsWith(".opticipher-") &&
                    source.isFile && source.uri.toString() !in processed &&
                    if (mode == FolderWatcher.ENCRYPT) ImageFormats.isSupported(name)
                    else name.endsWith(".png", ignoreCase = true)
            }
            var written = 0
            var skipped = 0
            var failed = 0
            var stopped = false
            FolderWatcher.progress(ctx, mode, "Checking ${sources.size} files", 0, sources.size)
            for ((index, source) in sources.withIndex()) {
                currentCoroutineContext().ensureActive()
                if (!FolderWatcher.isWatching(ctx, mode) || FolderWatcher.getInbox(ctx, mode) != inboxUri ||
                    FolderWatcher.getOutputTree(ctx, mode) != outputUri) {
                    stopped = true
                    break
                }
                val name = source.name ?: continue
                FolderWatcher.progress(ctx, mode, "Processing ${index + 1}/${sources.size} · $name", index, sources.size)
                try {
                    val image = ImageInput.decode(ctx, source.uri)
                    val encrypt = mode == FolderWatcher.ENCRYPT
                    if (encrypt == hasOptiCipherHeader(image)) {
                        skipped++
                        journal.outcome(scanId, FileOutcome(name, "SKIP", if (encrypt) "Already encrypted" else "No OptiCipher header"))
                    } else {
                        val result = if (encrypt) encryptImage(image, passphrase) else decryptImage(image, passphrase)
                        val stem = name.substringBeforeLast('.')
                        val outputName = if (encrypt) "${stem}_encrypted.png" else "${stem.removeSuffix("_encrypted")}.png"
                        val png = encodePNG(result.pixels, result.width, result.height, result.channels, compress = !encrypt)
                        currentCoroutineContext().ensureActive()
                        if (!FolderWatcher.isWatching(ctx, mode) || FolderWatcher.getInbox(ctx, mode) != inboxUri ||
                            FolderWatcher.getOutputTree(ctx, mode) != outputUri) {
                            stopped = true
                            break
                        }
                        val output = ImageOutput.write(ctx, outputUri, outputName, png,
                            if (overwrite) OutputConflict.OVERWRITE else OutputConflict.SKIP, source = source.uri)
                        if (output == null) {
                            skipped++
                            journal.outcome(scanId, FileOutcome(name, "SKIP", "$outputName already exists"))
                        } else {
                            written++
                            journal.outcome(scanId, FileOutcome(name, "OK", "Saved ${output.name}"))
                            if (FolderWatcher.isMoveOriginal(ctx, mode)) {
                                if (!runCatching {
                                    DocumentsContract.deleteDocument(ctx.contentResolver, source.uri)
                                }.getOrDefault(false)) FolderWatcher.log(ctx, "Could not move original $name")
                            }
                        }
                    }
                    processed.add(source.uri.toString())
                    if (FolderWatcher.getInbox(ctx, mode) == inboxUri) FolderWatcher.saveProcessed(ctx, mode, processed)
                } catch (error: CancellationException) {
                    throw error
                } catch (error: Exception) {
                    failed++
                    journal.outcome(scanId, FileOutcome(name, "ERROR", error.message ?: "Unknown error"))
                }
            }
            val summary = (if (stopped) "Stopped" else "Complete") + " · $written written, $skipped skipped, $failed failed"
            FolderWatcher.progress(ctx, mode, summary, sources.size, sources.size, true)
            journal.finish(scanId, jobName, summary)
            return Result.success()
        } catch (error: CancellationException) {
            jobId?.let { journal.finish(it, jobName, "Scan stopped") }
            throw error
        } catch (error: Exception) {
            val message = error.message ?: "Unknown error"
            FolderWatcher.progress(ctx, mode, "Failed · $message", 0, 0, true)
            jobId?.let { journal.finish(it, jobName, "Failed · $message") }
                ?: FolderWatcher.log(ctx, "Auto-$mode failed · $message")
            return Result.success()
        }
    }

    companion object {
        private val locks = FolderWatcher.MODES.associateWith { Mutex() }
    }
}
