package com.opticipher

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.lifecycle.MutableLiveData
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.UUID

internal data class LogEntry(val time: Long, val legacyTime: String, val message: String) {
    fun line(timestamps: Boolean): String {
        if (!timestamps) return message
        val prefix = if (time == 0L) legacyTime else jobTime(time)
        return if (prefix.isBlank()) message else "$prefix  $message"
    }
}

internal data class JobRecord(
    val id: String,
    val name: String,
    val started: Long,
    val finished: Long,
    val reviewed: Long,
    val summary: String,
)

internal data class FileOutcome(val name: String, val status: String, val detail: String) {
    fun line() = "[$status] $name · $detail"
}

internal fun jobTime(time: Long): String =
    Instant.ofEpochMilli(time).atZone(ZoneId.systemDefault()).format(DateTimeFormatter.ofPattern("uuuu-MM-dd HH:mm:ss"))

internal class JobJournal private constructor(private val context: Context) :
    SQLiteOpenHelper(context, "job_journal.db", null, 1) {
    val changes = MutableLiveData<Unit>()

    override fun onConfigure(db: SQLiteDatabase) {
        db.setForeignKeyConstraintsEnabled(true)
    }

    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE logs (id INTEGER PRIMARY KEY, created INTEGER NOT NULL, legacy_time TEXT NOT NULL, message TEXT NOT NULL)")
        db.execSQL("""CREATE TABLE jobs (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, started INTEGER NOT NULL, finished INTEGER NOT NULL DEFAULT 0,
            reviewed INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL
        )""".trimIndent())
        db.execSQL("""CREATE TABLE outcomes (
            id INTEGER PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            name TEXT NOT NULL, status TEXT NOT NULL, detail TEXT NOT NULL
        )""".trimIndent())
        db.execSQL("CREATE INDEX outcomes_job ON outcomes(job_id)")
        val legacy = context.getSharedPreferences("folder_watch", Context.MODE_PRIVATE)
            .getStringSet("activity_logs", emptySet()).orEmpty()
        for (record in legacy.sortedByDescending { it.substringBefore('|').toIntOrNull() ?: Int.MAX_VALUE }) {
            val line = record.substringAfter('|', "")
            if (line.isEmpty()) continue
            val stamp = line.substringBefore("  ", "")
            db.execSQL("INSERT INTO logs(created, legacy_time, message) VALUES(0, ?, ?)",
                arrayOf(stamp, line.substringAfter("  ", line)))
        }
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    override fun onOpen(db: SQLiteDatabase) {
        super.onOpen(db)
        db.execSQL("UPDATE jobs SET finished = ?, summary = 'Interrupted before completion' WHERE finished = 0",
            arrayOf(System.currentTimeMillis()))
    }

    fun log(message: String) = mutate { db ->
        appendLog(db, message)
    }

    fun begin(name: String, detail: String, id: String = UUID.randomUUID().toString()): String {
        mutate { db ->
            db.execSQL("INSERT INTO jobs(id, name, started, summary) VALUES(?, ?, ?, ?)",
                arrayOf(id, name, System.currentTimeMillis(), "Running"))
            appendLog(db, "[INFO] $name · $detail")
        }
        return id
    }

    fun outcome(id: String, outcome: FileOutcome) = mutate { db ->
        db.execSQL("INSERT INTO outcomes(job_id, name, status, detail) VALUES(?, ?, ?, ?)",
            arrayOf(id, outcome.name, outcome.status, outcome.detail))
        appendLog(db, outcome.line())
    }

    fun finish(id: String, name: String, summary: String) = mutate { db ->
        val updated = db.update("jobs", ContentValues().apply {
            put("finished", System.currentTimeMillis())
            put("summary", summary)
        }, "id = ? AND finished = 0", arrayOf(id))
        if (updated > 0) {
            db.execSQL("DELETE FROM jobs WHERE id IN (SELECT id FROM jobs WHERE finished > 0 ORDER BY started DESC, rowid DESC LIMIT -1 OFFSET 100)")
            appendLog(db, "[INFO] $name · $summary")
        }
    }

    fun confirm(job: JobRecord) = mutate { db ->
        val updated = db.update("jobs", ContentValues().apply { put("reviewed", System.currentTimeMillis()) },
            "id = ? AND finished > 0 AND reviewed = 0", arrayOf(job.id))
        if (updated > 0) appendLog(db, "[INFO] ${job.name} · Review confirmed")
    }

    fun logs(): List<LogEntry> = readableDatabase.rawQuery(
        "SELECT created, legacy_time, message FROM logs ORDER BY id DESC", null
    ).use { cursor ->
        buildList { while (cursor.moveToNext()) add(LogEntry(cursor.getLong(0), cursor.getString(1), cursor.getString(2))) }
    }.asReversed()

    fun jobs(): List<JobRecord> = readableDatabase.rawQuery(
        "SELECT id, name, started, finished, reviewed, summary FROM jobs ORDER BY started DESC, rowid DESC", null
    ).use { cursor ->
        buildList {
            while (cursor.moveToNext()) add(JobRecord(cursor.getString(0), cursor.getString(1), cursor.getLong(2),
                cursor.getLong(3), cursor.getLong(4), cursor.getString(5)))
        }
    }

    fun outcomes(id: String): List<FileOutcome> = readableDatabase.rawQuery(
        "SELECT name, status, detail FROM outcomes WHERE job_id = ? ORDER BY id", arrayOf(id)
    ).use { cursor ->
        buildList { while (cursor.moveToNext()) add(FileOutcome(cursor.getString(0), cursor.getString(1), cursor.getString(2))) }
    }

    fun clearLogs() = mutate { db ->
        db.delete("logs", null, null)
        context.getSharedPreferences("folder_watch", Context.MODE_PRIVATE).edit().remove("activity_logs").apply()
    }

    private fun appendLog(db: SQLiteDatabase, message: String) {
        db.execSQL("INSERT INTO logs(created, legacy_time, message) VALUES(?, '', ?)",
            arrayOf(System.currentTimeMillis(), message))
        db.execSQL("DELETE FROM logs WHERE id <= (SELECT id FROM logs ORDER BY id DESC LIMIT 1 OFFSET 300)")
    }

    private fun mutate(action: (SQLiteDatabase) -> Unit) {
        try {
            val db = writableDatabase
            db.beginTransaction()
            try {
                action(db)
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
            changes.postValue(Unit)
        } catch (error: android.database.SQLException) {
            android.util.Log.e("OptiCipher", "Could not write job journal", error)
        }
    }

    companion object {
        @Volatile private var instance: JobJournal? = null
        fun get(context: Context): JobJournal = instance ?: synchronized(this) {
            instance ?: JobJournal(context.applicationContext).also { instance = it }
        }
    }
}
