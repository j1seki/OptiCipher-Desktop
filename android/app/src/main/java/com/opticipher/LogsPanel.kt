package com.opticipher

import android.content.Context
import android.view.View
import com.google.android.material.checkbox.MaterialCheckBox
import com.google.android.material.dialog.MaterialAlertDialogBuilder

internal class LogsPanel(private val page: View) {
    private val context = page.context
    private val journal = JobJournal.get(context)
    private val prefs = context.getSharedPreferences("log_view", Context.MODE_PRIVATE)
    private val viewer = page.findViewById<LogTextView>(R.id.activityLog)
    private val timestamps = page.findViewById<MaterialCheckBox>(R.id.logTimestamps)
    private val wrap = page.findViewById<MaterialCheckBox>(R.id.logWrap)
    private val copy = page.findViewById<View>(R.id.copyLogBtn)
    private val clear = page.findViewById<View>(R.id.clearLogBtn)

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
        copy.setOnClickListener { viewer.copySelection(R.string.event_log) }
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

}
