package com.opticipher

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.content.Intent
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
import androidx.work.*
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.concurrent.TimeUnit

// Folder watching via SAF (Storage Access Framework):
//  - User picks an Inbox folder with ACTION_OPEN_DOCUMENT_TREE (no permission dialog).
//  - We keep a persistable URI permission and register a ContentObserver on it.
//  - New/changed files enqueue a WorkManager job; the job encrypts (or decrypts)
//    into the output tree. The output tree is excluded to prevent loops, already-
//    encrypted files are skipped by parsing the OPTC header (not by filename),
//    and outputs never overwrite ( _2, _3 ... ).
//  - A passphrase is required to process. By default it lives only in memory
//    (watcher queues + notifies "open the app"); enabling "remember passphrase"
//    stores it in EncryptedSharedPreferences so background processing can run.
object FolderWatcher {
    private const val PREFS = "folder_watch"
    private const val INBOX = "inbox_uri"
    private const val OUT = "out_uri"
    private const val MODE = "mode"
    private const val REMEMBER = "remember"
    private const val MOVE = "move_original"
    private const val PROCESSED = "processed"
    private const val WATCHING = "watching"
    const val WORK = "opticipher-folder-watch"

    private var observer: ContentObserver? = null

    fun setInbox(ctx: Context, uri: Uri) = prefs(ctx).edit().putString(INBOX, uri.toString()).apply()
    fun getInbox(ctx: Context): Uri? = prefs(ctx).getString(INBOX, null)?.let { Uri.parse(it) }
    fun setOutputTree(ctx: Context, uri: Uri) = prefs(ctx).edit().putString(OUT, uri.toString()).apply()
    fun getOutputTree(ctx: Context): Uri? = prefs(ctx).getString(OUT, null)?.let { Uri.parse(it) }
    fun setOutput(ctx: Context, uri: Uri) = prefs(ctx).edit().putString(OUT, uri.toString()).apply()
    fun getMode(ctx: Context): String = prefs(ctx).getString(MODE, "encrypt")!!
    fun setMode(ctx: Context, m: String) = prefs(ctx).edit().putString(MODE, m).apply()
    fun setRememberPassphrase(ctx: Context, on: Boolean) = prefs(ctx).edit().putBoolean(REMEMBER, on).apply()
    fun isRemembering(ctx: Context) = prefs(ctx).getBoolean(REMEMBER, false)
    fun setMoveOriginal(ctx: Context, on: Boolean) = prefs(ctx).edit().putBoolean(MOVE, on).apply()
    fun isMoveOriginal(ctx: Context) = prefs(ctx).getBoolean(MOVE, false)
    fun isWatching(ctx: Context) = prefs(ctx).getBoolean(WATCHING, false) && getInbox(ctx) != null

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun encPrefs(ctx: Context): android.content.SharedPreferences {
        val key = MasterKey.Builder(ctx).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
        return EncryptedSharedPreferences.create(ctx, "opticipher_secrets", key,
            EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
            EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
    }
    fun storePassphraseIfEnabled(ctx: Context, pass: String) {
        if (isRemembering(ctx)) encPrefs(ctx).edit().putString("passphrase", pass).apply()
    }
    fun restorePassphraseIfEnabled(ctx: Context): String? =
        if (isRemembering(ctx)) try { encPrefs(ctx).getString("passphrase", null) } catch (_: Exception) { null } else null

    fun startWatching(ctx: Context) {
        val inbox = getInbox(ctx) ?: return
        prefs(ctx).edit().putBoolean(WATCHING, true).apply()
        stopWatching(ctx, keepFlag = true)
        val app = ctx.applicationContext
        observer = object : ContentObserver(Handler(Looper.getMainLooper())) {
            override fun onChange(selfChange: Boolean) { enqueue(app) }
        }
        // Observe the tree via DocumentsContract; also poll periodically as a
        // fallback (some OEM file managers don't fire change events reliably).
        try { app.contentResolver.registerContentObserver(inbox, true, observer!!) } catch (_: Exception) {}
        enqueue(app)
        val periodic = PeriodicWorkRequestBuilder<WatchWorker>(15, TimeUnit.MINUTES).build()
        WorkManager.getInstance(app).enqueueUniquePeriodicWork(WORK, ExistingPeriodicWorkPolicy.KEEP, periodic)
    }

    fun stopWatching(ctx: Context, keepFlag: Boolean = false) {
        if (!keepFlag) prefs(ctx).edit().putBoolean(WATCHING, false).apply()
        observer?.let { try { ctx.contentResolver.unregisterContentObserver(it) } catch (_: Exception) {} }
        observer = null
        WorkManager.getInstance(ctx).cancelUniqueWork(WORK)
        WorkManager.getInstance(ctx).cancelUniqueWork(WORK + "-now")
    }

    fun enqueue(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<WatchWorker>().build()
        WorkManager.getInstance(ctx).enqueueUniqueWork(WORK + "-now", ExistingWorkPolicy.REPLACE, req)
        notify(ctx, "OptiCipher: new files detected — processing queued")
    }

    fun notify(ctx: Context, text: String) {
        val nm = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) {
            val ch = NotificationChannel("watch", "Folder watch", NotificationManager.IMPORTANCE_LOW)
            nm.createNotificationChannel(ch)
        }
        val n = NotificationCompat.Builder(ctx, "watch").setSmallIcon(android.R.drawable.ic_dialog_info)
            .setContentTitle("OptiCipher").setContentText(text).setAutoCancel(true).build()
        try { nm.notify(1, n) } catch (_: Exception) { /* POST_NOTIFICATIONS not granted */ }
    }
}

class WatchWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result = withContext(Dispatchers.IO) {
        try {
            val inboxUri = FolderWatcher.getInbox(applicationContext) ?: return@withContext Result.success()
            val pass = FolderWatcher.restorePassphraseIfEnabled(applicationContext)
            if (pass == null) {
                FolderWatcher.notify(applicationContext, "OptiCipher: files waiting — open the app and enter your passphrase to process them")
                return@withContext Result.success()
            }
            val inbox = DocumentFile.fromTreeUri(applicationContext, inboxUri) ?: return@withContext Result.success()
            val outUri = FolderWatcher.getOutputTree(applicationContext)
            val outTree = outUri?.let { DocumentFile.fromTreeUri(applicationContext, it) }
            val mode = FolderWatcher.getMode(applicationContext)
            val processed = applicationContext.getSharedPreferences("folder_watch", Context.MODE_PRIVATE).getStringSet("processed", mutableSetOf())!!.toMutableSet()
            for (doc in inbox.listFiles()) {
                if (!doc.isFile || doc.uri.toString() in processed) continue
                val name = doc.name ?: continue
                if (!name.lowercase().endsWith(".png")) continue
                // Skip files already inside the output tree (loop prevention) and
                // already-encrypted inputs when in encrypt mode (OPTC header check).
                val bytes = applicationContext.contentResolver.openInputStream(doc.uri)?.use { it.readBytes() } ?: continue
                if (bytes.size < 2) continue
                val img = try { decodePNG(bytes) } catch (_: Exception) { continue }
                if (mode == "encrypt" && isOptiCipher(img)) { processed.add(doc.uri.toString()); continue }
                val result = if (mode == "encrypt") encryptImage(img, pass) else decryptImage(img, pass)
                val suffix = if (mode == "encrypt") "_encrypted" else "_decrypted"
                val outName = name.substringBeforeLast('.') + suffix + ".png"
                val png = encodePNG(result.pixels, result.width, result.height, result.channels)
                if (outTree != null) {
                    var finalName = outName; var n = 2
                    while (outTree.findFile(finalName) != null) finalName = outName.substringBeforeLast('.') + "_${n++}.png"
                    val created = outTree.createFile("image/png", finalName) ?: continue
                    applicationContext.contentResolver.openOutputStream(created.uri)?.use { it.write(png) }
                } else {
                    val dir = File(applicationContext.getExternalFilesDir(null), "OptiCipher"); dir.mkdirs()
                    var f = File(dir, outName); var n = 2
                    while (f.exists()) f = File(dir, outName.substringBeforeLast('.') + "_${n++}.png")
                    f.writeBytes(png)
                }
                processed.add(doc.uri.toString())
                if (FolderWatcher.isMoveOriginal(applicationContext)) try { DocumentsContract.deleteDocument(applicationContext.contentResolver, doc.uri) } catch (_: Exception) {}
            }
            applicationContext.getSharedPreferences("folder_watch", Context.MODE_PRIVATE).edit().putStringSet("processed", processed).apply()
            FolderWatcher.notify(applicationContext, "OptiCipher: folder watch processing done")
            Result.success()
        } catch (e: Exception) {
            FolderWatcher.notify(applicationContext, "OptiCipher: folder watch failed — ${e.message}")
            Result.success() // don't retry-loop on bad passphrases/files
        }
    }

    private fun isOptiCipher(img: ImageData): Boolean = try {
        val bpr = img.width * img.channels
        val rows = minOf((70 + bpr - 1) / bpr, img.height - 1)
        val start = (img.height - rows) * bpr
        img.pixels[start] == 0x4f.toByte() && img.pixels[start + 1] == 0x50.toByte() &&
            img.pixels[start + 2] == 0x54.toByte() && img.pixels[start + 3] == 0x43.toByte()
    } catch (_: Exception) { false }
}
