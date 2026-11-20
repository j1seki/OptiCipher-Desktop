package com.opticipher

import android.content.Context
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import androidx.core.view.setPadding
import com.google.android.material.dialog.MaterialAlertDialogBuilder

internal class JobHistoryPanel(page: View) {
    private val context = page.context
    private val journal = JobJournal.get(context)
    private val prefs = context.getSharedPreferences("log_view", Context.MODE_PRIVATE)
    private val jobList = page.findViewById<LinearLayout>(R.id.jobHistory)
    private val emptyJobs = page.findViewById<TextView>(R.id.emptyJobHistory)
    private var shownJobs: List<JobRecord>? = null

    fun refresh() {
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
            wrapLines(prefs.getBoolean("wrap", true))
        }
        val dialog = MaterialAlertDialogBuilder(context)
            .setTitle(job.name)
            .setView(text)
            .setNegativeButton(android.R.string.cancel, null)
            .setNeutralButton(R.string.copy_job) { _, _ -> text.copySelection(R.string.job_history) }
        if (job.finished > 0 && job.reviewed == 0L && details.isSuccess) {
            dialog.setPositiveButton(R.string.confirm_review) { _, _ -> journal.confirm(job); refresh() }
        }
        dialog.show()
    }

}
