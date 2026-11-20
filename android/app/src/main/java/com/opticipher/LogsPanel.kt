package com.opticipher

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.os.PersistableBundle
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.core.view.setPadding
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.dialog.MaterialAlertDialogBuilder

internal class LogsPanel(private val page: View) {
    private val context = page.context
    private val journal = JobJournal.get(context)
    private val prefs = context.getSharedPreferences("log_view", Context.MODE_PRIVATE)
    private val viewer = page.findViewById<LogTextView>(R.id.activityLog)
    private val timestamps = page.findViewById<MaterialCheckBox>(R.id.logTimestamps)
    private val wrap = page.findViewById<MaterialCheckBox>(R.id.logWrap)
    private val jobList = page.findViewById<LinearLayout>(R.id.jobHistory)
    private val emptyJobs = page.findViewById<TextView>(R.id.emptyJobHistory)
    private val copy = page.findViewById<View>(R.id.copyLogBtn)
    private val clear = page.findViewById<View>(R.id.clearLogBtn)
    private var shownJobs: List<JobRecord>? = null

    init {
        timestamps.isChecked = prefs.getBoolean("timestamps", true)
        wrap.isChecked = prefs.getBoolean("wrap", true)
        viewer.wrapLines(wrap.isChecked)
        timestamps.setOnCheckedChangeListener { _, on ->
            prefs.edit().putBoolean("timestamps", on).apply()
            renderLog()
        }
        wrap.setOnCheckedChangeListener { _, on ->
            prefs.edit().putBoolean("wrap", on).apply()
            viewer.wrapLines(on)
        }
        copy.setOnClickListener { copyText(R.string.event_log, viewer.textForCopy()) }
        clear.setOnClickListener {
            MaterialAlertDialogBuilder(context)
                .setTitle(R.string.clear_logs)
                .setMessage(R.string.clear_logs_question)
                .setPositiveButton(R.string.clear_logs) { _, _ -> journal.clearLogs(); refresh() }
                .setNegativeButton(android.R.string.cancel, null)
                .show()
        }
    }

    fun refresh() {
        renderLog()
        val jobs = runCatching { journal.jobs() }.getOrDefault(emptyList())
        if (shownJobs == jobs) return
        shownJobs = jobs
        emptyJobs.visibility = if (jobs.isEmpty()) View.VISIBLE else View.GONE
        jobList.removeAllViews()
        val padding = (10 * context.resources.displayMetrics.density).toInt()
        for (job in jobs) {
            val review = when {
                job.reviewed > 0 -> R.string.review_confirmed
                job.finished > 0 -> R.string.review_pending
                else -> R.string.job_running
            }
            val row = TextView(context).apply {
                text = "${job.name}\n${jobTime(job.started)} · ${context.getString(review)}\n${job.summary}"
                setPadding(padding)
                val themeBackground = android.util.TypedValue()
                context.theme.resolveAttribute(android.R.attr.selectableItemBackground, themeBackground, true)
                setBackgroundResource(themeBackground.resourceId)
                isFocusable = true
                setOnClickListener { reviewJob(job) }
            }
            jobList.addView(row, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT))
        }
    }

    private fun renderLog() {
        val logs = runCatching { journal.logs() }
        val text = logs.getOrDefault(emptyList()).joinToString("\n") { it.line(timestamps.isChecked) }
        if (text != viewer.text.toString()) {
            val previousX = viewer.scrollX
            val previousY = viewer.scrollY
            val atEnd = !viewer.canScrollVertically(1)
            viewer.setText(text)
            viewer.post {
                val maximumY = ((viewer.layout?.height ?: 0) -
                    (viewer.height - viewer.paddingTop - viewer.paddingBottom)).coerceAtLeast(0)
                viewer.scrollTo(if (wrap.isChecked) 0 else previousX, if (atEnd) maximumY else minOf(previousY, maximumY))
            }
        }
        viewer.hint = context.getString(if (logs.isSuccess) R.string.no_log_entries else R.string.log_unavailable)
        copy.isEnabled = text.isNotEmpty()
        clear.isEnabled = text.isNotEmpty()
    }

    private fun reviewJob(job: JobRecord) {
        val details = runCatching { journal.outcomes(job.id) }
        val outcomes = details.getOrDefault(emptyList()).joinToString("\n\n") { it.line() }
        val report = buildString {
            append(jobTime(job.started))
            append("\n${job.summary}\n")
            if (job.reviewed > 0) append(context.getString(R.string.review_confirmed) + " · " + jobTime(job.reviewed) + "\n")
            append("\n")
            append(outcomes.ifEmpty { context.getString(if (details.isSuccess) R.string.no_file_outcomes else R.string.log_unavailable) })
        }
        val text = LogTextView(context).apply {
            setPadding((20 * resources.displayMetrics.density).toInt())
            setText(report)
            setBackgroundResource(android.R.color.transparent)
            minHeight = (160 * resources.displayMetrics.density).toInt()
            maxHeight = (330 * resources.displayMetrics.density).toInt()
            wrapLines(wrap.isChecked)
        }
        val dialog = MaterialAlertDialogBuilder(context)
            .setTitle(job.name)
            .setView(text)
            .setNegativeButton(android.R.string.cancel, null)
            .setNeutralButton(R.string.copy_job) { _, _ -> copyText(R.string.job_history, text.textForCopy()) }
        if (job.finished > 0 && job.reviewed == 0L && details.isSuccess) {
            dialog.setPositiveButton(R.string.confirm_review) { _, _ -> journal.confirm(job); refresh() }
        }
        dialog.show()
    }

    private fun LogTextView.textForCopy(): String {
        val content = text?.toString().orEmpty()
        val start = minOf(selectionStart, selectionEnd).coerceAtLeast(0)
        val end = maxOf(selectionStart, selectionEnd).coerceIn(0, content.length)
        return if (start < end) content.substring(start, end) else content
    }

    private fun copyText(label: Int, text: String) {
        val clip = ClipData.newPlainText(context.getString(label), text)
        // Explicit copies can contain private filenames. Hide their preview on newer Android versions.
        clip.description.extras = PersistableBundle().apply { putBoolean("android.content.extra.IS_SENSITIVE", true) }
        context.getSystemService(ClipboardManager::class.java).setPrimaryClip(clip)
        Toast.makeText(context, R.string.logs_copied, Toast.LENGTH_SHORT).show()
    }
}
