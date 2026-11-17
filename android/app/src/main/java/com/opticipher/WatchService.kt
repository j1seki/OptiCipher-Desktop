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
import android.os.PowerManager
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat

class WatchService : Service() {
    private val handler = Handler(Looper.getMainLooper())
    private val lastRun = mutableMapOf<String, Long>()
    private var wakeLock: PowerManager.WakeLock? = null
    private val poll = object : Runnable {
        override fun run() {
            val now = System.currentTimeMillis()
            var active = false
            for (mode in listOf(FolderWatcher.ENCRYPT, FolderWatcher.DECRYPT)) {
                if (!FolderWatcher.isWatching(this@WatchService, mode)) continue
                active = true
                val intervalMinutes = FolderWatcher.getIntervalMinutes(this@WatchService, mode)
                val intervalMs = if (intervalMinutes == 0) 60_000L else intervalMinutes * 60_000L
                val last = lastRun[mode] ?: 0L
                if (intervalMs == 0L || now - last >= intervalMs) {
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
        val encrypt = FolderWatcher.isWatching(this, FolderWatcher.ENCRYPT)
        val decrypt = FolderWatcher.isWatching(this, FolderWatcher.DECRYPT)
        if (!encrypt && !decrypt) {
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
        if (wakeLock == null) {
            wakeLock = getSystemService(PowerManager::class.java)
                ?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "OptiCipher:FolderWatch")
                ?.apply { setReferenceCounted(false); acquire() }
        }
        handler.removeCallbacks(poll)
        handler.post(poll)
        return START_STICKY
    }

    override fun onDestroy() {
        handler.removeCallbacks(poll)
        try { wakeLock?.takeIf { it.isHeld }?.release() } catch (_: Exception) { }
        wakeLock = null
        super.onDestroy()
    }

    override fun onBind(intent: Intent?): IBinder? = null

    companion object {
        private const val NOTIFICATION_ID = 42

        fun start(context: Context) {
            try {
                ContextCompat.startForegroundService(context, Intent(context, WatchService::class.java))
            } catch (_: Exception) {
                // The WorkManager fallback still covers background checks.
            }
        }

        fun stopIfIdle(context: Context) {
            if (!FolderWatcher.isWatching(context, FolderWatcher.ENCRYPT) &&
                !FolderWatcher.isWatching(context, FolderWatcher.DECRYPT)
            ) {
                context.stopService(Intent(context, WatchService::class.java))
            }
        }
    }
}
