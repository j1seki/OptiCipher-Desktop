package com.opticipher

import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.net.Uri
import androidx.core.app.NotificationCompat
import androidx.documentfile.provider.DocumentFile
import androidx.work.CoroutineWorker
import androidx.work.Data
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.File
import java.util.Calendar
import java.util.concurrent.TimeUnit

/** A single recurring, user-configured queue. WorkManager timings are approximate. */
object BatchSchedule {
    fun prefs(ctx: Context) = ctx.getSharedPreferences("scheduled_batch", Context.MODE_PRIVATE)
    fun progress(ctx: Context, title: String, detail: String, current: Int, total: Int, done: Boolean = false) {
        prefs(ctx).edit().putString("live_title", title).putString("live_detail", detail)
            .putInt("live_current", current).putInt("live_total", total).apply()
        val manager = ctx.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.createNotificationChannel(NotificationChannel("batch_progress", "Batch progress", NotificationManager.IMPORTANCE_LOW))
        val notification = NotificationCompat.Builder(ctx, "batch_progress")
            .setSmallIcon(R.drawable.ic_shield).setContentTitle(title).setContentText(detail)
            .setStyle(NotificationCompat.BigTextStyle().bigText(detail)).setOnlyAlertOnce(true)
            .setOngoing(!done).setAutoCancel(done)
            .setProgress(if (done) 0 else total.coerceAtLeast(1), if (done) 0 else current, !done && total == 0)
            .build()
        try { manager.notify(83, notification) } catch (_: SecurityException) { }
    }
}

