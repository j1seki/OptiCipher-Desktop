package com.opticipher

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

class WatchService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val lastRun = mutableMapOf<String, Long>()
    private val poll = object : Runnable {
        override fun run() {
            val now = SystemClock.elapsedRealtime()
            var active = false
            for (mode in FolderWatcher.MODES) {
                if (!runsInService(this@WatchService, mode)) {
                    lastRun.remove(mode)
                    continue
                }
                active = true
                val intervalMinutes = FolderWatcher.getIntervalMinutes(this@WatchService, mode)
                val intervalMs = intervalMinutes * 60_000L
                val last = lastRun.getOrPut(mode) { now }
                if (now - last >= intervalMs) {
                    lastRun[mode] = now
                    FolderWatcher.enqueue(this@WatchService, mode)
                }
            }
            if (!active) {
                stopSelf()
                return
            }
            handler.postDelayed(this, 30_000)
        }
    }

    override fun onCreate() {
        super.onCreate()
        val notifications = getSystemService(NOTIFICATION_SERVICE) as NotificationManager
        notifications.createNotificationChannel(
            NotificationChannel("watch", "Folder watch", NotificationManager.IMPORTANCE_LOW)
        )
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (FolderWatcher.MODES.none { runsInService(this, it) }) {
            stopSelf()
            return START_NOT_STICKY
        }
        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(this, "watch")
            .setSmallIcon(R.drawable.ic_shield)
            .setContentTitle("OptiCipher is watching")
            .setContentText("Watching for new images")
            .setContentIntent(open)
            .setOngoing(true)
            .setSilent(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()
        val type = if (Build.VERSION.SDK_INT >= 34) ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE else 0
        ServiceCompat.startForeground(this, NOTIFICATION_ID, notification, type)
        handler.removeCallbacks(poll)
        handler.post(poll)
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacks(poll)
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val NOTIFICATION_ID = 42

        private fun runsInService(context: Context, mode: String) =
            FolderWatcher.isWatching(context, mode) && !FolderWatcher.isWeekly(context, mode)

        fun update(context: Context) {
            if (FolderWatcher.MODES.none { runsInService(context, it) }) {
                context.stopService(Intent(context, WatchService::class.java))
                return
            }
            try {
                ContextCompat.startForegroundService(context, Intent(context, WatchService::class.java))
            } catch (_: Exception) {
                // The WorkManager fallback still covers background checks.
            }
        }

    }
}
