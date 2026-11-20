package com.opticipher

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.work.CoroutineWorker
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.Operation
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.await
import androidx.work.workDataOf
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.Duration
import java.time.Instant
import java.time.LocalTime
import java.time.ZonedDateTime
import java.time.temporal.TemporalAdjusters
import java.util.UUID
import java.util.concurrent.TimeUnit

internal data class WeeklyTime(val day: Int = 2, val hour: Int = 9, val minute: Int = 0) {
    fun nextAfter(now: ZonedDateTime): ZonedDateTime {
        val weekday = DayOfWeek.of((day + 5) % 7 + 1) // Calendar Sunday=1, DayOfWeek Monday=1
        val date = now.toLocalDate().with(TemporalAdjusters.nextOrSame(weekday))
        val localTime = LocalTime.of(hour, minute)
        val candidate = date.atTime(localTime).atZone(now.zone)
        return if (candidate.isAfter(now)) candidate else date.plusWeeks(1).atTime(localTime).atZone(now.zone)
    }
}

internal object WeeklyWatch {
    private fun prefs(ctx: Context) = ctx.getSharedPreferences("weekly_watch", Context.MODE_PRIVATE)
    private fun tag(mode: String) = "opticipher-$mode-weekly-watch"

    @Synchronized
    fun reset(ctx: Context, mode: String): Operation {
        val generation = UUID.randomUUID().toString()
        prefs(ctx).edit().putString(mode, generation).apply()
        val cancelled = WorkManager.getInstance(ctx).cancelAllWorkByTag(tag(mode))
        return if (FolderWatcher.isWatching(ctx, mode) && FolderWatcher.isWeekly(ctx, mode)) {
            schedule(ctx, mode, generation)
        } else cancelled
    }

    @Synchronized
    fun migrate(ctx: Context, mode: String) {
        if (FolderWatcher.isWatching(ctx, mode) && FolderWatcher.isWeekly(ctx, mode) &&
            !prefs(ctx).contains(mode)) {
            FolderWatcher.startWatching(ctx, mode)
        }
    }

    @Synchronized
    fun run(ctx: Context, mode: String, generation: String, due: Long): List<Operation> {
        if (prefs(ctx).getString(mode, null) != generation ||
            !FolderWatcher.isWatching(ctx, mode) || !FolderWatcher.isWeekly(ctx, mode)) return emptyList()
        return listOf(FolderWatcher.enqueue(ctx, mode), schedule(ctx, mode, generation, due))
    }

    private fun schedule(ctx: Context, mode: String, generation: String, previousDue: Long = 0): Operation {
        val now = ZonedDateTime.now()
        val anchor = Instant.ofEpochMilli(maxOf(previousDue, now.toInstant().toEpochMilli())).atZone(now.zone)
        val next = FolderWatcher.weeklyTime(ctx, mode).nextAfter(anchor)
        val due = next.toInstant().toEpochMilli()
        val request = OneTimeWorkRequestBuilder<WeeklyWatchWorker>()
            .setInputData(workDataOf("mode" to mode, "generation" to generation, "due" to due))
            .setInitialDelay(Duration.between(now, next).toMillis().coerceAtLeast(1) + 1, TimeUnit.MILLISECONDS)
            .addTag(tag(mode))
            .build()
        val name = "${tag(mode)}-$generation-${next.toEpochSecond()}"
        return WorkManager.getInstance(ctx).enqueueUniqueWork(name, ExistingWorkPolicy.KEEP, request)
    }
}

class WeeklyWatchWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val mode = inputData.getString("mode") ?: return Result.failure()
        val generation = inputData.getString("generation") ?: return Result.failure()
        val due = inputData.getLong("due", 0)
        return try {
            WeeklyWatch.run(applicationContext, mode, generation, due).forEach { it.await() }
            Result.success()
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            Result.retry()
        }
    }
}

class WatchClockReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                for (mode in FolderWatcher.MODES) {
                    if (!FolderWatcher.isWatching(context, mode) || !FolderWatcher.isWeekly(context, mode)) continue
                    if (intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) WeeklyWatch.migrate(context, mode)
                    else WeeklyWatch.reset(context, mode).await()
                }
            } catch (error: Exception) {
                FolderWatcher.log(context, "Could not refresh weekly schedules · ${error.message}")
            } finally {
                pending.finish()
            }
        }
    }
}
