package com.opticipher

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.database.ContentObserver
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.TimeUnit

/**
 * Two independent SAF folder-watch jobs: one encrypts incoming plain PNGs and
 * one decrypts incoming OptiCipher PNGs.  A SAF tree grant is the Android
 * folder permission; it is scoped to the selected folder and survives reboot.
 */
object FolderWatcher {
    const val ENCRYPT = "encrypt"
    const val DECRYPT = "decrypt"
    private const val PREFS = "folder_watch"
    private const val INBOX = "inbox_uri"
    private const val OUT = "out_uri"
    private const val REMEMBER = "remember"
    private const val MOVE = "move_original"
    private const val WATCHING = "watching"
    private const val INTERVAL = "interval_minutes" // 0: ContentObserver only
    private const val EXISTING = "process_existing"
    private const val CONFLICT = "conflict" // skip or overwrite; background cannot prompt
    private const val PROCESSED = "processed"
    private val observers = mutableMapOf<String, ContentObserver>()

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
    fun setMoveOriginal(ctx: Context, mode: String, on: Boolean) = prefs(ctx).edit().putBoolean(key(mode, MOVE), on).apply()
    fun isMoveOriginal(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, MOVE), false)
    fun setIntervalMinutes(ctx: Context, mode: String, minutes: Int) = prefs(ctx).edit().putInt(key(mode, INTERVAL), minutes).apply()
    fun getIntervalMinutes(ctx: Context, mode: String) = prefs(ctx).getInt(key(mode, INTERVAL), 15)
    fun setProcessExisting(ctx: Context, mode: String, on: Boolean) = prefs(ctx).edit().putBoolean(key(mode, EXISTING), on).apply()
    fun processExisting(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, EXISTING), false)
    fun setConflictPolicy(ctx: Context, mode: String, policy: String) = prefs(ctx).edit().putString(key(mode, CONFLICT), policy).apply()
    fun getConflictPolicy(ctx: Context, mode: String) = prefs(ctx).getString(key(mode, CONFLICT), "skip") ?: "skip"
    fun isWatching(ctx: Context, mode: String) = prefs(ctx).getBoolean(key(mode, WATCHING), false) && getInbox(ctx, mode) != null

    private fun encPrefs(ctx: Context): android.content.SharedPreferences {
        val masterKey = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        return EncryptedSharedPreferences.create(ctx, "opticipher_secrets", masterKey,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
    }
    fun storePassphraseIfEnabled(ctx: Context, mode: String, passphrase: String) {
        if (isRemembering(ctx, mode)) encPrefs(ctx).edit().putString("${mode}_watch_passphrase", passphrase).apply()
    }
    fun restorePassphraseIfEnabled(ctx: Context, mode: String): String? = if (isRemembering(ctx, mode)) try {
        encPrefs(ctx).getString("${mode}_watch_passphrase", null)
    } catch (_: Exception) { null } else null

    /** Mark files already in the selected folder as intentionally ignored. */
    fun markExistingProcessed(ctx: Context, mode: String) {
        val tree = getInbox(ctx, mode)?.let { DocumentFile.fromTreeUri(ctx, it) } ?: return
        val processed = processed(ctx, mode)
        tree.listFiles().filter { it.isFile && it.name?.lowercase()?.endsWith(".png") == true }
            .forEach { processed.add(it.uri.toString()) }
        saveProcessed(ctx, mode, processed)
    }

    fun startWatching(ctx: Context, mode: String) {
        val inbox = getInbox(ctx, mode) ?: return
        prefs(ctx).edit().putBoolean(key(mode, WATCHING), true).apply()
        stopWatching(ctx, mode, keepFlag = true)
        val app = ctx.applicationContext
        val observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) = enqueue(app, mode)
        }
        observers[mode] = observer
        try { app.contentResolver.registerContentObserver(inbox, true, observer) } catch (_: Exception) { }
        enqueue(app, mode)
        val interval = getIntervalMinutes(app, mode)
        if (interval > 0) {
            val request = PeriodicWorkRequestBuilder<WatchWorker>(interval.toLong(), TimeUnit.MINUTES)
                .setInputData(Data.Builder().putString("mode", mode).build())
                .build()
            WorkManager.getInstance(app).enqueueUniquePeriodicWork(work(mode), ExistingPeriodicWorkPolicy.UPDATE, request)
        }
    }

    fun stopWatching(ctx: Context, mode: String, keepFlag: Boolean = false) {
        if (!keepFlag) prefs(ctx).edit().putBoolean(key(mode, WATCHING), false).apply()
        observers.remove(mode)?.let { try { ctx.contentResolver.unregisterContentObserver(it) } catch (_: Exception) { } }
        WorkManager.getInstance(ctx).cancelUniqueWork(work(mode))
        WorkManager.getInstance(ctx).cancelUniqueWork(nowWork(mode))
    }

    fun enqueue(ctx: Context, mode: String) {
        val request = OneTimeWorkRequestBuilder<WatchWorker>()
            .setInputData(Data.Builder().putString("mode", mode).build()).build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(nowWork(mode), ExistingWorkPolicy.REPLACE, request)
    }

    private fun processed(ctx: Context, mode: String): MutableSet<String> =
        prefs(ctx).getStringSet(key(mode, PROCESSED), emptySet())!!.toMutableSet()
    private fun saveProcessed(ctx: Context, mode: String, items: Set<String>) =
        prefs(ctx).edit().putStringSet(key(mode, PROCESSED), items).apply()

    fun notify(ctx: Context, text: String) {
        val notifications = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) notifications.createNotificationChannel(
            NotificationChannel("watch", "Folder watch", NotificationManager.IMPORTANCE_LOW))
        val notification = NotificationCompat.Builder(ctx, "watch").setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("OptiCipher").setContentText(text).setAutoCancel(true).build()
        try { notifications.notify(text.hashCode(), notification) } catch (_: Exception) { }
    }
}

class WatchWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        val mode = inputData.getString("mode") ?: FolderWatcher.ENCRYPT
        try {
            if (!FolderWatcher.isWatching(applicationContext, mode)) return@withContext Result.success()
            val inboxUri = FolderWatcher.getInbox(applicationContext, mode) ?: return@withContext Result.success()
            val passphrase = FolderWatcher.restorePassphraseIfEnabled(applicationContext, mode)
            if (passphrase.isNullOrEmpty()) {
                FolderWatcher.notify(applicationContext, "OptiCipher: ${mode} watch needs its remembered passphrase")
                return@withContext Result.success()
            }
            val inbox = DocumentFile.fromTreeUri(applicationContext, inboxUri) ?: return@withContext Result.success()
            val outTree = FolderWatcher.getOutputTree(applicationContext, mode)?.let { DocumentFile.fromTreeUri(applicationContext, it) }
            val processed = applicationContext.getSharedPreferences("folder_watch", Context.MODE_PRIVATE)
                .getStringSet("${mode}_processed", emptySet())!!.toMutableSet()
            var written = 0
            for (source in inbox.listFiles()) {
                if (!source.isFile || source.uri.toString() in processed || source.name?.lowercase()?.endsWith(".png") != true) continue
                val bytes = applicationContext.contentResolver.openInputStream(source.uri)?.use { it.readBytes() } ?: continue
                val image = try { decodePNG(bytes) } catch (_: Exception) { continue }
                val encrypted = isOptiCipher(image)
                // Encrypt only plaintext; decrypt only files that actually carry an OPTC header.
                if ((mode == FolderWatcher.ENCRYPT && encrypted) || (mode == FolderWatcher.DECRYPT && !encrypted)) {
                    processed.add(source.uri.toString()); continue
                }
                val result = if (mode == FolderWatcher.ENCRYPT) encryptImage(image, passphrase) else decryptImage(image, passphrase)
                val sourceStem = source.name!!.substringBeforeLast('.')
                val stem = if (mode == FolderWatcher.DECRYPT && sourceStem.endsWith("_encrypted")) sourceStem.removeSuffix("_encrypted") else sourceStem
                val outputName = if (mode == FolderWatcher.ENCRYPT) "${stem}_encrypted.png" else "$stem.png"
                val png = encodePNG(result.pixels, result.width, result.height, result.channels)
                val wrote = writeWatchOutput(outTree, outputName, png, mode)
                processed.add(source.uri.toString())
                if (wrote) {
                    written++
                    if (FolderWatcher.isMoveOriginal(applicationContext, mode)) try {
                        DocumentsContract.deleteDocument(applicationContext.contentResolver, source.uri)
                    } catch (_: Exception) { }
                }
            }
            applicationContext.getSharedPreferences("folder_watch", Context.MODE_PRIVATE).edit()
                .putStringSet("${mode}_processed", processed).apply()
            if (written > 0) FolderWatcher.notify(applicationContext, "OptiCipher: $written file(s) ${mode}ed by folder watch")
            Result.success()
        } catch (exception: Exception) {
            FolderWatcher.notify(applicationContext, "OptiCipher: $mode watch failed — ${exception.message}")
            Result.success()
        }
    }

    private fun writeWatchOutput(tree: DocumentFile?, name: String, png: ByteArray, mode: String): Boolean {
        if (tree != null) {
            val existing = tree.findFile(name)
            if (existing != null && FolderWatcher.getConflictPolicy(applicationContext, mode) == "skip") return false
            val target = existing ?: tree.createFile("image/png", name) ?: return false
            applicationContext.contentResolver.openOutputStream(target.uri, "wt")?.use { it.write(png) } ?: return false
            return true
        }
        val dir = File(applicationContext.getExternalFilesDir(null), "OptiCipher").apply { mkdirs() }
        val target = File(dir, name)
        if (target.exists() && FolderWatcher.getConflictPolicy(applicationContext, mode) == "skip") return false
        target.writeBytes(png)
        return true
    }

    private fun isOptiCipher(image: ImageData): Boolean = try {
        val bytesPerRow = image.width * image.channels
        val rows = minOf((70 + bytesPerRow - 1) / bytesPerRow, image.height - 1)
        val start = (image.height - rows) * bytesPerRow
        image.pixels[start] == 0x4f.toByte() && image.pixels[start + 1] == 0x50.toByte() &&
            image.pixels[start + 2] == 0x54.toByte() && image.pixels[start + 3] == 0x43.toByte()
    } catch (_: Exception) { false }
}
